"""Shared-contract child mission packets for native downstream validation."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import load_schema, validate

SHARED_CONTRACT_CHILD_MISSION_REQUEST_SCHEMA_VERSION: Final[str] = (
    "SharedContractChildMissionRequest/v1"
)
SHARED_CONTRACT_CONFORMANCE_RECEIPT_SCHEMA_VERSION: Final[str] = (
    "SharedContractConformanceReceipt/v1"
)
_TEST_HMAC_SHA256: Final[str] = "test-hmac-sha256"


class SharedContractError(ContractError):
    """Raised when a shared-contract packet or vector is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


@dataclass(frozen=True)
class ConformanceVector:
    """One schema-bound public-safe conformance vector."""

    vector_id: str
    schema_name: str
    expected: str
    instance: dict[str, object]

    def __post_init__(self) -> None:
        for field in ("vector_id", "schema_name", "expected"):
            _require_non_empty(getattr(self, field), field)
        if self.expected not in {"ACCEPT", "REJECT"}:
            raise SharedContractError("expected must be ACCEPT or REJECT")
        if not isinstance(self.instance, dict):
            raise SharedContractError("instance must be an object")

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible vector data."""
        return {
            "vector_id": self.vector_id,
            "schema_name": self.schema_name,
            "expected": self.expected,
            "instance": self.instance,
        }


def default_shared_contract_vectors() -> tuple[ConformanceVector, ...]:
    """Return deterministic domain-neutral conformance vectors."""
    payload = {"kind": "synthetic-domain-neutral", "value": 1}
    request_id = "sha256:" + hashlib.sha256(dumps(payload)).hexdigest()
    trace_id = "sha256:" + hashlib.sha256(b"trace").hexdigest()
    valid_request = {
        "schema_version": "ScientificRequestEnvelope/v1",
        "request_id": request_id,
        "trace_id": trace_id,
        "payload": payload,
        "created_utc": "2026-07-29T00:00:00Z",
        "classification": "D0",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    result_payload = {"observed": "synthetic", "authority": "none"}
    valid_result = {
        "schema_version": "ScientificResultEnvelope/v1",
        "result_id": "sha256:" + hashlib.sha256(dumps(result_payload)).hexdigest(),
        "request_id": request_id,
        "status": "WAIT_CAPABILITY",
        "payload": result_payload,
        "created_utc": "2026-07-29T00:00:01Z",
        "classification": "D0",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    rejected_result = dict(valid_result)
    rejected_result["result_id"] = "sha256:" + hashlib.sha256(b"bad-result").hexdigest()
    rejected_result["grants_authority"] = True
    return (
        ConformanceVector(
            "request.accept.basic",
            "ScientificRequestEnvelope",
            "ACCEPT",
            valid_request,
        ),
        ConformanceVector("result.accept.wait", "ScientificResultEnvelope", "ACCEPT", valid_result),
        ConformanceVector(
            "result.reject.authority",
            "ScientificResultEnvelope",
            "REJECT",
            rejected_result,
        ),
    )


def build_shared_contract_conformance_receipt(
    *,
    vectors: tuple[ConformanceVector, ...] | None = None,
) -> dict[str, object]:
    """Validate vectors against local SRF schemas and return a receipt."""
    selected = vectors or default_shared_contract_vectors()
    outcomes: list[dict[str, object]] = []
    for vector in selected:
        accepted = _vector_accepted(vector)
        if vector.expected == "ACCEPT" and not accepted:
            raise SharedContractError(f"vector {vector.vector_id} should accept")
        if vector.expected == "REJECT" and accepted:
            raise SharedContractError(f"vector {vector.vector_id} should reject")
        outcomes.append(
            {
                "vector_id": vector.vector_id,
                "schema_name": vector.schema_name,
                "expected": vector.expected,
                "observed": "ACCEPT" if accepted else "REJECT",
            }
        )
    body: dict[str, object] = {
        "schema_version": SHARED_CONTRACT_CONFORMANCE_RECEIPT_SCHEMA_VERSION,
        "vectors": [vector.to_dict() for vector in selected],
        "outcomes": outcomes,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["receipt_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def build_shared_contract_child_mission_request(  # noqa: PLR0913
    *,
    source_head: str,
    target_head: str,
    target_status: str,
    signer_key_id: str,
    key_material: bytes,
    vectors: tuple[ConformanceVector, ...] | None = None,
) -> dict[str, object]:
    """Build a signed SRF-to-DualContour child mission request."""
    _require_non_empty(source_head, "source_head")
    _require_non_empty(target_head, "target_head")
    _require_non_empty(target_status, "target_status")
    _require_non_empty(signer_key_id, "signer_key_id")
    if not key_material:
        raise SharedContractError("key_material must not be empty")
    selected = vectors or default_shared_contract_vectors()
    schema_names = tuple(sorted({vector.schema_name for vector in selected}))
    receipt = build_shared_contract_conformance_receipt(vectors=selected)
    unsigned: dict[str, object] = {
        "schema_version": SHARED_CONTRACT_CHILD_MISSION_REQUEST_SCHEMA_VERSION,
        "mission_id": "srf-dualcontour-shared-contracts-v1",
        "source_project": "scientific-resource-lab",
        "target_project": "dual-contour-research-os",
        "source_head": source_head,
        "target_head": target_head,
        "target_status": target_status,
        "requested_action": "native validate shared schemas and conformance vectors",
        "schema_hashes": {name: _schema_hash(name) for name in schema_names},
        "conformance_vectors": [vector.to_dict() for vector in selected],
        "local_conformance_receipt_id": receipt["receipt_id"],
        "native_closeout_status": "WAIT_NATIVE_CHILD_CLOSEOUT",
        "authority_boundary": "proposal_only_no_domain_truth_no_target_write_by_parent",
        "classification": "D0",
        "parent_direct_external_writes": 0,
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


def verify_shared_contract_child_mission_request(
    request: dict[str, object],
    *,
    key_material_by_id: dict[str, bytes],
) -> None:
    """Verify a deterministic test-HMAC child mission request."""
    signer_key_id = request.get("signer_key_id")
    signature = request.get("signature")
    algorithm = request.get("signature_algorithm")
    if not isinstance(signer_key_id, str) or not signer_key_id:
        raise SharedContractError("signer_key_id must be a non-empty string")
    if not isinstance(signature, str) or not signature:
        raise SharedContractError("signature must be a non-empty string")
    if algorithm != _TEST_HMAC_SHA256:
        raise SharedContractError("unsupported signature algorithm")
    key_material = key_material_by_id.get(signer_key_id)
    if key_material is None:
        raise SharedContractError("unknown signer key")
    unsigned = {
        key: value
        for key, value in request.items()
        if key not in {"request_id", "signer_key_id", "signature_algorithm", "signature"}
    }
    expected = hmac.new(key_material, dumps(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise SharedContractError("signature verification failed")


def _schema_hash(name: str) -> str:
    return hashlib.sha256(dumps(load_schema(name))).hexdigest()


def _vector_accepted(vector: ConformanceVector) -> bool:
    try:
        validate(vector.instance, vector.schema_name)
    except ContractError:
        return False
    return True


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise SharedContractError(f"{field} must be a non-empty string")


__all__ = [
    "SHARED_CONTRACT_CHILD_MISSION_REQUEST_SCHEMA_VERSION",
    "SHARED_CONTRACT_CONFORMANCE_RECEIPT_SCHEMA_VERSION",
    "ConformanceVector",
    "SharedContractError",
    "build_shared_contract_child_mission_request",
    "build_shared_contract_conformance_receipt",
    "default_shared_contract_vectors",
    "verify_shared_contract_child_mission_request",
]
