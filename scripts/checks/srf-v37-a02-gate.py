#!/usr/bin/env python3
"""V3.7 A02 non-destructive T7 binding gate.

This gate proves the software side of A02 and prevents false closure. It does
not write to the operator's T7 volume. A PASS means:

- the SRF namespace and 400 GiB / 100 GiB quota contract are pinned;
- the cold-CAS layout performs real fixture-root object write/read/corruption
  checks and refuses active DB/WAL artifacts in cold storage;
- the committed read-only T7 preflight remains non-authorizing and capacity OK;
- a T7BindingReceipt cannot claim ACTIVE without native authority plus all
  protected physical evidence fields;
- the exact protected operator action exists for the remaining physical bind.

It intentionally accepts the current terminal state ``WAIT_T7_BINDING`` as
truthful. It would fail only if the repo tried to claim physical ACTIVE/DONE
without the protected evidence.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.capabilities.truth import build_truth_ledger, evaluate_release_candidate  # noqa: E402
from srl.cas import (  # noqa: E402
    DEFAULT_MIN_FREE_RESERVE_GIB,
    DEFAULT_SRF_ALLOCATION_GIB,
    T7_BINDING_ACTIVE_STATE,
    T7_BINDING_WAIT_STATE,
    SrfStorageLayout,
    StorageLayoutError,
    StoreIntegrityError,
    build_t7_binding_receipt,
    manifest_hash,
    namespace_manifest,
    protected_operator_action,
    quota_manifest,
)
from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A02"
A02_ALLOCATION_GIB: Final[int] = 400
A02_MIN_FREE_RESERVE_GIB: Final[int] = 100

PREFLIGHT = REPO_ROOT / "docs" / "target-binding" / "t7-readonly-preflight.json"
BINDING_REQUEST = REPO_ROOT / "docs" / "target-binding" / "t7-physical-binding-request.json"
OPERATOR_ACTION = REPO_ROOT / "docs" / "target-binding" / "t7-native-binding-operator-action.json"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _check_namespace_quota() -> dict[str, Any]:
    namespace = namespace_manifest()
    quota = quota_manifest()
    failures: list[str] = []
    if namespace["cold_namespace"] != "cold-cas":
        failures.append("cold namespace drifted")
    if namespace["mutable_work_namespaces"] != ["envs", "caches", "scratch", "spool", "indexes"]:
        failures.append("mutable work namespaces drifted")
    if (
        quota["maximum_allocation_gib"] != DEFAULT_SRF_ALLOCATION_GIB
        or quota["maximum_allocation_gib"] != A02_ALLOCATION_GIB
    ):
        failures.append("SRF allocation is not 400 GiB")
    if (
        quota["minimum_free_reserve_gib"] != DEFAULT_MIN_FREE_RESERVE_GIB
        or quota["minimum_free_reserve_gib"] != A02_MIN_FREE_RESERVE_GIB
    ):
        failures.append("minimum free reserve is not 100 GiB")
    return {
        "check_id": "A02-01-namespace-quota",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures) if failures else "namespace and quota manifests are pinned",
        "namespace_hash": manifest_hash(namespace),
        "quota_hash": manifest_hash(quota),
    }


def _check_fixture_cold_cas() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        layout = SrfStorageLayout.at(Path(tmp) / "SRF")
        layout.initialize()
        store = layout.cold_store()
        data = b"A02 cold-cas nonsecret probe object"
        desc = store.put(data)
        roundtrip_ok = store.get(desc.digest) == data
        cases.append(
            {
                "case": "fixture-root-object-roundtrip",
                "status": "PASS" if roundtrip_ok else "FAIL",
                "digest": desc.digest,
            }
        )
        if not roundtrip_ok:
            failures.append("fixture-root object roundtrip failed")

        object_path = store._object_path(desc.digest)
        object_path.write_bytes(b"corrupted")
        corruption_rejected = False
        try:
            store.get(desc.digest)
        except StoreIntegrityError:
            corruption_rejected = True
        fsck_report = store.fsck()
        cases.append(
            {
                "case": "fixture-root-corruption-rejected",
                "status": "PASS" if corruption_rejected else "FAIL",
                "fsck_failed": fsck_report.failed_digests,
            }
        )
        if not corruption_rejected or desc.digest not in fsck_report.failed_digests:
            failures.append("corruption was not rejected by get/fsck")

        layout.assert_cold_cas_immutable()
        (layout.cold_cas / "active.sqlite-wal").write_text("mutable", encoding="utf-8")
        wal_rejected = False
        try:
            layout.assert_cold_cas_immutable()
        except StorageLayoutError:
            wal_rejected = True
        cases.append(
            {
                "case": "cold-cas-refuses-db-wal",
                "status": "PASS" if wal_rejected else "FAIL",
            }
        )
        if not wal_rejected:
            failures.append("cold-cas accepted active DB/WAL artifact")
    return {
        "check_id": "A02-02-fixture-cold-cas-smoke",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "fixture-root CAS roundtrip, corruption rejection and WAL rejection passed",
        "cases": cases,
        "physical_t7_writes": 0,
    }


def _check_current_wait_receipt(
    preflight: dict[str, Any],
    binding_request: dict[str, Any],
) -> dict[str, Any]:
    receipt = build_t7_binding_receipt(preflight=preflight, binding_request=binding_request)
    failures: list[str] = []
    if receipt["status"] != T7_BINDING_WAIT_STATE:
        failures.append(
            f"current receipt status is {receipt['status']!r}, expected WAIT_T7_BINDING"
        )
    if receipt["capacity_check"]["status"] != "OK":
        failures.append("read-only capacity check is not OK")
    if receipt["authority"]["binding_request_grants_authority"]:
        failures.append("binding request unexpectedly grants authority")
    if receipt["authority"]["preflight_grants_authority"]:
        failures.append("preflight unexpectedly grants authority")
    rendered = json.dumps(receipt, sort_keys=True)
    for leak in ("/Volumes/", "/Users/", "Volume UUID"):
        if leak in rendered:
            failures.append(f"receipt leaks {leak}")
    return {
        "check_id": "A02-03-current-wait-receipt",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "current non-authorizing preflight yields WAIT_T7_BINDING with capacity OK",
        "receipt": receipt,
    }


def _check_false_active_guard(
    preflight: dict[str, Any],
    binding_request: dict[str, Any],
) -> dict[str, Any]:
    complete_evidence = {
        "authority_receipt_id": "AuthorityReceipt/test",
        "namespace_created": True,
        "physical_object_roundtrip": True,
        "physical_corruption_rejected": True,
        "unplug_wait_observed": True,
        "replug_resume_observed": True,
        "no_internal_mac_project_data": True,
    }
    no_grant_receipt = build_t7_binding_receipt(
        preflight=preflight,
        binding_request=binding_request,
        physical_evidence=complete_evidence,
    )
    grant_preflight = dict(preflight)
    grant_preflight["grants_authority"] = True
    grant_request = dict(binding_request)
    grant_request["grants_authority"] = True
    missing_evidence = dict(complete_evidence)
    missing_evidence["no_internal_mac_project_data"] = False
    missing_field_receipt = build_t7_binding_receipt(
        preflight=grant_preflight,
        binding_request=grant_request,
        physical_evidence=missing_evidence,
    )
    active_receipt = build_t7_binding_receipt(
        preflight=grant_preflight,
        binding_request=grant_request,
        physical_evidence=complete_evidence,
    )
    release_decision = evaluate_release_candidate(
        {
            "target_release": "v2.0.0",
            "target_result": "DONE",
            "production_signer": "missing",
            "sandbox": "policy_only",
            "t7_binding": no_grant_receipt["status"],
            "ledger": build_truth_ledger(),
        }
    )
    cases = [
        {
            "case": "complete-evidence-without-authority-stays-wait",
            "status": no_grant_receipt["status"],
        },
        {
            "case": "missing-one-protected-field-stays-wait",
            "status": missing_field_receipt["status"],
        },
        {
            "case": "complete-authority-and-evidence-can-be-active",
            "status": active_receipt["status"],
        },
        {
            "case": "release-gate-rejects-current-wait",
            "verdict": release_decision["verdict"],
            "blockers": release_decision["blockers"],
        },
    ]
    failures: list[str] = []
    if no_grant_receipt["status"] != T7_BINDING_WAIT_STATE:
        failures.append("complete evidence without authority became ACTIVE")
    if missing_field_receipt["status"] != T7_BINDING_WAIT_STATE:
        failures.append("missing protected field became ACTIVE")
    if active_receipt["status"] != T7_BINDING_ACTIVE_STATE:
        failures.append("complete authority/evidence did not model ACTIVE")
    if (
        release_decision["verdict"] != "REJECT"
        or "T7_NOT_ACTIVE" not in release_decision["blockers"]
    ):
        failures.append("release gate did not reject current WAIT_T7_BINDING")
    return {
        "check_id": "A02-04-false-active-guard",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures) if failures else "false ACTIVE/DONE closure is blocked",
        "cases": cases,
    }


def _check_operator_action_doc() -> dict[str, Any]:
    expected = protected_operator_action()
    actual = _load_json(OPERATOR_ACTION)
    failures: list[str] = []
    if actual != expected:
        failures.append("operator action doc drifted from code")
    if actual.get("grants_authority") is not False:
        failures.append("operator action must not grant authority")
    required = {
        "write_read_and_hashcheck_one_nonsecret_probe_object",
        "unplug_target_and_record_WAIT_T7_BINDING_without_corruption",
        "replug_target_and_record_safe_resume",
        "prove_no_project_data_dependency_on_internal_mac_storage",
    }
    if not required <= set(actual.get("allowed_actions_after_authority", [])):
        failures.append("operator action does not name all protected A02 evidence")
    return {
        "check_id": "A02-05-operator-action-doc",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "protected operator action is exact, non-authorizing and documented",
        "operator_action_hash": actual.get("action_hash_grouped_sha256"),
    }


def main() -> int:
    preflight = _load_json(PREFLIGHT)
    binding_request = _load_json(BINDING_REQUEST)
    checks = [
        _check_namespace_quota(),
        _check_fixture_cold_cas(),
        _check_current_wait_receipt(preflight, binding_request),
        _check_false_active_guard(preflight, binding_request),
        _check_operator_action_doc(),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "terminal_state": T7_BINDING_WAIT_STATE,
        "stage_closure": "PARKED_WAIT_AUTHORITY",
        "checks": checks,
        "canonical_writes": 0,
        "physical_t7_writes": 0,
        "grants_authority": False,
        "next_stage_policy": (
            "continue independent lanes; do not claim A02 ACTIVE until native receipt exists"
        ),
    }
    receipt["receipt_id"] = object_id(
        {key: value for key, value in receipt.items() if key != "receipt_id"}
    )
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
