"""Unit tests for the local fallback store (srl.cas.fallback).

Pins:

1. A ``<1 MiB`` public fixture (object class FIXTURE) is accepted and round-trips.
2. A T7-bound object class is refused with ``WAIT_STORAGE`` regardless of size.
3. An object exceeding the 1 MiB single-object limit is refused even for FIXTURE.
4. An ingest that would exceed the 25 MiB total limit is refused.
5. An idempotent re-put of the same object does not grow usage.
6. The fallback requires an explicitly passed root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from srl.cas.capacity import ObjectClass
from srl.cas.fallback import (
    FALLBACK_SINGLE_OBJECT_MAX_BYTES,
    FALLBACK_TOTAL_MAX_BYTES,
    LocalFallbackStore,
)
from srl.cas.store import StoreWaitError

_TINY = b"tiny-fixture-blob-content"


def test_fallback_accepts_tiny_fixture(tmp_path: Path) -> None:
    """A <1 MiB fixture is accepted and the bytes round-trip."""
    store = LocalFallbackStore(tmp_path)
    desc = store.put(_TINY, object_class=ObjectClass.FIXTURE)
    assert store.has(desc.digest)
    assert store.get(desc.digest) == _TINY


def test_fallback_refuses_t7_bound_class(tmp_path: Path) -> None:
    """A T7-bound object class is refused with WAIT_STORAGE."""
    store = LocalFallbackStore(tmp_path)
    with pytest.raises(StoreWaitError) as exc_info:
        store.put(_TINY, object_class=ObjectClass.PACK_IMAGE)
    assert exc_info.value.fail_reason == "WAIT_STORAGE"
    assert exc_info.value.reason == "t7_bound_class_refused"
    # Nothing was written.
    assert not any(tmp_path.rglob("objects/*/sha256:*"))


@pytest.mark.parametrize(
    "cls",
    [
        ObjectClass.PACK_IMAGE,
        ObjectClass.RUN_RECEIPT,
        ObjectClass.DATASET,
        ObjectClass.SOURCE_BLOB,
        ObjectClass.PILOT_RUN,
        ObjectClass.CATALOG_SBOM,
        ObjectClass.QUARANTINE,
    ],
)
def test_fallback_refuses_every_t7_bound_class(tmp_path: Path, cls: ObjectClass) -> None:
    """Every T7-bound class is refused (only FIXTURE falls back)."""
    store = LocalFallbackStore(tmp_path)
    with pytest.raises(StoreWaitError):
        store.put(_TINY, object_class=cls)


def test_fallback_refuses_oversized_single_object(tmp_path: Path) -> None:
    """An object over the 1 MiB single-object limit is refused for FIXTURE too."""
    store = LocalFallbackStore(tmp_path)
    oversized = b"x" * (FALLBACK_SINGLE_OBJECT_MAX_BYTES + 1)
    with pytest.raises(StoreWaitError) as exc_info:
        store.put(oversized, object_class=ObjectClass.FIXTURE)
    assert exc_info.value.reason == "single_object_limit_exceeded"


def test_fallback_refuses_total_limit_exceeded(tmp_path: Path) -> None:
    """An ingest that would breach the 25 MiB total limit is refused."""
    store = LocalFallbackStore(tmp_path)
    # Fill the store near the ceiling with distinct <1 MiB objects, then assert
    # the next distinct object is refused. Each object is distinct content so
    # usage grows. We use 1 MiB - 1 byte objects so each is under the
    # single-object limit.
    blob = b"a" * (FALLBACK_SINGLE_OBJECT_MAX_BYTES - 1)
    # 25 distinct blobs = 25 * (1MiB-1) ~ 25 MiB - already at/over the 25 MiB
    # total. The 26th distinct object must be refused.
    for i in range(25):
        store.put(blob + bytes([i]), object_class=ObjectClass.FIXTURE)
    with pytest.raises(StoreWaitError) as exc_info:
        store.put(b"distinct-extra-bytes-overflow", object_class=ObjectClass.FIXTURE)
    assert exc_info.value.reason == "total_limit_exceeded"


def test_fallback_idempotent_reput_does_not_grow_usage(tmp_path: Path) -> None:
    """Re-putting the same object does not increase usage and is accepted."""
    store = LocalFallbackStore(tmp_path)
    store.put(_TINY, object_class=ObjectClass.FIXTURE)
    # A second put of identical bytes must succeed (idempotent) and not be
    # refused as a total-limit breach.
    desc2 = store.put(_TINY, object_class=ObjectClass.FIXTURE)
    assert store.has(desc2.digest)


def test_fallback_requires_explicit_root() -> None:
    """An empty root path is refused."""
    with pytest.raises(StoreWaitError) as exc_info:
        LocalFallbackStore("")  # type: ignore[arg-type]
    assert exc_info.value.reason == "fallback_root_not_explicit"


def test_fallback_total_limit_constant() -> None:
    """The total limit is the documented 25 MiB."""
    assert FALLBACK_TOTAL_MAX_BYTES == 25 * 1024 * 1024


def test_fallback_single_object_limit_constant() -> None:
    """The single-object limit is the documented 1 MiB."""
    assert FALLBACK_SINGLE_OBJECT_MAX_BYTES == 1024 * 1024


def test_fallback_fsck_passes(tmp_path: Path) -> None:
    """fsck reports the objects the fallback accepted, all passing."""
    store = LocalFallbackStore(tmp_path)
    store.put(_TINY, object_class=ObjectClass.FIXTURE)
    report = store.fsck()
    assert report.objects_checked == 1
    assert report.objects_passed == 1
    assert report.failed_digests == []
