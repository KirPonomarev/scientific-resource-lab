"""Security native bridge closeout import.

SRF may prepare an inactive proposal-only bridge and later import native
Security evidence, but SRF must not activate scanners, execute target actions,
move D2/D3 material, or treat child evidence as scientific or operational
authority. This module is the SRF-side fail-closed projection for A20.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id, validate_object_id
from srl.integrations.native_child import verify_native_bridge_child_request

SECURITY_NATIVE_CLOSEOUT_SCHEMA_VERSION: Final[str] = "SecurityNativeBridgeCloseout/v1"
SECURITY_CLOSEOUT_IMPORT_RECEIPT_SCHEMA_VERSION: Final[str] = "SecurityCloseoutImportReceipt/v1"
SECURITY_WAIT_STATUS: Final[str] = "WAIT_NATIVE_CHILD_CLOSEOUT"
SECURITY_IMPORTED_STATUS: Final[str] = "IMPORTED_NATIVE_CHILD_CLOSEOUT"
SECURITY_REJECTED_STATUS: Final[str] = "REJECT_NATIVE_CHILD_CLOSEOUT"
SECURITY_OFFLINE_WAIT_STATUS: Final[str] = "WAIT_SRF"


class SecurityCloseoutError(ContractError):
    """Raised when a Security native bridge closeout cannot be imported."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def security_closeout_payload_hash(native_closeout: dict[str, Any]) -> str:
    """Return the canonical SHA-256 hash of a native Security closeout payload."""
    return hashlib.sha256(dumps(native_closeout)).hexdigest()


def build_security_closeout_import_receipt(
    *,
    child_request: dict[str, Any],
    native_closeout: dict[str, Any] | None,
    key_material_by_id: dict[str, bytes],
    native_bootstrap_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Project native Security closeout evidence into an authority-negative receipt."""
    verify_native_bridge_child_request(
        child_request,
        key_material_by_id=key_material_by_id,
    )
    request_id = _require_object_id(child_request.get("request_id"), "child_request.request_id")
    bootstrap_status = _require_non_empty(
        native_bootstrap_evidence.get("status"),
        "native_bootstrap_evidence.status",
    )
    bootstrap_head = _require_non_empty(
        native_bootstrap_evidence.get("runtime_head"),
        "native_bootstrap_evidence.runtime_head",
    )
    body: dict[str, Any] = {
        "schema_version": SECURITY_CLOSEOUT_IMPORT_RECEIPT_SCHEMA_VERSION,
        "child_request_id": request_id,
        "mission_id": child_request.get("mission_id"),
        "source_project": child_request.get("source_project"),
        "source_head": child_request.get("source_head"),
        "target_project": child_request.get("target_project"),
        "target_head": child_request.get("target_head"),
        "adapter_receipt_id": child_request.get("adapter_receipt_id"),
        "native_bootstrap_evidence": {
            "status": bootstrap_status,
            "runtime_head": bootstrap_head,
            "organism_status": native_bootstrap_evidence.get("organism_status"),
            "technical_health": native_bootstrap_evidence.get("technical_health"),
            "next_gate": native_bootstrap_evidence.get("next_gate"),
            "operator_required": native_bootstrap_evidence.get("operator_required"),
            "no_live_authority": native_bootstrap_evidence.get("no_live_authority"),
            "root_reason_code": native_bootstrap_evidence.get("root_reason_code"),
        },
        "status": SECURITY_WAIT_STATUS,
        "srf_offline_status": SECURITY_OFFLINE_WAIT_STATUS,
        "native_closeout_payload_sha256": None,
        "native_closeout_receipt_id": None,
        "native_suite_status": None,
        "srf_suite_status": None,
        "containment_suite_status": None,
        "activation_state": "INACTIVE",
        "native_executor_boundary": "ebashim",
        "ebashim_preserved": None,
        "D0_D1_only_transport": None,
        "parent_direct_external_writes": 0,
        "security_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "security_actions": 0,
        "target_actions": 0,
        "D2_D3_transfers": 0,
        "credential_transfers": 0,
        "private_evidence_transfers": 0,
        "direct_scanner_control": False,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "security_activation_authority_granted": False,
    }
    if native_closeout is not None:
        _validate_native_closeout(child_request=child_request, native_closeout=native_closeout)
        body["status"] = SECURITY_IMPORTED_STATUS
        body["native_closeout_payload_sha256"] = security_closeout_payload_hash(native_closeout)
        body["native_closeout_receipt_id"] = native_closeout.get("receipt_id")
        body["native_suite_status"] = _suite_status(native_closeout, "native_suite")
        body["srf_suite_status"] = _suite_status(native_closeout, "srf_suite")
        body["containment_suite_status"] = _suite_status(native_closeout, "containment_suite")
        body["ebashim_preserved"] = native_closeout.get("ebashim_preserved")
        body["D0_D1_only_transport"] = native_closeout.get("D0_D1_only_transport")
    body["receipt_id"] = object_id(body)
    return body


def _validate_native_closeout(
    *,
    child_request: dict[str, Any],
    native_closeout: dict[str, Any],
) -> None:
    if native_closeout.get("schema_version") != SECURITY_NATIVE_CLOSEOUT_SCHEMA_VERSION:
        raise SecurityCloseoutError("unexpected Security closeout schema_version")
    _validate_native_closeout_identity(child_request, native_closeout)
    _validate_native_closeout_suites(native_closeout)
    _validate_native_closeout_containment(native_closeout)


def _validate_native_closeout_identity(
    child_request: dict[str, Any],
    native_closeout: dict[str, Any],
) -> None:
    _require_object_id(native_closeout.get("receipt_id"), "native_closeout.receipt_id")
    for field in (
        "mission_id",
        "source_project",
        "source_head",
        "target_project",
        "target_head",
        "adapter_receipt_id",
    ):
        if native_closeout.get(field) != child_request.get(field):
            raise SecurityCloseoutError(f"native closeout {field} does not match child request")
    if native_closeout.get("child_request_id") != child_request.get("request_id"):
        raise SecurityCloseoutError("native closeout child_request_id does not match request_id")


def _validate_native_closeout_suites(native_closeout: dict[str, Any]) -> None:
    if _suite_status(native_closeout, "native_suite") != "PASS":
        raise SecurityCloseoutError("native suite did not PASS")
    if _suite_status(native_closeout, "srf_suite") != "PASS":
        raise SecurityCloseoutError("SRF suite did not PASS")
    if _suite_status(native_closeout, "containment_suite") != "PASS":
        raise SecurityCloseoutError("containment suite did not PASS")


def _validate_native_closeout_containment(native_closeout: dict[str, Any]) -> None:
    for field in (
        "parent_direct_external_writes",
        "security_writes",
        "canonical_writes",
        "live_actions",
        "security_actions",
        "target_actions",
        "D2_D3_transfers",
        "credential_transfers",
        "private_evidence_transfers",
    ):
        if native_closeout.get(field) != 0:
            raise SecurityCloseoutError(f"native closeout {field} must be 0")
    for field in (
        "grants_authority",
        "scientific_authority_granted",
        "security_activation_authority_granted",
        "direct_scanner_control",
        "target_material_crossed",
        "exploit_material_crossed",
        "credential_material_crossed",
        "private_evidence_crossed",
    ):
        if native_closeout.get(field) is not False:
            raise SecurityCloseoutError(f"native closeout {field} must be false")
    if native_closeout.get("activation_state") != "INACTIVE":
        raise SecurityCloseoutError("native closeout activation_state must stay INACTIVE")
    if native_closeout.get("native_executor_boundary") != "ebashim":
        raise SecurityCloseoutError("native closeout must preserve ebashim")
    if native_closeout.get("ebashim_preserved") is not True:
        raise SecurityCloseoutError("native closeout ebashim_preserved must be true")
    if native_closeout.get("D0_D1_only_transport") is not True:
        raise SecurityCloseoutError("native closeout D0/D1 transport proof must be true")


def _suite_status(native_closeout: dict[str, Any], key: str) -> str:
    suite = native_closeout.get(key)
    if not isinstance(suite, dict):
        raise SecurityCloseoutError(f"native closeout {key} must be an object")
    return _require_non_empty(suite.get("status"), f"native_closeout.{key}.status")


def _require_object_id(value: Any, field: str) -> str:
    try:
        return validate_object_id(value)
    except ContractError as exc:
        raise SecurityCloseoutError(f"{field} must be a canonical object id") from exc


def _require_non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SecurityCloseoutError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "SECURITY_CLOSEOUT_IMPORT_RECEIPT_SCHEMA_VERSION",
    "SECURITY_IMPORTED_STATUS",
    "SECURITY_NATIVE_CLOSEOUT_SCHEMA_VERSION",
    "SECURITY_OFFLINE_WAIT_STATUS",
    "SECURITY_REJECTED_STATUS",
    "SECURITY_WAIT_STATUS",
    "SecurityCloseoutError",
    "build_security_closeout_import_receipt",
    "security_closeout_payload_hash",
]
