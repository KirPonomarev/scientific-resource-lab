"""Tests for the S04 SRF storage layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from srl.cas import (
    BYTES_PER_GIB,
    WORK_NAMESPACES,
    SrfStorageLayout,
    StorageLayoutError,
    StorageQuotaStatus,
    check_srf_storage_quota,
)


def test_layout_initializes_cold_work_quarantine_and_restore_dirs(tmp_path: Path) -> None:
    """The fixture layout creates exactly the expected namespace families."""
    layout = SrfStorageLayout.at(tmp_path / "SRF")
    layout.initialize()
    assert layout.cold_cas.is_dir()
    assert layout.quarantine.is_dir()
    assert layout.restore_tests.is_dir()
    for namespace in WORK_NAMESPACES:
        assert layout.work_path(namespace).is_dir()


def test_cold_store_round_trips_without_using_work_namespace(tmp_path: Path) -> None:
    """The cold-cas namespace is a real LocalArtifactStore root."""
    layout = SrfStorageLayout.at(tmp_path / "SRF")
    store = layout.cold_store()
    desc = store.put(b"immutable-object")
    assert store.get(desc.digest) == b"immutable-object"
    assert str(desc.store_root_redacted).startswith("redacted:")
    assert not list(layout.work.rglob("sha256:*"))


def test_unknown_work_namespace_rejected(tmp_path: Path) -> None:
    """Only the declared rebuildable work namespaces are addressable."""
    layout = SrfStorageLayout.at(tmp_path / "SRF")
    with pytest.raises(StorageLayoutError):
        layout.work_path("database")


@pytest.mark.parametrize("name", ["active.db", "index.sqlite", "store.sqlite3", "run.wal"])
def test_cold_cas_rejects_mutable_database_and_wal_artifacts(tmp_path: Path, name: str) -> None:
    """An active DB or WAL file in cold-cas violates the immutable namespace."""
    layout = SrfStorageLayout.at(tmp_path / "SRF")
    layout.initialize()
    (layout.cold_cas / name).write_text("mutable", encoding="utf-8")
    with pytest.raises(StorageLayoutError):
        layout.assert_cold_cas_immutable()


def test_cold_cas_allows_regular_content_addressed_files(tmp_path: Path) -> None:
    """A regular content object does not trip the DB/WAL guard."""
    layout = SrfStorageLayout.at(tmp_path / "SRF")
    store = layout.cold_store()
    store.put(b"regular")
    layout.assert_cold_cas_immutable()


def test_storage_quota_ok() -> None:
    """Usage inside allocation and reserve is admitted."""
    decision = check_srf_storage_quota(
        observed_used_bytes=10 * BYTES_PER_GIB,
        observed_free_bytes=150 * BYTES_PER_GIB,
    )
    assert decision.status is StorageQuotaStatus.OK
    assert decision.reason == "ok"


def test_storage_quota_exceeded() -> None:
    """Usage above the 400 GiB allocation is refused."""
    decision = check_srf_storage_quota(
        observed_used_bytes=401 * BYTES_PER_GIB,
        observed_free_bytes=150 * BYTES_PER_GIB,
    )
    assert decision.status is StorageQuotaStatus.T7_QUOTA_EXCEEDED
    assert decision.reason == "allocation_exceeded"


def test_storage_quota_waits_when_free_reserve_too_low() -> None:
    """Free space below the 100 GiB reserve is a WAIT_T7_BINDING."""
    decision = check_srf_storage_quota(
        observed_used_bytes=10 * BYTES_PER_GIB,
        observed_free_bytes=99 * BYTES_PER_GIB,
    )
    assert decision.status is StorageQuotaStatus.WAIT_T7_BINDING
    assert decision.reason == "free_reserve_below_minimum"


def test_storage_quota_rejects_negative_observations() -> None:
    """Negative byte observations are structural errors."""
    with pytest.raises(StorageLayoutError):
        check_srf_storage_quota(observed_used_bytes=-1, observed_free_bytes=0)
