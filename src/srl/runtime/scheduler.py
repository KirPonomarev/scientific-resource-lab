"""File-backed runtime scheduler for one bounded SRF run at a time.

The scheduler is deliberately on-demand: it has no timer, listener or
background worker. A caller submits requests, then explicitly calls
``dispatch_next``. Each dispatch admits a request through the existing resource
policy, materializes exact CAS inputs, invokes the fixed-entrypoint runner, and
seals the result. Terminal receipts are written once and only once.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, cast

from srl.cas.layout import SrfStorageLayout
from srl.cas.store import LocalArtifactStore
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id
from srl.execution.estimate import ResourceEstimate
from srl.execution.materialize import StagedRun, materialize_run
from srl.execution.policy import (
    OVERFLOW_ACTION,
    AdmissionDecision,
    ResourcePolicy,
    admit,
)
from srl.execution.runner import RunOutcome, RunStatus, run_adapter
from srl.execution.sandbox import prepare_scratch
from srl.execution.sealer import SealedRun, seal_run
from srl.packs.governance import PackLifecycleStatus

RUN_REQUEST_SCHEMA_VERSION: Final[str] = "RuntimeRunRequest/v1"
RUN_CHECKPOINT_SCHEMA_VERSION: Final[str] = "RuntimeRunCheckpoint/v1"
RUN_TERMINAL_RECEIPT_SCHEMA_VERSION: Final[str] = "RuntimeRunTerminalReceipt/v1"
RUN_NAMESPACE_SCHEMA_VERSION: Final[str] = "RuntimeT7WorkNamespace/v1"
RUNNER_CONFORMANCE_RECEIPT_SCHEMA_VERSION: Final[str] = "RunnerConformanceReceipt/v1"

_REQUEST_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_INPUT_MEDIA_TYPE: Final[str] = "application/json"
_RESOURCE_WAIT_REASON: Final[str] = "WAIT_REMOTE_EXECUTOR"
_BACKPRESSURE_REASON: Final[str] = "WAIT_BACKPRESSURE"
_PACK_WAIT_REASON: Final[str] = "WAIT_PACK_GOVERNANCE"
_CANCELLED_REASON: Final[str] = "CANCELLED_BY_OPERATOR"
_INTERRUPTED_REASON: Final[str] = "INTERRUPTED_BEFORE_TERMINAL"
_DISK_WAIT_REASON: Final[str] = "WAIT_LOCAL_DISK"
_DEFAULT_RUNTIME_NAMESPACE: Final[str] = "scheduler"
_RUNTIME_NAMESPACE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class SchedulerError(ContractError):
    """Raised when scheduler input or state violates the runtime contract."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class RuntimeRunStatus(StrEnum):
    """Durable scheduler status values."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAIT_BACKPRESSURE = "wait_backpressure"
    WAIT_PACK_GOVERNANCE = "wait_pack_governance"
    WAIT_REMOTE_EXECUTOR = "wait_remote_executor"
    WAIT_LOCAL_DISK = "wait_local_disk"


class RuntimePool(StrEnum):
    """Dispatch pool for bounded local runtime work."""

    LIGHT = "light"
    HEAVY = "heavy"


@dataclass(frozen=True)
class SchedulerTerminalReceipt:
    """One truthful terminal outcome for a runtime request."""

    schema_version: str
    request_id: str
    status: RuntimeRunStatus
    generation: int
    fail_reason: str | None
    detail: str
    staged_input_digests: dict[str, str]
    run_receipt_id: str | None
    engine_receipt_id: str | None
    output_digests: dict[str, str]
    sealed: bool
    terminal_receipt_id: str | None = None
    canonical_writes: int = 0
    grants_authority: bool = False

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        """Return a stable JSON-compatible terminal receipt."""
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "status": self.status.value,
            "generation": self.generation,
            "fail_reason": self.fail_reason,
            "detail": self.detail,
            "staged_input_digests": dict(sorted(self.staged_input_digests.items())),
            "run_receipt_id": self.run_receipt_id,
            "engine_receipt_id": self.engine_receipt_id,
            "output_digests": dict(sorted(self.output_digests.items())),
            "sealed": self.sealed,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }
        if include_id:
            payload["terminal_receipt_id"] = self.terminal_receipt_id
        return payload


@dataclass(frozen=True)
class RuntimeRunRequest:
    """A bounded runtime request.

    ``input_payload`` is the exact JSON-serializable object handed to the fixed
    adapter. It is also ingested into CAS before execution so the final receipt
    binds the input bytes the runner saw.
    """

    request_id: str
    adapter_id: str
    input_payload: Any
    resource_estimate: ResourceEstimate
    pack_id: str | None = None
    use_exception: bool = False
    priority: int = 0
    pool: RuntimePool | str = RuntimePool.LIGHT

    def __post_init__(self) -> None:
        _validate_request_id(self.request_id)
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise SchedulerError("adapter_id must be a non-empty string")
        if self.pack_id is not None and not isinstance(self.pack_id, str):
            raise SchedulerError("pack_id must be a string or None")
        if isinstance(self.use_exception, bool) is False:
            raise SchedulerError("use_exception must be a bool")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise SchedulerError("priority must be an int")
        object.__setattr__(self, "pool", _normalize_pool(self.pool))
        dumps(self.input_payload)

    def to_dict(self) -> dict[str, object]:
        """Return the request as stable JSON-compatible data."""
        return {
            "schema_version": RUN_REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "adapter_id": self.adapter_id,
            "input_payload": self.input_payload,
            "resource_estimate": self.resource_estimate.to_canonical_dict(),
            "resource_estimate_digest": self.resource_estimate.digest(),
            "pack_id": self.pack_id,
            "use_exception": self.use_exception,
            "priority": self.priority,
            "pool": _normalize_pool(self.pool).value,
            "canonical_writes": 0,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class RuntimeRunCheckpoint:
    """Durable nonterminal checkpoint for a queued or running request."""

    request: RuntimeRunRequest
    status: RuntimeRunStatus
    generation: int
    sequence: int
    input_digest: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible checkpoint."""
        return {
            "schema_version": RUN_CHECKPOINT_SCHEMA_VERSION,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "generation": self.generation,
            "sequence": self.sequence,
            "input_digest": self.input_digest,
            "canonical_writes": 0,
            "grants_authority": False,
        }


RunnerCallable = Callable[[RuntimeRunRequest, ResourcePolicy, Path], RunOutcome]
OutputValidator = Callable[[object], None]


@dataclass(frozen=True)
class SchedulerRoots:
    """Filesystem roots owned by one bounded scheduler instance."""

    root: Path
    store: LocalArtifactStore

    @classmethod
    def create(cls, root: str | Path) -> SchedulerRoots:
        """Create the runtime directory layout under ``root``."""
        root_path = Path(root)
        store = LocalArtifactStore(root_path / "cas")
        for rel in (
            "queued",
            "running",
            "terminal",
            "cancel",
            "staging",
            "scratch",
            "receipts",
        ):
            (root_path / rel).mkdir(parents=True, exist_ok=True)
        return cls(root=root_path, store=store)

    @classmethod
    def create_t7_work_namespace(
        cls,
        layout: SrfStorageLayout,
        *,
        runtime_namespace: str = _DEFAULT_RUNTIME_NAMESPACE,
    ) -> SchedulerRoots:
        """Create scheduler state under the SRF mutable T7 ``work/spool`` namespace.

        The method is target-neutral: tests use a fixture layout, while native
        operation supplies the authority-bound T7 layout from A02. CAS objects
        are stored in the layout cold-CAS; mutable FSM/checkpoints/receipts stay
        in ``work/spool/<runtime_namespace>``.
        """
        _validate_runtime_namespace(runtime_namespace)
        layout.initialize()
        root = layout.work_path("spool") / runtime_namespace
        roots = cls(root=root, store=layout.cold_store())
        roots._initialize_runtime_dirs()
        return roots

    def _initialize_runtime_dirs(self) -> None:
        for rel in ("queued", "running", "terminal", "cancel", "staging", "scratch", "receipts"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)

    def namespace_manifest(self) -> dict[str, object]:
        """Return the stable runtime namespace contract without local paths."""
        return {
            "schema_version": RUN_NAMESPACE_SCHEMA_VERSION,
            "state_root_role": "t7_work_spool_runtime_namespace",
            "cas_root_role": "t7_cold_cas",
            "required_state_directories": [
                "queued",
                "running",
                "terminal",
                "cancel",
                "staging",
                "scratch",
                "receipts",
            ],
            "request_fsm": [
                RuntimeRunStatus.QUEUED.value,
                RuntimeRunStatus.RUNNING.value,
                RuntimeRunStatus.COMPLETED.value,
                RuntimeRunStatus.FAILED.value,
                RuntimeRunStatus.CANCELLED.value,
                RuntimeRunStatus.WAIT_BACKPRESSURE.value,
                RuntimeRunStatus.WAIT_PACK_GOVERNANCE.value,
                RuntimeRunStatus.WAIT_REMOTE_EXECUTOR.value,
                RuntimeRunStatus.WAIT_LOCAL_DISK.value,
            ],
            "pools": [RuntimePool.LIGHT.value, RuntimePool.HEAVY.value],
            "heavy_m1_concurrency": 1,
            "canonical_writes": 0,
            "grants_authority": False,
        }

    @property
    def queued(self) -> Path:
        return self.root / "queued"

    @property
    def running(self) -> Path:
        return self.root / "running"

    @property
    def terminal(self) -> Path:
        return self.root / "terminal"

    @property
    def cancel(self) -> Path:
        return self.root / "cancel"

    @property
    def staging(self) -> Path:
        return self.root / "staging"

    @property
    def scratch(self) -> Path:
        return self.root / "scratch"

    @property
    def receipts(self) -> Path:
        return self.root / "receipts"

    def submit(
        self,
        request: RuntimeRunRequest,
        *,
        max_queued: int,
    ) -> RuntimeRunCheckpoint | SchedulerTerminalReceipt:
        """Queue ``request`` or park it with backpressure."""
        _validate_request_id(request.request_id)
        if max_queued < 0:
            raise SchedulerError("max_queued must be non-negative")
        if self._terminal_path(request.request_id).exists():
            return _read_terminal(self._terminal_path(request.request_id))
        if (
            self._queued_path(request.request_id).exists()
            or self._running_path(request.request_id).exists()
        ):
            raise SchedulerError(f"request {request.request_id!r} is already active")
        queued = sorted(self.queued.glob("*.json"))
        if len(queued) >= max_queued:
            return self._write_terminal_once(
                SchedulerTerminalReceipt(
                    schema_version=RUN_TERMINAL_RECEIPT_SCHEMA_VERSION,
                    request_id=request.request_id,
                    status=RuntimeRunStatus.WAIT_BACKPRESSURE,
                    generation=1,
                    fail_reason=_BACKPRESSURE_REASON,
                    detail=f"queue capacity {max_queued} reached",
                    staged_input_digests={},
                    run_receipt_id=None,
                    engine_receipt_id=None,
                    output_digests={},
                    sealed=False,
                )
            )
        checkpoint = RuntimeRunCheckpoint(
            request=request,
            status=RuntimeRunStatus.QUEUED,
            generation=1,
            sequence=_next_sequence(queued),
        )
        _atomic_write_json(self._queued_path(request.request_id), checkpoint.to_dict())
        return checkpoint

    def cancel_request(self, request_id: str) -> SchedulerTerminalReceipt | RuntimeRunCheckpoint:
        """Cancel a queued request or mark a running request for cooperative cancel."""
        _validate_request_id(request_id)
        queued_path = self._queued_path(request_id)
        if queued_path.exists():
            queued = _read_checkpoint(queued_path)
            queued_path.unlink()
            return self._write_terminal_once(
                SchedulerTerminalReceipt(
                    schema_version=RUN_TERMINAL_RECEIPT_SCHEMA_VERSION,
                    request_id=request_id,
                    status=RuntimeRunStatus.CANCELLED,
                    generation=queued.generation + 1,
                    fail_reason=_CANCELLED_REASON,
                    detail="cancelled before dispatch",
                    staged_input_digests={},
                    run_receipt_id=None,
                    engine_receipt_id=None,
                    output_digests={},
                    sealed=False,
                )
            )
        running_path = self._running_path(request_id)
        if running_path.exists():
            running = _read_checkpoint(running_path)
            _atomic_write_json(
                self.cancel / f"{request_id}.json",
                {
                    "schema_version": "RuntimeCancelRequest/v1",
                    "request_id": request_id,
                    "generation": running.generation,
                    "canonical_writes": 0,
                    "grants_authority": False,
                },
            )
            return running
        terminal_path = self._terminal_path(request_id)
        if terminal_path.exists():
            return _read_terminal(terminal_path)
        raise SchedulerError(f"request {request_id!r} is not active")

    def recover_interrupted(self) -> tuple[RuntimeRunCheckpoint, ...]:
        """Move interrupted running checkpoints back to the queue."""
        recovered: list[RuntimeRunCheckpoint] = []
        queued_paths = sorted(self.queued.glob("*.json"))
        for running_path in sorted(self.running.glob("*.json")):
            checkpoint = _read_checkpoint(running_path)
            if self._terminal_path(checkpoint.request.request_id).exists():
                running_path.unlink()
                continue
            if self._cancel_path(checkpoint.request.request_id).exists():
                terminal = SchedulerTerminalReceipt(
                    schema_version=RUN_TERMINAL_RECEIPT_SCHEMA_VERSION,
                    request_id=checkpoint.request.request_id,
                    status=RuntimeRunStatus.CANCELLED,
                    generation=checkpoint.generation + 1,
                    fail_reason=_CANCELLED_REASON,
                    detail="cancelled during interrupted run recovery",
                    staged_input_digests={},
                    run_receipt_id=None,
                    engine_receipt_id=None,
                    output_digests={},
                    sealed=False,
                )
                self._write_terminal_once(terminal)
                running_path.unlink()
                continue
            resumed = RuntimeRunCheckpoint(
                request=checkpoint.request,
                status=RuntimeRunStatus.QUEUED,
                generation=checkpoint.generation + 1,
                sequence=_next_sequence(queued_paths),
                input_digest=checkpoint.input_digest,
            )
            _atomic_write_json(self._queued_path(resumed.request.request_id), resumed.to_dict())
            running_path.unlink()
            queued_paths.append(self._queued_path(resumed.request.request_id))
            recovered.append(resumed)
        return tuple(recovered)

    def dispatch_next(
        self,
        *,
        policy: ResourcePolicy,
        max_queued: int,
        pack_statuses: Mapping[str, PackLifecycleStatus] | None = None,
        runner: RunnerCallable | None = None,
        output_validator: OutputValidator | None = None,
    ) -> SchedulerTerminalReceipt | None:
        """Dispatch one queued request and return its terminal receipt."""
        if max_queued < 0:
            raise SchedulerError("max_queued must be non-negative")
        if list(self.running.glob("*.json")):
            return None
        queued_path = self._next_queued_path()
        if queued_path is None:
            return None
        checkpoint = _read_checkpoint(queued_path)
        running = RuntimeRunCheckpoint(
            request=checkpoint.request,
            status=RuntimeRunStatus.RUNNING,
            generation=checkpoint.generation + 1,
            sequence=checkpoint.sequence,
            input_digest=checkpoint.input_digest,
        )
        os.replace(queued_path, self._running_path(running.request.request_id))
        _atomic_write_json(self._running_path(running.request.request_id), running.to_dict())
        terminal = self._dispatch_running(
            running,
            policy=policy,
            pack_statuses=pack_statuses or {},
            runner=runner or _default_runner,
            output_validator=output_validator,
        )
        self._running_path(running.request.request_id).unlink(missing_ok=True)
        self._cancel_path(running.request.request_id).unlink(missing_ok=True)
        return terminal

    def _dispatch_running(
        self,
        checkpoint: RuntimeRunCheckpoint,
        *,
        policy: ResourcePolicy,
        pack_statuses: Mapping[str, PackLifecycleStatus],
        runner: RunnerCallable,
        output_validator: OutputValidator | None,
    ) -> SchedulerTerminalReceipt:
        request = checkpoint.request
        if self._cancel_path(request.request_id).exists():
            return self._terminal_from_wait(
                request,
                checkpoint.generation + 1,
                RuntimeRunStatus.CANCELLED,
                _CANCELLED_REASON,
                "cancelled before runner spawn",
            )
        pack_wait = _pack_wait_detail(request, pack_statuses)
        if pack_wait is not None:
            return self._terminal_from_wait(
                request,
                checkpoint.generation + 1,
                RuntimeRunStatus.WAIT_PACK_GOVERNANCE,
                _PACK_WAIT_REASON,
                pack_wait,
            )
        admission = admit(request.resource_estimate, policy, use_exception=request.use_exception)
        if admission is AdmissionDecision.WAIT_REMOTE_EXECUTOR:
            return self._terminal_from_wait(
                request,
                checkpoint.generation + 1,
                RuntimeRunStatus.WAIT_REMOTE_EXECUTOR,
                _RESOURCE_WAIT_REASON,
                OVERFLOW_ACTION,
            )
        if shutil.disk_usage(self.root).free < policy.required_free_disk_bytes:
            return self._terminal_from_wait(
                request,
                checkpoint.generation + 1,
                RuntimeRunStatus.WAIT_LOCAL_DISK,
                _DISK_WAIT_REASON,
                "local runtime root is below required free disk floor",
            )

        input_digest = (
            checkpoint.input_digest
            or self.store.ingest_bytes(
                dumps(request.input_payload),
                _INPUT_MEDIA_TYPE,
            ).digest
        )
        running_with_input = RuntimeRunCheckpoint(
            request=request,
            status=RuntimeRunStatus.RUNNING,
            generation=checkpoint.generation + 1,
            sequence=checkpoint.sequence,
            input_digest=input_digest,
        )
        _atomic_write_json(self._running_path(request.request_id), running_with_input.to_dict())

        staged = materialize_run(
            {
                "adapter_id": request.adapter_id,
                "input_payloads": {"input.json": input_digest},
                "pack_ref": None,
            },
            self.store,
            self.staging,
        )
        scratch = prepare_scratch(parent=self.scratch)
        try:
            outcome = runner(request, policy, scratch)
            sealed = seal_run(
                staged,
                outcome,
                self.store,
                self.receipts,
                output_validator=output_validator,
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return self._terminal_from_sealed(
            request,
            generation=checkpoint.generation + 2,
            staged=staged,
            outcome=outcome,
            sealed=sealed,
        )

    def _terminal_from_wait(
        self,
        request: RuntimeRunRequest,
        generation: int,
        status: RuntimeRunStatus,
        fail_reason: str,
        detail: str,
    ) -> SchedulerTerminalReceipt:
        return self._write_terminal_once(
            SchedulerTerminalReceipt(
                schema_version=RUN_TERMINAL_RECEIPT_SCHEMA_VERSION,
                request_id=request.request_id,
                status=status,
                generation=generation,
                fail_reason=fail_reason,
                detail=detail,
                staged_input_digests={},
                run_receipt_id=None,
                engine_receipt_id=None,
                output_digests={},
                sealed=False,
            )
        )

    def _terminal_from_sealed(
        self,
        request: RuntimeRunRequest,
        *,
        generation: int,
        staged: StagedRun,
        outcome: RunOutcome,
        sealed: SealedRun,
    ) -> SchedulerTerminalReceipt:
        status = (
            RuntimeRunStatus.COMPLETED
            if outcome.status is RunStatus.COMPLETED
            else RuntimeRunStatus.FAILED
        )
        return self._write_terminal_once(
            SchedulerTerminalReceipt(
                schema_version=RUN_TERMINAL_RECEIPT_SCHEMA_VERSION,
                request_id=request.request_id,
                status=status,
                generation=generation,
                fail_reason=outcome.fail_reason,
                detail=outcome.detail,
                staged_input_digests=staged.input_digests,
                run_receipt_id=sealed.run_receipt["receipt_id"],
                engine_receipt_id=sealed.engine_receipt_id,
                output_digests=sealed.run_receipt["output_digests"],
                sealed=True,
            )
        )

    def _write_terminal_once(self, receipt: SchedulerTerminalReceipt) -> SchedulerTerminalReceipt:
        path = self._terminal_path(receipt.request_id)
        if path.exists():
            return _read_terminal(path)
        bound = (
            receipt
            if receipt.terminal_receipt_id is not None
            else replace(
                receipt,
                terminal_receipt_id=object_id(receipt.to_dict(include_id=False)),
            )
        )
        _atomic_write_json(path, bound.to_dict())
        return bound

    def _next_queued_path(self) -> Path | None:
        candidates = [_read_checkpoint(path) for path in sorted(self.queued.glob("*.json"))]
        if not candidates:
            return None
        latest_sequence = max(item.sequence for item in candidates)
        chosen = sorted(
            candidates,
            key=lambda item: _queue_sort_key(item, latest_sequence=latest_sequence),
        )[0]
        return self._queued_path(chosen.request.request_id)

    def _queued_path(self, request_id: str) -> Path:
        return self.queued / f"{request_id}.json"

    def _running_path(self, request_id: str) -> Path:
        return self.running / f"{request_id}.json"

    def _terminal_path(self, request_id: str) -> Path:
        return self.terminal / f"{request_id}.json"

    def _cancel_path(self, request_id: str) -> Path:
        return self.cancel / f"{request_id}.json"


def submit_and_dispatch_once(  # noqa: PLR0913 - one-shot helper mirrors dispatch knobs.
    roots: SchedulerRoots,
    request: RuntimeRunRequest,
    *,
    policy: ResourcePolicy,
    max_queued: int,
    pack_statuses: Mapping[str, PackLifecycleStatus] | None = None,
    runner: RunnerCallable | None = None,
    output_validator: OutputValidator | None = None,
) -> SchedulerTerminalReceipt:
    """Submit ``request`` and dispatch exactly one queued item."""
    submitted = roots.submit(request, max_queued=max_queued)
    if isinstance(submitted, SchedulerTerminalReceipt):
        return submitted
    terminal = roots.dispatch_next(
        policy=policy,
        max_queued=max_queued,
        pack_statuses=pack_statuses,
        runner=runner,
        output_validator=output_validator,
    )
    if terminal is None:
        raise SchedulerError("dispatch did not produce a terminal receipt")
    return terminal


def _default_runner(
    request: RuntimeRunRequest, policy: ResourcePolicy, scratch: Path
) -> RunOutcome:
    return run_adapter(request.adapter_id, request.input_payload, policy, scratch)


def _pack_wait_detail(
    request: RuntimeRunRequest,
    pack_statuses: Mapping[str, PackLifecycleStatus],
) -> str | None:
    if request.pack_id is None:
        return None
    status = pack_statuses.get(request.pack_id)
    if status is PackLifecycleStatus.ACTIVE:
        return None
    if status is None:
        return f"pack {request.pack_id!r} has no ACTIVE governance record"
    return f"pack {request.pack_id!r} status is {status.value}"


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise SchedulerError("request_id must be 1-128 safe filename characters")


def _next_sequence(paths: list[Path]) -> int:
    if not paths:
        return 1
    return max(_read_checkpoint(path).sequence for path in paths) + 1


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(dumps(dict(payload)))
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _read_checkpoint(path: Path) -> RuntimeRunCheckpoint:
    data = _read_json(path)
    req = data["request"]
    estimate = req["resource_estimate"]
    request = RuntimeRunRequest(
        request_id=req["request_id"],
        adapter_id=req["adapter_id"],
        input_payload=req["input_payload"],
        resource_estimate=ResourceEstimate(
            wall_seconds=estimate["wall_seconds"],
            rss_bytes=estimate["rss_bytes"],
            scratch_bytes=estimate["scratch_bytes"],
            cpu_cores=estimate["cpu_cores"],
        ),
        pack_id=req["pack_id"],
        use_exception=req["use_exception"],
        priority=req["priority"],
        pool=RuntimePool(req.get("pool", RuntimePool.LIGHT.value)),
    )
    return RuntimeRunCheckpoint(
        request=request,
        status=RuntimeRunStatus(data["status"]),
        generation=data["generation"],
        sequence=data["sequence"],
        input_digest=data.get("input_digest"),
    )


def _read_terminal(path: Path) -> SchedulerTerminalReceipt:
    data = _read_json(path)
    return SchedulerTerminalReceipt(
        schema_version=data["schema_version"],
        request_id=data["request_id"],
        status=RuntimeRunStatus(data["status"]),
        generation=data["generation"],
        fail_reason=data["fail_reason"],
        detail=data["detail"],
        staged_input_digests=dict(data["staged_input_digests"]),
        run_receipt_id=data["run_receipt_id"],
        engine_receipt_id=data["engine_receipt_id"],
        output_digests=dict(data["output_digests"]),
        sealed=data["sealed"],
        terminal_receipt_id=data.get("terminal_receipt_id"),
        canonical_writes=data["canonical_writes"],
        grants_authority=data["grants_authority"],
    )


def _queue_sort_key(
    checkpoint: RuntimeRunCheckpoint,
    *,
    latest_sequence: int,
) -> tuple[int, int, int]:
    # Newer requests may carry priority, but each older queued item earns one
    # deterministic aging point per later enqueue so small priority deltas cannot
    # starve old work.
    age_bonus = max(0, latest_sequence - checkpoint.sequence)
    effective_priority = checkpoint.request.priority + age_bonus
    return (
        -effective_priority,
        _pool_rank(_normalize_pool(checkpoint.request.pool)),
        checkpoint.sequence,
    )


def _pool_rank(pool: RuntimePool) -> int:
    return 0 if pool is RuntimePool.LIGHT else 1


def _normalize_pool(pool: RuntimePool | str) -> RuntimePool:
    if isinstance(pool, RuntimePool):
        return pool
    try:
        return RuntimePool(str(pool))
    except ValueError as exc:
        raise SchedulerError("pool must be 'light' or 'heavy'") from exc


def _validate_runtime_namespace(namespace: str) -> None:
    if not isinstance(namespace, str) or not _RUNTIME_NAMESPACE_RE.fullmatch(namespace):
        raise SchedulerError("runtime_namespace must be 1-64 safe filename characters")


__all__ = [
    "RUNNER_CONFORMANCE_RECEIPT_SCHEMA_VERSION",
    "RUN_CHECKPOINT_SCHEMA_VERSION",
    "RUN_NAMESPACE_SCHEMA_VERSION",
    "RUN_REQUEST_SCHEMA_VERSION",
    "RUN_TERMINAL_RECEIPT_SCHEMA_VERSION",
    "RuntimePool",
    "RuntimeRunCheckpoint",
    "RuntimeRunRequest",
    "RuntimeRunStatus",
    "SchedulerError",
    "SchedulerRoots",
    "SchedulerTerminalReceipt",
    "submit_and_dispatch_once",
]
