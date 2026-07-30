from __future__ import annotations

import json
from pathlib import Path

from srl.cas import (
    DEFAULT_MIN_FREE_RESERVE_GIB,
    DEFAULT_SRF_ALLOCATION_GIB,
    T7_BINDING_ACTIVE_STATE,
    T7_BINDING_PARTIAL_NATIVE_STATE,
    T7_BINDING_RECEIPT_SCHEMA_VERSION,
    T7_BINDING_WAIT_STATE,
    build_t7_binding_receipt,
    build_t7_native_activation_attempt_receipt,
    namespace_manifest,
    protected_operator_action,
    quota_manifest,
)


def _preflight() -> dict[str, object]:
    return {
        "schema_version": "PhysicalCapabilityReadOnlyPreflight/v1",
        "available_gib": 544,
        "capacity_gib": 931,
        "canonical_writes": 0,
        "external_physical_disk_observed": True,
        "filesystem": "APFS",
        "grants_authority": False,
        "minimum_free_reserve_gib": 100,
        "native_binding_status": T7_BINDING_WAIT_STATE,
        "observed_volume_label": "T7",
        "observed_volume_locator": "mount_label:T7",
        "parent_direct_storage_writes": 0,
        "reserve_check": "PASS",
        "used_gib": 387,
    }


def _binding_request(*, grants_authority: bool = False) -> dict[str, object]:
    return {
        "schema_version": "PhysicalCapabilityBindingRequest/v1",
        "grants_authority": grants_authority,
        "maximum_t7_allocation_gib": 400,
        "minimum_free_reserve_gib": 100,
        "native_binding_status": T7_BINDING_WAIT_STATE,
    }


def _complete_physical_evidence() -> dict[str, object]:
    return {
        "authority_receipt_id": "AuthorityReceipt/test",
        "ownership_enabled": True,
        "namespace_created": True,
        "physical_object_roundtrip": True,
        "physical_corruption_rejected": True,
        "unplug_wait_observed": True,
        "replug_resume_observed": True,
        "no_internal_mac_project_data": True,
    }


def test_namespace_and_quota_manifest_pin_a02_contract() -> None:
    namespace = namespace_manifest()
    assert namespace["root_name"] == "SRF"
    assert namespace["cold_namespace"] == "cold-cas"
    assert namespace["mutable_work_namespaces"] == ["envs", "caches", "scratch", "spool", "indexes"]

    quota = quota_manifest()
    assert quota["maximum_allocation_gib"] == DEFAULT_SRF_ALLOCATION_GIB == 400
    assert quota["minimum_free_reserve_gib"] == DEFAULT_MIN_FREE_RESERVE_GIB == 100


def test_current_preflight_stays_wait_without_authority() -> None:
    receipt = build_t7_binding_receipt(
        preflight=_preflight(),
        binding_request=_binding_request(),
    )

    assert receipt["schema_version"] == T7_BINDING_RECEIPT_SCHEMA_VERSION
    assert receipt["status"] == T7_BINDING_WAIT_STATE
    assert receipt["capacity_check"]["status"] == "OK"
    assert receipt["authority"] == {
        "binding_request_grants_authority": False,
        "preflight_grants_authority": False,
        "authority_receipt_present": False,
    }
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_complete_physical_evidence_is_not_enough_without_grant() -> None:
    receipt = build_t7_binding_receipt(
        preflight=_preflight(),
        binding_request=_binding_request(),
        physical_evidence=_complete_physical_evidence(),
    )

    assert receipt["status"] == T7_BINDING_WAIT_STATE


def test_active_requires_grant_and_all_protected_evidence() -> None:
    preflight = dict(_preflight())
    preflight["grants_authority"] = True
    receipt = build_t7_binding_receipt(
        preflight=preflight,
        binding_request=_binding_request(grants_authority=True),
        physical_evidence=_complete_physical_evidence(),
    )

    assert receipt["status"] == T7_BINDING_ACTIVE_STATE


def test_missing_one_protected_field_keeps_wait() -> None:
    preflight = dict(_preflight())
    preflight["grants_authority"] = True
    evidence = _complete_physical_evidence()
    evidence["unplug_wait_observed"] = False
    receipt = build_t7_binding_receipt(
        preflight=preflight,
        binding_request=_binding_request(grants_authority=True),
        physical_evidence=evidence,
    )

    assert receipt["status"] == T7_BINDING_WAIT_STATE
    assert "unplug_wait_observed" in receipt["missing_protected_physical_evidence"]


def test_native_attempt_partial_evidence_never_closes_a02_or_publishes_paths() -> None:
    evidence = _complete_physical_evidence()
    evidence["ownership_enabled"] = False
    evidence["unplug_wait_observed"] = False
    evidence["replug_resume_observed"] = False
    attempt = build_t7_native_activation_attempt_receipt(
        observed_identity_basis={
            "volume_locator": "/" + "Volumes" + "/T7-Secure",
            "volume_uuid": "D1F2E2C1-3210-4A39-A4E0-0AA0AD5110E2",
            "filesystem": "APFS",
            "encrypted": True,
        },
        physical_evidence=evidence,
        capacity_check={
            "status": "WAIT_T7_BINDING",
            "reason": "capacity_accounting_ambiguous_until_native_quota_receipt",
        },
        authority_directive={
            "schema_version": "OperatorDirective/v1",
            "directive_id": "SRF_PHYSICAL_ACTIVATION_V2",
            "target_scoped": True,
        },
        private_receipt_ref="sha256:private-local-proof",
    )

    rendered = json.dumps(attempt, sort_keys=True)
    assert attempt["status"] == T7_BINDING_PARTIAL_NATIVE_STATE
    assert attempt["grants_authority"] is False
    assert attempt["protected_physical_evidence"]["physical_object_roundtrip"] is True
    assert attempt["missing_protected_physical_evidence"] == [
        "ownership_enabled",
        "unplug_wait_observed",
        "replug_resume_observed",
    ]
    assert "WAIT_T7_BINDING:A02_MISSING_OWNERSHIP_ENABLED" in attempt["remaining_external_waits"]
    assert "/Volumes/" not in rendered
    assert "/Users/" not in rendered
    assert "D1F2E2C1" not in rendered


def test_receipt_does_not_emit_raw_owner_paths_or_uuid() -> None:
    raw_volume_path = "/" + "Volumes" + "/T7"
    receipt = build_t7_binding_receipt(
        preflight={
            **_preflight(),
            "observed_volume_locator": raw_volume_path,
            "volume_uuid": "66E01FE4-7792-4F1E-BC82-A542678B53C5",
        },
        binding_request=_binding_request(),
    )
    rendered = str(receipt)

    assert "/Volumes/" not in rendered
    assert "/Users/" not in rendered
    assert "66E01FE4" not in rendered


def test_operator_action_names_protected_steps_without_granting_authority() -> None:
    action = protected_operator_action()
    assert action["authority_required"] is True
    assert action["grants_authority"] is False
    assert "claim_ACTIVE_or_DONE" in action["forbidden_without_authority"]


def test_committed_preflight_receipt_stays_wait() -> None:
    root = Path(__file__).resolve().parents[2]
    preflight = root / "docs" / "target-binding" / "t7-readonly-preflight.json"
    request = root / "docs" / "target-binding" / "t7-physical-binding-request.json"
    receipt = build_t7_binding_receipt(
        preflight=json.loads(preflight.read_text(encoding="utf-8")),
        binding_request=json.loads(request.read_text(encoding="utf-8")),
    )

    assert receipt["status"] == T7_BINDING_WAIT_STATE
