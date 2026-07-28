"""Unit tests for the T7 capacity policy (srl.cas.capacity).

Pins:

1. The decision bands at the default thresholds (35/45/50 GiB).
2. The P0 allocation table sums to the hard ceiling.
3. Object-class T7-boundness (only FIXTURE is not T7-bound).
4. ``check_capacity`` rejects negative usage.
"""

from __future__ import annotations

import pytest

from srl.cas.capacity import (
    DEFAULT_ALLOCATION,
    T7_QUOTA_EXCEEDED_FAIL_REASON,
    AllocationTable,
    CapacityDecision,
    ObjectClass,
    check_capacity,
)

_GIB = 1024**3


def test_check_capacity_ok_below_warning() -> None:
    """Usage below 35 GiB is OK."""
    assert check_capacity(0) is CapacityDecision.OK
    assert check_capacity(34 * _GIB) is CapacityDecision.OK


def test_check_capacity_warning_at_threshold() -> None:
    """Usage in [35, 45) GiB is WARNING (half-open: 35 inclusive)."""
    assert check_capacity(35 * _GIB) is CapacityDecision.WARNING
    assert check_capacity(44 * _GIB) is CapacityDecision.WARNING


def test_check_capacity_review_at_threshold() -> None:
    """Usage in [45, 50) GiB is REVIEW_REQUIRED."""
    assert check_capacity(45 * _GIB) is CapacityDecision.REVIEW_REQUIRED
    assert check_capacity(49 * _GIB) is CapacityDecision.REVIEW_REQUIRED


def test_check_capacity_exceeded_at_ceiling() -> None:
    """Usage at or above 50 GiB is EXCEEDED."""
    assert check_capacity(50 * _GIB) is CapacityDecision.EXCEEDED
    assert check_capacity(100 * _GIB) is CapacityDecision.EXCEEDED


def test_check_capacity_just_below_ceiling_is_review() -> None:
    """One byte below the ceiling is REVIEW_REQUIRED, not EXCEEDED."""
    assert check_capacity(50 * _GIB - 1) is CapacityDecision.REVIEW_REQUIRED


def test_check_capacity_rejects_negative() -> None:
    """Negative usage is a ValueError."""
    with pytest.raises(ValueError):
        check_capacity(-1)


def test_default_allocation_sums_to_ceiling() -> None:
    """The six named budgets sum to the 50 GiB hard ceiling."""
    table = DEFAULT_ALLOCATION
    total = (
        table.packs_gib
        + table.source_blobs_gib
        + table.fixtures_gib
        + table.pilot_runs_gib
        + table.catalog_sbom_gib
        + table.quarantine_gib
    )
    assert total == table.hard_ceiling_gib == 50


def test_default_allocation_thresholds() -> None:
    """The default thresholds are the documented P0 values."""
    t = DEFAULT_ALLOCATION
    assert (t.hard_ceiling_gib, t.warning_gib, t.review_gib) == (50, 35, 45)


@pytest.mark.parametrize(
    "cls,expected_budget",
    [
        (ObjectClass.PACK_IMAGE, 20),
        (ObjectClass.RUN_RECEIPT, 20),
        (ObjectClass.SOURCE_BLOB, 10),
        (ObjectClass.DATASET, 10),
        (ObjectClass.FIXTURE, 5),
        (ObjectClass.PILOT_RUN, 5),
        (ObjectClass.CATALOG_SBOM, 5),
        (ObjectClass.QUARANTINE, 5),
    ],
)
def test_class_budget(cls: ObjectClass, expected_budget: int) -> None:
    """The per-class budget matches the P0 table (receipts/datasets fold in)."""
    assert DEFAULT_ALLOCATION.class_budget_gib(cls) == expected_budget


def test_only_fixture_is_not_t7_bound() -> None:
    """Every object class except FIXTURE is T7-bound."""
    not_bound = [c for c in ObjectClass if not c.t7_bound]
    assert not_bound == [ObjectClass.FIXTURE]


def test_custom_table_respected() -> None:
    """check_capacity honors a caller-supplied allocation table."""
    small = AllocationTable(
        hard_ceiling_gib=10,
        warning_gib=7,
        review_gib=9,
        packs_gib=4,
        source_blobs_gib=2,
        fixtures_gib=1,
        pilot_runs_gib=1,
        catalog_sbom_gib=1,
        quarantine_gib=1,
    )
    assert check_capacity(7 * _GIB, table=small) is CapacityDecision.WARNING
    assert check_capacity(10 * _GIB, table=small) is CapacityDecision.EXCEEDED


def test_quota_exceeded_fail_reason_constant() -> None:
    """The quota fail reason is the registry value."""
    assert T7_QUOTA_EXCEEDED_FAIL_REASON == "T7_QUOTA_EXCEEDED"
