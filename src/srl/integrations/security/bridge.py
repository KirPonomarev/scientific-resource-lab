"""Inactive advisory bridge between SRF and the native Security cell."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate

SECURITY_ADAPTER_INACTIVE_RECEIPT_SCHEMA_VERSION: Final[str] = "SecurityAdapterInactiveReceipt/v1"
SECURITY_OBSERVATION_PACKET_SCHEMA_VERSION: Final[str] = "SecurityObservationPacket/v1"

_CREATED_UTC: Final[str] = "2026-07-29T00:00:00Z"
_BLOCKED_SECURITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(exploit|payload|shellcode|reverse\s+shell|rce|0day|cve-\d)", re.I),
    re.compile(r"\b(scan|attack|enumerate|bruteforce|phish)\s+(target|host|ip|domain)\b", re.I),
    re.compile(r"\b(api[_ -]?key|credential|secret|token|password)\b", re.I),
    re.compile(r"\bD[23]\b"),
    re.compile(r"\bPRIVATE_PATH_MARKER\b"),
    re.compile(r"/Users/|/Volumes/|/private/", re.I),
    re.compile(r"\b(ignore previous|system prompt|developer message|jailbreak)\b", re.I),
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
)


class SecurityBridgeError(ContractError):
    """Raised when Security bridge input violates inactive advisory boundaries."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class SecurityBridgeStatus(StrEnum):
    """Inactive Security bridge health projection."""

    INACTIVE = "INACTIVE"
    WAIT_SECURITY_HEALTH = "WAIT_SECURITY_HEALTH"


@dataclass(frozen=True)
class SecurityObservationPacket:
    """Validated Security-origin advisory packet."""

    observation_id: str
    request_id: str
    security_head: str
    payload: dict[str, object]
    classification: str = "D0"
    semantic_class: str = "C3_PROPOSAL"
    executor: str = "ebashim"
    authority_claimed: bool = False
    target_action: str | None = None

    def __post_init__(self) -> None:
        _require_sha(self.observation_id, "observation_id")
        _require_sha(self.request_id, "request_id")
        _require_git_head(self.security_head, "security_head")
        if self.classification not in {"D0", "D1"}:
            raise SecurityBridgeError("Security packet classification must be D0 or D1")
        if self.semantic_class != "C3_PROPOSAL":
            raise SecurityBridgeError("Security packet must remain C3_PROPOSAL")
        if self.executor != "ebashim":
            raise SecurityBridgeError("ebashim must remain the sole native executor boundary")
        if self.authority_claimed:
            raise SecurityBridgeError("Security packet must not claim authority")
        if self.target_action not in {None, ""}:
            raise SecurityBridgeError("Security packet must not carry a target action")
        _scan_public_safe(self.payload)


def build_security_science_request(
    *,
    objective: str,
    security_head: str,
    evidence_refs: tuple[str, ...] = (),
    classification: str = "D0",
) -> dict[str, object]:
    """Build a sanitized ScientificRequestEnvelope for inactive Security intake."""
    _require_non_empty(objective, "objective")
    _require_git_head(security_head, "security_head")
    _require_tuple(evidence_refs, "evidence_refs")
    if classification not in {"D0", "D1"}:
        raise SecurityBridgeError("classification must be D0 or D1")
    _scan_public_safe(objective)
    payload: dict[str, object] = {
        "domain": "security",
        "objective": objective,
        "evidence_refs": list(evidence_refs),
        "semantic_class": "C3_PROPOSAL",
        "activation_state": "INACTIVE",
        "native_executor_boundary": "ebashim",
        "native_admission_required": True,
        "target_actions_allowed": False,
        "direct_scanner_control": False,
        "security_head": security_head,
    }
    request_id = "sha256:" + hashlib.sha256(dumps(payload)).hexdigest()
    envelope: dict[str, object] = {
        "schema_version": "ScientificRequestEnvelope/v1",
        "request_id": request_id,
        "trace_id": "sha256:" + hashlib.sha256((request_id + security_head).encode()).hexdigest(),
        "payload": payload,
        "created_utc": _CREATED_UTC,
        "classification": classification,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    validate(envelope, "ScientificRequestEnvelope")
    return envelope


def import_security_observation_packet(
    packet: dict[str, object] | SecurityObservationPacket,
    *,
    expected_security_head: str,
    seen_observation_ids: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Validate a Security C3 observation and map it to a result envelope."""
    _require_git_head(expected_security_head, "expected_security_head")
    observation = _coerce_packet(packet)
    if observation.security_head != expected_security_head:
        raise SecurityBridgeError("stale or cross-bound Security head")
    if observation.observation_id in seen_observation_ids:
        raise SecurityBridgeError("duplicate Security observation import")
    result_payload: dict[str, object] = {
        "source": "security",
        "semantic_class": observation.semantic_class,
        "activation_state": "INACTIVE",
        "native_executor_boundary": observation.executor,
        "native_admission_required": True,
        "target_actions_allowed": False,
        "observation": observation.payload,
        "security_head": observation.security_head,
    }
    result_id = "sha256:" + hashlib.sha256(dumps(result_payload)).hexdigest()
    envelope: dict[str, object] = {
        "schema_version": "ScientificResultEnvelope/v1",
        "result_id": result_id,
        "request_id": observation.request_id,
        "status": "COMPLETED",
        "payload": result_payload,
        "created_utc": "2026-07-29T00:00:01Z",
        "classification": observation.classification,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    validate(envelope, "ScientificResultEnvelope")
    return envelope


def build_security_bridge_health_projection(
    *,
    security_gate: str,
    security_head: str,
) -> dict[str, object]:
    """Project native Security health into inactive SRF bridge status."""
    _require_non_empty(security_gate, "security_gate")
    _require_git_head(security_head, "security_head")
    status = (
        SecurityBridgeStatus.INACTIVE
        if security_gate == "GREEN"
        else SecurityBridgeStatus.WAIT_SECURITY_HEALTH
    )
    body: dict[str, object] = {
        "schema_version": SECURITY_ADAPTER_INACTIVE_RECEIPT_SCHEMA_VERSION,
        "status": status.value,
        "security_gate": security_gate,
        "security_head": security_head,
        "activation_state": "INACTIVE",
        "native_executor_boundary": "ebashim",
        "security_actions": 0,
        "target_actions": 0,
        "D2_D3_transfers": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["receipt_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def _coerce_packet(
    packet: dict[str, object] | SecurityObservationPacket,
) -> SecurityObservationPacket:
    if isinstance(packet, SecurityObservationPacket):
        return packet
    if packet.get("schema_version") != SECURITY_OBSERVATION_PACKET_SCHEMA_VERSION:
        raise SecurityBridgeError("unexpected Security observation schema_version")
    payload = packet.get("payload")
    if not isinstance(payload, dict):
        raise SecurityBridgeError("payload must be an object")
    return SecurityObservationPacket(
        observation_id=_expect_str(packet, "observation_id"),
        request_id=_expect_str(packet, "request_id"),
        security_head=_expect_str(packet, "security_head"),
        payload=payload,
        classification=_expect_str(packet, "classification"),
        semantic_class=_expect_str(packet, "semantic_class"),
        executor=_expect_str(packet, "executor"),
        authority_claimed=_expect_bool(packet, "authority_claimed"),
        target_action=_optional_str(packet, "target_action"),
    )


def _scan_public_safe(value: object) -> None:
    text = dumps(value).decode()
    for pattern in _BLOCKED_SECURITY_PATTERNS:
        if pattern.search(text):
            raise SecurityBridgeError("Security bridge input contains forbidden sensitive material")


def _expect_str(packet: dict[str, object], key: str) -> str:
    value = packet.get(key)
    if not isinstance(value, str) or not value:
        raise SecurityBridgeError(f"{key} must be a non-empty string")
    return value


def _expect_bool(packet: dict[str, object], key: str) -> bool:
    value = packet.get(key)
    if not isinstance(value, bool):
        raise SecurityBridgeError(f"{key} must be a bool")
    return value


def _optional_str(packet: dict[str, object], key: str) -> str | None:
    value = packet.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SecurityBridgeError(f"{key} must be a string or null")
    return value


def _require_sha(value: str, field: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise SecurityBridgeError(f"{field} must be a sha256 digest")


def _require_git_head(value: str, field: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise SecurityBridgeError(f"{field} must be a git commit SHA")


def _require_tuple(values: object, field: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise SecurityBridgeError(f"{field} must be a tuple of non-empty strings")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise SecurityBridgeError(f"{field} must be a non-empty string")


__all__ = [
    "SECURITY_ADAPTER_INACTIVE_RECEIPT_SCHEMA_VERSION",
    "SECURITY_OBSERVATION_PACKET_SCHEMA_VERSION",
    "SecurityBridgeError",
    "SecurityBridgeStatus",
    "build_security_bridge_health_projection",
    "build_security_science_request",
    "import_security_observation_packet",
]
