"""SRL capability catalog: registry, deterministic snapshot, cache, and verify.

This package provides the capability catalog layer (WP-C24): an immutable
identity registry of the 15 science-lab capabilities, a deterministic
content-addressed :class:`ScientificCatalogSnapshot` whose identity is a pure
function of its entries (immune to input order and to dynamic location changes),
a small local JSON cache that stays queryable when the artifact store is absent,
and a verifier that recomputes the snapshot identity and raises a typed
``CONTRACT_INVALID`` on any mismatch.

Identity vs dynamic
-------------------
A registry entry is **identity** (what the capability *is*: profile, adapter,
provenance, admission stage). Location/availability is **dynamic** state stored
separately: it feeds ``location_state_ref`` but never the snapshot's
``snapshot_id``, bytes, or ``merkle_root``. A capability appearing in the
registry never implies it is ready to run — readiness is reported honestly as
``{"state": "unknown"}`` until a store confirms availability.
"""

from __future__ import annotations

from srl.catalog.local_cache import (
    LocalCacheError,
    LocationState,
    SnapshotCache,
)
from srl.catalog.registry import (
    ADMISSION_STAGES,
    NOT_ADMITTED_STAGE,
    CapabilityRegistryEntry,
    CatalogError,
    MeasuredResources,
    PlatformSpec,
    Provenance,
    build_default_registry,
    build_entry,
    load_registry_seed,
)
from srl.catalog.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ScientificCatalogSnapshot,
    SnapshotError,
    build_snapshot,
)
from srl.catalog.verify import (
    SnapshotMismatchError,
    verify_snapshot,
)

__all__ = [
    "ADMISSION_STAGES",
    "NOT_ADMITTED_STAGE",
    "SNAPSHOT_SCHEMA_VERSION",
    "CapabilityRegistryEntry",
    "CatalogError",
    "LocalCacheError",
    "LocationState",
    "MeasuredResources",
    "PlatformSpec",
    "Provenance",
    "ScientificCatalogSnapshot",
    "SnapshotCache",
    "SnapshotError",
    "SnapshotMismatchError",
    "build_default_registry",
    "build_entry",
    "build_snapshot",
    "load_registry_seed",
    "verify_snapshot",
]
