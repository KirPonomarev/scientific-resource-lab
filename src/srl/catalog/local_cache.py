"""Small local JSON cache for catalog snapshots.

A :class:`SnapshotCache` is the on-disk landing pad for a
:class:`~srl.catalog.snapshot.ScientificCatalogSnapshot` and its dynamic location
state. It is deliberately tiny (the cache file is kept under 1 MiB) and
**store-agnostic**: the listing/inspection API never requires the content-
addressed artifact store to be present. When the store is absent, a capability's
location state is reported honestly as ``{"state": "unknown"}`` — registry
presence never implies readiness.

Design
------
The cache holds exactly one snapshot at a time (the latest minted). Writes are
whole-file and atomic (write-temp-then-rename) so a crash never leaves a torn
cache. Reads validate the cached snapshot against its recomputed identity before
returning it (defense in depth); a cache whose identity no longer verifies is
treated as empty and re-minted by the caller.

The cache file is canonical JSON (sorted keys, compact, UTF-8, trailing newline)
so its size is predictable and two processes minting the same snapshot write
byte-identical files.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Final

from srl.catalog.registry import _build_entry_from_raw
from srl.catalog.snapshot import (
    ScientificCatalogSnapshot,
    build_snapshot,
)
from srl.catalog.verify import SnapshotMismatchError, verify_snapshot
from srl.contracts.canonical import dumps as _dumps
from srl.contracts.errors import ContractError

# Hard ceiling on the on-disk cache size. The 15-entry seed snapshot is a few
# KiB; this leaves ample headroom for a richer future registry while keeping the
# cache firmly in "small" territory.
_MAX_CACHE_BYTES: Final[int] = 1024 * 1024  # 1 MiB

# Schema identity for the cache envelope. Bumped only on a cache-shape change.
_CACHE_SCHEMA_VERSION: Final[str] = "CapabilityCatalogCache/v1"


class LocalCacheError(ContractError):
    """Raised when the local snapshot cache violates its contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default.
    """


#: Type alias for one capability's dynamic location state. ``state`` is the
#: honest availability label: ``"unknown"`` (store absent), ``"available"``
#: (store confirms the artifact), or ``"missing"`` (store present but the
#: artifact is gone). Registry identity is stored on the entry, not here.
LocationState = dict[str, Any]


class SnapshotCache:
    """On-disk cache for the latest catalog snapshot and location state.

    Attributes
    ----------
    path:
        Path to the cache JSON file.
    """

    def __init__(self, path: str | Path) -> None:
        self.path: Final[Path] = Path(path)

    # ------------------------------------------------------------------ write

    def write(
        self,
        snapshot: ScientificCatalogSnapshot,
        locations: dict[str, LocationState] | None = None,
    ) -> None:
        """Persist ``snapshot`` and ``locations`` to the cache file atomically.

        The snapshot is rebuilt from its entries together with ``locations`` so
        the persisted record (entry set, merkle root, snapshot id, and dynamic
        ``location_state_ref``) is internally consistent with the stored
        location map, regardless of how ``snapshot`` was originally built. The
        recorded ``created_utc`` is preserved.

        Raises
        ------
        LocalCacheError
            If the serialized cache would exceed the 1 MiB ceiling.
        """
        # Materialize the full location map so the persisted snapshot's dynamic
        # ``location_state_ref`` reflects an honest state for EVERY capability.
        # Capabilities with no explicit recorded location default to "unknown"
        # (the store-absent honest state); this matches build_snapshot's default
        # map and keeps the cache self-consistent under verify_snapshot().
        recorded = dict(locations) if locations is not None else {}
        stored_locations: dict[str, LocationState] = {
            entry.capability_id: recorded.get(entry.capability_id, {"state": "unknown"})
            for entry in snapshot.entries
        }
        rebuilt = build_snapshot(
            snapshot.entries,
            stored_locations,
            created_utc=snapshot.created_utc,
        )
        envelope = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "snapshot": rebuilt.to_dict(),
            "locations": stored_locations,
        }
        blob = _dumps(envelope)
        if len(blob) > _MAX_CACHE_BYTES:
            msg = (
                f"cache size {len(blob)} bytes exceeds the {_MAX_CACHE_BYTES} "
                "byte ceiling; refusing to write an oversized cache"
            )
            raise LocalCacheError(msg)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, blob)

    # ------------------------------------------------------------------- read

    def read(self) -> tuple[ScientificCatalogSnapshot, dict[str, LocationState]] | None:
        """Read and verify the cached snapshot.

        Returns
        -------
        tuple or None
            ``(snapshot, locations)`` if a valid cache exists; ``None`` if the
            cache file is absent (the store may be unavailable — callers fall
            back to ``{"state": "unknown"}``).

        Raises
        ------
        LocalCacheError
            If the cache exists but is malformed JSON, has the wrong envelope
            schema, or its snapshot fails identity verification.
        """
        if not self.path.is_file():
            return None
        raw = self.path.read_bytes()
        if len(raw) > _MAX_CACHE_BYTES:
            msg = (
                f"cache file {self.path} is {len(raw)} bytes, exceeding the "
                f"{_MAX_CACHE_BYTES} byte ceiling; refusing to load"
            )
            raise LocalCacheError(msg)
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = f"cache file {self.path} is not valid JSON: {exc}"
            raise LocalCacheError(msg) from exc
        if not isinstance(envelope, dict):
            msg = f"cache envelope must be an object, got {type(envelope).__name__}"
            raise LocalCacheError(msg)
        if envelope.get("schema_version") != _CACHE_SCHEMA_VERSION:
            msg = (
                f"cache schema_version must be {_CACHE_SCHEMA_VERSION!r}, "
                f"got {envelope.get('schema_version')!r}"
            )
            raise LocalCacheError(msg)
        snapshot_dict = envelope.get("snapshot")
        if not isinstance(snapshot_dict, dict):
            msg = "cache envelope missing 'snapshot' object"
            raise LocalCacheError(msg)
        locations = envelope.get("locations")
        if not isinstance(locations, dict):
            msg = "cache envelope 'locations' must be an object"
            raise LocalCacheError(msg)

        snapshot = _snapshot_from_dict(snapshot_dict, locations)
        # Defense in depth: re-verify the cached snapshot identity before
        # trusting it. A mismatch means the cache was tampered with or written
        # by a divergent builder; surface it as a typed contract failure. We
        # pass the recorded locations so the dynamic digest recompute matches
        # the recorded location_state_ref.
        try:
            verify_snapshot(snapshot, locations)
        except SnapshotMismatchError as exc:
            msg = f"cached snapshot failed identity verification: {exc}"
            raise LocalCacheError(msg) from exc
        return snapshot, dict(locations)

    # -------------------------------------------------------------- query API

    def list_capabilities(
        self,
        store_present: bool = False,
    ) -> list[dict[str, Any]]:
        """Return a list of capability summaries from the cache.

        Each item is the entry dict augmented with a ``location_state`` key.
        When ``store_present`` is ``False`` (the default, and the honest state
        for an offline/local read), every capability reports
        ``{"state": "unknown"}`` — registry presence never implies readiness.
        When ``store_present`` is ``True`` and the cache carries a recorded
        location for the capability, that recorded state is used instead.

        Returns an empty list if no cache exists yet.
        """
        loaded = self.read()
        if loaded is None:
            return []
        snapshot, locations = loaded
        out: list[dict[str, Any]] = []
        for entry in snapshot.entries:
            summary = entry.to_dict()
            summary["location_state"] = _resolve_location_state(
                entry.capability_id, locations, store_present
            )
            out.append(summary)
        return out

    def inspect(self, capability_id: str, store_present: bool = False) -> dict[str, Any] | None:
        """Return the augmented entry for ``capability_id``, or ``None``.

        The returned dict is the entry dict plus a ``location_state`` key
        resolved the same way as :meth:`list_capabilities`. Returns ``None`` if
        no cache exists or the capability is not in the registry.
        """
        loaded = self.read()
        if loaded is None:
            return None
        snapshot, locations = loaded
        for entry in snapshot.entries:
            if entry.capability_id == capability_id:
                summary = entry.to_dict()
                summary["location_state"] = _resolve_location_state(
                    capability_id, locations, store_present
                )
                return summary
        return None


def _resolve_location_state(
    capability_id: str,
    locations: dict[str, LocationState],
    store_present: bool,
) -> dict[str, Any]:
    """Resolve the honest location state for ``capability_id``.

    When the store is absent (``store_present=False``), the state is always
    ``{"state": "unknown"}`` regardless of any recorded location — the cache
    must not claim availability it cannot prove.
    """
    if not store_present:
        return {"state": "unknown"}
    recorded = locations.get(capability_id)
    if isinstance(recorded, dict) and "state" in recorded:
        return dict(recorded)
    return {"state": "unknown"}


def _snapshot_from_dict(
    value: dict[str, Any],
    locations: dict[str, LocationState],
) -> ScientificCatalogSnapshot:
    """Reconstruct a snapshot from its wire dict and recorded locations.

    Rebuilds via :func:`build_snapshot` over the entry dicts and the recorded
    locations so every derived field (``snapshot_id``, ``merkle_root``,
    ``location_state_ref``) is recomputed consistently from the cached record.
    The recorded ``created_utc`` is preserved so two reads of the same cache
    return equal timestamps.
    """
    entries = tuple(_build_entry_from_raw(e) for e in value.get("entries", []))
    created_utc = value.get("created_utc")
    if not isinstance(created_utc, str):
        created_utc = None
    return build_snapshot(entries, locations, created_utc=created_utc)


def _atomic_write(path: Path, blob: bytes) -> None:
    """Write ``blob`` to ``path`` atomically (temp file + rename)."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
        os.replace(tmp_path, path)
    except BaseException:
        # Best-effort cleanup of the temp file on any failure path; the rename
        # either happened (path now points at the new content) or did not (the
        # original file is untouched).
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


__all__ = [
    "LocalCacheError",
    "LocationState",
    "SnapshotCache",
]
