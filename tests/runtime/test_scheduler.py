from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.cas.layout import SrfStorageLayout
from srl.execution import RunOutcome, RunStatus, RunUsage, load_policy
from srl.execution.estimate import ResourceEstimate
from srl.packs.governance import PackLifecycleStatus
from srl.runtime import (
    RUN_NAMESPACE_SCHEMA_VERSION,
    RuntimePool,
    RuntimeRunCheckpoint,
    RuntimeRunRequest,
    RuntimeRunStatus,
    SchedulerError,
    SchedulerRoots,
    SchedulerTerminalReceipt,
    submit_and_dispatch_once,
)

_POLICY_PATH = Path("policies/resource-policy-m1.json")


@pytest.fixture
def policy() -> Any:
    return load_policy(_POLICY_PATH)


@pytest.fixture
def roots(tmp_path: Path) -> SchedulerRoots:
    return SchedulerRoots.create(tmp_path / "runtime")


def _estimate() -> ResourceEstimate:
    return ResourceEstimate(wall_seconds=1, rss_bytes=1024, scratch_bytes=1024, cpu_cores=1)


def _request(request_id: str = "req-1", **overrides: Any) -> RuntimeRunRequest:
    data: dict[str, Any] = {
        "request_id": request_id,
        "adapter_id": "echo.v1",
        "input_payload": {"value": "hello"},
        "resource_estimate": _estimate(),
    }
    data.update(overrides)
    return RuntimeRunRequest(**data)


def _runner(request: RuntimeRunRequest, _policy: Any, _scratch: Path) -> RunOutcome:
    return RunOutcome(
        adapter_id=request.adapter_id,
        status=RunStatus.COMPLETED,
        output=request.input_payload,
        usage=RunUsage(wall_seconds=0.001, rss_bytes=1024, output_bytes=0),
        receipt_written=True,
        fail_reason=None,
        detail="fixture completed",
    )


def _valid_output(output: object) -> None:
    if not isinstance(output, dict) or "value" not in output:
        raise ValueError("bad output")


def test_submit_and_dispatch_seals_exactly_one_terminal_receipt(
    roots: SchedulerRoots, policy: Any
) -> None:
    receipt = submit_and_dispatch_once(
        roots,
        _request(),
        policy=policy,
        max_queued=4,
        runner=_runner,
        output_validator=_valid_output,
    )

    assert receipt.status is RuntimeRunStatus.COMPLETED
    assert receipt.sealed is True
    assert receipt.run_receipt_id is not None
    assert receipt.engine_receipt_id is not None
    assert receipt.staged_input_digests == {
        "input.json": receipt.staged_input_digests["input.json"]
    }
    assert len(list(roots.terminal.glob("req-1.json"))) == 1
    assert not list(roots.running.glob("*.json"))
    assert receipt.terminal_receipt_id is not None
    assert receipt.terminal_receipt_id.startswith("sha256:")


def test_backpressure_parks_request_without_queueing(roots: SchedulerRoots, policy: Any) -> None:
    queued = roots.submit(_request("req-a"), max_queued=1)
    assert isinstance(queued, RuntimeRunCheckpoint)

    parked = roots.submit(_request("req-b"), max_queued=1)

    assert isinstance(parked, SchedulerTerminalReceipt)
    assert parked.status is RuntimeRunStatus.WAIT_BACKPRESSURE
    assert parked.fail_reason == "WAIT_BACKPRESSURE"
    assert not (roots.queued / "req-b.json").exists()
    assert roots.dispatch_next(policy=policy, max_queued=1, runner=_runner) is not None


def test_cancel_queued_request_writes_terminal_receipt(
    roots: SchedulerRoots,
) -> None:
    roots.submit(_request(), max_queued=2)

    receipt = roots.cancel_request("req-1")

    assert isinstance(receipt, SchedulerTerminalReceipt)
    assert receipt.status is RuntimeRunStatus.CANCELLED
    assert not list(roots.queued.glob("*.json"))
    assert len(list(roots.terminal.glob("*.json"))) == 1


def test_cancel_running_checkpoint_terminalizes_on_recovery(roots: SchedulerRoots) -> None:
    checkpoint = RuntimeRunCheckpoint(
        request=_request(),
        status=RuntimeRunStatus.RUNNING,
        generation=2,
        sequence=1,
    )
    (roots.running / "req-1.json").write_bytes(json.dumps(checkpoint.to_dict()).encode("utf-8"))

    roots.cancel_request("req-1")
    recovered = roots.recover_interrupted()

    assert recovered == ()
    receipt = json.loads((roots.terminal / "req-1.json").read_text(encoding="utf-8"))
    assert receipt["status"] == RuntimeRunStatus.CANCELLED.value


def test_interrupted_running_checkpoint_requeues_for_resume(roots: SchedulerRoots) -> None:
    checkpoint = RuntimeRunCheckpoint(
        request=_request(),
        status=RuntimeRunStatus.RUNNING,
        generation=2,
        sequence=1,
    )
    (roots.running / "req-1.json").write_bytes(json.dumps(checkpoint.to_dict()).encode("utf-8"))

    recovered = roots.recover_interrupted()

    assert len(recovered) == 1
    assert recovered[0].generation == 3
    assert (roots.queued / "req-1.json").exists()
    assert not list(roots.running.glob("*.json"))


def test_stale_or_missing_pack_governance_parks_request(roots: SchedulerRoots, policy: Any) -> None:
    receipt = submit_and_dispatch_once(
        roots,
        _request(pack_id="pack.alpha"),
        policy=policy,
        max_queued=2,
        pack_statuses={"pack.alpha": PackLifecycleStatus.WAIT_SBOM},
        runner=_runner,
    )

    assert receipt.status is RuntimeRunStatus.WAIT_PACK_GOVERNANCE
    assert receipt.fail_reason == "WAIT_PACK_GOVERNANCE"
    assert receipt.sealed is False


def test_remote_executor_wait_for_estimate_over_policy(roots: SchedulerRoots, policy: Any) -> None:
    large = ResourceEstimate(
        wall_seconds=policy.exception.wall_seconds + 1,
        rss_bytes=policy.exception.rss_bytes + 1,
        scratch_bytes=policy.default.scratch_bytes + 1,
        cpu_cores=policy.exception.cpu_cores + 1,
    )
    receipt = submit_and_dispatch_once(
        roots,
        _request(resource_estimate=large),
        policy=policy,
        max_queued=2,
        runner=_runner,
    )

    assert receipt.status is RuntimeRunStatus.WAIT_REMOTE_EXECUTOR
    assert receipt.fail_reason == "WAIT_REMOTE_EXECUTOR"
    assert receipt.run_receipt_id is None


def test_dispatch_is_fifo_and_single_wip(roots: SchedulerRoots, policy: Any) -> None:
    roots.submit(_request("req-a"), max_queued=4)
    roots.submit(_request("req-b"), max_queued=4)
    active = RuntimeRunCheckpoint(
        request=_request("req-running"),
        status=RuntimeRunStatus.RUNNING,
        generation=2,
        sequence=99,
    )
    (roots.running / "req-running.json").write_bytes(json.dumps(active.to_dict()).encode("utf-8"))

    assert roots.dispatch_next(policy=policy, max_queued=4, runner=_runner) is None

    (roots.running / "req-running.json").unlink()
    first = roots.dispatch_next(policy=policy, max_queued=4, runner=_runner)

    assert first is not None
    assert first.request_id == "req-a"
    assert (roots.queued / "req-b.json").exists()


def test_t7_work_namespace_uses_spool_state_and_cold_cas(tmp_path: Path) -> None:
    layout = SrfStorageLayout.at(tmp_path / "SRF")
    roots = SchedulerRoots.create_t7_work_namespace(layout, runtime_namespace="a06")

    manifest = roots.namespace_manifest()

    assert roots.root == layout.work_path("spool") / "a06"
    assert roots.store.objects_dir == layout.cold_cas / "objects"
    assert manifest["schema_version"] == RUN_NAMESPACE_SCHEMA_VERSION
    assert manifest["state_root_role"] == "t7_work_spool_runtime_namespace"
    assert manifest["cas_root_role"] == "t7_cold_cas"
    assert manifest["heavy_m1_concurrency"] == 1


def test_priority_aging_prefers_older_small_delta(roots: SchedulerRoots, policy: Any) -> None:
    roots.submit(_request("old", priority=0), max_queued=4)
    roots.submit(_request("new", priority=1), max_queued=4)

    first = roots.dispatch_next(policy=policy, max_queued=4, runner=_runner)

    assert first is not None
    assert first.request_id == "old"


def test_heavy_pool_keeps_m1_single_concurrency(roots: SchedulerRoots, policy: Any) -> None:
    roots.submit(_request("heavy-a", pool=RuntimePool.HEAVY), max_queued=4)
    roots.submit(_request("heavy-b", pool=RuntimePool.HEAVY), max_queued=4)
    active = RuntimeRunCheckpoint(
        request=_request("heavy-running", pool=RuntimePool.HEAVY),
        status=RuntimeRunStatus.RUNNING,
        generation=2,
        sequence=99,
    )
    (roots.running / "heavy-running.json").write_bytes(json.dumps(active.to_dict()).encode("utf-8"))

    assert roots.dispatch_next(policy=policy, max_queued=4, runner=_runner) is None
    assert len(list(roots.running.glob("*.json"))) == 1
    assert len(list(roots.queued.glob("heavy-*.json"))) == 2


def test_disk_reserve_waits_before_ingest_or_runner(
    roots: SchedulerRoots, policy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots.submit(_request(), max_queued=2)
    calls = {"runner": 0, "ingest": 0}

    def counted_ingest(*args: Any, **kwargs: Any) -> Any:
        calls["ingest"] += 1
        return original_ingest(*args, **kwargs)

    def counted_runner(request: RuntimeRunRequest, _policy: Any, _scratch: Path) -> RunOutcome:
        calls["runner"] += 1
        return _runner(request, _policy, _scratch)

    original_ingest = roots.store.ingest_bytes
    monkeypatch.setattr(roots.store, "ingest_bytes", counted_ingest)
    reserve_policy = policy.__class__(
        name=policy.name,
        concurrency=policy.concurrency,
        default=policy.default,
        exception=policy.exception,
        overflow_action=policy.overflow_action,
        required_free_disk_bytes=10**30,
        canonical_writes=policy.canonical_writes,
        grants_authority=policy.grants_authority,
    )

    receipt = roots.dispatch_next(policy=reserve_policy, max_queued=2, runner=counted_runner)

    assert receipt is not None
    assert receipt.status is RuntimeRunStatus.WAIT_LOCAL_DISK
    assert calls == {"runner": 0, "ingest": 0}


def test_crash_recovery_reuses_input_digest_and_writes_one_terminal(
    roots: SchedulerRoots, policy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots.submit(_request(), max_queued=2)

    def crashing_runner(_request: RuntimeRunRequest, _policy: Any, _scratch: Path) -> RunOutcome:
        raise RuntimeError("simulated process kill after input checkpoint")

    with pytest.raises(RuntimeError, match="simulated process kill"):
        roots.dispatch_next(policy=policy, max_queued=2, runner=crashing_runner)

    running_payload = json.loads((roots.running / "req-1.json").read_text(encoding="utf-8"))
    input_digest = running_payload["input_digest"]
    assert input_digest.startswith("sha256:")
    assert not list(roots.terminal.glob("*.json"))

    recovered = roots.recover_interrupted()
    assert len(recovered) == 1
    assert recovered[0].input_digest == input_digest
    assert not list(roots.running.glob("*.json"))

    original_ingest = roots.store.ingest_bytes
    application_json_ingests = 0

    def counted_ingest(source_bytes: bytes, media_type: str, **kwargs: Any) -> Any:
        nonlocal application_json_ingests
        if media_type == "application/json":
            application_json_ingests += 1
        return original_ingest(source_bytes, media_type, **kwargs)

    monkeypatch.setattr(roots.store, "ingest_bytes", counted_ingest)

    receipt = roots.dispatch_next(policy=policy, max_queued=2, runner=_runner)

    assert receipt is not None
    assert receipt.status is RuntimeRunStatus.COMPLETED
    assert receipt.staged_input_digests["input.json"] == input_digest
    assert application_json_ingests == 0
    assert len(list(roots.terminal.glob("req-1.json"))) == 1
    assert not list(roots.running.glob("*.json"))


def test_invalid_request_id_rejected() -> None:
    with pytest.raises(SchedulerError):
        _request("../bad")
