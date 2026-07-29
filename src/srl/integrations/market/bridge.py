"""Inactive proposal-only bridge between SRF and Market Research OS."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate

MARKET_ADAPTER_INACTIVE_RECEIPT_SCHEMA_VERSION: Final[str] = "MarketAdapterInactiveReceipt/v1"
MARKET_OBSERVATION_PACKET_SCHEMA_VERSION: Final[str] = "MarketScienceObservationPacket/v1"

_CREATED_UTC: Final[str] = "2026-07-29T00:00:00Z"
_BLOCKED_MARKET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(place|submit|send|execute)\s+(order|trade)\b", re.I),
    re.compile(r"\b(buy|sell|long|short|leverage|liquidate)\b", re.I),
    re.compile(r"\btrading\s+strategy\b", re.I),
    re.compile(r"\b(api[_ -]?key|credential|secret)\b", re.I),
    re.compile(r"\bD[23]\b"),
    re.compile(r"/Users/|/Volumes/|/private/", re.I),
)


class MarketBridgeError(ContractError):
    """Raised when Market bridge input violates inactive C3 boundaries."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class MarketBridgeStatus(StrEnum):
    """Inactive Market bridge health projection."""

    INACTIVE = "INACTIVE"
    WAIT_RUNTIME_HEALTH = "WAIT_RUNTIME_HEALTH"


@dataclass(frozen=True)
class MarketObservationPacket:
    """Validated Market-origin observation packet."""

    observation_id: str
    request_id: str
    market_head: str
    payload: dict[str, object]
    classification: str = "D0"
    semantic_class: str = "C3_PROPOSAL"
    authority_claimed: bool = False
    trading_action: str | None = None

    def __post_init__(self) -> None:
        _require_sha(self.observation_id, "observation_id")
        _require_sha(self.request_id, "request_id")
        _require_git_head(self.market_head, "market_head")
        if self.classification not in {"D0", "D1"}:
            raise MarketBridgeError("Market packet classification must be D0 or D1")
        if self.semantic_class != "C3_PROPOSAL":
            raise MarketBridgeError("Market packet must remain C3_PROPOSAL")
        if self.authority_claimed:
            raise MarketBridgeError("Market packet must not claim authority")
        if self.trading_action not in {None, ""}:
            raise MarketBridgeError("Market packet must not carry a trading action")
        _scan_public_safe(self.payload)

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible packet."""
        return {
            "schema_version": MARKET_OBSERVATION_PACKET_SCHEMA_VERSION,
            "observation_id": self.observation_id,
            "request_id": self.request_id,
            "market_head": self.market_head,
            "payload": self.payload,
            "classification": self.classification,
            "semantic_class": self.semantic_class,
            "authority_claimed": self.authority_claimed,
            "trading_action": self.trading_action,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def build_market_science_request(
    *,
    objective: str,
    market_head: str,
    evidence_refs: tuple[str, ...] = (),
    classification: str = "D0",
) -> dict[str, object]:
    """Build a ScientificRequestEnvelope for inactive Market intake."""
    _require_non_empty(objective, "objective")
    _require_git_head(market_head, "market_head")
    _require_tuple(evidence_refs, "evidence_refs")
    if classification not in {"D0", "D1"}:
        raise MarketBridgeError("classification must be D0 or D1")
    _scan_public_safe(objective)
    payload: dict[str, object] = {
        "domain": "market",
        "objective": objective,
        "evidence_refs": list(evidence_refs),
        "semantic_class": "C3_PROPOSAL",
        "activation_state": "INACTIVE",
        "central_projector_required": True,
        "native_admission_required": True,
        "trading_allowed": False,
        "live_actions_allowed": False,
        "market_head": market_head,
    }
    request_id = "sha256:" + hashlib.sha256(dumps(payload)).hexdigest()
    envelope: dict[str, object] = {
        "schema_version": "ScientificRequestEnvelope/v1",
        "request_id": request_id,
        "trace_id": "sha256:" + hashlib.sha256((request_id + market_head).encode()).hexdigest(),
        "payload": payload,
        "created_utc": _CREATED_UTC,
        "classification": classification,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    validate(envelope, "ScientificRequestEnvelope")
    return envelope


def import_market_observation_packet(
    packet: dict[str, object] | MarketObservationPacket,
    *,
    expected_market_head: str,
    seen_observation_ids: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Validate a Market C3 observation and map it to a ScientificResultEnvelope."""
    _require_git_head(expected_market_head, "expected_market_head")
    observation = _coerce_packet(packet)
    if observation.market_head != expected_market_head:
        raise MarketBridgeError("stale or cross-bound Market head")
    if observation.observation_id in seen_observation_ids:
        raise MarketBridgeError("duplicate Market observation import")
    result_payload: dict[str, object] = {
        "source": "market",
        "semantic_class": observation.semantic_class,
        "activation_state": "INACTIVE",
        "central_projector_required": True,
        "native_admission_required": True,
        "observation": observation.payload,
        "market_head": observation.market_head,
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


def build_market_bridge_health_projection(
    *,
    market_gate: str,
    market_head: str,
) -> dict[str, object]:
    """Project Market health into the inactive SRF bridge status."""
    _require_non_empty(market_gate, "market_gate")
    _require_git_head(market_head, "market_head")
    status = (
        MarketBridgeStatus.INACTIVE
        if market_gate == "GREEN"
        else MarketBridgeStatus.WAIT_RUNTIME_HEALTH
    )
    body: dict[str, object] = {
        "schema_version": MARKET_ADAPTER_INACTIVE_RECEIPT_SCHEMA_VERSION,
        "status": status.value,
        "market_gate": market_gate,
        "market_head": market_head,
        "activation_state": "INACTIVE",
        "market_writes": 0,
        "live_actions": 0,
        "trading_allowed": False,
        "central_projector_required": True,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["receipt_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def _coerce_packet(packet: dict[str, object] | MarketObservationPacket) -> MarketObservationPacket:
    if isinstance(packet, MarketObservationPacket):
        return packet
    if packet.get("schema_version") != MARKET_OBSERVATION_PACKET_SCHEMA_VERSION:
        raise MarketBridgeError("unexpected Market observation schema_version")
    payload = packet.get("payload")
    if not isinstance(payload, dict):
        raise MarketBridgeError("payload must be an object")
    return MarketObservationPacket(
        observation_id=_expect_str(packet, "observation_id"),
        request_id=_expect_str(packet, "request_id"),
        market_head=_expect_str(packet, "market_head"),
        payload=payload,
        classification=_expect_str(packet, "classification"),
        semantic_class=_expect_str(packet, "semantic_class"),
        authority_claimed=_expect_bool(packet, "authority_claimed"),
        trading_action=_optional_str(packet, "trading_action"),
    )


def _scan_public_safe(value: object) -> None:
    text = dumps(value).decode()
    for pattern in _BLOCKED_MARKET_PATTERNS:
        if pattern.search(text):
            raise MarketBridgeError("Market bridge input contains forbidden live/private material")


def _expect_str(packet: dict[str, object], key: str) -> str:
    value = packet.get(key)
    if not isinstance(value, str) or not value:
        raise MarketBridgeError(f"{key} must be a non-empty string")
    return value


def _expect_bool(packet: dict[str, object], key: str) -> bool:
    value = packet.get(key)
    if not isinstance(value, bool):
        raise MarketBridgeError(f"{key} must be a bool")
    return value


def _optional_str(packet: dict[str, object], key: str) -> str | None:
    value = packet.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MarketBridgeError(f"{key} must be a string or null")
    return value


def _require_sha(value: str, field: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise MarketBridgeError(f"{field} must be a sha256 digest")


def _require_git_head(value: str, field: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise MarketBridgeError(f"{field} must be a git commit SHA")


def _require_tuple(values: object, field: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise MarketBridgeError(f"{field} must be a tuple of non-empty strings")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise MarketBridgeError(f"{field} must be a non-empty string")


__all__ = [
    "MARKET_ADAPTER_INACTIVE_RECEIPT_SCHEMA_VERSION",
    "MARKET_OBSERVATION_PACKET_SCHEMA_VERSION",
    "MarketBridgeError",
    "MarketBridgeStatus",
    "build_market_bridge_health_projection",
    "build_market_science_request",
    "import_market_observation_packet",
]
