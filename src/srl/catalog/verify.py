"""Recompute-and-compare verification for catalog snapshots.

:func:`verify_snapshot` recomputes the snapshot identity (``snapshot_id`` and
``merkle_root``) and the dynamic ``location_state_ref`` from the snapshot's own
entry list, then compares them to the values the snapshot claims. Any divergence
is a typed :class:`SnapshotMismatchError` (``CONTRACT_INVALID``): a snapshot that
fails to verify must never be trusted, and the caller routes the failure through
the fail-reason machinery as a hard, non-retriable contract failure.

This is the read-side counterpart to :func:`srl.catalog.snapshot.build_snapshot`:
the builder derives the identity deterministically, and the verifier proves a
record still matches its identity. The two share no mutable state; the verifier
reads only the snapshot's entries and recomputes from scratch.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from srl.catalog.registry import CapabilityRegistryEntry
from srl.catalog.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ScientificCatalogSnapshot,
    _entry_digest,
    _merkle_root,
)
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id

# The typed fail reason for any snapshot-verification mismatch. A mismatch is a
# structural contract failure: the record does not equal its own claimed
# content-addressed identity.
VERIFY_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON


class SnapshotMismatchError(ContractError):
    """Raised when a snapshot's recorded identity does not match a recompute.

    The snapshot record claims a ``snapshot_id`` and/or ``merkle_root`` that
    differ from the values recomputed from its own entries. Carries the typed
    fail reason ``CONTRACT_INVALID``.

    Attributes
    ----------
    field:
        The field that diverged (e.g. ``"snapshot_id"``, ``"merkle_root"``,
        ``"location_state_ref"``, ``"schema_version"``).
    recorded:
        The value recorded on the snapshot.
    recomputed:
        The value recomputed from the entry list.
    """

    def __init__(
        self,
        field: str,
        *,
        recorded: object,
        recomputed: object,
    ) -> None:
        self.field: str = field
        self.recorded: object = recorded
        self.recomputed: object = recomputed
        msg = f"snapshot {field!r} mismatch: recorded {recorded!r} != recomputed {recomputed!r}"
        super().__init__(msg, fail_reason=VERIFY_FAIL_REASON)


def verify_snapshot(
    snapshot: ScientificCatalogSnapshot,
    locations: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Verify that ``snapshot`` matches its recomputed identity.

    Recomputes the canonical per-entry digests, the merkle root, the snapshot
    identity (``snapshot_id``), and the dynamic ``location_state_ref`` from the
    snapshot's entry list, then compares each to the recorded value. Also
    asserts the fixed record tail (``schema_version``, ``canonical_writes``,
    ``grants_authority``) is unchanged.

    Parameters
    ----------
    snapshot:
        The snapshot record to verify.
    locations:
        Optional explicit location map. When ``None`` (the common case), the
        dynamic digest is recomputed over every entry's ``capability_id`` mapped
        to ``{"state": "unknown"}``, matching the builder default. Pass an
        explicit map only when verifying a snapshot built with a known
        non-default location set.

    Raises
    ------
    SnapshotMismatchError
        With fail reason ``CONTRACT_INVALID`` if any identity field, the
        location digest, or the fixed tail does not match the recompute.
    """
    _verify_fixed_tail(snapshot)

    sorted_entries = sorted(snapshot.entries, key=lambda e: e.capability_id)
    recorded_order = [e.capability_id for e in snapshot.entries]
    recomputed_order = [e.capability_id for e in sorted_entries]
    if recorded_order != recomputed_order:
        # The builder stores entries sorted by capability_id; an unsorted stored
        # entry tuple is itself a contract violation (it would change bytes).
        raise SnapshotMismatchError(
            "entries_order",
            recorded=recorded_order,
            recomputed=recomputed_order,
        )

    recomputed_merkle = _merkle_root([_entry_digest(e) for e in sorted_entries])
    if recomputed_merkle != snapshot.merkle_root:
        raise SnapshotMismatchError(
            "merkle_root",
            recorded=snapshot.merkle_root,
            recomputed=recomputed_merkle,
        )

    recomputed_id = _recompute_snapshot_id(sorted_entries, recomputed_merkle)
    if recomputed_id != snapshot.snapshot_id:
        raise SnapshotMismatchError(
            "snapshot_id",
            recorded=snapshot.snapshot_id,
            recomputed=recomputed_id,
        )

    if locations is None:
        loc_map: dict[str, dict[str, Any]] = {
            e.capability_id: {"state": "unknown"} for e in sorted_entries
        }
    else:
        loc_map = locations
    recomputed_loc_ref = _recompute_location_state_ref(loc_map)
    if recomputed_loc_ref != snapshot.location_state_ref:
        raise SnapshotMismatchError(
            "location_state_ref",
            recorded=snapshot.location_state_ref,
            recomputed=recomputed_loc_ref,
        )


def _verify_fixed_tail(snapshot: ScientificCatalogSnapshot) -> None:
    """Assert the immutable record tail fields are unchanged."""
    if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotMismatchError(
            "schema_version",
            recorded=snapshot.schema_version,
            recomputed=SNAPSHOT_SCHEMA_VERSION,
        )
    if snapshot.canonical_writes != 0:
        raise SnapshotMismatchError(
            "canonical_writes",
            recorded=snapshot.canonical_writes,
            recomputed=0,
        )
    if snapshot.grants_authority is not False:
        raise SnapshotMismatchError(
            "grants_authority",
            recorded=snapshot.grants_authority,
            recomputed=False,
        )


def _recompute_snapshot_id(
    sorted_entries: list[CapabilityRegistryEntry],
    merkle_root: str,
) -> str:
    """Recompute the snapshot identity from the identity body."""
    identity_body: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "entries": [e.to_dict() for e in sorted_entries],
        "merkle_root": merkle_root,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    recomputed = object_id(identity_body)
    return recomputed


def _recompute_location_state_ref(loc_map: dict[str, dict[str, Any]]) -> str:
    """Recompute the dynamic location-state digest from a location map."""
    body = deepcopy(loc_map)
    recomputed = object_id(body)
    return recomputed


__all__ = [
    "VERIFY_FAIL_REASON",
    "SnapshotMismatchError",
    "verify_snapshot",
]
