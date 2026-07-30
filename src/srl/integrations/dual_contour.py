"""DualContour native shared-contract closeout import.

The parent SRF repository may prepare and later import evidence from the
native DualContour repository, but it must not write the child repository or
turn a child receipt into scientific/domain authority. This module is the
fail-closed SRF-side projection for that boundary.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id, validate_object_id
from srl.integrations.shared_contracts import verify_shared_contract_child_mission_request

DUAL_CONTOUR_CLOSEOUT_SCHEMA_VERSION: Final[str] = "DualContourSharedContractCloseout/v1"
DUAL_CONTOUR_IMPORT_RECEIPT_SCHEMA_VERSION: Final[str] = "DualContourCloseoutImportReceipt/v1"
DUAL_CONTOUR_WAIT_STATUS: Final[str] = "WAIT_NATIVE_CHILD_CLOSEOUT"
DUAL_CONTOUR_IMPORTED_STATUS: Final[str] = "IMPORTED_NATIVE_CHILD_CLOSEOUT"
DUAL_CONTOUR_REJECTED_STATUS: Final[str] = "REJECT_NATIVE_CHILD_CLOSEOUT"


class DualContourCloseoutError(ContractError):
    """Raised when a DualContour native closeout cannot be imported."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def conformance_vectors_hash(child_request: dict[str, Any]) -> str:
    """Return the canonical SHA-256 hash of the child request conformance vectors."""
    vectors = child_request.get("conformance_vectors")
    if not isinstance(vectors, list) or not vectors:
        raise DualContourCloseoutError("child request conformance_vectors must be non-empty")
    return hashlib.sha256(dumps(vectors)).hexdigest()


def closeout_payload_hash(native_closeout: dict[str, Any]) -> str:
    """Return the canonical SHA-256 hash of the native closeout payload."""
    return hashlib.sha256(dumps(native_closeout)).hexdigest()


def build_dual_contour_closeout_import_receipt(
    *,
    child_request: dict[str, Any],
    native_closeout: dict[str, Any] | None,
    key_material_by_id: dict[str, bytes],
    native_startup_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Project the native DualContour closeout into a SRF import receipt.

    A missing closeout is a truthful WAIT receipt. A present closeout must pass
    all hash/head/schema/suite/authority checks or the function raises
    :class:`DualContourCloseoutError`.
    """
    verify_shared_contract_child_mission_request(
        child_request,
        key_material_by_id=key_material_by_id,
    )
    request_id = _require_object_id(child_request.get("request_id"), "child_request.request_id")
    startup_status = _require_non_empty(
        native_startup_evidence.get("status"),
        "native_startup_evidence.status",
    )
    startup_command = _require_non_empty(
        native_startup_evidence.get("command"),
        "native_startup_evidence.command",
    )
    startup_head = _require_non_empty(
        native_startup_evidence.get("target_head"),
        "native_startup_evidence.target_head",
    )
    body: dict[str, Any] = {
        "schema_version": DUAL_CONTOUR_IMPORT_RECEIPT_SCHEMA_VERSION,
        "child_request_id": request_id,
        "mission_id": child_request.get("mission_id"),
        "source_project": child_request.get("source_project"),
        "source_head": child_request.get("source_head"),
        "target_project": child_request.get("target_project"),
        "target_head": child_request.get("target_head"),
        "native_startup_evidence": {
            "status": startup_status,
            "command": startup_command,
            "target_head": startup_head,
            "result": native_startup_evidence.get("result"),
        },
        "status": DUAL_CONTOUR_WAIT_STATUS,
        "native_closeout_payload_sha256": None,
        "native_closeout_receipt_id": None,
        "producer_suite_status": None,
        "consumer_suite_status": None,
        "conformance_vectors_hash": conformance_vectors_hash(child_request),
        "parent_direct_external_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "domain_authority_granted": False,
    }
    if native_closeout is not None:
        _validate_native_closeout(child_request=child_request, native_closeout=native_closeout)
        body["status"] = DUAL_CONTOUR_IMPORTED_STATUS
        body["native_closeout_payload_sha256"] = closeout_payload_hash(native_closeout)
        body["native_closeout_receipt_id"] = native_closeout.get("receipt_id")
        body["producer_suite_status"] = _suite_status(native_closeout, "producer_suite")
        body["consumer_suite_status"] = _suite_status(native_closeout, "consumer_suite")
    body["receipt_id"] = object_id(body)
    return body


def _validate_native_closeout(
    *,
    child_request: dict[str, Any],
    native_closeout: dict[str, Any],
) -> None:
    if native_closeout.get("schema_version") != DUAL_CONTOUR_CLOSEOUT_SCHEMA_VERSION:
        raise DualContourCloseoutError("unexpected DualContour closeout schema_version")
    _validate_native_closeout_identity(child_request, native_closeout)
    _validate_native_closeout_suites(child_request, native_closeout)
    _validate_native_closeout_authority(native_closeout)


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
    ):
        if native_closeout.get(field) != child_request.get(field):
            raise DualContourCloseoutError(f"native closeout {field} does not match child request")
    if native_closeout.get("child_request_id") != child_request.get("request_id"):
        raise DualContourCloseoutError("native closeout child_request_id does not match request_id")
    if native_closeout.get("schema_hashes") != child_request.get("schema_hashes"):
        raise DualContourCloseoutError("native closeout schema_hashes do not match child request")
    if native_closeout.get("conformance_vectors_hash") != conformance_vectors_hash(child_request):
        raise DualContourCloseoutError("native closeout conformance_vectors_hash mismatch")


def _validate_native_closeout_suites(
    child_request: dict[str, Any],
    native_closeout: dict[str, Any],
) -> None:
    if native_closeout.get("schema_hashes") != child_request.get("schema_hashes"):
        raise DualContourCloseoutError("native closeout schema_hashes do not match child request")
    if _suite_status(native_closeout, "producer_suite") != "PASS":
        raise DualContourCloseoutError("native producer suite did not PASS")
    if _suite_status(native_closeout, "consumer_suite") != "PASS":
        raise DualContourCloseoutError("native consumer suite did not PASS")


def _validate_native_closeout_authority(native_closeout: dict[str, Any]) -> None:
    for field in (
        "parent_direct_external_writes",
        "live_actions",
    ):
        if native_closeout.get(field) != 0:
            raise DualContourCloseoutError(f"native closeout {field} must be 0")
    for field in (
        "grants_authority",
        "scientific_authority_granted",
        "domain_authority_granted",
    ):
        if native_closeout.get(field) is not False:
            raise DualContourCloseoutError(f"native closeout {field} must be false")


def _suite_status(native_closeout: dict[str, Any], key: str) -> str:
    suite = native_closeout.get(key)
    if not isinstance(suite, dict):
        raise DualContourCloseoutError(f"native closeout {key} must be an object")
    return _require_non_empty(suite.get("status"), f"native_closeout.{key}.status")


def _require_object_id(value: Any, field: str) -> str:
    try:
        return validate_object_id(value)
    except ContractError as exc:
        raise DualContourCloseoutError(f"{field} must be a canonical object id") from exc


def _require_non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DualContourCloseoutError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "DUAL_CONTOUR_CLOSEOUT_SCHEMA_VERSION",
    "DUAL_CONTOUR_IMPORTED_STATUS",
    "DUAL_CONTOUR_IMPORT_RECEIPT_SCHEMA_VERSION",
    "DUAL_CONTOUR_REJECTED_STATUS",
    "DUAL_CONTOUR_WAIT_STATUS",
    "DualContourCloseoutError",
    "build_dual_contour_closeout_import_receipt",
    "closeout_payload_hash",
    "conformance_vectors_hash",
]
