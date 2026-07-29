"""SRL resource pack manifest, safe extraction, materialization, builder, and admission.

This package provides the control-plane contracts for handling scientific
resource packs: content-addressed bundles that declare their license,
entrypoints, supported platforms, and deterministic tree hash. The pack
runtime extracts them safely, verifies their integrity, materializes them
into a mutable staging area, and admits them through an eight-stage pipeline
before any execution step.
"""

from __future__ import annotations

from srl.packs.admission import (
    ACTUAL_COMPUTE_FAILED_REASON,
    DEPENDENCY_LOCK_DRIFT_REASON,
    PACK_PROBE_ONLY_REASON,
    UPSTREAM_SOURCE_UNVERIFIED_REASON,
    AdmissionError,
    AdmissionState,
    advance,
    initial_state,
)
from srl.packs.builder import BuilderError, build_pack
from srl.packs.extract import ExtractionReport, PackIntegrityError, extract_pack
from srl.packs.governance import (
    PACK_GOVERNANCE_RECEIPT_SCHEMA_VERSION,
    PACK_GOVERNANCE_RECORD_SCHEMA_VERSION,
    PACK_REVOCATION_REGISTRY_SCHEMA_VERSION,
    SCIENCE_PACK_MANIFEST_V2_SCHEMA_VERSION,
    DependencyRecord,
    PackGovernanceError,
    PackGovernanceEvidence,
    PackGovernanceRecord,
    PackLifecycleStatus,
    PackRevocationRegistry,
    VulnerabilityScanSummary,
    assess_pack_governance,
    build_pack_governance_receipt,
    build_science_pack_manifest_v2,
    load_pack_inventory,
)
from srl.packs.manifest import (
    LICENSE_INCOMPATIBLE_REASON,
    LICENSE_UNKNOWN_REASON,
    PACK_INTEGRITY_FAILURE_REASON,
    PACK_MANIFEST_SCHEMA_VERSION,
    PLATFORM_UNSUPPORTED_REASON,
    LicenseError,
    LicenseSpec,
    PackManifestError,
    PlatformSpec,
    ProbesSpec,
    ResourcePackManifest,
    SourceSpec,
    build_manifest,
    compute_tree_sha256,
)
from srl.packs.materialize import (
    RECEIPT_SCHEMA_VERSION as MATERIALIZATION_RECEIPT_SCHEMA_VERSION,
)
from srl.packs.materialize import (
    MaterializationError,
    MaterializationReceipt,
    materialize,
)
from srl.packs.platform import (
    CurrentPlatform,
    PlatformError,
    check_manifest_platform,
    current_platform,
)
from srl.packs.receipts import (
    RECEIPT_SCHEMA_VERSION as PACK_STAGE_RECEIPT_SCHEMA_VERSION,
)
from srl.packs.receipts import (
    STAGES as ADMISSION_STAGES,
)
from srl.packs.receipts import (
    PackStageReceipt,
    ReceiptError,
    build_pack_stage_receipt,
)
from srl.packs.sciml_domain import (
    CROSS_LANGUAGE_FIXTURE_RECEIPT_SCHEMA_VERSION,
    SCIML_DOMAIN_ADMISSION_BUNDLE_SCHEMA_VERSION,
    SCIML_DOMAIN_RESULT_RECEIPT_SCHEMA_VERSION,
    SciMLDomainError,
    SciMLDomainProfile,
    SciMLDomainResultSpec,
    SciMLDomainStatus,
    build_cross_language_fixture_receipt,
    build_sciml_domain_admission_bundle,
    build_sciml_domain_result_receipt,
    default_sciml_domain_profiles,
)

__all__ = [
    "ACTUAL_COMPUTE_FAILED_REASON",
    "ADMISSION_STAGES",
    "CROSS_LANGUAGE_FIXTURE_RECEIPT_SCHEMA_VERSION",
    "DEPENDENCY_LOCK_DRIFT_REASON",
    "LICENSE_INCOMPATIBLE_REASON",
    "LICENSE_UNKNOWN_REASON",
    "MATERIALIZATION_RECEIPT_SCHEMA_VERSION",
    "PACK_GOVERNANCE_RECEIPT_SCHEMA_VERSION",
    "PACK_GOVERNANCE_RECORD_SCHEMA_VERSION",
    "PACK_INTEGRITY_FAILURE_REASON",
    "PACK_MANIFEST_SCHEMA_VERSION",
    "PACK_PROBE_ONLY_REASON",
    "PACK_REVOCATION_REGISTRY_SCHEMA_VERSION",
    "PACK_STAGE_RECEIPT_SCHEMA_VERSION",
    "PLATFORM_UNSUPPORTED_REASON",
    "SCIENCE_PACK_MANIFEST_V2_SCHEMA_VERSION",
    "SCIML_DOMAIN_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "SCIML_DOMAIN_RESULT_RECEIPT_SCHEMA_VERSION",
    "UPSTREAM_SOURCE_UNVERIFIED_REASON",
    "AdmissionError",
    "AdmissionState",
    "BuilderError",
    "CurrentPlatform",
    "DependencyRecord",
    "ExtractionReport",
    "LicenseError",
    "LicenseSpec",
    "MaterializationError",
    "MaterializationReceipt",
    "PackGovernanceError",
    "PackGovernanceEvidence",
    "PackGovernanceRecord",
    "PackIntegrityError",
    "PackLifecycleStatus",
    "PackManifestError",
    "PackRevocationRegistry",
    "PackStageReceipt",
    "PlatformError",
    "PlatformSpec",
    "ProbesSpec",
    "ReceiptError",
    "ResourcePackManifest",
    "SciMLDomainError",
    "SciMLDomainProfile",
    "SciMLDomainResultSpec",
    "SciMLDomainStatus",
    "SourceSpec",
    "VulnerabilityScanSummary",
    "advance",
    "assess_pack_governance",
    "build_cross_language_fixture_receipt",
    "build_manifest",
    "build_pack",
    "build_pack_governance_receipt",
    "build_pack_stage_receipt",
    "build_science_pack_manifest_v2",
    "build_sciml_domain_admission_bundle",
    "build_sciml_domain_result_receipt",
    "check_manifest_platform",
    "compute_tree_sha256",
    "current_platform",
    "default_sciml_domain_profiles",
    "extract_pack",
    "initial_state",
    "load_pack_inventory",
    "materialize",
]
