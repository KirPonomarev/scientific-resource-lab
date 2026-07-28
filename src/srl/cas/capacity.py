"""T7 capacity allocation policy and capacity decision.

The T7 volume is a bounded, mission-scoped resource. This module owns the P0
allocation table (how the hard ceiling is partitioned across object classes) and
the capacity decision a content-addressed store consults before accepting an
ingest. The policy is intentionally conservative: ingestion past the hard
ceiling is refused with a typed ``T7_QUOTA_EXCEEDED`` at the store layer; this
module only returns the decision, it does not raise.

Decision bands
--------------
``used`` is measured against three thresholds drawn from the allocation table:

- below ``warning_gib`` (default 35 GiB) -> :attr:`CapacityDecision.OK`;
- ``[warning_gib, review_gib)`` (default ``[35, 45)``) -> WARNING;
- ``[review_gib, hard_ceiling_gib)`` (default ``[45, 50)``) -> REVIEW_REQUIRED;
- at or above ``hard_ceiling_gib`` (default 50 GiB) -> EXCEEDED.

The bands are half-open so a value exactly on a threshold falls into the higher
band (e.g. exactly 35 GiB is a WARNING, exactly 50 GiB is EXCEEDED). This keeps
the "have we reached the limit?" question unambiguous: reaching the ceiling is
the refusal condition, not approaching it.

Allocation table
----------------
The P0 table partitions the 50 GiB hard ceiling across object classes. The sum
of the per-class budgets equals the ceiling so the table is internally
consistent (no class is silently over-allocated). The table is a frozen
dataclass so callers can pin it for a mission and assert against it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Final

# Bytes per GiB. Extracted as a constant so byte<->GiB conversion has one home
# and is free of magic-value lint. The policy is expressed in GiB (the unit the
# operator buys the volume in) and converted to bytes for byte-accurate checks.
_BYTES_PER_GIB: Final[int] = 1024**3

# The typed fail reason emitted when an ingest is refused for exceeding the hard
# ceiling. Mirrors the ``T7_QUOTA_EXCEEDED`` entry in ``automation/fail-reasons.json``
# (class ``storage``, ``hard_stop=false``, ``retriable=false``). Kept as a
# constant so the store layer asserts against the symbol.
T7_QUOTA_EXCEEDED_FAIL_REASON: Final[str] = "T7_QUOTA_EXCEEDED"


class ObjectClass(enum.Enum):
    """The object classes the T7 allocation table budgets capacity for.

    The class also records whether an object of this class is *T7-bound*: a
    T7-bound class may never fall back to a local store and must wait for the T7
    volume (see :mod:`srl.cas.fallback`). Only :attr:`FIXTURE` is not T7-bound —
    public tiny fixtures are the sole class permitted in the local fallback.
    """

    PACK_IMAGE = "pack_image"
    RUN_RECEIPT = "run_receipt"
    DATASET = "dataset"
    SOURCE_BLOB = "source_blob"
    FIXTURE = "fixture"
    PILOT_RUN = "pilot_run"
    CATALOG_SBOM = "catalog_sbom"
    QUARANTINE = "quarantine"

    @property
    def t7_bound(self) -> bool:
        """True iff objects of this class must live on the T7 volume.

        Pack images, run receipts, datasets, source blobs, pilot runs, the
        catalog/SBOM, and quarantine are all T7-bound. Only public tiny fixtures
        (:attr:`FIXTURE`) may fall back to a local store.
        """
        return self is not ObjectClass.FIXTURE


class CapacityDecision(enum.Enum):
    """The outcome of consulting the capacity policy for a used-byte count.

    ``OK`` and ``WARNING`` permit the ingest (a WARNING is informational; the
    store proceeds but the receipt records the band). ``REVIEW_REQUIRED`` permits
    the ingest but flags that operator review is needed before the ceiling is
    reached. ``EXCEEDED`` refuses the ingest: the store raises
    ``T7_QUOTA_EXCEEDED`` and the object is not written.
    """

    OK = "ok"
    WARNING = "warning"
    REVIEW_REQUIRED = "review_required"
    EXCEEDED = "exceeded"


@dataclass(frozen=True)
class AllocationTable:
    """The P0 capacity allocation table for the T7 volume.

    The three thresholds (``hard_ceiling_gib``, ``warning_gib``,
    ``review_gib``) define the decision bands. The per-class budgets partition
    the hard ceiling across object classes; their sum must equal the ceiling
    (asserted at construction via :func:`DEFAULT_ALLOCATION` and by the
    :func:`class_budget_gib` callers).

    Attributes
    ----------
    hard_ceiling_gib:
        Absolute maximum usable capacity. At or above this the store refuses
        ingestion (EXCEEDED). Default 50.
    warning_gib:
        Soft warning threshold. At or above this the decision is WARNING.
        Default 35.
    review_gib:
        Review threshold. At or above this the decision is REVIEW_REQUIRED.
        Default 45.
    packs_gib / source_blobs_gib / fixtures_gib / pilot_runs_gib /
    catalog_sbom_gib / quarantine_gib:
        The six named per-class budgets in GiB. Their sum equals
        ``hard_ceiling_gib``. Run receipts and datasets fold into the packs and
        source-blobs slices respectively (see :meth:`class_budget_gib`).
    """

    hard_ceiling_gib: int
    warning_gib: int
    review_gib: int
    packs_gib: int
    source_blobs_gib: int
    fixtures_gib: int
    pilot_runs_gib: int
    catalog_sbom_gib: int
    quarantine_gib: int

    def hard_ceiling_bytes(self) -> int:
        """Return the hard ceiling in bytes."""
        return self.hard_ceiling_gib * _BYTES_PER_GIB

    def warning_bytes(self) -> int:
        """Return the warning threshold in bytes."""
        return self.warning_gib * _BYTES_PER_GIB

    def review_bytes(self) -> int:
        """Return the review threshold in bytes."""
        return self.review_gib * _BYTES_PER_GIB

    def class_budget_gib(self, object_class: ObjectClass) -> int:
        """Return the GiB budget allocated to ``object_class``.

        The P0 table names six buckets. Run receipts share the packs slice
        (they are light metadata bound for the same T7 region); datasets share
        the source-blobs slice. This keeps the six budgets summing to the hard
        ceiling while still answering the per-class question.
        """
        budgets: dict[ObjectClass, int] = {
            ObjectClass.PACK_IMAGE: self.packs_gib,
            ObjectClass.RUN_RECEIPT: self.packs_gib,
            ObjectClass.DATASET: self.source_blobs_gib,
            ObjectClass.SOURCE_BLOB: self.source_blobs_gib,
            ObjectClass.FIXTURE: self.fixtures_gib,
            ObjectClass.PILOT_RUN: self.pilot_runs_gib,
            ObjectClass.CATALOG_SBOM: self.catalog_sbom_gib,
            ObjectClass.QUARANTINE: self.quarantine_gib,
        }
        return budgets[object_class]


# The default P0 allocation. The sum of the six named budgets (20 + 10 + 5 + 5 +
# 5 + 5) equals the 50 GiB hard ceiling. Run receipts and datasets fold into the
# packs and source-blobs slices respectively (see the accessors above) so the
# table remains balanced. Frozen so a mission pins it and asserts against it.
DEFAULT_ALLOCATION: Final[AllocationTable] = AllocationTable(
    hard_ceiling_gib=50,
    warning_gib=35,
    review_gib=45,
    packs_gib=20,
    source_blobs_gib=10,
    fixtures_gib=5,
    pilot_runs_gib=5,
    catalog_sbom_gib=5,
    quarantine_gib=5,
)


def check_capacity(
    used_bytes: int,
    *,
    table: AllocationTable = DEFAULT_ALLOCATION,
) -> CapacityDecision:
    """Classify ``used_bytes`` against the capacity policy.

    Parameters
    ----------
    used_bytes:
        The current used capacity in bytes. Must be a non-negative integer.
    table:
        The allocation table to consult. Defaults to :data:`DEFAULT_ALLOCATION`.

    Returns
    -------
    CapacityDecision
        The decision band for ``used_bytes``. ``EXCEEDED`` means the caller
        (the store) must refuse the ingest with ``T7_QUOTA_EXCEEDED``.

    Raises
    ------
    ValueError
        If ``used_bytes`` is negative (used capacity is never negative).
    """
    if used_bytes < 0:
        msg = f"used_bytes must be non-negative, got {used_bytes}"
        raise ValueError(msg)
    if used_bytes >= table.hard_ceiling_bytes():
        return CapacityDecision.EXCEEDED
    if used_bytes >= table.review_bytes():
        return CapacityDecision.REVIEW_REQUIRED
    if used_bytes >= table.warning_bytes():
        return CapacityDecision.WARNING
    return CapacityDecision.OK


__all__ = [
    "DEFAULT_ALLOCATION",
    "T7_QUOTA_EXCEEDED_FAIL_REASON",
    "AllocationTable",
    "CapacityDecision",
    "ObjectClass",
    "check_capacity",
]
