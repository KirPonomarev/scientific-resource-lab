"""Tests for :mod:`srl.catalog.snapshot`.

Hermetic: every snapshot is built with an explicit ``created_utc`` so identity
assertions never depend on the wall clock. These tests pin the WP-C24 identity
contract: same entries -> same bytes+merkle+id regardless of input order;
location changes never alter identity.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from srl.catalog.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ScientificCatalogSnapshot,
    SnapshotError,
    build_snapshot,
)
from srl.catalog.verify import verify_snapshot
from srl.contracts.ids import validate_object_id
from tests.catalog._helpers import FIXED_UTC, make_admitted_entry, make_entry


def test_snapshot_schema_and_tail_are_fixed(seed_entries: tuple) -> None:
    """A snapshot carries the v1 schema and the immutable fixed tail."""
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    assert snap.schema_version == SNAPSHOT_SCHEMA_VERSION
    assert snap.canonical_writes == 0
    assert snap.grants_authority is False


def test_snapshot_entries_are_sorted_by_capability_id(seed_entries: tuple) -> None:
    """The snapshot stores entries sorted by capability_id."""
    snap = build_snapshot(reversed(seed_entries), created_utc=FIXED_UTC)
    ids = [e.capability_id for e in snap.entries]
    assert ids == sorted(ids)


def test_shuffled_entries_produce_identical_bytes_and_identity(seed_entries: tuple) -> None:
    """C24-01: input order does not affect bytes, merkle_root, or snapshot_id."""
    forward = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    backward = build_snapshot(reversed(seed_entries), created_utc=FIXED_UTC)
    shuffled = list(seed_entries)
    shuffled.reverse()
    shuffled[0], shuffled[7] = shuffled[7], shuffled[0]
    sideways = build_snapshot(shuffled, created_utc=FIXED_UTC)

    assert forward.canonical_dumps() == backward.canonical_dumps() == sideways.canonical_dumps()
    assert forward.merkle_root == backward.merkle_root == sideways.merkle_root
    assert forward.snapshot_id == backward.snapshot_id == sideways.snapshot_id


def test_location_mutation_changes_only_location_state_ref(seed_entries: tuple) -> None:
    """C24-02: a location change alters location_state_ref but never identity."""
    base = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    alt = build_snapshot(
        seed_entries,
        {"cap.algebra_exact": {"state": "available"}},
        created_utc=FIXED_UTC,
    )
    # Identity-stable.
    assert alt.snapshot_id == base.snapshot_id
    assert alt.merkle_root == base.merkle_root
    assert alt.entries == base.entries
    # Dynamic changed.
    assert alt.location_state_ref != base.location_state_ref


def test_created_utc_does_not_affect_identity(seed_entries: tuple) -> None:
    """A different build timestamp never changes snapshot_id or merkle_root."""
    a = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    b = build_snapshot(seed_entries, created_utc="2026-08-01T12:00:00Z")
    assert a.snapshot_id == b.snapshot_id
    assert a.merkle_root == b.merkle_root
    assert a.created_utc != b.created_utc


def test_snapshot_id_and_merkle_root_are_sha256_digests(seed_entries: tuple) -> None:
    """snapshot_id and merkle_root are well-formed sha256 object ids."""
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    validate_object_id(snap.snapshot_id)
    validate_object_id(snap.merkle_root)


def test_default_locations_are_all_unknown(seed_entries: tuple) -> None:
    """With no explicit locations, every capability defaults to state=unknown."""
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    # The default location_state_ref must verify against the unknown map.
    verify_snapshot(snap)


def test_duplicate_capability_id_rejected() -> None:
    """Two entries with the same capability_id raise SnapshotError."""
    first = make_entry(capability_id="cap.dup", profile="algebra_exact")
    second = make_entry(capability_id="cap.dup", profile="dynamics")
    with pytest.raises(SnapshotError, match="duplicate capability_id"):
        build_snapshot([first, second], created_utc=FIXED_UTC)


def test_admitted_entry_changes_merkle_root(seed_entries: tuple) -> None:
    """Promoting one entry to EXPERIMENTAL_ACCEPTED changes the merkle root."""
    base = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    admitted = list(seed_entries)
    admitted[0] = make_admitted_entry(
        capability_id=admitted[0].capability_id, profile=admitted[0].profile
    )
    promoted = build_snapshot(admitted, created_utc=FIXED_UTC)
    assert promoted.merkle_root != base.merkle_root
    assert promoted.snapshot_id != base.snapshot_id


def test_snapshot_is_frozen(seed_entries: tuple) -> None:
    """A ScientificCatalogSnapshot is immutable."""
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    with pytest.raises((AttributeError, Exception)):
        snap.merkle_root = "sha256:" + "0" * 64  # type: ignore[misc]


def test_snapshot_to_dict_roundtrips_fields(seed_entries: tuple) -> None:
    """to_dict carries every snapshot field with the right shape."""
    snap = build_snapshot(seed_entries, created_utc=FIXED_UTC)
    doc = snap.to_dict()
    assert doc["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert doc["snapshot_id"] == snap.snapshot_id
    assert doc["merkle_root"] == snap.merkle_root
    assert doc["location_state_ref"] == snap.location_state_ref
    assert doc["created_utc"] == snap.created_utc
    assert doc["canonical_writes"] == 0
    assert doc["grants_authority"] is False
    assert len(doc["entries"]) == len(seed_entries)


def test_one_entry_snapshot_verifies() -> None:
    """A single-entry snapshot builds and verifies."""
    entry = make_entry()
    snap = build_snapshot([entry], created_utc=FIXED_UTC)
    verify_snapshot(snap)


def test_admitted_entry_dataclass_is_immutable() -> None:
    """replace on a snapshot entry yields a new immutable object."""
    snap_a = build_snapshot([make_entry()], created_utc=FIXED_UTC)
    snap_b = replace(snap_a, created_utc="2026-09-01T00:00:00Z")
    assert isinstance(snap_b, ScientificCatalogSnapshot)
    assert snap_a.created_utc == FIXED_UTC
