from __future__ import annotations

from typing import Any

import pytest

from srl.packs import build_manifest
from srl.packs.governance import (
    DependencyRecord,
    PackGovernanceError,
    PackGovernanceEvidence,
    PackLifecycleStatus,
    PackRevocationRegistry,
    VulnerabilityScanSummary,
    assess_pack_governance,
    build_pack_governance_receipt,
    build_science_pack_manifest_v2,
    load_pack_inventory,
)
from srl.packs.receipts import STAGES

_DIGEST = "sha256:" + "a" * 64
_DEFAULT_SCAN = object()


def _manifest() -> Any:
    return build_manifest(
        {
            "schema_version": "ResourcePackManifest/v1",
            "pack_id": "test.pack.0.1.0",
            "name": "test-pack",
            "version": "0.1.0",
            "capability_profiles": ["algebra_exact"],
            "platforms": [{"os": "linux", "arch": "x86_64", "abi": None}],
            "source": {
                "url": "https://example.invalid/src",
                "commit": None,
                "source_sha256": _DIGEST,
            },
            "lock_sha256": "sha256:" + "b" * 64,
            "tree_sha256": "sha256:" + "c" * 64,
            "license": {"spdx": "MIT", "texts_sha256": ["sha256:" + "d" * 64]},
            "sbom_sha256": None,
            "entrypoints": [{"entrypoint_id": "runtime", "kind": "python_module", "ref": "run.py"}],
            "probes": {"runtime_probe": "runtime", "actual_compute_probe": "runtime"},
            "created_utc": "2026-07-29T00:00:00Z",
            "canonical_writes": 0,
            "grants_authority": False,
        }
    )


def _dependency(name: str = "dep") -> DependencyRecord:
    return DependencyRecord(
        dependency_id=name,
        version="1.0.0",
        license_spdx="MIT",
        artifact_sha256="sha256:" + "e" * 64,
    )


def _scan(*, critical: int = 0, high: int = 0) -> VulnerabilityScanSummary:
    return VulnerabilityScanSummary(
        scanner="fixture-vuln",
        database_sha256="sha256:" + "f" * 64,
        critical_count=critical,
        high_count=high,
    )


def _receipt_ids() -> tuple[str, ...]:
    return tuple(f"sha256:{i:064x}" for i in range(1, len(STAGES)))


def _evidence(
    *,
    sbom_sha256: str | None = "sha256:" + "1" * 64,
    lock_sha256: str | None = "sha256:" + "2" * 64,
    dependencies: tuple[DependencyRecord, ...] = (),
    vulnerability_scan: VulnerabilityScanSummary | object | None = _DEFAULT_SCAN,
    admission_receipt_ids: tuple[str, ...] | None = None,
) -> PackGovernanceEvidence:
    scan = _scan() if vulnerability_scan is _DEFAULT_SCAN else vulnerability_scan
    if scan is not None and not isinstance(scan, VulnerabilityScanSummary):
        raise TypeError("vulnerability_scan must be a VulnerabilityScanSummary, None or default")
    return PackGovernanceEvidence(
        sbom_sha256=sbom_sha256,
        lock_sha256=lock_sha256,
        dependencies=dependencies or (_dependency(),),
        vulnerability_scan=scan,
        admission_receipt_ids=(
            _receipt_ids() if admission_receipt_ids is None else admission_receipt_ids
        ),
    )


def test_science_pack_manifest_v2_schema_validates() -> None:
    payload = build_science_pack_manifest_v2(_manifest(), resource_envelope={"trust_class": "T1"})

    assert payload["schema_version"] == "SciencePackManifest/v2"
    assert payload["canonical_writes"] == 0
    assert payload["grants_authority"] is False


def test_complete_governance_evidence_makes_pack_active() -> None:
    record = assess_pack_governance(
        _manifest(),
        _evidence(),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    assert record.status is PackLifecycleStatus.ACTIVE
    assert record.reasons == ("complete_governance_evidence",)


def test_missing_sbom_cannot_be_active() -> None:
    record = assess_pack_governance(
        _manifest(),
        _evidence(sbom_sha256=None),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    assert record.status is PackLifecycleStatus.WAIT_SBOM


def test_missing_lock_cannot_be_active() -> None:
    record = assess_pack_governance(
        _manifest(),
        _evidence(lock_sha256=None),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    assert record.status is PackLifecycleStatus.WAIT_LOCK


def test_vulnerability_threshold_cannot_be_active() -> None:
    record = assess_pack_governance(
        _manifest(),
        _evidence(vulnerability_scan=_scan(high=1)),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    assert record.status is PackLifecycleStatus.WAIT_VULNERABILITY_SCAN
    assert "vulnerability_threshold_exceeded" in record.reasons


def test_incomplete_admission_receipts_cannot_be_active() -> None:
    record = assess_pack_governance(
        _manifest(),
        _evidence(admission_receipt_ids=("sha256:" + "3" * 64,)),
        PackRevocationRegistry(frozenset(), frozenset()),
    )

    assert record.status is PackLifecycleStatus.WAIT_ADMISSION_RECEIPT


def test_direct_revocation_wins_over_complete_evidence() -> None:
    record = assess_pack_governance(
        _manifest(),
        _evidence(),
        PackRevocationRegistry(frozenset({"test.pack.0.1.0"}), frozenset()),
    )

    assert record.status is PackLifecycleStatus.REVOKED
    assert record.reasons == ("pack_id_revoked",)


def test_transitive_dependency_revocation_revokes_pack() -> None:
    record = assess_pack_governance(
        _manifest(),
        _evidence(dependencies=(_dependency("revoked-dep"),)),
        PackRevocationRegistry(frozenset(), frozenset({"revoked-dep"})),
    )

    assert record.status is PackLifecycleStatus.REVOKED
    assert record.reasons == ("revoked_dependency:revoked-dep",)


def test_unhashed_dependency_is_rejected() -> None:
    with pytest.raises(PackGovernanceError):
        DependencyRecord(
            dependency_id="bad",
            version="1.0.0",
            license_spdx="MIT",
            artifact_sha256="not-a-digest",
        )


def test_governance_receipt_rejects_active_without_complete_receipts() -> None:
    manifest = _manifest()
    record = assess_pack_governance(
        manifest,
        _evidence(admission_receipt_ids=("sha256:" + "4" * 64,)),
        PackRevocationRegistry(frozenset(), frozenset()),
    )
    forged = record.__class__(
        pack_id=record.pack_id,
        status=PackLifecycleStatus.ACTIVE,
        reasons=record.reasons,
        manifest_v2=record.manifest_v2,
        evidence=record.evidence,
    )

    with pytest.raises(PackGovernanceError):
        build_pack_governance_receipt((forged,))


def test_current_pack_inventory_has_no_unknown_licenses_and_no_active_without_evidence() -> None:
    manifests = load_pack_inventory("packs")
    records = tuple(
        assess_pack_governance(
            manifest,
            _evidence(
                sbom_sha256=None,
                lock_sha256=None,
                vulnerability_scan=None,
                admission_receipt_ids=(),
            ),
            PackRevocationRegistry(frozenset(), frozenset()),
        )
        for manifest in manifests
    )

    assert manifests
    assert {manifest.license.spdx for manifest in manifests} <= {
        "MIT",
        "BSD-3-Clause",
        "Apache-2.0",
    }
    assert all(record.status is not PackLifecycleStatus.ACTIVE for record in records)
    receipt = build_pack_governance_receipt(records)
    assert receipt["active_pack_ids"] == []
