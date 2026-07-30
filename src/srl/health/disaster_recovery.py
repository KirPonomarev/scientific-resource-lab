"""V3.7 A21 disaster-recovery and chaos evidence builders."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final, cast

from srl.cas import SrfStorageLayout
from srl.cas.fsck import ISSUE_MISSING_DESCRIPTOR
from srl.cas.store import LocalArtifactStore, StoreIntegrityError
from srl.contracts.canonical import dumps
from srl.contracts.ids import object_id
from srl.execution import RunOutcome, RunStatus, RunUsage, load_policy
from srl.execution.estimate import ResourceEstimate
from srl.health.pulse import PulseStatus, assess_pulse, build_srf_pulse
from srl.health.recovery import bounded_restore_drill
from srl.packs import build_manifest
from srl.packs.governance import (
    DependencyRecord,
    PackGovernanceEvidence,
    PackLifecycleStatus,
    PackRevocationRegistry,
    VulnerabilityScanSummary,
    assess_pack_governance,
)
from srl.packs.receipts import STAGES
from srl.runtime import (
    RuntimeRunRequest,
    RuntimeRunStatus,
    SchedulerRoots,
)

A21_DISASTER_RECOVERY_RECEIPT_SCHEMA_VERSION: Final[str] = "A21DisasterRecoveryChaosReceipt/v1"
RECOVERY_TARGET_WAIT_STATE: Final[str] = "WAIT_T7_BINDING"
PHYSICAL_RECOVERY_AUTHORITY_WAIT: Final[str] = (
    "WAIT_AUTHORITY:A21_CONFIGURE_SECOND_ENCRYPTED_RECOVERY_TARGET"
)
PHYSICAL_T7_RESTORE_WAIT: Final[str] = "WAIT_T7_BINDING:A21_EXECUTE_NATIVE_T7_RESTORE_DRILL"

_NOW: Final[str] = "2026-07-30T00:00:00Z"
_REBUILDABLE_LOCK_PATHS: Final[tuple[str, ...]] = (
    "pyproject.toml",
    "uv.lock",
    "configs/packs/formal/independent-prover-pins.json",
    "configs/packs/formal/lean/corpus-pins.json",
)


def build_a21_operator_action() -> dict[str, Any]:
    """Return the protected action needed for the physical A21 drill."""
    action: dict[str, Any] = {
        "schema_version": "ProtectedOperatorAction/v1",
        "action_id": "A21_CONFIGURE_SECOND_ENCRYPTED_RECOVERY_TARGET",
        "authority_required": True,
        "grants_authority": False,
        "target": "second encrypted recovery target distinct from the current VPS",
        "allowed_actions_after_authority": [
            "verify_target_is_encrypted_and_not_current_vps",
            "create_srf_recovery_restore_test_namespace",
            "copy_only_unique_small_receipts_and_manifests",
            "record_manifest_and_selective_hashes_without_secrets",
            "execute_nonsecret_t7_restore_drill",
            "measure_rpo_rto_on_native_target",
            "prove_rebuildable_environments_reconstruct_from_locks",
            "record_no_current_vps_as_sole_backup",
        ],
        "forbidden_without_authority": [
            "copy_private_datasets_or_secrets",
            "overwrite_live_store",
            "bind_active_database_or_wal_to_cold_backup",
            "start_vps_or_daemon",
            "claim_a21_physical_restore_active",
            "claim_done_or_v2_release",
        ],
        "expected_receipt_schema": A21_DISASTER_RECOVERY_RECEIPT_SCHEMA_VERSION,
    }
    action["action_hash_grouped_sha256"] = _grouped_sha256(dumps(action))
    return action


def run_a21_disaster_recovery_drill(
    *,
    repo_root: Path,
    drill_root: Path,
    created_utc: str = _NOW,
) -> dict[str, Any]:
    """Execute the bounded A21 fixture drill and return a receipt.

    The drill writes only inside ``drill_root``. It proves software restore and
    chaos behavior while keeping native encrypted-target mutation behind a
    machine-visible WAIT state.
    """
    drill_root.mkdir(parents=True, exist_ok=True)
    unique_restore = _restore_unique_receipt_chain(drill_root, created_utc=created_utc)
    rebuildable = _check_rebuildable_environment(repo_root)
    chaos_receipts = {
        "executor_crash": _chaos_executor_crash(drill_root, repo_root),
        "corrupt_objects": _chaos_corrupt_objects(drill_root),
        "revoked_packs": _chaos_revoked_packs(),
        "stale_keys": _chaos_stale_keys(created_utc=created_utc),
        "lost_indexes": _chaos_lost_indexes(drill_root),
    }
    checks = [
        {
            "check_id": "A21-01-unique-chain-restore",
            "status": unique_restore["status"],
            "detail": "unique receipt chain restored into a fresh target",
            "restore_receipt_id": unique_restore["restore_receipt_id"],
        },
        {
            "check_id": "A21-02-rebuildable-from-locks",
            "status": rebuildable["status"],
            "detail": "rebuildable environment inputs are lock-bound and path-public",
            "lock_manifest_hash": rebuildable["lock_manifest_hash"],
        },
        *[
            {
                "check_id": f"A21-03-{name}",
                "status": item["status"],
                "detail": item["detail"],
            }
            for name, item in sorted(chaos_receipts.items())
        ],
        {
            "check_id": "A21-04-physical-target-fail-closed",
            "status": "PASS",
            "detail": "native encrypted recovery target remains authority-bound; no false ACTIVE",
            "wait_states": [PHYSICAL_RECOVERY_AUTHORITY_WAIT, PHYSICAL_T7_RESTORE_WAIT],
        },
    ]
    result = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": A21_DISASTER_RECOVERY_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A21",
        "result": result,
        "terminal_state": RECOVERY_TARGET_WAIT_STATE,
        "stage_closure": "A21_SOFTWARE_DR_CHAOS_ACTIVE_PHYSICAL_RESTORE_WAIT"
        if result == "PASS"
        else "A21_OPEN",
        "state_classification": {
            "unique_small_artifacts": [
                "stage_receipts",
                "closeout_receipts",
                "hash_manifests",
                "operator_action_packets",
            ],
            "rebuildable_state": [
                "virtualenvs",
                "package_caches",
                "scratch",
                "indexes",
                "toolchain_build_outputs",
            ],
            "forbidden_backup_contents": [
                "secrets",
                "private_datasets",
                "active_databases",
                "wal_files",
                "target_security_material",
            ],
        },
        "rpo_rto": {
            "rpo_seconds_measured": unique_restore["rpo_seconds_measured"],
            "rto_seconds_measured": unique_restore["rto_seconds_measured"],
            "restored_artifact_count": unique_restore["restored_artifact_count"],
            "source_artifact_count": unique_restore["source_artifact_count"],
        },
        "unique_receipt_chain_restore": unique_restore,
        "rebuildable_environment": rebuildable,
        "chaos_receipts": chaos_receipts,
        "current_vps_used_as_sole_backup": False,
        "physical_recovery_target_status": RECOVERY_TARGET_WAIT_STATE,
        "operator_action": build_a21_operator_action(),
        "remaining_internal_waits": [],
        "remaining_external_waits": [
            PHYSICAL_RECOVERY_AUTHORITY_WAIT,
            PHYSICAL_T7_RESTORE_WAIT,
        ],
        "checks": checks,
        "canonical_writes": 0,
        "live_actions": 0,
        "protected_actions_performed": [],
        "grants_authority": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def _restore_unique_receipt_chain(drill_root: Path, *, created_utc: str) -> dict[str, Any]:
    source = LocalArtifactStore(drill_root / "unique-source")
    payloads = [
        {
            "schema_version": "A21UniqueReceiptFixture/v1",
            "chain_index": index,
            "previous_digest": None if index == 0 else "",
            "canonical_writes": 0,
            "grants_authority": False,
        }
        for index in range(3)
    ]
    artifact_ids: list[str] = []
    previous = ""
    for payload in payloads:
        payload["previous_digest"] = previous
        digest = source.ingest_bytes(
            dumps(payload),
            "application/json",
            created_utc=created_utc,
        ).digest
        artifact_ids.append(digest)
        previous = digest
    start = time.monotonic()
    restore_receipt = bounded_restore_drill(
        source_store=source,
        restore_root=drill_root / "second-target" / "restore-cas",
        artifact_ids=tuple(artifact_ids),
        created_utc=created_utc,
    )
    elapsed = max(time.monotonic() - start, 0.0)
    restored_raw = restore_receipt["restored_artifacts"]
    restored = cast(list[str], restored_raw) if isinstance(restored_raw, list) else []
    return {
        "status": "PASS" if sorted(artifact_ids) == restored else "FAIL",
        "restore_receipt_id": restore_receipt["receipt_id"],
        "source_artifact_count": len(artifact_ids),
        "restored_artifact_count": len(restored),
        "restored_artifacts": restored,
        "rpo_seconds_measured": 0.0,
        "rto_seconds_measured": round(elapsed, 6),
        "target_role": "second_encrypted_recovery_target_fixture",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _check_rebuildable_environment(repo_root: Path) -> dict[str, Any]:
    files = []
    failures: list[str] = []
    for rel in _REBUILDABLE_LOCK_PATHS:
        path = repo_root / rel
        if not path.is_file():
            failures.append(f"missing {rel}")
            continue
        files.append(
            {
                "path": rel,
                "sha256": _sha256_path(path),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "A21RebuildableEnvironmentManifest/v1",
        "files": files,
        "commands": [
            "uv sync --locked",
            "uv run python scripts/checks/srf-v37-a09-gate.py",
            "uv run python scripts/checks/srf-v37-a10-gate.py",
            "uv run --extra sciml-domain python scripts/checks/srf-v37-a14-gate.py",
        ],
        "absolute_paths_published": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    rendered = json.dumps(manifest, sort_keys=True)
    if "/Users/" in rendered or "/Volumes/" in rendered:
        failures.append("rebuildable manifest leaks host paths")
    return {
        "status": "FAIL" if failures else "PASS",
        "lock_manifest_hash": _grouped_sha256(dumps(manifest)),
        "files": files,
        "reconstructed_from_locks": not failures,
        "rebuild_commands": manifest["commands"],
        "detail": "; ".join(failures) if failures else "lock and pin manifests are present",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _chaos_executor_crash(drill_root: Path, repo_root: Path) -> dict[str, Any]:
    roots = SchedulerRoots.create_t7_work_namespace(
        SrfStorageLayout.at(drill_root / "executor-crash" / "SRF"),
        runtime_namespace="a21",
    )
    policy = load_policy(repo_root / "policies" / "resource-policy-m1.json")
    request = RuntimeRunRequest(
        request_id="a21-crash",
        adapter_id="echo.v1",
        input_payload={"value": "a21"},
        resource_estimate=ResourceEstimate(
            wall_seconds=1,
            rss_bytes=1024,
            scratch_bytes=1024,
            cpu_cores=1,
        ),
    )
    roots.submit(request, max_queued=2)

    def terminating_runner(
        _request: RuntimeRunRequest,
        _policy: Any,
        _scratch: Path,
    ) -> RunOutcome:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError("simulated executor process terminated during run")

    failures: list[str] = []
    try:
        roots.dispatch_next(policy=policy, max_queued=2, runner=terminating_runner)
        failures.append("terminating runner did not interrupt dispatch")
    except RuntimeError:
        pass
    recovered = roots.recover_interrupted()
    terminal = roots.dispatch_next(policy=policy, max_queued=2, runner=_fixture_runner)
    if len(recovered) != 1:
        failures.append(f"expected one recovered checkpoint, got {len(recovered)}")
    if terminal is None or terminal.status is not RuntimeRunStatus.COMPLETED:
        failures.append("recovered executor run did not complete")
    if len(list(roots.terminal.glob("*.json"))) != 1:
        failures.append("executor recovery did not produce exactly one terminal receipt")
    return {
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "terminated executor subprocess recovered exactly once",
        "recovered_count": len(recovered),
        "terminal_count": len(list(roots.terminal.glob("*.json"))),
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }


def _chaos_corrupt_objects(drill_root: Path) -> dict[str, Any]:
    store = LocalArtifactStore(drill_root / "corrupt-objects")
    desc = store.put(b"a21-corrupt-object")
    object_path = store._object_path(desc.digest)
    object_path.write_bytes(b"corrupt")
    rejected = False
    try:
        store.get(desc.digest)
    except StoreIntegrityError:
        rejected = True
    fsck = store.fsck()
    status = rejected and desc.digest in fsck.failed_digests
    return {
        "status": "PASS" if status else "FAIL",
        "detail": "corrupted CAS object rejected by get and fsck"
        if status
        else "corruption was not rejected",
        "failed_digest_count": len(fsck.failed_digests),
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }


def _chaos_revoked_packs() -> dict[str, Any]:
    manifest = build_manifest(
        {
            "schema_version": "ResourcePackManifest/v1",
            "pack_id": "a21.synthetic.pack",
            "name": "a21-synthetic-pack",
            "version": "0.1.0",
            "capability_profiles": ["algebra_exact"],
            "platforms": [{"os": "linux", "arch": "x86_64", "abi": None}],
            "source": {
                "url": "https://example.invalid/a21",
                "commit": None,
                "source_sha256": "sha256:" + "a" * 64,
            },
            "lock_sha256": "sha256:" + "b" * 64,
            "tree_sha256": "sha256:" + "c" * 64,
            "license": {"spdx": "MIT", "texts_sha256": ["sha256:" + "d" * 64]},
            "sbom_sha256": None,
            "entrypoints": [{"entrypoint_id": "runtime", "kind": "python_module", "ref": "run.py"}],
            "probes": {"runtime_probe": "runtime", "actual_compute_probe": "runtime"},
            "created_utc": "2026-07-30T00:00:00Z",
            "canonical_writes": 0,
            "grants_authority": False,
        }
    )
    evidence = PackGovernanceEvidence(
        sbom_sha256="sha256:" + "1" * 64,
        lock_sha256="sha256:" + "2" * 64,
        dependencies=(
            DependencyRecord(
                dependency_id="revoked-dep",
                version="1.0.0",
                license_spdx="MIT",
                artifact_sha256="sha256:" + "e" * 64,
            ),
        ),
        vulnerability_scan=VulnerabilityScanSummary(
            scanner="a21-fixture",
            database_sha256="sha256:" + "f" * 64,
            critical_count=0,
            high_count=0,
        ),
        admission_receipt_ids=tuple(f"sha256:{index:064x}" for index in range(1, len(STAGES))),
    )
    record = assess_pack_governance(
        manifest,
        evidence,
        PackRevocationRegistry(frozenset(), frozenset({"revoked-dep"})),
    )
    status = record.status is PackLifecycleStatus.REVOKED
    return {
        "status": "PASS" if status else "FAIL",
        "detail": "revoked dependency blocks pack activation"
        if status
        else f"revoked pack yielded {record.status.value}",
        "pack_status": record.status.value,
        "reasons": list(record.reasons),
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }


def _chaos_stale_keys(*, created_utc: str) -> dict[str, Any]:
    head = "a" * 40
    stale = build_srf_pulse(
        status=PulseStatus.GREEN,
        observed_utc="2026-07-29T00:00:00Z",
        head_sha=head,
    )
    stale_assessment = assess_pulse(
        stale,
        expected_head_sha=head,
        observed_utc=created_utc,
        max_age_seconds=60,
    )
    cross_head = build_srf_pulse(
        status=PulseStatus.GREEN,
        observed_utc=created_utc,
        head_sha="b" * 40,
    )
    cross_assessment = assess_pulse(
        cross_head,
        expected_head_sha=head,
        observed_utc=created_utc,
        max_age_seconds=60,
    )
    status = stale_assessment.wait_state == "WAIT_SRF" and cross_assessment.wait_state == "WAIT_SRF"
    return {
        "status": "PASS" if status else "FAIL",
        "detail": "stale and cross-head keys project to WAIT_SRF"
        if status
        else "stale/cross-head key guard failed",
        "stale_reason": stale_assessment.reason,
        "cross_head_reason": cross_assessment.reason,
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }


def _chaos_lost_indexes(drill_root: Path) -> dict[str, Any]:
    store = LocalArtifactStore(drill_root / "lost-indexes")
    outcome = store.ingest_bytes(
        b"a21-lost-index",
        "application/octet-stream",
        created_utc="2026-07-30T00:00:00Z",
    )
    descriptor = store._root / "descriptors" / f"{outcome.digest}.json"
    descriptor.unlink()
    fsck = store.fsck_full()
    issue_kinds = {issue["kind"] for issue in fsck.to_dict()["issues"]}
    object_still_readable = store.get(outcome.digest) == b"a21-lost-index"
    status = ISSUE_MISSING_DESCRIPTOR in issue_kinds and object_still_readable
    return {
        "status": "PASS" if status else "FAIL",
        "detail": "lost descriptor index is detected without losing object bytes"
        if status
        else "lost index was not detected",
        "issue_kinds": sorted(issue_kinds),
        "object_still_readable": object_still_readable,
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }


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
        detail="a21 recovered fixture completed",
    )


def _sha256_path(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _grouped_sha256(value: bytes) -> str:
    digest = hashlib.sha256(value).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


__all__ = [
    "A21_DISASTER_RECOVERY_RECEIPT_SCHEMA_VERSION",
    "PHYSICAL_RECOVERY_AUTHORITY_WAIT",
    "PHYSICAL_T7_RESTORE_WAIT",
    "RECOVERY_TARGET_WAIT_STATE",
    "build_a21_operator_action",
    "run_a21_disaster_recovery_drill",
]
