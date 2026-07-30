"""Market native bridge closeout import.

SRF may prepare an inactive proposal-only bridge and later import native
Market evidence, but SRF must not activate Market, write Market state, trade,
or treat child evidence as scientific or operational authority. This module is
the SRF-side fail-closed projection for A19.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id, validate_object_id
from srl.integrations.native_child import verify_native_bridge_child_request

MARKET_NATIVE_CLOSEOUT_SCHEMA_VERSION: Final[str] = "MarketNativeBridgeCloseout/v1"
MARKET_CLOSEOUT_IMPORT_RECEIPT_SCHEMA_VERSION: Final[str] = "MarketCloseoutImportReceipt/v1"
MARKET_WAIT_STATUS: Final[str] = "WAIT_NATIVE_CHILD_CLOSEOUT"
MARKET_IMPORTED_STATUS: Final[str] = "IMPORTED_NATIVE_CHILD_CLOSEOUT"
MARKET_REJECTED_STATUS: Final[str] = "REJECT_NATIVE_CHILD_CLOSEOUT"
MARKET_OFFLINE_WAIT_STATUS: Final[str] = "WAIT_SRF"


class MarketCloseoutError(ContractError):
    """Raised when a Market native bridge closeout cannot be imported."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def market_closeout_payload_hash(native_closeout: dict[str, Any]) -> str:
    """Return the canonical SHA-256 hash of a native Market closeout payload."""
    return hashlib.sha256(dumps(native_closeout)).hexdigest()


def build_market_closeout_import_receipt(
    *,
    child_request: dict[str, Any],
    native_closeout: dict[str, Any] | None,
    key_material_by_id: dict[str, bytes],
    native_bootstrap_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Project native Market closeout evidence into an authority-negative receipt.

    A missing closeout is a truthful WAIT receipt. A present closeout must match
    the child request, include passing native/SRF suites, reuse the central
    projector, and remain inactive/no-trading/no-authority.
    """
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
        "schema_version": MARKET_CLOSEOUT_IMPORT_RECEIPT_SCHEMA_VERSION,
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
            "autonomous_mode": native_bootstrap_evidence.get("autonomous_mode"),
            "next_gate": native_bootstrap_evidence.get("next_gate"),
            "operator_required": native_bootstrap_evidence.get("operator_required"),
            "trading_allowed": native_bootstrap_evidence.get("trading_allowed"),
            "canonical_mutation_allowed": native_bootstrap_evidence.get(
                "canonical_mutation_allowed"
            ),
        },
        "status": MARKET_WAIT_STATUS,
        "srf_offline_status": MARKET_OFFLINE_WAIT_STATUS,
        "native_closeout_payload_sha256": None,
        "native_closeout_receipt_id": None,
        "native_suite_status": None,
        "srf_suite_status": None,
        "activation_state": "INACTIVE",
        "central_projector_required": True,
        "central_projector_reused": None,
        "parent_direct_external_writes": 0,
        "market_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "trading_allowed": False,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "market_activation_authority_granted": False,
    }
    if native_closeout is not None:
        _validate_native_closeout(child_request=child_request, native_closeout=native_closeout)
        body["status"] = MARKET_IMPORTED_STATUS
        body["native_closeout_payload_sha256"] = market_closeout_payload_hash(native_closeout)
        body["native_closeout_receipt_id"] = native_closeout.get("receipt_id")
        body["native_suite_status"] = _suite_status(native_closeout, "native_suite")
        body["srf_suite_status"] = _suite_status(native_closeout, "srf_suite")
        body["central_projector_reused"] = native_closeout.get("central_projector_reused")
    body["receipt_id"] = object_id(body)
    return body


def _validate_native_closeout(
    *,
    child_request: dict[str, Any],
    native_closeout: dict[str, Any],
) -> None:
    if native_closeout.get("schema_version") != MARKET_NATIVE_CLOSEOUT_SCHEMA_VERSION:
        raise MarketCloseoutError("unexpected Market closeout schema_version")
    _validate_native_closeout_identity(child_request, native_closeout)
    _validate_native_closeout_suites(native_closeout)
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
        "adapter_receipt_id",
    ):
        if native_closeout.get(field) != child_request.get(field):
            raise MarketCloseoutError(f"native closeout {field} does not match child request")
    if native_closeout.get("child_request_id") != child_request.get("request_id"):
        raise MarketCloseoutError("native closeout child_request_id does not match request_id")
    if native_closeout.get("central_projector_reused") is not True:
        raise MarketCloseoutError("native closeout must reuse the central projector")


def _validate_native_closeout_suites(native_closeout: dict[str, Any]) -> None:
    if _suite_status(native_closeout, "native_suite") != "PASS":
        raise MarketCloseoutError("native suite did not PASS")
    if _suite_status(native_closeout, "srf_suite") != "PASS":
        raise MarketCloseoutError("SRF suite did not PASS")


def _validate_native_closeout_authority(native_closeout: dict[str, Any]) -> None:
    for field in (
        "parent_direct_external_writes",
        "market_writes",
        "canonical_writes",
        "live_actions",
    ):
        if native_closeout.get(field) != 0:
            raise MarketCloseoutError(f"native closeout {field} must be 0")
    for field in (
        "grants_authority",
        "scientific_authority_granted",
        "market_activation_authority_granted",
        "trading_allowed",
    ):
        if native_closeout.get(field) is not False:
            raise MarketCloseoutError(f"native closeout {field} must be false")
    if native_closeout.get("activation_state") != "INACTIVE":
        raise MarketCloseoutError("native closeout activation_state must stay INACTIVE")


def _suite_status(native_closeout: dict[str, Any], key: str) -> str:
    suite = native_closeout.get(key)
    if not isinstance(suite, dict):
        raise MarketCloseoutError(f"native closeout {key} must be an object")
    return _require_non_empty(suite.get("status"), f"native_closeout.{key}.status")


def _require_object_id(value: Any, field: str) -> str:
    try:
        return validate_object_id(value)
    except ContractError as exc:
        raise MarketCloseoutError(f"{field} must be a canonical object id") from exc


def _require_non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MarketCloseoutError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "MARKET_CLOSEOUT_IMPORT_RECEIPT_SCHEMA_VERSION",
    "MARKET_IMPORTED_STATUS",
    "MARKET_NATIVE_CLOSEOUT_SCHEMA_VERSION",
    "MARKET_OFFLINE_WAIT_STATUS",
    "MARKET_REJECTED_STATUS",
    "MARKET_WAIT_STATUS",
    "MarketCloseoutError",
    "build_market_closeout_import_receipt",
    "market_closeout_payload_hash",
]
