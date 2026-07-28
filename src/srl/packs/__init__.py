"""SRL resource pack manifest, safe extraction, and materialization.

This package provides the control-plane contracts for handling scientific
resource packs: content-addressed bundles that declare their license,
entrypoints, supported platforms, and deterministic tree hash. The pack
runtime extracts them safely, verifies their integrity, and materializes them
into a mutable staging area before any execution step.
"""

from __future__ import annotations

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
    RECEIPT_SCHEMA_VERSION,
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

__all__ = [
    "LICENSE_INCOMPATIBLE_REASON",
    "LICENSE_UNKNOWN_REASON",
    "PACK_INTEGRITY_FAILURE_REASON",
    "PACK_MANIFEST_SCHEMA_VERSION",
    "PLATFORM_UNSUPPORTED_REASON",
    "RECEIPT_SCHEMA_VERSION",
    "CurrentPlatform",
    "ExtractionReport",
    "LicenseError",
    "LicenseSpec",
    "MaterializationError",
    "MaterializationReceipt",
    "PackIntegrityError",
    "PackManifestError",
    "PlatformError",
    "PlatformSpec",
    "ProbesSpec",
    "ResourcePackManifest",
    "SourceSpec",
    "build_manifest",
    "check_manifest_platform",
    "compute_tree_sha256",
    "current_platform",
    "extract_pack",
    "materialize",
]
