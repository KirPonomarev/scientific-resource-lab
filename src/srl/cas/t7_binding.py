"""V3.7 A02 non-destructive T7 binding truth model.

A02 is the boundary between software-verifiable storage machinery and
operator-owned physical storage. The public repository may prove the layout,
quota, cold-CAS immutability, path privacy, and false-closure gates. It may not
claim the physical T7 target is ACTIVE until a target-scoped native authority
receipt supplies the protected evidence: namespace creation on the real volume,
real object write/read/corruption checks on that namespace, unplug/replug
resume proof, and proof that project data does not depend on the internal Mac
disk.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from srl.cas.layout import (
    COLD_CAS_DIR,
    DEFAULT_MIN_FREE_RESERVE_GIB,
    DEFAULT_SRF_ALLOCATION_GIB,
    QUARANTINE_DIR,
    RESTORE_TESTS_DIR,
    WORK_DIR,
    WORK_NAMESPACES,
    StorageQuotaStatus,
    check_srf_storage_quota,
)
from srl.contracts import dumps
from srl.contracts.ids import object_id

T7_BINDING_RECEIPT_SCHEMA_VERSION: Final[str] = "T7BindingReceipt/v1"
T7_OPERATOR_ACTION_SCHEMA_VERSION: Final[str] = "ProtectedOperatorAction/v1"
T7_BINDING_WAIT_STATE: Final[str] = "WAIT_T7_BINDING"
T7_BINDING_ACTIVE_STATE: Final[str] = "ACTIVE"

_PROTECTED_EVIDENCE_FIELDS: Final[tuple[str, ...]] = (
    "authority_receipt_id",
    "namespace_created",
    "physical_object_roundtrip",
    "physical_corruption_rejected",
    "unplug_wait_observed",
    "replug_resume_observed",
    "no_internal_mac_project_data",
)


def grouped_sha256(value: bytes | str) -> str:
    """Return a grouped SHA-256 digest suitable for public receipts."""
    data = value.encode("utf-8") if isinstance(value, str) else value
    digest = hashlib.sha256(data).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, len(digest), 8))


def manifest_hash(value: Any) -> str:
    """Hash a canonical JSON value and group the digest for secret-scan hygiene."""
    return grouped_sha256(dumps(value))


def namespace_manifest() -> dict[str, Any]:
    """Return the public SRF namespace layout manifest for the T7 target."""
    return {
        "schema_version": "SrfT7NamespaceManifest/v1",
        "root_name": "SRF",
        "cold_namespace": COLD_CAS_DIR,
        "mutable_work_root": WORK_DIR,
        "mutable_work_namespaces": list(WORK_NAMESPACES),
        "quarantine_namespace": QUARANTINE_DIR,
        "restore_test_namespace": RESTORE_TESTS_DIR,
        "cold_namespace_forbids": [
            "active_database",
            "sqlite",
            "wal",
            "package_manager_database",
        ],
    }


def quota_manifest() -> dict[str, Any]:
    """Return the A02 SRF T7 quota manifest."""
    return {
        "schema_version": "SrfT7QuotaManifest/v1",
        "maximum_allocation_gib": DEFAULT_SRF_ALLOCATION_GIB,
        "minimum_free_reserve_gib": DEFAULT_MIN_FREE_RESERVE_GIB,
    }


def protected_operator_action() -> dict[str, Any]:
    """Return the exact protected operator action required to finish A02."""
    action: dict[str, Any] = {
        "schema_version": T7_OPERATOR_ACTION_SCHEMA_VERSION,
        "action_id": "A02_BIND_T7_NATIVE_TARGET",
        "authority_required": True,
        "grants_authority": False,
        "target": "operator-owned external T7 volume mounted by label",
        "allowed_actions_after_authority": [
            "verify_exact_volume_identity_from_out_of_repo_expected_identity",
            "create_srf_namespaces_under_target_root",
            "enforce_400_gib_allocation_and_100_gib_free_reserve",
            "bind_private_overlay_envs_caches_scratch_spool_to_target",
            "write_read_and_hashcheck_one_nonsecret_probe_object",
            "corrupt_copy_inside_restore_test_namespace_and_verify_rejection",
            "unplug_target_and_record_WAIT_T7_BINDING_without_corruption",
            "replug_target_and_record_safe_resume",
            "prove_no_project_data_dependency_on_internal_mac_storage",
        ],
        "forbidden_without_authority": [
            "format",
            "erase",
            "restore_overwrite",
            "active_database_or_wal_inside_cold_cas",
            "copy_owner_paths_or_volume_uuid_into_git",
            "claim_ACTIVE_or_DONE",
        ],
        "expected_receipt_schema": T7_BINDING_RECEIPT_SCHEMA_VERSION,
    }
    action["action_hash_grouped_sha256"] = manifest_hash(action)
    return action


def _capacity_status(preflight: dict[str, Any]) -> dict[str, Any]:
    """Classify documented T7 capacity facts against the A02 quota policy."""
    used_gib = int(preflight.get("used_gib", -1))
    available_gib = int(preflight.get("available_gib", -1))
    decision = check_srf_storage_quota(
        observed_used_bytes=used_gib * 1024**3,
        observed_free_bytes=available_gib * 1024**3,
    )
    return {
        "status": decision.status.value,
        "reason": decision.reason,
        "observed_used_gib": used_gib,
        "observed_available_gib": available_gib,
        "allocation_gib": DEFAULT_SRF_ALLOCATION_GIB,
        "minimum_free_reserve_gib": DEFAULT_MIN_FREE_RESERVE_GIB,
    }


def _physical_evidence_complete(evidence: dict[str, Any]) -> bool:
    """Return True iff all protected A02 physical evidence fields are present."""
    return all(bool(evidence.get(field)) for field in _PROTECTED_EVIDENCE_FIELDS)


def build_t7_binding_receipt(
    *,
    preflight: dict[str, Any],
    binding_request: dict[str, Any],
    physical_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the current A02 T7 binding receipt without performing target writes.

    The receipt returns ``ACTIVE`` only if the caller supplies complete
    authority-bound physical evidence and the read-only capacity facts pass.
    With the repository's current request/preflight artifacts it honestly
    remains ``WAIT_T7_BINDING``.
    """
    evidence = dict(physical_evidence or {})
    namespace = namespace_manifest()
    quota = quota_manifest()
    capacity = _capacity_status(preflight)
    request_grants_authority = bool(binding_request.get("grants_authority"))
    preflight_grants_authority = bool(preflight.get("grants_authority"))
    authority_bound = bool(evidence.get("authority_receipt_id"))
    protected_complete = _physical_evidence_complete(evidence)
    active = (
        capacity["status"] == StorageQuotaStatus.OK.value
        and request_grants_authority
        and preflight_grants_authority
        and authority_bound
        and protected_complete
    )

    observed_identity_basis = {
        "volume_locator": preflight.get("observed_volume_locator"),
        "volume_label": preflight.get("observed_volume_label"),
        "filesystem": preflight.get("filesystem"),
        "capacity_gib": preflight.get("capacity_gib"),
    }
    receipt: dict[str, Any] = {
        "schema_version": T7_BINDING_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A02",
        "status": T7_BINDING_ACTIVE_STATE if active else T7_BINDING_WAIT_STATE,
        "volume_identity_hash": manifest_hash(observed_identity_basis),
        "namespace_hash": manifest_hash(namespace),
        "quota_hash": manifest_hash(quota),
        "namespace_manifest": namespace,
        "quota_manifest": quota,
        "capacity_check": capacity,
        "external_physical_disk_observed": bool(preflight.get("external_physical_disk_observed")),
        "reserve_check": preflight.get("reserve_check"),
        "native_binding_status": preflight.get("native_binding_status", T7_BINDING_WAIT_STATE),
        "authority": {
            "binding_request_grants_authority": request_grants_authority,
            "preflight_grants_authority": preflight_grants_authority,
            "authority_receipt_present": authority_bound,
        },
        "protected_physical_evidence": {
            field: bool(evidence.get(field)) for field in _PROTECTED_EVIDENCE_FIELDS
        },
        "operator_action": protected_operator_action(),
        "canonical_writes": 0,
        "parent_direct_storage_writes": int(preflight.get("parent_direct_storage_writes", 0)),
        "grants_authority": False,
        "false_done_guard": "ACTIVE requires native authority plus every protected evidence field",
    }
    receipt["receipt_id"] = object_id(
        {key: value for key, value in receipt.items() if key != "receipt_id"}
    )
    return receipt


__all__ = [
    "T7_BINDING_ACTIVE_STATE",
    "T7_BINDING_RECEIPT_SCHEMA_VERSION",
    "T7_BINDING_WAIT_STATE",
    "T7_OPERATOR_ACTION_SCHEMA_VERSION",
    "build_t7_binding_receipt",
    "grouped_sha256",
    "manifest_hash",
    "namespace_manifest",
    "protected_operator_action",
    "quota_manifest",
]
