#!/usr/bin/env python3
"""V3.7 A06 durable executor and scheduler gate.

This gate proves the software side of A06 without touching the protected
operator T7 target or starting a daemon. It exercises the on-demand scheduler
against a fixture SRF storage layout, verifies crash/restart reconciliation,
pool/backpressure behavior, pack governance waits, real subprocess dispatch,
terminal receipt binding, and disk-reserve admission before any ingest/spawn.

A PASS does not claim native T7-backed persistence is ACTIVE; it records the
remaining protected binding as WAIT_T7_BINDING.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.cas import T7_BINDING_WAIT_STATE, SrfStorageLayout, manifest_hash  # noqa: E402
from srl.contracts import object_id  # noqa: E402
from srl.execution import RunOutcome, RunStatus, RunUsage, load_policy  # noqa: E402
from srl.execution.estimate import ResourceEstimate  # noqa: E402
from srl.packs.governance import PackLifecycleStatus  # noqa: E402
from srl.runtime import (  # noqa: E402
    RUN_NAMESPACE_SCHEMA_VERSION,
    RuntimePool,
    RuntimeRunCheckpoint,
    RuntimeRunRequest,
    RuntimeRunStatus,
    SchedulerRoots,
    SchedulerTerminalReceipt,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A06"
POLICY_PATH: Final[Path] = REPO_ROOT / "policies" / "resource-policy-m1.json"


def _estimate() -> ResourceEstimate:
    return ResourceEstimate(wall_seconds=1, rss_bytes=1024, scratch_bytes=1024, cpu_cores=1)


def _request(request_id: str = "req-1", **overrides: Any) -> RuntimeRunRequest:
    payload: dict[str, Any] = {
        "request_id": request_id,
        "adapter_id": "echo.v1",
        "input_payload": {"value": request_id},
        "resource_estimate": _estimate(),
    }
    payload.update(overrides)
    return RuntimeRunRequest(**payload)


def _fixture_runner(
    request: RuntimeRunRequest,
    _policy: Any,
    _scratch: Path,
) -> RunOutcome:
    return RunOutcome(
        adapter_id=request.adapter_id,
        status=RunStatus.COMPLETED,
        output=request.input_payload,
        usage=RunUsage(wall_seconds=0.001, rss_bytes=1024, output_bytes=0),
        receipt_written=True,
        fail_reason=None,
        detail="fixture completed",
    )


def _new_roots(tmp: Path, name: str) -> SchedulerRoots:
    layout = SrfStorageLayout.at(tmp / name / "SRF")
    return SchedulerRoots.create_t7_work_namespace(layout, runtime_namespace="a06")


def _check_t7_work_namespace_and_real_dispatch(tmp: Path) -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    roots = _new_roots(tmp, "namespace")
    manifest = roots.namespace_manifest()
    submitted = roots.submit(_request("real-dispatch"), max_queued=2)
    terminal = roots.dispatch_next(policy=policy, max_queued=2)

    failures: list[str] = []
    if manifest.get("schema_version") != RUN_NAMESPACE_SCHEMA_VERSION:
        failures.append("runtime namespace schema drifted")
    if manifest.get("state_root_role") != "t7_work_spool_runtime_namespace":
        failures.append("runtime state root role is not T7 work/spool")
    if manifest.get("cas_root_role") != "t7_cold_cas":
        failures.append("runtime CAS root role is not T7 cold-cas")
    rendered = json.dumps(manifest, sort_keys=True)
    if "/Users/" in rendered or "/Volumes/" in rendered:
        failures.append("namespace manifest leaks local absolute paths")
    if not isinstance(submitted, RuntimeRunCheckpoint):
        failures.append("request was not queued before dispatch")
    if terminal is None or terminal.status is not RuntimeRunStatus.COMPLETED:
        failures.append("real subprocess dispatch did not complete")
    elif (
        terminal.run_receipt_id is None
        or terminal.engine_receipt_id is None
        or terminal.terminal_receipt_id is None
    ):
        failures.append("terminal receipt is not bound to run, engine and terminal ids")
    return {
        "check_id": "A06-01-t7-work-namespace-real-dispatch",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "fixture SRF layout persists FSM under work/spool, CAS under cold-cas, "
            "and real echo.v1 subprocess dispatch completes"
        ),
        "namespace_hash": manifest_hash(manifest),
        "terminal_bound": terminal is not None and terminal.terminal_receipt_id is not None,
        "run_bound": terminal is not None and terminal.run_receipt_id is not None,
        "engine_bound": terminal is not None and terminal.engine_receipt_id is not None,
        "t7_native_status": T7_BINDING_WAIT_STATE,
    }


def _check_crash_restart_exact_once(tmp: Path) -> dict[str, Any]:  # noqa: C901
    policy = load_policy(POLICY_PATH)
    roots = _new_roots(tmp, "crash")
    roots.submit(_request("crashy"), max_queued=2)

    def crashing_runner(
        _request: RuntimeRunRequest,
        _policy: Any,
        _scratch: Path,
    ) -> RunOutcome:
        raise RuntimeError("simulated process kill after input checkpoint")

    failures: list[str] = []
    try:
        roots.dispatch_next(policy=policy, max_queued=2, runner=crashing_runner)
        failures.append("crashing runner did not interrupt dispatch")
    except RuntimeError:
        pass

    running_path = roots.running / "crashy.json"
    input_digest = None
    if not running_path.exists():
        failures.append("interrupted dispatch did not preserve running checkpoint")
    else:
        running_payload = json.loads(running_path.read_text(encoding="utf-8"))
        input_digest = running_payload.get("input_digest")
        if not isinstance(input_digest, str) or not input_digest.startswith("sha256:"):
            failures.append("running checkpoint did not bind input digest before crash")

    recovered = roots.recover_interrupted()
    if len(recovered) != 1:
        failures.append(f"expected one recovered checkpoint, got {len(recovered)}")
    elif recovered[0].input_digest != input_digest:
        failures.append("recovered checkpoint did not preserve input digest")

    original_ingest = roots.store.ingest_bytes
    application_json_ingests = 0

    def counted_ingest(source_bytes: bytes, media_type: str, **kwargs: Any) -> Any:
        nonlocal application_json_ingests
        if media_type == "application/json":
            application_json_ingests += 1
        return original_ingest(source_bytes, media_type, **kwargs)

    roots.store.ingest_bytes = counted_ingest  # type: ignore[method-assign]
    terminal = roots.dispatch_next(policy=policy, max_queued=2, runner=_fixture_runner)
    if terminal is None or terminal.status is not RuntimeRunStatus.COMPLETED:
        failures.append("recovered dispatch did not complete exactly once")
    elif terminal.staged_input_digests.get("input.json") != input_digest:
        failures.append("recovered dispatch did not use the original input digest")
    if application_json_ingests != 0:
        failures.append("recovered dispatch re-imported input JSON")
    if len(list(roots.terminal.glob("crashy.json"))) != 1:
        failures.append("terminal receipt count is not exactly one")
    if list(roots.running.glob("*.json")):
        failures.append("running checkpoint remained after terminal completion")

    return {
        "check_id": "A06-02-crash-restart-exact-once",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "interrupted running checkpoint requeues once, reuses input digest, "
            "and writes exactly one terminal receipt"
        ),
        "recovered_count": len(recovered),
        "application_json_ingests_after_recovery": application_json_ingests,
        "terminal_count": len(list(roots.terminal.glob("*.json"))),
    }


def _check_no_double_result_or_import(tmp: Path) -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    roots = _new_roots(tmp, "double")
    terminal = roots.submit(_request("done"), max_queued=2)
    if not isinstance(terminal, RuntimeRunCheckpoint):
        raise AssertionError("unexpected submit terminal")
    completed = roots.dispatch_next(policy=policy, max_queued=2, runner=_fixture_runner)
    if not isinstance(completed, SchedulerTerminalReceipt):
        raise AssertionError("dispatch did not produce a terminal receipt")

    stale = RuntimeRunCheckpoint(
        request=_request("done"),
        status=RuntimeRunStatus.RUNNING,
        generation=completed.generation,
        sequence=99,
        input_digest=completed.staged_input_digests["input.json"],
    )
    (roots.running / "done.json").write_bytes(json.dumps(stale.to_dict()).encode("utf-8"))

    recovered = roots.recover_interrupted()
    resubmitted = roots.submit(_request("done"), max_queued=2)
    failures: list[str] = []
    if recovered:
        failures.append("stale running checkpoint with terminal receipt was requeued")
    if not isinstance(resubmitted, SchedulerTerminalReceipt):
        failures.append("resubmitting terminal request did not return existing receipt")
    elif resubmitted.terminal_receipt_id != completed.terminal_receipt_id:
        failures.append("resubmit returned a different terminal receipt id")
    if list(roots.queued.glob("*.json")) or list(roots.running.glob("*.json")):
        failures.append("stale recovery left active queue/running state")
    if len(list(roots.terminal.glob("done.json"))) != 1:
        failures.append("terminal directory contains duplicate result")
    return {
        "check_id": "A06-03-no-double-result-or-import",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "existing terminal receipt wins over stale running checkpoint and duplicate submit",
        "recovered_count": len(recovered),
        "terminal_count": len(list(roots.terminal.glob("*.json"))),
    }


def _check_pools_aging_backpressure(tmp: Path) -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    roots = _new_roots(tmp, "pools")
    roots.submit(_request("old", priority=0, pool=RuntimePool.LIGHT), max_queued=4)
    roots.submit(_request("new", priority=1, pool=RuntimePool.LIGHT), max_queued=4)
    aged_first = roots.dispatch_next(policy=policy, max_queued=4, runner=_fixture_runner)

    heavy_roots = _new_roots(tmp, "heavy")
    heavy_roots.submit(_request("heavy-a", pool=RuntimePool.HEAVY), max_queued=4)
    heavy_roots.submit(_request("heavy-b", pool=RuntimePool.HEAVY), max_queued=4)
    active = RuntimeRunCheckpoint(
        request=_request("heavy-running", pool=RuntimePool.HEAVY),
        status=RuntimeRunStatus.RUNNING,
        generation=2,
        sequence=99,
    )
    (heavy_roots.running / "heavy-running.json").write_bytes(
        json.dumps(active.to_dict()).encode("utf-8")
    )
    heavy_dispatch = heavy_roots.dispatch_next(policy=policy, max_queued=4, runner=_fixture_runner)

    pressure_roots = _new_roots(tmp, "pressure")
    pressure_roots.submit(_request("queued"), max_queued=1)
    pressured = pressure_roots.submit(_request("pressured"), max_queued=1)

    failures: list[str] = []
    if aged_first is None or aged_first.request_id != "old":
        failures.append("aging did not keep older request ahead of one-point newer priority")
    if heavy_dispatch is not None:
        failures.append("heavy pool dispatched while one M1 heavy checkpoint was running")
    if not isinstance(pressured, SchedulerTerminalReceipt):
        failures.append("backpressure did not terminalize overflow request")
    elif pressured.status is not RuntimeRunStatus.WAIT_BACKPRESSURE:
        failures.append(f"backpressure status was {pressured.status.value}")
    return {
        "check_id": "A06-04-pools-aging-backpressure",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "aging, heavy M1 single-concurrency and queue backpressure are enforced",
        "aged_first_request": aged_first.request_id if aged_first else None,
        "heavy_dispatch_started": heavy_dispatch is not None,
        "backpressure_status": pressured.status.value
        if isinstance(pressured, SchedulerTerminalReceipt)
        else "not-terminal",
    }


def _check_pack_revocation_and_disk_reserve(tmp: Path) -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    pack_roots = _new_roots(tmp, "pack")
    pack_roots.submit(_request("revoked-pack", pack_id="pack.revoked"), max_queued=2)
    pack_terminal = pack_roots.dispatch_next(
        policy=policy,
        max_queued=2,
        pack_statuses={"pack.revoked": PackLifecycleStatus.REVOKED},
        runner=_fixture_runner,
    )

    disk_roots = _new_roots(tmp, "disk")
    disk_roots.submit(_request("disk"), max_queued=2)
    calls = {"ingest": 0, "runner": 0}
    original_ingest = disk_roots.store.ingest_bytes

    def counted_ingest(source_bytes: bytes, media_type: str, **kwargs: Any) -> Any:
        calls["ingest"] += 1
        return original_ingest(source_bytes, media_type, **kwargs)

    def counted_runner(
        request: RuntimeRunRequest,
        runner_policy: Any,
        scratch: Path,
    ) -> RunOutcome:
        calls["runner"] += 1
        return _fixture_runner(request, runner_policy, scratch)

    disk_roots.store.ingest_bytes = counted_ingest  # type: ignore[method-assign]
    reserve_policy = replace(policy, required_free_disk_bytes=10**30)
    disk_terminal = disk_roots.dispatch_next(
        policy=reserve_policy,
        max_queued=2,
        runner=counted_runner,
    )

    failures: list[str] = []
    if pack_terminal is None or pack_terminal.status is not RuntimeRunStatus.WAIT_PACK_GOVERNANCE:
        failures.append("revoked pack was not parked before runner dispatch")
    if disk_terminal is None or disk_terminal.status is not RuntimeRunStatus.WAIT_LOCAL_DISK:
        failures.append("disk reserve did not park request before breach")
    if calls != {"ingest": 0, "runner": 0}:
        failures.append(f"disk reserve performed work before wait: {calls}")
    return {
        "check_id": "A06-05-pack-revocation-disk-reserve",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "revoked pack waits before runner and disk reserve prevents ingest/spawn",
        "pack_status": pack_terminal.status.value if pack_terminal else None,
        "disk_status": disk_terminal.status.value if disk_terminal else None,
        "pre_wait_calls": calls,
    }


def _build_receipt(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [check for check in checks if check["status"] != "PASS"]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "status": "FAIL" if failures else "PASS",
        "stage_closure": "SOFTWARE_DURABLE_SCHEDULER_T7_NATIVE_WAIT",
        "terminal_state": "A06_ACCEPTED_WAIT_T7_NATIVE_PERSISTENCE",
        "checks": checks,
        "protected_blockers": [
            "WAIT_T7_BINDING:A02_BIND_T7_NATIVE_TARGET",
            "WAIT_COMPUTE_TARGET:A05_BIND_NATIVE_SANDBOX_COMPUTE_TARGET",
        ],
        "canonical_writes": 0,
        "grants_authority": False,
    }
    payload["receipt_id"] = object_id(payload)
    return payload


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        checks = [
            _check_t7_work_namespace_and_real_dispatch(tmp),
            _check_crash_restart_exact_once(tmp),
            _check_no_double_result_or_import(tmp),
            _check_pools_aging_backpressure(tmp),
            _check_pack_revocation_and_disk_reserve(tmp),
        ]
    receipt = _build_receipt(checks)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
