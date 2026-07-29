"""Independent SRFPulse and read-only federation status projection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate as schema_validate

SRF_PULSE_SCHEMA_VERSION: Final[str] = "SRFPulse/v1"
FEDERATION_STATUS_SCHEMA_VERSION: Final[str] = "FederationStatus/v1"

_SHA256_ZERO: Final[str] = "sha256:" + "0" * 64
_GIT_SHA_LEN: Final[int] = 40


class HealthContractError(ContractError):
    """Raised when an SRF health object violates its local contract."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class PulseStatus(StrEnum):
    """SRFPulse status values from the public contract."""

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    WAIT = "WAIT"


@dataclass(frozen=True)
class PulseAssessment:
    """Read-only assessment of one pulse against expected freshness and head."""

    status: PulseStatus
    reason: str
    wait_state: str | None


@dataclass(frozen=True)
class CellProjection:
    """Read-only status projection for one federation cell."""

    cell_id: str
    native_status: str
    projection: str
    source: str
    detail: str = ""

    def __post_init__(self) -> None:
        for field in ("cell_id", "native_status", "projection", "source"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise HealthContractError(f"{field} must be a non-empty string")

    def to_dict(self) -> dict[str, object]:
        """Return a schema-compatible cell projection object."""
        return {
            "cell_id": self.cell_id,
            "native_status": self.native_status,
            "projection": self.projection,
            "source": self.source,
            "detail": self.detail,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def build_srf_pulse(
    *,
    status: PulseStatus,
    observed_utc: str,
    head_sha: str,
) -> dict[str, object]:
    """Build and validate an ``SRFPulse/v1`` with a self hash."""
    _validate_head_sha(head_sha)
    _parse_utc(observed_utc)
    body: dict[str, object] = {
        "schema_version": SRF_PULSE_SCHEMA_VERSION,
        "pulse_id": _SHA256_ZERO,
        "status": status.value,
        "observed_utc": observed_utc,
        "head_sha": head_sha,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["pulse_id"] = _self_digest(body, "pulse_id")
    schema_validate(body, "SRFPulse")
    return body


def assess_pulse(
    pulse: dict[str, object],
    *,
    expected_head_sha: str,
    observed_utc: str,
    max_age_seconds: int,
) -> PulseAssessment:
    """Assess pulse freshness and HEAD binding without mutating health."""
    schema_validate(pulse, "SRFPulse")
    _validate_head_sha(expected_head_sha)
    if max_age_seconds < 0:
        raise HealthContractError("max_age_seconds must be non-negative")
    if pulse["head_sha"] != expected_head_sha:
        return PulseAssessment(PulseStatus.WAIT, "cross_head_pulse", "WAIT_SRF")
    pulse_time = _parse_utc(str(pulse["observed_utc"]))
    observed_time = _parse_utc(observed_utc)
    if (observed_time - pulse_time).total_seconds() > max_age_seconds:
        return PulseAssessment(PulseStatus.WAIT, "stale_pulse", "WAIT_SRF")
    return PulseAssessment(PulseStatus(str(pulse["status"])), "fresh", None)


def project_cell(
    *,
    cell_id: str,
    native_status: str,
    source: str,
    detail: str = "",
    is_srf: bool = False,
) -> CellProjection:
    """Project a native cell status without changing native health authority."""
    projection = "WAIT_SRF" if is_srf and native_status in {"WAIT", "RED"} else native_status
    return CellProjection(
        cell_id=cell_id,
        native_status=native_status,
        projection=projection,
        source=source,
        detail=detail,
    )


def build_federation_status(
    *,
    cells: tuple[CellProjection, ...],
    observed_utc: str,
) -> dict[str, object]:
    """Build and validate read-only ``FederationStatus/v1``."""
    _parse_utc(observed_utc)
    cell_dicts = sorted((cell.to_dict() for cell in cells), key=lambda item: dumps(item))
    body: dict[str, object] = {
        "schema_version": FEDERATION_STATUS_SCHEMA_VERSION,
        "status_id": _SHA256_ZERO,
        "observed_utc": observed_utc,
        "cells": cell_dicts,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["status_id"] = _self_digest(body, "status_id")
    schema_validate(body, "FederationStatus")
    return body


def _self_digest(body: dict[str, object], id_field: str) -> str:
    seed = dict(body)
    seed[id_field] = _SHA256_ZERO
    return "sha256:" + hashlib.sha256(dumps(seed)).hexdigest()


def _validate_head_sha(head_sha: str) -> None:
    if not isinstance(head_sha, str) or len(head_sha) != _GIT_SHA_LEN:
        raise HealthContractError("head_sha must be a 40-character Git SHA")
    if any(ch not in "0123456789abcdef" for ch in head_sha):
        raise HealthContractError("head_sha must be lowercase hex")


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise HealthContractError("timestamp must be UTC ISO-8601 seconds") from exc
    return parsed.replace(tzinfo=UTC)


__all__ = [
    "FEDERATION_STATUS_SCHEMA_VERSION",
    "SRF_PULSE_SCHEMA_VERSION",
    "CellProjection",
    "HealthContractError",
    "PulseAssessment",
    "PulseStatus",
    "assess_pulse",
    "build_federation_status",
    "build_srf_pulse",
    "project_cell",
]
