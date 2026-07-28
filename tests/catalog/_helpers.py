"""Shared builders for the catalog test suite.

Kept in a plain module (not conftest) so tests can import it directly. Every
builder produces a structurally valid, immutable
:class:`~srl.catalog.registry.CapabilityRegistryEntry` via
:func:`srl.catalog.registry.build_entry`, so identity/merkle and tamper
assertions are exact and hermetic.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from srl.catalog.registry import (
    CapabilityRegistryEntry,
    MeasuredResources,
    PlatformSpec,
    Provenance,
    build_entry,
)

# A fixed UTC timestamp used wherever a deterministic created_utc is needed.
FIXED_UTC: str = "2026-07-28T00:00:00Z"

# A valid sha256 digest reused across synthetic entries.
_GOOD_DIGEST: str = "sha256:" + "a" * 64


def make_entry(  # noqa: PLR0913 - mirrors the 9-field CapabilityRegistryEntry dataclass
    capability_id: str = "cap.algebra_exact",
    profile: str = "algebra_exact",
    *,
    adapter_id: str | None = None,
    pack_manifest_digest: str | None = None,
    platforms: tuple[PlatformSpec, ...] = (),
    measured_resources: MeasuredResources | None = None,
    license_spdx: str = "NOASSERTION",
    provenance: Provenance | None = None,
    admission_stage: str = "not_admitted",
) -> CapabilityRegistryEntry:
    """Build a synthetic, valid registry entry for tests."""
    return build_entry(
        capability_id=capability_id,
        profile=profile,
        adapter_id=adapter_id,
        pack_manifest_digest=pack_manifest_digest,
        platforms=platforms,
        measured_resources=measured_resources,
        license_spdx=license_spdx,
        provenance=provenance
        if provenance is not None
        else Provenance(source_url=None, source_sha256=None),
        admission_stage=admission_stage,
    )


def make_admitted_entry(
    capability_id: str = "cap.geometry_tda",
    profile: str = "geometry_tda",
    *,
    adapter_id: str = "ripser",
) -> CapabilityRegistryEntry:
    """Build a synthetic EXPERIMENTAL_ACCEPTED entry with full metadata."""
    return build_entry(
        capability_id=capability_id,
        profile=profile,
        adapter_id=adapter_id,
        pack_manifest_digest=_GOOD_DIGEST,
        platforms=(PlatformSpec(os="linux", arch="x86_64", abi=None),),
        measured_resources=MeasuredResources(expanded_bytes=1024, rss_bytes=2048, wall_seconds=3.5),
        license_spdx="MIT",
        provenance=Provenance(source_url="https://example.org/src", source_sha256=_GOOD_DIGEST),
        admission_stage="EXPERIMENTAL_ACCEPTED",
    )


def tamper_entry(entry: CapabilityRegistryEntry, **changes: Any) -> CapabilityRegistryEntry:
    """Return a copy of ``entry`` with the given fields replaced."""
    return replace(entry, **changes)


__all__ = [
    "FIXED_UTC",
    "make_admitted_entry",
    "make_entry",
    "tamper_entry",
]
