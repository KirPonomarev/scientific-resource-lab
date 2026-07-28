"""Tests for :mod:`srl.catalog.verify`.

Hermetic: builds snapshots with explicit timestamps and tampers them via
``dataclasses.replace`` to confirm the typed mismatch contract.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from srl.catalog.snapshot import build_snapshot
from srl.catalog.verify import (
    VERIFY_FAIL_REASON,
    SnapshotMismatchError,
    verify_snapshot,
)
from tests.catalog._helpers import FIXED_UTC, make_entry


def _base_snapshot(entries: tuple) -> object:
    return build_snapshot(entries, created_utc=FIXED_UTC)


def test_verify_passes_on_fresh_snapshot(seed_entries: tuple) -> None:
    """A freshly built snapshot verifies cleanly."""
    snap = _base_snapshot(seed_entries)
    verify_snapshot(snap)  # no exception


def test_verify_detects_tampered_merkle_root(seed_entries: tuple) -> None:
    """C24-04: a mutated merkle_root raises SnapshotMismatchError."""
    snap = _base_snapshot(seed_entries)
    bad = replace(snap, merkle_root="sha256:" + "0" * 64)
    with pytest.raises(SnapshotMismatchError) as exc_info:
        verify_snapshot(bad)
    assert exc_info.value.field == "merkle_root"
    assert exc_info.value.fail_reason == VERIFY_FAIL_REASON
    assert exc_info.value.recorded != exc_info.value.recomputed


def test_verify_detects_tampered_snapshot_id(seed_entries: tuple) -> None:
    """A mutated snapshot_id is detected as a mismatch."""
    snap = _base_snapshot(seed_entries)
    bad = replace(snap, snapshot_id="sha256:" + "1" * 64)
    with pytest.raises(SnapshotMismatchError) as exc_info:
        verify_snapshot(bad)
    assert exc_info.value.field == "snapshot_id"


def test_verify_detects_tampered_entry_field(seed_entries: tuple) -> None:
    """C24-04: mutating an entry's adapter changes the merkle and is detected."""
    snap = _base_snapshot(seed_entries)
    tampered_entry = replace(snap.entries[0], adapter_id="bogus_adapter")
    tampered_entries = (tampered_entry, *snap.entries[1:])
    bad = replace(snap, entries=tampered_entries)
    with pytest.raises(SnapshotMismatchError) as exc_info:
        verify_snapshot(bad)
    assert exc_info.value.field == "merkle_root"


def test_verify_detects_wrong_schema_version(seed_entries: tuple) -> None:
    """A wrong schema_version is caught by the fixed-tail check."""
    snap = _base_snapshot(seed_entries)
    bad = replace(snap, schema_version="ScientificCatalogSnapshot/v2")
    with pytest.raises(SnapshotMismatchError) as exc_info:
        verify_snapshot(bad)
    assert exc_info.value.field == "schema_version"


def test_verify_detects_nonzero_canonical_writes(seed_entries: tuple) -> None:
    """canonical_writes != 0 is caught by the fixed-tail check."""
    snap = _base_snapshot(seed_entries)
    bad = replace(snap, canonical_writes=1)
    with pytest.raises(SnapshotMismatchError) as exc_info:
        verify_snapshot(bad)
    assert exc_info.value.field == "canonical_writes"


def test_verify_detects_grants_authority_true(seed_entries: tuple) -> None:
    """grants_authority=True is caught by the fixed-tail check."""
    snap = _base_snapshot(seed_entries)
    bad = replace(snap, grants_authority=True)
    with pytest.raises(SnapshotMismatchError) as exc_info:
        verify_snapshot(bad)
    assert exc_info.value.field == "grants_authority"


def test_verify_detects_location_state_ref_mismatch(seed_entries: tuple) -> None:
    """A location_state_ref that does not match the recompute is detected."""
    snap = build_snapshot(
        seed_entries,
        {"cap.algebra_exact": {"state": "available"}},
        created_utc=FIXED_UTC,
    )
    bad = replace(snap, location_state_ref="sha256:" + "f" * 64)
    with pytest.raises(SnapshotMismatchError) as exc_info:
        verify_snapshot(bad, {"cap.algebra_exact": {"state": "available"}})
    assert exc_info.value.field == "location_state_ref"


def test_verify_with_explicit_locations_passes(seed_entries: tuple) -> None:
    """verify_snapshot passes when given the matching explicit locations."""
    locs = {"cap.algebra_exact": {"state": "available"}}
    snap = build_snapshot(seed_entries, locs, created_utc=FIXED_UTC)
    verify_snapshot(snap, locs)


def test_verify_single_entry_snapshot() -> None:
    """Verification works on a minimal single-entry snapshot."""
    snap = build_snapshot([make_entry()], created_utc=FIXED_UTC)
    verify_snapshot(snap)
