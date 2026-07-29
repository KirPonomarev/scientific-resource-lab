"""Bounded restore drill over content-addressed fixture stores."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from srl.cas.store import ArtifactStore, LocalArtifactStore
from srl.contracts.artifact_refs import validate_digest
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate as schema_validate

RESTORE_DRILL_RECEIPT_SCHEMA_VERSION: Final[str] = "RestoreDrillReceipt/v1"
_SHA256_ZERO: Final[str] = "sha256:" + "0" * 64


class RestoreDrillError(ContractError):
    """Raised when a bounded restore drill would violate its safety contract."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def bounded_restore_drill(
    *,
    source_store: ArtifactStore,
    restore_root: str | Path,
    artifact_ids: tuple[str, ...],
    created_utc: str,
) -> dict[str, object]:
    """Restore exact artifacts into a fresh fixture target and return a receipt.

    The drill never overwrites a non-empty target. It reads from the source CAS,
    letting the source store perform integrity checks, then writes the bytes into
    a fresh local fixture store and verifies that each restored digest is present.
    """
    target_root = Path(restore_root)
    if target_root.exists() and any(target_root.iterdir()):
        raise RestoreDrillError("restore target must be empty; refusing overwrite")
    target_root.mkdir(parents=True, exist_ok=True)
    unique_ids = tuple(dict.fromkeys(_validate_artifacts(artifact_ids)))
    target = LocalArtifactStore(target_root)
    restored: list[str] = []
    for artifact_id in unique_ids:
        data = source_store.get(artifact_id)
        descriptor = target.put(data)
        if descriptor.digest != artifact_id or not target.has(artifact_id):
            raise RestoreDrillError(f"restored digest mismatch for {artifact_id!r}")
        restored.append(artifact_id)
    body: dict[str, object] = {
        "schema_version": RESTORE_DRILL_RECEIPT_SCHEMA_VERSION,
        "receipt_id": _SHA256_ZERO,
        "result": "PASS",
        "restored_artifacts": sorted(restored),
        "created_utc": created_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["receipt_id"] = _self_digest(body)
    schema_validate(body, "RestoreDrillReceipt")
    return body


def _validate_artifacts(artifact_ids: tuple[str, ...]) -> tuple[str, ...]:
    if not artifact_ids:
        raise RestoreDrillError("artifact_ids must not be empty")
    validated: list[str] = []
    for artifact_id in artifact_ids:
        try:
            validated.append(validate_digest(artifact_id, field="artifact_ids"))
        except ContractError as exc:
            raise RestoreDrillError(f"invalid artifact id: {artifact_id!r}") from exc
    return tuple(validated)


def _self_digest(body: dict[str, object]) -> str:
    seed = dict(body)
    seed["receipt_id"] = _SHA256_ZERO
    return "sha256:" + hashlib.sha256(dumps(seed)).hexdigest()


__all__ = [
    "RESTORE_DRILL_RECEIPT_SCHEMA_VERSION",
    "RestoreDrillError",
    "bounded_restore_drill",
]
