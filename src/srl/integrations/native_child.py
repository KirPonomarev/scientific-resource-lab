"""Native child mission packets for external repository bridge lanes."""

from __future__ import annotations

import hashlib
import hmac
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

NATIVE_BRIDGE_CHILD_REQUEST_SCHEMA_VERSION: Final[str] = "NativeBridgeChildRequest/v1"
NATIVE_BRIDGE_WAIT_RECEIPT_SCHEMA_VERSION: Final[str] = "NativeBridgeWaitReceipt/v1"
_TEST_HMAC_SHA256: Final[str] = "test-hmac-sha256"


class NativeChildError(ContractError):
    """Raised when a native child request is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def build_native_bridge_child_request(  # noqa: PLR0913
    *,
    mission_id: str,
    source_head: str,
    target_project: str,
    target_head: str,
    dependency_status: str,
    adapter_receipt_id: str,
    requested_action: str,
    signer_key_id: str,
    key_material: bytes,
) -> dict[str, object]:
    """Build a signed proposal-only native bridge child request."""
    for field, value in (
        ("mission_id", mission_id),
        ("source_head", source_head),
        ("target_project", target_project),
        ("target_head", target_head),
        ("dependency_status", dependency_status),
        ("adapter_receipt_id", adapter_receipt_id),
        ("requested_action", requested_action),
        ("signer_key_id", signer_key_id),
    ):
        _require_non_empty(value, field)
    if not key_material:
        raise NativeChildError("key_material must not be empty")
    unsigned: dict[str, object] = {
        "schema_version": NATIVE_BRIDGE_CHILD_REQUEST_SCHEMA_VERSION,
        "mission_id": mission_id,
        "source_project": "scientific-resource-lab",
        "source_head": source_head,
        "target_project": target_project,
        "target_head": target_head,
        "dependency_status": dependency_status,
        "adapter_receipt_id": adapter_receipt_id,
        "requested_action": requested_action,
        "native_closeout_status": "WAIT_NATIVE_CHILD_CLOSEOUT",
        "activation_state": "INACTIVE",
        "authority_boundary": "proposal_only_no_parent_target_write_no_activation",
        "parent_direct_external_writes": 0,
        "live_actions": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    signature = hmac.new(key_material, dumps(unsigned), hashlib.sha256).hexdigest()
    request = dict(unsigned)
    request["signer_key_id"] = signer_key_id
    request["signature_algorithm"] = _TEST_HMAC_SHA256
    request["signature"] = signature
    request["request_id"] = "sha256:" + hashlib.sha256(dumps(request)).hexdigest()
    return request


def build_native_bridge_wait_receipt(
    *,
    child_request: dict[str, object],
    wait_state: str,
    next_native_gate: str,
) -> dict[str, object]:
    """Build an authority-negative receipt for a parked native child lane."""
    _require_non_empty(wait_state, "wait_state")
    _require_non_empty(next_native_gate, "next_native_gate")
    request_id = child_request.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise NativeChildError("child_request.request_id must be a non-empty string")
    body: dict[str, object] = {
        "schema_version": NATIVE_BRIDGE_WAIT_RECEIPT_SCHEMA_VERSION,
        "child_request_id": request_id,
        "target_project": child_request.get("target_project"),
        "target_head": child_request.get("target_head"),
        "wait_state": wait_state,
        "next_native_gate": next_native_gate,
        "parent_direct_external_writes": 0,
        "live_actions": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["receipt_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def verify_native_bridge_child_request(
    request: dict[str, object],
    *,
    key_material_by_id: dict[str, bytes],
) -> None:
    """Verify a deterministic test-HMAC native child request."""
    signer_key_id = request.get("signer_key_id")
    signature = request.get("signature")
    algorithm = request.get("signature_algorithm")
    if not isinstance(signer_key_id, str) or not signer_key_id:
        raise NativeChildError("signer_key_id must be a non-empty string")
    if not isinstance(signature, str) or not signature:
        raise NativeChildError("signature must be a non-empty string")
    if algorithm != _TEST_HMAC_SHA256:
        raise NativeChildError("unsupported signature algorithm")
    key_material = key_material_by_id.get(signer_key_id)
    if key_material is None:
        raise NativeChildError("unknown signer key")
    unsigned = {
        key: value
        for key, value in request.items()
        if key not in {"request_id", "signer_key_id", "signature_algorithm", "signature"}
    }
    expected = hmac.new(key_material, dumps(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise NativeChildError("signature verification failed")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise NativeChildError(f"{field} must be a non-empty string")


__all__ = [
    "NATIVE_BRIDGE_CHILD_REQUEST_SCHEMA_VERSION",
    "NATIVE_BRIDGE_WAIT_RECEIPT_SCHEMA_VERSION",
    "NativeChildError",
    "build_native_bridge_child_request",
    "build_native_bridge_wait_receipt",
    "verify_native_bridge_child_request",
]
