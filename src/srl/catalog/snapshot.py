"""Deterministic capability catalog snapshot with content-addressed identity.

A :class:`ScientificCatalogSnapshot` is the immutable, content-addressed view of
the capability registry at a point in time. Its **identity** (``snapshot_id``)
is a pure function of its entries (sorted by ``capability_id``) and their
canonical per-entry digests (the ``merkle_root``), independent of the input
order, the build timestamp, and any dynamic location state.

Identity vs dynamic
-------------------
- **Identity** (immutable, content-addressed): the entry set + merkle root. Two
  agents that build a snapshot over the same entries compute the same
  ``snapshot_id`` and identical canonical bytes, regardless of the order the
  entries were supplied in.
- **Dynamic** (mutable, not part of identity): ``created_utc`` (when this
  particular record was minted) and ``location_state_ref`` (a content-addressed
  digest over the separate location/availability map). Changing either never
  changes ``snapshot_id``, the entry bytes, or ``merkle_root``.

This split is load-bearing: a registry entry *existing* in a snapshot never
implies its capability is ready to run — readiness is a dynamic location
property reported separately (and honestly absent, i.e. ``{"state": "unknown"}``,
until a store confirms availability).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final

from srl.catalog.registry import CapabilityRegistryEntry
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id

# Schema identity. Bumped only on a contract change to the snapshot shape.
SNAPSHOT_SCHEMA_VERSION: Final[str] = "ScientificCatalogSnapshot/v1"

# Sentinel for the merkle root of an empty catalog.
_EMPTY_DIGEST: Final[bytes] = b""

# Number of hex characters in a SHA-256 digest.
_SHA256_HEX_LEN: Final[int] = 64


class SnapshotError(ContractError):
    """Raised when a catalog snapshot violates its structural contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class ScientificCatalogSnapshot:
    """ScientificCatalogSnapshot/v1: immutable identity of the capability catalog.

    Attributes
    ----------
    schema_version:
        Always ``ScientificCatalogSnapshot/v1``.
    snapshot_id:
        ``sha256:<hex>`` content-addressed identity of the snapshot. Computed
        over the identity body only (schema_version, entries, merkle_root,
        canonical_writes, grants_authority) — never over ``created_utc`` or
        ``location_state_ref``, so the id is stable across builds and immune to
        location changes.
    created_utc:
        RFC 3339 UTC timestamp when this record was minted. Dynamic: two builds
        of the same entries may carry different timestamps yet share an id.
    entries:
        Tuple of registry entries, sorted by ``capability_id``.
    merkle_root:
        Merkle root over the ordered canonical per-entry digests. Part of
        identity.
    location_state_ref:
        ``sha256:<hex>`` digest over the dynamic location map. Dynamic: not part
        of identity.
    canonical_writes:
        Always ``0``; snapshots are read-only records.
    grants_authority:
        Always ``False``; the catalog never grants scientific authority.
    """

    schema_version: str
    snapshot_id: str
    created_utc: str
    entries: tuple[CapabilityRegistryEntry, ...]
    merkle_root: str
    location_state_ref: str
    canonical_writes: int
    grants_authority: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the snapshot as a plain JSON-serializable dict."""
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "created_utc": self.created_utc,
            "entries": [e.to_dict() for e in self.entries],
            "merkle_root": self.merkle_root,
            "location_state_ref": self.location_state_ref,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }

    def canonical_dumps(self) -> bytes:
        """Return canonical JSON bytes (sorted keys, compact, trailing newline)."""
        return dumps(self.to_dict())


def _utc_now() -> str:
    """Return an RFC 3339 UTC timestamp string with a trailing ``Z``."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_digest(value: str) -> bytes:
    """Return the raw 32-byte digest from a ``sha256:<hex>`` string."""
    if not isinstance(value, str) or not value.startswith("sha256:"):
        msg = f"digest must be 'sha256:<hex>', got {value!r}"
        raise SnapshotError(msg)
    hex_part = value[len("sha256:") :]
    if len(hex_part) != _SHA256_HEX_LEN:
        msg = f"digest hex must be {_SHA256_HEX_LEN} characters, got {len(hex_part)}"
        raise SnapshotError(msg)
    try:
        return bytes.fromhex(hex_part)
    except ValueError as exc:
        msg = f"digest {value!r} is not valid hex"
        raise SnapshotError(msg) from exc


def _format_digest(raw: bytes) -> str:
    """Return a ``sha256:<hex>`` string from raw digest bytes."""
    return f"sha256:{raw.hex()}"


def _entry_digest(entry: CapabilityRegistryEntry) -> str:
    """Compute the canonical ``sha256:<hex>`` digest of one registry entry."""
    blob = dumps(entry.to_dict())
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"


def _merkle_root(digests: list[str]) -> str:
    """Compute the binary Merkle root over an ordered list of ``sha256:<hex>`` digests.

    The tree is built by pairing adjacent raw digests, concatenating them, and
    hashing the result. If a level has an odd number of nodes, the final node is
    duplicated. The root of an empty leaf set is the SHA-256 of the empty byte
    string.
    """
    if not digests:
        return _format_digest(hashlib.sha256(_EMPTY_DIGEST).digest())

    level: list[bytes] = [_parse_digest(d) for d in digests]
    while len(level) > 1:
        next_level: list[bytes] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            next_level.append(hashlib.sha256(left + right).digest())
        level = next_level
    return _format_digest(level[0])


def _location_state_ref(locations: Mapping[str, Mapping[str, Any]]) -> str:
    """Compute the content-addressed digest over the dynamic location map."""
    # Deep-copy and convert to plain dict so we do not mutate the caller.
    body = deepcopy(dict(locations))
    return object_id(body)


def build_snapshot(
    entries: Iterable[CapabilityRegistryEntry],
    locations: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    created_utc: str | None = None,
) -> ScientificCatalogSnapshot:
    """Build a deterministic, content-addressed catalog snapshot.

    Parameters
    ----------
    entries:
        Registry entries. Input order does not affect the snapshot identity.
    locations:
        Optional dynamic location map from ``capability_id`` to a location state
        dict. Defaults to every capability id mapped to ``{"state": "unknown"}``.
    created_utc:
        Optional RFC 3339 UTC timestamp. If ``None``, the current UTC time is used.

    Returns
    -------
    ScientificCatalogSnapshot
        A validated, immutable snapshot with ``snapshot_id`` and ``merkle_root``
        computed deterministically.

    Raises
    ------
    SnapshotError
        If entries contain duplicate ``capability_id`` values or malformed data.
    CatalogError
        Propagated from entry validation.
    """
    sorted_entries = tuple(sorted(entries, key=lambda e: e.capability_id))
    seen: set[str] = set()
    for entry in sorted_entries:
        if entry.capability_id in seen:
            msg = f"duplicate capability_id in snapshot: {entry.capability_id!r}"
            raise SnapshotError(msg)
        seen.add(entry.capability_id)

    entry_digests = [_entry_digest(e) for e in sorted_entries]
    merkle_root = _merkle_root(entry_digests)

    if created_utc is None:
        created_utc = _utc_now()

    loc_map: dict[str, dict[str, Any]]
    if locations is None:
        loc_map = {e.capability_id: {"state": "unknown"} for e in sorted_entries}
    else:
        loc_map = {cid: dict(state) for cid, state in locations.items()}
    location_state_ref = _location_state_ref(loc_map)

    # The snapshot *identity* is a pure function of its entries: schema version,
    # the ordered canonical entry digests (merkle_root), and the fixed record
    # tail (canonical_writes=0, grants_authority=false). It deliberately excludes
    # created_utc (a per-build observation time) and location_state_ref (dynamic
    # location state) so two builds of the same entries yield the same snapshot_id
    # and location changes never alter identity. The full record (to_dict) carries
    # those dynamic fields for human inspection; only the id is content-addressed.
    identity_body: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "entries": [e.to_dict() for e in sorted_entries],
        "merkle_root": merkle_root,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    snapshot_id = object_id(identity_body)

    return ScientificCatalogSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        created_utc=created_utc,
        entries=sorted_entries,
        merkle_root=merkle_root,
        location_state_ref=location_state_ref,
        canonical_writes=0,
        grants_authority=False,
    )


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "ScientificCatalogSnapshot",
    "SnapshotError",
    "build_snapshot",
]
