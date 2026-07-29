"""Content-addressed storage: abstraction, T7 identity guard, and transaction engine.

This package owns the storage plane of the SRL fabric: the abstract byte-store
interface, its local implementation, the T7 volume identity guard that refuses
to write to the wrong volume, the capacity allocation policy, the mount-state
probe, the public-tiny-fixture fallback, the path-redaction privacy layer
(WP-C20), and the crash-safe transaction engine with its canonical descriptor
and ingest-receipt records and the full integrity sweep (WP-C21).

Everything here is *admission*, *routing*, and *integrity*: a green return from
a store operation means the bytes were content-addressed, read-back verified,
and durably published with a commit-marker receipt; it never means a scientific
claim is supported (see ``GOVERNANCE.md`` for the evidence rules).

Design invariants
-----------------
- **Content addressing**: an object's key is the SHA-256 of its bytes, never a
  caller-supplied digest (the store computes it).
- **T7 identity is mandatory**: the T7 store verifies the mounted volume's UUID
  against the expected identity before any operation; a mismatch is a hard stop
  (``WRONG_T7_VOLUME``), an absence is a wait (``WAIT_STORAGE``).
- **No fallback for T7-bound content**: when the T7 is unavailable the store
  waits; only public tiny fixtures may use the local fallback.
- **Receipt-last transaction** (WP-C21): an ingest writes the object, then the
  descriptor, then the ingest receipt **last**; the receipt is the commit marker
  whose presence proves the ingest completed. A crash at any point leaves the
  store in old-or-new valid state, never a partial visible object.
- **No raw paths in public output**: every receipt and descriptor carries a
  redacted store-root token, never a raw ``/Volumes/`` or ``/Users/`` path.
- **Standard library only**: no new runtime dependencies (see
  ``pyproject.toml``); the CAS engine imports ``srl.contracts`` (which pulls
  ``jsonschema``) because it is a control-plane component, and keeps canonical
  encoding out of the hot byte path.
"""

from __future__ import annotations

from srl.cas.capacity import (
    DEFAULT_ALLOCATION,
    T7_QUOTA_EXCEEDED_FAIL_REASON,
    AllocationTable,
    CapacityDecision,
    ObjectClass,
    check_capacity,
)
from srl.cas.descriptors import (
    INGEST_RECEIPT_SCHEMA_VERSION,
    OBJECT_DESCRIPTOR_SCHEMA_VERSION,
    DescriptorError,
    build_ingest_receipt,
    build_object_descriptor,
    canonical_receipt_id,
    validate_ingest_receipt,
    validate_object_descriptor,
)
from srl.cas.engine import (
    CapacityHook,
    CasIntegrityError,
    IngestOutcome,
    PartialEntry,
    QuotaExceededError,
    default_capacity_hook,
    ingest,
    recover_partials,
)
from srl.cas.fallback import (
    FALLBACK_SINGLE_OBJECT_MAX_BYTES,
    FALLBACK_TOTAL_MAX_BYTES,
    LocalFallbackStore,
)
from srl.cas.fsck import (
    CAS_FSCK_REPORT_SCHEMA_VERSION,
    ISSUE_BAD_RECEIPT,
    ISSUE_HASH_MISMATCH,
    ISSUE_MALFORMED_RECORD,
    ISSUE_MISSING_DESCRIPTOR,
    ISSUE_ORPHAN_DESCRIPTOR,
    ISSUE_SIZE_DRIFT,
    CasFsckReport,
    FsckIssue,
    run_fsck,
)
from srl.cas.layout import (
    BYTES_PER_GIB,
    COLD_CAS_DIR,
    DEFAULT_MIN_FREE_RESERVE_GIB,
    DEFAULT_SRF_ALLOCATION_GIB,
    QUARANTINE_DIR,
    RESTORE_TESTS_DIR,
    WORK_DIR,
    WORK_NAMESPACES,
    SrfStorageLayout,
    StorageLayoutError,
    StorageQuotaDecision,
    StorageQuotaStatus,
    check_srf_storage_quota,
)
from srl.cas.mount_state import (
    WAIT_STORAGE_EXIT,
    MountState,
    probe_mount,
)
from srl.cas.privacy import PrivacyError, redact_store_path
from srl.cas.store import (
    ARTIFACT_DESCRIPTOR_SCHEMA_VERSION,
    CAS_INTEGRITY_FAIL_REASON,
    STORE_FAIL_REASON,
    ArtifactDescriptor,
    ArtifactStore,
    FsckReport,
    LocalArtifactStore,
    StoreError,
    StoreIntegrityError,
    StoreWaitError,
    T7ArtifactStore,
)
from srl.cas.t7_identity import (
    IDENTITY_RECEIPT_SCHEMA_VERSION,
    T7_UNAVAILABLE_FAIL_REASON,
    WAIT_STORAGE_FAIL_REASON,
    WRONG_T7_VOLUME_FAIL_REASON,
    MountInfo,
    MountInfoProvider,
    T7UnavailableError,
    WrongVolumeError,
    default_mount_info_provider,
    load_expected_identity,
    verify_t7_identity,
)

__all__ = [
    "ARTIFACT_DESCRIPTOR_SCHEMA_VERSION",
    "BYTES_PER_GIB",
    "CAS_FSCK_REPORT_SCHEMA_VERSION",
    "CAS_INTEGRITY_FAIL_REASON",
    "COLD_CAS_DIR",
    "DEFAULT_ALLOCATION",
    "DEFAULT_MIN_FREE_RESERVE_GIB",
    "DEFAULT_SRF_ALLOCATION_GIB",
    "FALLBACK_SINGLE_OBJECT_MAX_BYTES",
    "FALLBACK_TOTAL_MAX_BYTES",
    "IDENTITY_RECEIPT_SCHEMA_VERSION",
    "INGEST_RECEIPT_SCHEMA_VERSION",
    "ISSUE_BAD_RECEIPT",
    "ISSUE_HASH_MISMATCH",
    "ISSUE_MALFORMED_RECORD",
    "ISSUE_MISSING_DESCRIPTOR",
    "ISSUE_ORPHAN_DESCRIPTOR",
    "ISSUE_SIZE_DRIFT",
    "OBJECT_DESCRIPTOR_SCHEMA_VERSION",
    "QUARANTINE_DIR",
    "RESTORE_TESTS_DIR",
    "STORE_FAIL_REASON",
    "T7_QUOTA_EXCEEDED_FAIL_REASON",
    "T7_UNAVAILABLE_FAIL_REASON",
    "WAIT_STORAGE_EXIT",
    "WAIT_STORAGE_FAIL_REASON",
    "WORK_DIR",
    "WORK_NAMESPACES",
    "WRONG_T7_VOLUME_FAIL_REASON",
    "AllocationTable",
    "ArtifactDescriptor",
    "ArtifactStore",
    "CapacityDecision",
    "CapacityHook",
    "CasFsckReport",
    "CasIntegrityError",
    "DescriptorError",
    "FsckIssue",
    "FsckReport",
    "IngestOutcome",
    "LocalArtifactStore",
    "LocalFallbackStore",
    "MountInfo",
    "MountInfoProvider",
    "MountState",
    "ObjectClass",
    "PartialEntry",
    "PrivacyError",
    "QuotaExceededError",
    "SrfStorageLayout",
    "StorageLayoutError",
    "StorageQuotaDecision",
    "StorageQuotaStatus",
    "StoreError",
    "StoreIntegrityError",
    "StoreWaitError",
    "T7ArtifactStore",
    "T7UnavailableError",
    "WrongVolumeError",
    "build_ingest_receipt",
    "build_object_descriptor",
    "canonical_receipt_id",
    "check_capacity",
    "check_srf_storage_quota",
    "default_capacity_hook",
    "default_mount_info_provider",
    "ingest",
    "load_expected_identity",
    "probe_mount",
    "recover_partials",
    "redact_store_path",
    "run_fsck",
    "validate_ingest_receipt",
    "validate_object_descriptor",
    "verify_t7_identity",
]
