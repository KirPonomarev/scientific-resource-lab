"""The fixed-entrypoint bounded runner (WP-D31).

:func:`run_adapter` is the single entry point the orchestrator calls to execute
a scientific step locally. It is **bounded** on every axis that can escape:

- **fixed entrypoint**: the adapter id is looked up in the static registry (see
  :mod:`srl.execution.entrypoints`). An unknown id — including anything that
  looks like command injection — raises before any process is created.
- **subprocess sandbox**: the handler runs in a child process with a sanitized
  environment, a private scratch dir, POSIX resource limits, a process-group
  watchdog, and capped output capture (see :mod:`srl.execution.sandbox`).
- **wall timeout**: the child is killed if it runs past ``policy.wall_seconds``.
- **receipt-last**: a run receipt is written to scratch *only after* output
  validation passes. A policy/limit violation never produces a receipt.

The runner is standard library only and imports nothing from the scientific
contracts layer. The run receipt is a plain canonical-JSON dict (no
``RunReceipt`` dependency on :mod:`srl.semantic.evidence`); it is an
execution-engine concern, not a scientific-evidence one.

Outcome taxonomy
----------------
A :class:`RunOutcome` carries a :class:`RunStatus`:

- ``completed`` — the child exited 0 and its output validated;
- ``failed`` — the child exited 2 (contract/handler failure);
- ``timeout`` — the wall watchdog killed the child;
- ``resource_limit`` — an output cap or RLIMIT fired (no orphan);
- ``policy_violation`` — an orphan survived the watchdog kill (hard stop).

``output`` is the validated handler dict on ``completed`` and ``None``
otherwise. ``receipt_written`` is ``True`` only on ``completed``.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from srl.execution import sandbox
from srl.execution.entrypoints import UnknownAdapterError, get_adapter, validate_output
from srl.execution.policy import PolicyError, ResourcePolicy

# Canonical JSON separators and newline contract, mirroring the execution pkg.
_SEP: Final[tuple[str, str]] = (",", ":")
_NEWLINE: Final[str] = "\n"
_ENCODING: Final[str] = "utf-8"

# The fixed module the runner spawns. There is exactly one child entrypoint;
# the adapter id is an argument to it, not a command.
_CHILD_MODULE: Final[str] = "srl.execution.child"

# The schema identity for the run receipt written on success.
RUN_RECEIPT_SCHEMA_VERSION: Final[str] = "RunReceipt/v1"

# The typed fail reason surfaced on a policy violation (orphan survivor). The
# runner records it on the outcome; the orchestrator routes via fail-reasons.
POLICY_VIOLATION_FAIL_REASON: Final[str] = sandbox.ORPHAN_FAIL_REASON


class RunStatus(StrEnum):
    """The outcome status of a bounded run.

    ``StrEnum`` keeps the serialized form a plain JSON string while giving enum
    membership tests. The five members cover every bounded-run outcome; a
    receipt is written only for ``completed``.
    """

    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    POLICY_VIOLATION = "policy_violation"


@dataclass(frozen=True)
class RunUsage:
    """Observed resource usage of one run.

    Attributes
    ----------
    wall_seconds:
        Elapsed wall-clock seconds from spawn to reap (``>= 0``).
    rss_bytes:
        Peak resident set size in bytes from :func:`resource.getrusage`
        (``ru_maxrss``). On macOS the unit is bytes; on Linux it is KiB — the
        runner normalises to bytes.
    output_bytes:
        Total captured output bytes (stdout + stderr, post-cap).
    """

    wall_seconds: float
    rss_bytes: int
    output_bytes: int

    def to_dict(self) -> dict[str, Any]:
        """Return the usage as a canonical-key-order dict."""
        return {
            "wall_seconds": self.wall_seconds,
            "rss_bytes": self.rss_bytes,
            "output_bytes": self.output_bytes,
        }


@dataclass(frozen=True)
class RunOutcome:
    """The result of :func:`run_adapter`.

    Attributes
    ----------
    adapter_id:
        The adapter id that ran (echoed for receipt/identity context).
    status:
        The :class:`RunStatus`.
    output:
        The validated handler dict on ``completed``; ``None`` otherwise.
    usage:
        Observed :class:`RunUsage` (wall, rss, output bytes).
    receipt_written:
        ``True`` iff a ``RunReceipt/v1`` was written to scratch. Only ``True``
        on ``completed`` (receipt-last invariant).
    fail_reason:
        Typed fail reason for a non-completed status, or ``None`` on success.
    detail:
        Short human-readable diagnostic (e.g. the exit code, the cap hit).
    """

    adapter_id: str
    status: RunStatus
    output: dict[str, Any] | None
    usage: RunUsage
    receipt_written: bool
    fail_reason: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """Return the outcome as a canonical dict (no ``output`` payload body).

        The receipt embeds status, usage, and the receipt flag, but not the full
        output payload (the payload lives in its own canonical file in scratch).
        """
        return {
            "adapter_id": self.adapter_id,
            "status": self.status.value,
            "usage": self.usage.to_dict(),
            "receipt_written": self.receipt_written,
            "fail_reason": self.fail_reason,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _canonical_dump(obj: Any) -> bytes:
    """Encode ``obj`` as canonical JSON bytes (sorted, compact, UTF-8, newline)."""
    text = json.dumps(obj, sort_keys=True, separators=_SEP, ensure_ascii=False, allow_nan=False)
    return (text + _NEWLINE).encode(_ENCODING)


def _srl_src_root() -> str | None:
    """Return the ``src/`` directory containing the ``srl`` package, if any.

    The fixed child entrypoint (``-m srl.execution.child``) must be able to
    import ``srl``. In an installed environment the package is already on
    ``sys.path`` and this returns ``None`` (no ``PYTHONPATH`` needed). In a dev
    checkout (``PYTHONPATH=src`` or running from source) this returns the path
    to ``src/`` so the runner can pass it to the child env explicitly.

    Derivation: the ``srl.execution.runner`` module's ``__file__`` is at
    ``<src>/srl/execution/runner.py``; three parents up is ``<src>``. We confirm
    the resolved path actually contains ``srl/__init__.py`` before returning it
    so a relocated/imported-from-zip layout returns ``None`` rather than a wrong
    path.
    """
    try:
        here = Path(__file__).resolve()
    except OSError:
        return None
    src_root = here.parents[2]  # .../src
    if (src_root / "srl" / "__init__.py").is_file():
        return str(src_root)
    return None


def _materialize_input(input_payload: Any, scratch: Path, adapter_id: str) -> Path:
    """Write ``input_payload`` as canonical JSON into ``scratch``; chmod 0o400.

    The input file is the only data the child reads. After writing, it is made
    read-only (0o400) so the child cannot mutate its own input and so a
    tamper-attempt surfaces as an OSError. The filename includes a random suffix
    so two runs of the same adapter in one scratch dir do not collide on the
    read-only re-write.
    """
    suffix = secrets.token_hex(4)
    safe_id = adapter_id.replace(".", "_").replace("/", "_")
    in_path = scratch / f"input-{os.getpid()}-{safe_id}-{suffix}.json"
    in_path.write_bytes(_canonical_dump(input_payload))
    os.chmod(in_path, 0o400)
    return in_path


def _normalize_rss(ru_maxrss: int) -> int:
    """Normalise ``ru_maxrss`` to bytes.

    POSIX :func:`resource.getrusage` reports ``ru_maxrss`` in KiB on Linux and
    in bytes on macOS/BSD. The runner reports a single byte unit everywhere.
    """
    if ru_maxrss <= 0:
        return 0
    # Compare against a runtime str (not the literal sys.platform, which mypy
    # narrows to a single value under --platform and would flag the else branch
    # as unreachable on Linux CI).
    platform_name: str = sys.platform
    if platform_name == "linux":
        return ru_maxrss * 1024
    return ru_maxrss


def _write_receipt(
    scratch: Path, adapter_id: str, usage: RunUsage, output_path: Path | None
) -> Path:
    """Write the ``RunReceipt/v1`` JSON into ``scratch``; return its path.

    The receipt is canonical JSON: schema version, adapter id, status, usage,
    and the path to the validated output. It is written *only* on ``completed``
    (the caller enforces receipt-last by calling this after output validation).
    """
    body: dict[str, Any] = {
        "schema_version": RUN_RECEIPT_SCHEMA_VERSION,
        "adapter_id": adapter_id,
        "status": RunStatus.COMPLETED.value,
        "usage": usage.to_dict(),
        "output_path": str(output_path) if output_path else None,
    }
    blob = _canonical_dump(body)
    digest = hashlib.sha256(blob).hexdigest()
    receipt_path = scratch / f"receipt-{digest[:16]}.json"
    receipt_path.write_bytes(blob)
    return receipt_path


@dataclass
class _SpawnDeps:
    """Injectable spawn dependencies, so tests can swap the executor.

    The runner builds a :class:`subprocess.Popen` with the sandbox env, limits,
    and process group. Tests inject a factory that returns a fake ``Popen``-like
    object to assert the *command* without spawning anything.
    """

    popen_factory: Any = subprocess.Popen
    preexec_factory: Any = sandbox.make_preexec
    env_builder: Any = sandbox.build_child_env
    resource_limits: Any = None  # ResourceLimits | None; None -> derive from policy


def _build_command(adapter_id: str, input_path: Path, output_path: Path) -> list[str]:
    """Build the fixed child command line. No shell, no interpolation.

    The adapter id is passed *positionally* to ``-m srl.execution.child`` and is
    never embedded in a shell string, so an adapter id containing shell
    metacharacters is inert. There is no ``shell=True`` anywhere in the runner.
    """
    return [sys.executable, "-m", _CHILD_MODULE, adapter_id, str(input_path), str(output_path)]


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def run_adapter(  # noqa: PLR0913 (kw-only set IS the run's tunable set)
    adapter_id: str,
    input_payload: Any,
    policy: ResourcePolicy,
    scratch: Path,
    *,
    wall_seconds: int | None = None,
    output_cap_bytes: int = sandbox.DEFAULT_OUTPUT_CAP_BYTES,
    deps: _SpawnDeps | None = None,
) -> RunOutcome:
    """Run ``adapter_id`` on ``input_payload`` under ``policy``; return the outcome.

    The runner validates the adapter id *first* (raising before any process is
    created), materialises the input as a read-only canonical-JSON file in
    ``scratch``, spawns the fixed child module under the sandbox, enforces the
    wall timeout via the process-group watchdog, captures output with byte caps,
    validates the child's output against the adapter's output schema, and
    returns a :class:`RunOutcome`.

    Parameters
    ----------
    adapter_id:
        The adapter to run. Must be in the static registry.
    input_payload:
        The JSON-serialisable payload (validated against the adapter input
        schema inside the child).
    policy:
        The loaded :class:`ResourcePolicy`. Its ``wall_seconds`` and
        ``rss_bytes`` bound the run.
    scratch:
        A private scratch directory (see :func:`srl.execution.sandbox.prepare_scratch`).
    wall_seconds:
        Optional override for the wall cap (defaults to
        ``policy.default.wall_seconds``). Tests pass a short value (2-5 s).
    output_cap_bytes:
        Per-stream byte cap for stdout/stderr (default 1 MiB).
    deps:
        Injectable spawn dependencies for tests.

    Returns
    -------
    RunOutcome
        The bounded run result.

    Raises
    ------
    UnknownAdapterError
        If ``adapter_id`` is not in the static registry. Raised *before* any
        process is created (command-injection guard).
    PolicyError
        If ``policy`` is structurally invalid for running (e.g. wall <= 0).
    """
    # 1. Validate the adapter id FIRST. An unknown id (including anything that
    #    looks like command injection) raises here, before any subprocess exists.
    get_adapter(adapter_id)

    deps = deps or _SpawnDeps()
    wall = wall_seconds if wall_seconds is not None else policy.default.wall_seconds
    if wall <= 0:
        msg = f"policy wall_seconds must be > 0, got {wall}"
        raise PolicyError(msg)

    # 2. Materialise input as a read-only canonical JSON file in scratch.
    input_path = _materialize_input(input_payload, scratch, adapter_id)
    out_suffix = secrets.token_hex(4)
    out_safe = adapter_id.replace(".", "_").replace("/", "_")
    output_path = scratch / f"output-{os.getpid()}-{out_safe}-{out_suffix}.json"

    # 3. Build the sandbox: env, limits, preexec, command.
    # Derive the in-repo srl package root so the fixed ``-m srl.execution.child``
    # entrypoint is importable in the child. This is not a leak of parent
    # secrets: it points at the same package the orchestrator is running from.
    # In an installed env (venv) the package is already importable and this is a
    # harmless redundant prefix; in a dev checkout it is required.
    # The test-gate env var is forwarded only if the caller set it (the runner
    # never sets it itself); this lets the WP-D31 gate load test adapters.
    env = deps.env_builder(
        home_dir=scratch,
        tmp_dir=scratch,
        pythonpath=_srl_src_root(),
        forward_test_gate=True,
    )
    limits = deps.resource_limits or sandbox.ResourceLimits(
        rss_bytes=policy.default.rss_bytes,
        # CPU cap is wall + a small slack so a CPU-bound child is killed by
        # SIGXCPU just after its wall budget, before the watchdog's grace.
        cpu_seconds=max(1, wall + 1),
        fsize_bytes=output_cap_bytes,
    )
    preexec = deps.preexec_factory(limits)
    # The adapter id is a positional argument; no shell, no interpolation.
    cmd = _build_command(adapter_id, input_path, output_path)

    started = time.monotonic()
    popen_kwargs: dict[str, Any] = {
        "args": cmd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "start_new_session": True,
        "close_fds": True,
    }
    # preexec_fn is POSIX-only; the child module path is the entrypoint on all
    # platforms, but resource limits require POSIX. On non-POSIX we skip the
    # preexec (the sandbox still sanitises env + caps output).
    if sys.platform != "win32":
        popen_kwargs["preexec_fn"] = preexec

    # A preexec failure (e.g. a limit that cannot be applied) surfaces from
    # subprocess as ``SubprocessError("Exception occurred in preexec_fn.")`` —
    # the original exception is not re-raised. We catch it and translate it to a
    # resource_limit outcome so the run aborts cleanly with no child and no
    # receipt. The original cause is preserved via ``__cause__`` where possible.
    try:
        proc = deps.popen_factory(**popen_kwargs)
    except subprocess.SubprocessError as exc:
        if "preexec_fn" in str(exc):
            elapsed = max(0.0, time.monotonic() - started)
            usage = RunUsage(
                wall_seconds=round(elapsed, 6),
                rss_bytes=0,
                output_bytes=0,
            )
            return RunOutcome(
                adapter_id=adapter_id,
                status=RunStatus.RESOURCE_LIMIT,
                output=None,
                usage=usage,
                receipt_written=False,
                fail_reason=sandbox.RESOURCE_LIMIT_FAIL_REASON,
                detail=f"limit setup failed before exec; no child ran: {exc}",
            )
        raise

    # 4. Watch the child: drain output with caps, enforce the wall timeout.
    ctx = _RunContext(
        proc=proc,
        started=started,
        wall=wall,
        cap=output_cap_bytes,
        adapter_id=adapter_id,
        output_path=output_path,
        scratch=scratch,
    )
    return _watch(ctx)


@dataclass(frozen=True)
class _RunContext:
    """The fixed parameters of a run, bundled for the classify/watch helpers.

    Carrying these as one value object keeps ``_classify`` / ``_classify_exit``
    / ``_watch`` under the argument-count limit (PLR0913) and makes the call
    sites read as a single handoff rather than a long positional list.

    Attributes
    ----------
    proc:
        The spawned child process (a ``subprocess.Popen`` or a test double).
    started:
        The ``time.monotonic()`` reading at spawn, for elapsed-wall accounting.
    wall:
        The wall cap in seconds.
    cap:
        The per-stream output byte cap.
    adapter_id:
        The adapter id that ran.
    output_path:
        The path the child is expected to write its canonical output to.
    scratch:
        The private scratch directory (receipts are written here).
    """

    proc: Any
    started: float
    wall: int
    cap: int
    adapter_id: str
    output_path: Path
    scratch: Path


def _drain_and_wait(proc: Any, wall: int, cap: int) -> tuple[bool, sandbox.CapturedOutput]:
    """Drain the child's stdout/stderr with caps and enforce the wall timeout.

    Returns ``(timed_out, captured)``. On timeout the process group is killed by
    the watchdog before this returns. The captured streams are each bounded by
    ``cap`` bytes; ``captured.truncated`` is set if either hit the cap.
    """
    stdout_reader = sandbox._CappedReader(proc.stdout, cap)
    stderr_reader = sandbox._CappedReader(proc.stderr, cap)
    t_out = threading.Thread(target=stdout_reader.run, daemon=True)
    t_err = threading.Thread(target=stderr_reader.run, daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=wall)
    except subprocess.TimeoutExpired:
        timed_out = True
        sandbox._kill_group(proc)

    t_out.join(timeout=sandbox._GRACE_SECONDS + 1)
    t_err.join(timeout=sandbox._GRACE_SECONDS + 1)

    # Close the child pipes to avoid ResourceWarning on unclosed file handles.
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass

    captured = sandbox.CapturedOutput(
        stdout=stdout_reader.bytes,
        stderr=stderr_reader.bytes,
        truncated=stdout_reader.truncated or stderr_reader.truncated,
    )
    return timed_out, captured


def _build_usage(captured: sandbox.CapturedOutput, started: float) -> RunUsage:
    """Assemble the :class:`RunUsage` from elapsed wall and reaped-child RSS."""
    elapsed = max(0.0, time.monotonic() - started)
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return RunUsage(
        wall_seconds=round(elapsed, 6),
        rss_bytes=_normalize_rss(ru.ru_maxrss),
        output_bytes=len(captured.stdout) + len(captured.stderr),
    )


def _classify(ctx: _RunContext, timed_out: bool, captured: sandbox.CapturedOutput) -> RunOutcome:
    """Classify the drained run into a :class:`RunOutcome` (receipt-last).

    Order of checks: orphan (hard stop) -> output cap -> timeout -> exit code.
    A receipt is written only on a clean exit (0) with validated output.
    """
    orphan_msg = ""
    try:
        sandbox.verify_no_orphan(ctx.proc)
    except sandbox.OrphanDetectedError as exc:
        orphan_msg = str(exc)

    usage = _build_usage(captured, ctx.started)

    if orphan_msg:
        return RunOutcome(
            adapter_id=ctx.adapter_id,
            status=RunStatus.POLICY_VIOLATION,
            output=None,
            usage=usage,
            receipt_written=False,
            fail_reason=POLICY_VIOLATION_FAIL_REASON,
            detail=orphan_msg,
        )
    if captured.truncated:
        return RunOutcome(
            adapter_id=ctx.adapter_id,
            status=RunStatus.RESOURCE_LIMIT,
            output=None,
            usage=usage,
            receipt_written=False,
            fail_reason=sandbox.RESOURCE_LIMIT_FAIL_REASON,
            detail=(
                f"output exceeded the {ctx.cap}-byte per-stream cap; "
                f"captured {usage.output_bytes} bytes"
            ),
        )
    if timed_out:
        elapsed = max(0.0, time.monotonic() - ctx.started)
        return RunOutcome(
            adapter_id=ctx.adapter_id,
            status=RunStatus.TIMEOUT,
            output=None,
            usage=usage,
            receipt_written=False,
            fail_reason=sandbox.RESOURCE_LIMIT_FAIL_REASON,
            detail=f"wall timeout after {ctx.wall}s (elapsed {elapsed:.3f}s)",
        )
    return _classify_exit(ctx, captured, usage)


def _classify_exit(
    ctx: _RunContext, captured: sandbox.CapturedOutput, usage: RunUsage
) -> RunOutcome:
    """Classify a non-timed-out run by the child exit code (receipt-last)."""
    rc = ctx.proc.returncode
    if rc == 0:
        return _completed_outcome(ctx, usage)
    return _failed_exit_outcome(ctx, captured, usage, rc)


def _completed_outcome(ctx: _RunContext, usage: RunUsage) -> RunOutcome:
    """Build the completed outcome: validate output, then write the receipt."""
    try:
        raw = ctx.output_path.read_bytes()
        payload = json.loads(raw)
        validated = validate_output(ctx.adapter_id, payload)
    except (UnknownAdapterError, json.JSONDecodeError, OSError, ValueError) as exc:
        return RunOutcome(
            adapter_id=ctx.adapter_id,
            status=RunStatus.FAILED,
            output=None,
            usage=usage,
            receipt_written=False,
            fail_reason=None,
            detail=f"output validation failed: {exc}",
        )
    # Receipt-last: write the receipt ONLY after output validation passes.
    receipt_path = _write_receipt(ctx.scratch, ctx.adapter_id, usage, ctx.output_path)
    return RunOutcome(
        adapter_id=ctx.adapter_id,
        status=RunStatus.COMPLETED,
        output=validated,
        usage=usage,
        receipt_written=True,
        fail_reason=None,
        detail=f"completed; receipt at {receipt_path.name}",
    )


def _failed_exit_outcome(
    ctx: _RunContext, captured: sandbox.CapturedOutput, usage: RunUsage, rc: int
) -> RunOutcome:
    """Build the failed outcome for a non-zero, non-timeout child exit."""
    detail = f"child exited {rc}"
    if captured.stderr:
        first = captured.stderr.decode(_ENCODING, errors="replace").strip().splitlines()
        if first:
            detail += f": {first[0][:200]}"
    return RunOutcome(
        adapter_id=ctx.adapter_id,
        status=RunStatus.FAILED,
        output=None,
        usage=usage,
        receipt_written=False,
        fail_reason=None,
        detail=detail,
    )


def _watch(ctx: _RunContext) -> RunOutcome:
    """Drain output with caps, enforce the wall timeout, and classify the run.

    Two reader threads drain stdout/stderr into capped buffers; the main thread
    waits up to ``wall`` seconds. On timeout it kills the group and verifies no
    orphan. On a truncated stream (over-cap) it kills the group and classifies
    the run as ``resource_limit``. On a clean exit it reads/validates output.
    """
    timed_out, captured = _drain_and_wait(ctx.proc, ctx.wall, ctx.cap)
    return _classify(ctx, timed_out, captured)


def build_command_for(adapter_id: str, input_path: Path, output_path: Path) -> list[str]:
    """Return the fixed child command line for the given paths.

    Exposed for tests and the conformance gate so they can assert the exact
    command shape: the interpreter, the fixed ``-m srl.execution.child`` module,
    and the adapter id / paths as positional arguments. No shell, no
    interpolation; the adapter id is inert even if it contains metacharacters.
    """
    return [sys.executable, "-m", _CHILD_MODULE, adapter_id, str(input_path), str(output_path)]


__all__ = [
    "POLICY_VIOLATION_FAIL_REASON",
    "RUN_RECEIPT_SCHEMA_VERSION",
    "RunOutcome",
    "RunStatus",
    "RunUsage",
    "build_command_for",
    "run_adapter",
]
