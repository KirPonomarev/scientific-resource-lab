"""Science pack governance: SBOM, lock, revocation and ACTIVE admission gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from srl.contracts.artifact_refs import validate_digest
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate as schema_validate
from srl.packs.manifest import LICENSE_ALLOWLIST, ResourcePackManifest, build_manifest
from srl.packs.receipts import STAGES

SCIENCE_PACK_MANIFEST_V2_SCHEMA_VERSION: Final[str] = "SciencePackManifest/v2"
PACK_GOVERNANCE_RECORD_SCHEMA_VERSION: Final[str] = "PackGovernanceRecord/v1"
PACK_REVOCATION_REGISTRY_SCHEMA_VERSION: Final[str] = "PackRevocationRegistry/v1"
PACK_GOVERNANCE_RECEIPT_SCHEMA_VERSION: Final[str] = "PackGovernanceReceipt/v1"


class PackGovernanceError(ContractError):
    """Raised when pack governance evidence is structurally invalid."""

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


class PackLifecycleStatus(StrEnum):
    """Pack lifecycle status after governance assessment."""

    ACTIVE = "ACTIVE"
    WAIT_SBOM = "WAIT_SBOM"
    WAIT_LOCK = "WAIT_LOCK"
    WAIT_VULNERABILITY_SCAN = "WAIT_VULNERABILITY_SCAN"
    WAIT_ADMISSION_RECEIPT = "WAIT_ADMISSION_RECEIPT"
    WAIT_LICENSE = "WAIT_LICENSE"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class DependencyRecord:
    """One dependency entry from a pack SBOM or lock."""

    dependency_id: str
    version: str
    license_spdx: str
    artifact_sha256: str

    def __post_init__(self) -> None:
        _require_non_empty(self.dependency_id, "dependency_id")
        _require_non_empty(self.version, "version")
        _require_non_empty(self.license_spdx, "license_spdx")
        try:
            validate_digest(self.artifact_sha256, field="artifact_sha256")
        except ContractError as exc:
            msg = f"dependency {self.dependency_id!r} has an invalid artifact_sha256"
            raise PackGovernanceError(msg) from exc

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON-compatible dependency record."""
        return {
            "dependency_id": self.dependency_id,
            "version": self.version,
            "license_spdx": self.license_spdx,
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True)
class VulnerabilityScanSummary:
    """A bounded vulnerability scan summary."""

    scanner: str
    database_sha256: str
    critical_count: int
    high_count: int
    max_allowed_critical: int = 0
    max_allowed_high: int = 0

    def __post_init__(self) -> None:
        _require_non_empty(self.scanner, "scanner")
        validate_digest(self.database_sha256, field="database_sha256")
        for field in (
            "critical_count",
            "high_count",
            "max_allowed_critical",
            "max_allowed_high",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                msg = f"{field} must be a non-negative integer"
                raise PackGovernanceError(msg)

    @property
    def passed(self) -> bool:
        """Return True iff observed vulnerabilities are within policy."""
        return (
            self.critical_count <= self.max_allowed_critical
            and self.high_count <= self.max_allowed_high
        )

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible scan summary."""
        return {
            "scanner": self.scanner,
            "database_sha256": self.database_sha256,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "max_allowed_critical": self.max_allowed_critical,
            "max_allowed_high": self.max_allowed_high,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PackGovernanceEvidence:
    """Evidence required before a pack may become ACTIVE."""

    sbom_sha256: str | None
    lock_sha256: str | None
    dependencies: tuple[DependencyRecord, ...]
    vulnerability_scan: VulnerabilityScanSummary | None
    admission_receipt_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.sbom_sha256 is not None:
            validate_digest(self.sbom_sha256, field="sbom_sha256")
        if self.lock_sha256 is not None:
            validate_digest(self.lock_sha256, field="lock_sha256")
        for receipt_id in self.admission_receipt_ids:
            validate_digest(receipt_id, field="admission_receipt_ids")
        if len(set(self.admission_receipt_ids)) != len(self.admission_receipt_ids):
            msg = "admission_receipt_ids must be unique"
            raise PackGovernanceError(msg)

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible evidence record."""
        return {
            "sbom_sha256": self.sbom_sha256,
            "lock_sha256": self.lock_sha256,
            "dependencies": [dep.to_dict() for dep in self.dependencies],
            "vulnerability_scan": (
                None if self.vulnerability_scan is None else self.vulnerability_scan.to_dict()
            ),
            "admission_receipt_ids": list(self.admission_receipt_ids),
        }


@dataclass(frozen=True)
class PackRevocationRegistry:
    """Revoked pack and dependency identities."""

    revoked_pack_ids: frozenset[str]
    revoked_dependency_ids: frozenset[str]
    schema_version: str = PACK_REVOCATION_REGISTRY_SCHEMA_VERSION
    canonical_writes: int = 0
    grants_authority: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != PACK_REVOCATION_REGISTRY_SCHEMA_VERSION:
            msg = f"schema_version must be {PACK_REVOCATION_REGISTRY_SCHEMA_VERSION!r}"
            raise PackGovernanceError(msg)
        if self.canonical_writes != 0 or self.grants_authority:
            msg = "revocation registry must not grant authority or canonical writes"
            raise PackGovernanceError(msg)

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible revocation registry."""
        return {
            "schema_version": self.schema_version,
            "revoked_pack_ids": sorted(self.revoked_pack_ids),
            "revoked_dependency_ids": sorted(self.revoked_dependency_ids),
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }


@dataclass(frozen=True)
class PackGovernanceRecord:
    """Governance assessment result for one pack."""

    pack_id: str
    status: PackLifecycleStatus
    reasons: tuple[str, ...]
    manifest_v2: dict[str, Any]
    evidence: PackGovernanceEvidence
    canonical_writes: int = 0
    grants_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible governance record."""
        return {
            "schema_version": PACK_GOVERNANCE_RECORD_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "manifest_v2": self.manifest_v2,
            "evidence": self.evidence.to_dict(),
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }

    def canonical_digest(self) -> str:
        """Return the content digest of this governance record."""
        return "sha256:" + hashlib.sha256(dumps(self.to_dict())).hexdigest()


def build_science_pack_manifest_v2(
    manifest: ResourcePackManifest,
    *,
    resource_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a schema-valid ``SciencePackManifest/v2`` projection."""
    sources = [manifest.source.source_sha256]
    if manifest.source.url is not None:
        sources.append(manifest.source.url)
    licenses = [manifest.license.spdx, *manifest.license.texts_sha256]
    payload: dict[str, Any] = {
        "schema_version": SCIENCE_PACK_MANIFEST_V2_SCHEMA_VERSION,
        "pack_id": manifest.pack_id,
        "version": manifest.version,
        "licenses": sorted(set(licenses)),
        "sources": sorted(set(sources)),
        "resource_envelope": resource_envelope or {},
        "canonical_writes": 0,
        "grants_authority": False,
    }
    schema_validate(payload, "SciencePackManifestV2")
    return payload


def assess_pack_governance(
    manifest: ResourcePackManifest,
    evidence: PackGovernanceEvidence,
    revocations: PackRevocationRegistry,
    *,
    resource_envelope: dict[str, Any] | None = None,
) -> PackGovernanceRecord:
    """Assess whether a pack may be ACTIVE under S07 governance."""
    manifest_v2 = build_science_pack_manifest_v2(manifest, resource_envelope=resource_envelope)
    status, reasons = _status_for(manifest, evidence, revocations)
    return PackGovernanceRecord(
        pack_id=manifest.pack_id,
        status=status,
        reasons=tuple(reasons),
        manifest_v2=manifest_v2,
        evidence=evidence,
    )


def load_pack_inventory(pack_root: str | Path) -> tuple[ResourcePackManifest, ...]:
    """Load every ``packs/*/manifest.json`` under ``pack_root`` deterministically."""
    root = Path(pack_root)
    manifests: list[ResourcePackManifest] = []
    for path in sorted(root.glob("*/manifest.json")):
        manifests.append(build_manifest(json.loads(path.read_text(encoding="utf-8"))))
    return tuple(manifests)


def build_pack_governance_receipt(records: tuple[PackGovernanceRecord, ...]) -> dict[str, object]:
    """Build a deterministic pack governance receipt."""
    active_without_complete = [
        record.pack_id
        for record in records
        if record.status is PackLifecycleStatus.ACTIVE
        and len(record.evidence.admission_receipt_ids) != len(STAGES) - 1
    ]
    if active_without_complete:
        msg = f"ACTIVE pack(s) without complete admission receipt chain: {active_without_complete}"
        raise PackGovernanceError(msg)
    payload: dict[str, object] = {
        "schema_version": PACK_GOVERNANCE_RECEIPT_SCHEMA_VERSION,
        "record_count": len(records),
        "active_pack_ids": sorted(
            record.pack_id for record in records if record.status is PackLifecycleStatus.ACTIVE
        ),
        "wait_pack_ids": sorted(
            record.pack_id for record in records if record.status is not PackLifecycleStatus.ACTIVE
        ),
        "record_digests": sorted(record.canonical_digest() for record in records),
        "canonical_writes": 0,
        "grants_authority": False,
    }
    return payload


def _status_for(  # noqa: PLR0911 - each return is a distinct terminal WAIT/REVOKED gate.
    manifest: ResourcePackManifest,
    evidence: PackGovernanceEvidence,
    revocations: PackRevocationRegistry,
) -> tuple[PackLifecycleStatus, list[str]]:
    if manifest.pack_id in revocations.revoked_pack_ids:
        return PackLifecycleStatus.REVOKED, ["pack_id_revoked"]
    revoked_deps = sorted(
        dep.dependency_id
        for dep in evidence.dependencies
        if dep.dependency_id in revocations.revoked_dependency_ids
    )
    if revoked_deps:
        return PackLifecycleStatus.REVOKED, [f"revoked_dependency:{dep}" for dep in revoked_deps]
    if manifest.license.spdx not in LICENSE_ALLOWLIST:
        return PackLifecycleStatus.WAIT_LICENSE, [f"license_not_allowed:{manifest.license.spdx}"]
    if evidence.sbom_sha256 is None:
        return PackLifecycleStatus.WAIT_SBOM, ["missing_sbom"]
    if evidence.lock_sha256 is None:
        return PackLifecycleStatus.WAIT_LOCK, ["missing_lock"]
    if evidence.vulnerability_scan is None:
        return PackLifecycleStatus.WAIT_VULNERABILITY_SCAN, ["missing_vulnerability_scan"]
    if not evidence.vulnerability_scan.passed:
        return PackLifecycleStatus.WAIT_VULNERABILITY_SCAN, ["vulnerability_threshold_exceeded"]
    if len(evidence.admission_receipt_ids) != len(STAGES) - 1:
        return PackLifecycleStatus.WAIT_ADMISSION_RECEIPT, ["incomplete_admission_receipt_chain"]
    return PackLifecycleStatus.ACTIVE, ["complete_governance_evidence"]


def _require_non_empty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value:
        msg = f"{field} must be a non-empty string"
        raise PackGovernanceError(msg)


__all__ = [
    "PACK_GOVERNANCE_RECEIPT_SCHEMA_VERSION",
    "PACK_GOVERNANCE_RECORD_SCHEMA_VERSION",
    "PACK_REVOCATION_REGISTRY_SCHEMA_VERSION",
    "SCIENCE_PACK_MANIFEST_V2_SCHEMA_VERSION",
    "DependencyRecord",
    "PackGovernanceError",
    "PackGovernanceEvidence",
    "PackGovernanceRecord",
    "PackLifecycleStatus",
    "PackRevocationRegistry",
    "VulnerabilityScanSummary",
    "assess_pack_governance",
    "build_pack_governance_receipt",
    "build_science_pack_manifest_v2",
    "load_pack_inventory",
]
