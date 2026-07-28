"""Content-addressed storage abstraction and T7 volume identity guard (WP-C20).

This package owns the storage plane of the SRL fabric: the abstract byte-store
interface, its local implementation, the T7 volume identity guard that refuses
to write to the wrong volume, the capacity allocation policy, the mount-state
probe, the public-tiny-fixture fallback, and the path-redaction privacy layer.

Everything here is *admission* and *routing*: a green return from a store
operation means the bytes were content-addressed and integrity-verified; it
never means a scientific claim is supported (see ``GOVERNANCE.md`` for the
evidence rules).

Design invariants
-----------------
- **Content addressing**: an object's key is the SHA-256 of its bytes, never a
  caller-supplied digest (the store computes it).
- **T7 identity is mandatory**: the T7 store verifies the mounted volume's UUID
  against the expected identity before any operation; a mismatch is a hard stop
  (``WRONG_T7_VOLUME``), an absence is a wait (``WAIT_STORAGE``).
- **No fallback for T7-bound content**: when the T7 is unavailable the store
  waits; only public tiny fixtures may use the local fallback.
- **No raw paths in public output**: every receipt and descriptor carries a
  redacted store-root token, never a raw ``/Volumes/`` or ``/Users/`` path.
- **Standard library only**: no new runtime dependencies (see
  ``pyproject.toml``).
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
from srl.cas.fallback import (
    FALLBACK_SINGLE_OBJECT_MAX_BYTES,
    FALLBACK_TOTAL_MAX_BYTES,
    LocalFallbackStore,
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
    "CAS_INTEGRITY_FAIL_REASON",
    "DEFAULT_ALLOCATION",
    "FALLBACK_SINGLE_OBJECT_MAX_BYTES",
    "FALLBACK_TOTAL_MAX_BYTES",
    "IDENTITY_RECEIPT_SCHEMA_VERSION",
    "STORE_FAIL_REASON",
    "T7_QUOTA_EXCEEDED_FAIL_REASON",
    "T7_UNAVAILABLE_FAIL_REASON",
    "WAIT_STORAGE_EXIT",
    "WAIT_STORAGE_FAIL_REASON",
    "WRONG_T7_VOLUME_FAIL_REASON",
    "AllocationTable",
    "ArtifactDescriptor",
    "ArtifactStore",
    "CapacityDecision",
    "FsckReport",
    "LocalArtifactStore",
    "LocalFallbackStore",
    "MountInfo",
    "MountInfoProvider",
    "MountState",
    "ObjectClass",
    "PrivacyError",
    "StoreError",
    "StoreIntegrityError",
    "StoreWaitError",
    "T7ArtifactStore",
    "T7UnavailableError",
    "WrongVolumeError",
    "check_capacity",
    "default_mount_info_provider",
    "load_expected_identity",
    "probe_mount",
    "redact_store_path",
    "verify_t7_identity",
]
