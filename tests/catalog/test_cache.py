"""Tests for :mod:`srl.catalog.local_cache`.

Hermetic: each test writes to a temp directory; the listing/inspection API is
exercised with the store both absent (honest "unknown") and present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from srl.catalog.local_cache import LocalCacheError, SnapshotCache
from srl.catalog.snapshot import build_snapshot
from srl.catalog.verify import verify_snapshot
from tests.catalog._helpers import FIXED_UTC


def test_read_returns_none_when_cache_absent(tmp_path: Path) -> None:
    """C24-03: read() is None when no cache file exists (store absent)."""
    cache = SnapshotCache(tmp_path / "missing.json")
    assert cache.read() is None
    assert cache.list_capabilities() == []
    assert cache.inspect("cap.algebra_exact") is None


def test_write_then_read_round_trips_identity(tmp_path: Path, seed_entries: tuple) -> None:
    """A written snapshot round-trips with identical identity fields."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap)
    loaded = cache.read()
    assert loaded is not None
    loaded_snap, _locations = loaded
    assert loaded_snap.snapshot_id == snap.snapshot_id
    assert loaded_snap.merkle_root == snap.merkle_root
    assert [e.capability_id for e in loaded_snap.entries] == [e.capability_id for e in snap.entries]


def test_list_capabilities_store_absent_reports_unknown(
    tmp_path: Path, seed_entries: tuple
) -> None:
    """C24-03: with the store absent, every capability reports state=unknown."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap)
    caps = cache.list_capabilities(store_present=False)
    assert len(caps) == len(seed_entries)
    for cap in caps:
        assert cap["location_state"] == {"state": "unknown"}
        # Identity fields are still present.
        assert cap["admission_stage"] == "not_admitted"


def test_list_capabilities_store_present_uses_recorded(tmp_path: Path, seed_entries: tuple) -> None:
    """With the store present, a recorded location state is surfaced."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap, locations={"cap.algebra_exact": {"state": "available"}})
    caps = cache.list_capabilities(store_present=True)
    by_id = {c["capability_id"]: c for c in caps}
    assert by_id["cap.algebra_exact"]["location_state"] == {"state": "available"}
    # Unrecorded capabilities still fall back to unknown.
    assert by_id["cap.dynamics"]["location_state"] == {"state": "unknown"}


def test_inspect_returns_entry_with_location(tmp_path: Path, seed_entries: tuple) -> None:
    """inspect() returns a single entry augmented with location_state."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap)
    entry = cache.inspect("cap.geometry_tda", store_present=False)
    assert entry is not None
    assert entry["adapter_id"] == "ripser"
    assert entry["location_state"] == {"state": "unknown"}


def test_inspect_unknown_capability_returns_none(tmp_path: Path, seed_entries: tuple) -> None:
    """inspect() on an absent capability returns None."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap)
    assert cache.inspect("cap.does_not_exist") is None


def test_cache_file_is_under_one_mib(tmp_path: Path, seed_entries: tuple) -> None:
    """The cache file is well under the 1 MiB ceiling."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap)
    size = (tmp_path / "catalog.json").stat().st_size
    assert size < 1024 * 1024
    assert size < 20_000  # the 15-entry seed cache is a few KiB


def test_cache_read_verifies_identity(tmp_path: Path, seed_entries: tuple) -> None:
    """read() re-verifies the cached snapshot identity internally."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap)
    loaded = cache.read()
    assert loaded is not None
    loaded_snap, _ = loaded
    locs = {e.capability_id: {"state": "unknown"} for e in loaded_snap.entries}
    verify_snapshot(loaded_snap, locs)


def test_corrupt_cache_raises(tmp_path: Path) -> None:
    """A cache file with invalid JSON raises LocalCacheError."""
    path = tmp_path / "catalog.json"
    path.write_text("{not valid json", encoding="utf-8")
    cache = SnapshotCache(path)
    with pytest.raises(LocalCacheError, match="not valid JSON"):
        cache.read()


def test_wrong_envelope_schema_raises(tmp_path: Path, seed_entries: tuple) -> None:
    """A cache with the wrong envelope schema_version raises LocalCacheError."""
    cache = SnapshotCache(tmp_path / "catalog.json")
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    cache.write(snap)
    # Tamper the envelope schema version in place.
    raw = (tmp_path / "catalog.json").read_text(encoding="utf-8")
    raw = raw.replace("CapabilityCatalogCache/v1", "CapabilityCatalogCache/v2")
    (tmp_path / "catalog.json").write_text(raw, encoding="utf-8")
    with pytest.raises(LocalCacheError, match="schema_version"):
        cache.read()


def test_write_is_atomic_on_existing_file(tmp_path: Path, seed_entries: tuple) -> None:
    """A second write fully replaces the first, leaving a valid file."""
    path = tmp_path / "catalog.json"
    cache = SnapshotCache(path)
    snap1 = build_snapshot(seed_entries, created_utc="2026-01-01T00:00:00Z")
    snap2 = build_snapshot(seed_entries, created_utc="2026-02-02T00:00:00Z")
    cache.write(snap1)
    cache.write(snap2)
    loaded = cache.read()
    assert loaded is not None
    loaded_snap, _ = loaded
    assert loaded_snap.created_utc == "2026-02-02T00:00:00Z"
