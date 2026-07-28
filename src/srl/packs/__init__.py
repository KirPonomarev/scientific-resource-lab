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

__all__ = [
    "ACTUAL_COMPUTE_FAILED_REASON",
    "ADMISSION_STAGES",
    "DEPENDENCY_LOCK_DRIFT_REASON",
    "LICENSE_INCOMPATIBLE_REASON",
    "LICENSE_UNKNOWN_REASON",
    "MATERIALIZATION_RECEIPT_SCHEMA_VERSION",
    "PACK_INTEGRITY_FAILURE_REASON",
    "PACK_MANIFEST_SCHEMA_VERSION",
    "PACK_PROBE_ONLY_REASON",
    "PACK_STAGE_RECEIPT_SCHEMA_VERSION",
    "PLATFORM_UNSUPPORTED_REASON",
    "UPSTREAM_SOURCE_UNVERIFIED_REASON",
    "AdmissionError",
    "AdmissionState",
    "BuilderError",
    "CurrentPlatform",
    "ExtractionReport",
    "LicenseError",
    "LicenseSpec",
    "MaterializationError",
    "MaterializationReceipt",
    "PackIntegrityError",
    "PackManifestError",
    "PackStageReceipt",
    "PlatformError",
    "PlatformSpec",
    "ProbesSpec",
    "ReceiptError",
    "ResourcePackManifest",
    "SourceSpec",
    "advance",
    "build_manifest",
    "build_pack",
    "build_pack_stage_receipt",
    "check_manifest_platform",
    "compute_tree_sha256",
    "current_platform",
    "extract_pack",
    "initial_state",
    "materialize",
]
