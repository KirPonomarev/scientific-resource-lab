"""Unit tests for the CAS transaction engine (srl.cas.engine + LocalArtifactStore).

Pins the receipt-last transaction invariant:

1. A fresh ingest publishes exactly one object, one descriptor, one receipt; the
   receipt is the LAST artifact written; the bytes round-trip.
2. A re-ingest of identical bytes is a dedup: no new object, no new receipt,
   ``deduplicated=True``, and the existing receipt id is carried forward.
3. 1,000 deduplicating ingests of the same bytes produce exactly one object file
   and one receipt file (no overwrites, no growth).
4. The capacity policy hook is consulted before any byte is written; a refusal
   raises ``QuotaExceededError`` (``T7_QUOTA_EXCEEDED``) and writes nothing.
5. The descriptor and receipt records validate against their canonical schemas.
6. ``recover_partials`` reports stale partials and never auto-deletes them.
7. The plain ``put``/``fsck`` (WP-C20) path still works unchanged.

All tests are hermetic (``tmp_path``); the 1,000-ingest stress uses a 256-byte
payload so it finishes well within the unit CI budget.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from srl.cas import (
    LocalArtifactStore,
    QuotaExceededError,
    default_capacity_hook,
    recover_partials,
)
from srl.cas.descriptors import (
    INGEST_RECEIPT_SCHEMA_VERSION,
    OBJECT_DESCRIPTOR_SCHEMA_VERSION,
    canonical_receipt_id,
    validate_ingest_receipt,
    validate_object_descriptor,
)
from srl.cas.store import StoreError

_TS = "2026-07-28T12:00:00Z"
_PAYLOAD = b"cas-engine-deterministic-payload"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Fresh ingest: exactly one object, one descriptor, one receipt; receipt-last.
# ---------------------------------------------------------------------------


def test_fresh_ingest_publishes_one_of_each_record(tmp_path: Path) -> None:
    """A fresh ingest publishes one object, one descriptor, one receipt."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)

    assert out.deduplicated is False
    assert out.size_bytes == len(_PAYLOAD)
    assert out.digest == "sha256:" + _sha256_hex(_PAYLOAD)
    # Object, descriptor, receipt each present exactly once.
    objects = list((tmp_path / "objects").rglob("sha256:*"))
    descriptors = list((tmp_path / "descriptors").glob("*.json"))
    receipts = list((tmp_path / "receipts").glob("*.json"))
    assert len(objects) == 1
    assert len(descriptors) == 1
    assert len(receipts) == 1
    # The object filename is the full digest.
    assert objects[0].name == out.digest
    # The descriptor filename is <digest>.json.
    assert descriptors[0].name == f"{out.digest}.json"
    # The receipt filename is <receipt_id>.json.
    assert receipts[0].name == f"{out.receipt_id}.json"


def test_fresh_ingest_round_trips(tmp_path: Path) -> None:
    """The published object reads back to the source bytes."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    assert store.has(out.digest)
    assert store.get(out.digest) == _PAYLOAD


def test_receipt_is_last_artifact_written(tmp_path: Path) -> None:
    """The receipt's mtime is >= the descriptor's mtime (receipt-last order).

    The transaction writes the descriptor (step 9) before the receipt (step 10),
    so on a successful ingest the receipt file is the most recently written. We
    assert the ordering via mtimes, which the atomic-write helper sets via
    ``os.replace`` at the moment each record is committed.
    """
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    desc_path = tmp_path / "descriptors" / f"{out.digest}.json"
    rec_path = tmp_path / "receipts" / f"{out.receipt_id}.json"
    # Allow equal mtimes (filesystem second-resolution); receipt must not be
    # strictly older than the descriptor.
    assert rec_path.stat().st_mtime >= desc_path.stat().st_mtime


# ---------------------------------------------------------------------------
# Dedup: re-ingest of identical bytes writes nothing new.
# ---------------------------------------------------------------------------


def test_reingest_identical_bytes_dedups_no_new_object(tmp_path: Path) -> None:
    """A re-ingest of identical bytes is a dedup: no new object or receipt."""
    store = LocalArtifactStore(tmp_path)
    out1 = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    out2 = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)

    assert out2.deduplicated is True
    assert out2.digest == out1.digest
    # The dedup carries forward the original receipt id.
    assert out2.receipt_id == out1.receipt_id
    # Still exactly one of each record.
    assert len(list((tmp_path / "objects").rglob("sha256:*"))) == 1
    assert len(list((tmp_path / "receipts").glob("*.json"))) == 1
    assert len(list((tmp_path / "descriptors").glob("*.json"))) == 1


def test_dedup_does_not_overwrite_existing_object(tmp_path: Path) -> None:
    """A dedup never overwrites the published object (no byte write)."""
    store = LocalArtifactStore(tmp_path)
    out1 = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    obj_path = tmp_path / "objects" / out1.digest[7:9] / out1.digest
    mtime_before = obj_path.stat().st_mtime
    # Re-ingest many times.
    for _ in range(5):
        store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    mtime_after = obj_path.stat().st_mtime
    assert mtime_after == mtime_before  # the object file was not rewritten


# ---------------------------------------------------------------------------
# Stress: 1,000 deduplicating ingests -> exactly one object, no overwrites.
# ---------------------------------------------------------------------------


def test_thousand_deduplicating_ingests_produce_one_object(tmp_path: Path) -> None:
    """1,000 deduplicating ingests produce exactly one object and one receipt.

    Uses a 256-byte payload so the run stays well within the unit CI budget
    (~30s). Counts files at the end: exactly one object, one descriptor, one
    receipt, and zero partials.
    """
    store = LocalArtifactStore(tmp_path)
    payload = b"k" * 256
    out_first = store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
    for _ in range(999):
        out = store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
        assert out.deduplicated is True
        assert out.receipt_id == out_first.receipt_id

    objects = list((tmp_path / "objects").rglob("sha256:*"))
    descriptors = list((tmp_path / "descriptors").glob("*.json"))
    receipts = list((tmp_path / "receipts").glob("*.json"))
    partials = list((tmp_path / "incoming").glob("partial-*"))
    assert len(objects) == 1
    assert len(descriptors) == 1
    assert len(receipts) == 1
    assert len(partials) == 0


# ---------------------------------------------------------------------------
# Capacity policy: consulted before any byte is written.
# ---------------------------------------------------------------------------


def test_capacity_hook_refusal_writes_nothing(tmp_path: Path) -> None:
    """A capacity-hook refusal raises QuotaExceededError and writes nothing."""
    store = LocalArtifactStore(tmp_path)
    hook = default_capacity_hook(10)  # 10-byte ceiling
    with pytest.raises(QuotaExceededError) as exc_info:
        store.ingest_bytes(
            b"x" * 100,
            "application/octet-stream",
            capacity_hook=hook,
            created_utc=_TS,
        )
    assert exc_info.value.fail_reason == "T7_QUOTA_EXCEEDED"
    assert exc_info.value.size_bytes == 100
    # Nothing was written.
    assert list((tmp_path / "objects").rglob("sha256:*")) == []
    assert list((tmp_path / "descriptors").glob("*.json")) == []
    assert list((tmp_path / "receipts").glob("*.json")) == []


def test_capacity_hook_admits_when_within_ceiling(tmp_path: Path) -> None:
    """A capacity hook admits an ingest that fits under the ceiling."""
    store = LocalArtifactStore(tmp_path)
    hook = default_capacity_hook(1024)  # 1 KiB ceiling
    out = store.ingest_bytes(
        b"fits",
        "application/octet-stream",
        capacity_hook=hook,
        created_utc=_TS,
    )
    assert out.deduplicated is False
    assert store.has(out.digest)


def test_custom_capacity_hook_invoked_before_write(tmp_path: Path) -> None:
    """A custom hook receives (used_bytes, size_bytes) and can refuse."""
    store = LocalArtifactStore(tmp_path)
    seen: list[tuple[int, int]] = []

    def hook(used: int, size: int) -> None:
        seen.append((used, size))

    store.ingest_bytes(
        b"custom-hook",
        "application/octet-stream",
        capacity_hook=hook,
        used_bytes=42,
        created_utc=_TS,
    )
    assert seen == [(42, len(b"custom-hook"))]


# ---------------------------------------------------------------------------
# Descriptor and receipt records validate against their canonical schemas.
# ---------------------------------------------------------------------------


def test_descriptor_record_is_valid_canonical(tmp_path: Path) -> None:
    """The on-disk descriptor validates as ObjectDescriptor/v1."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    desc_path = tmp_path / "descriptors" / f"{out.digest}.json"
    parsed = json.loads(desc_path.read_text(encoding="utf-8"))
    validated = validate_object_descriptor(parsed)
    assert validated["schema_version"] == OBJECT_DESCRIPTOR_SCHEMA_VERSION
    assert validated["digest"] == out.digest
    assert validated["size_bytes"] == len(_PAYLOAD)
    assert validated["media_type"] == "application/octet-stream"
    assert validated["ingest_receipt_id"] == out.receipt_id


def test_receipt_record_is_valid_canonical(tmp_path: Path) -> None:
    """The on-disk receipt validates as IngestReceipt/v1."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    rec_path = tmp_path / "receipts" / f"{out.receipt_id}.json"
    parsed = json.loads(rec_path.read_text(encoding="utf-8"))
    validated = validate_ingest_receipt(parsed)
    assert validated["schema_version"] == INGEST_RECEIPT_SCHEMA_VERSION
    assert validated["receipt_id"] == out.receipt_id
    assert validated["digest"] == out.digest
    assert validated["source_hash_verified"] is True
    assert validated["readback_hash_verified"] is True
    assert validated["fsynced"] is True


def test_receipt_id_is_content_addressed(tmp_path: Path) -> None:
    """The receipt_id is the canonical hash of the receipt minus its own id."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    rec_path = tmp_path / "receipts" / f"{out.receipt_id}.json"
    parsed = json.loads(rec_path.read_text(encoding="utf-8"))
    recomputed = canonical_receipt_id(parsed)
    assert recomputed == out.receipt_id
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", out.receipt_id)


def test_descriptor_references_receipt_id(tmp_path: Path) -> None:
    """The descriptor's ingest_receipt_id equals the receipt's id."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    desc = store.read_descriptor(out.digest)
    assert desc is not None
    assert desc["ingest_receipt_id"] == out.receipt_id


# ---------------------------------------------------------------------------
# recover_partials: reports, never auto-deletes.
# ---------------------------------------------------------------------------


def test_recover_partials_empty_on_clean_store(tmp_path: Path) -> None:
    """recover_partials returns nothing on a clean store."""
    store = LocalArtifactStore(tmp_path)
    store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    assert store.recover_partials() == []


def test_recover_partials_reports_planted_partial(tmp_path: Path) -> None:
    """A planted partial is reported (not auto-deleted) by recover_partials."""
    # Create the store subtree so incoming/ exists, then plant a partial.
    LocalArtifactStore(tmp_path)
    hex_digest = _sha256_hex(b"unpublished")
    partial = tmp_path / "incoming" / f"partial-{hex_digest}.tmp"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"unpublished-bytes")
    entries = recover_partials(tmp_path)
    assert len(entries) == 1
    assert entries[0].digest_hint == "sha256:" + hex_digest
    assert entries[0].published is False
    assert entries[0].size_bytes == len(b"unpublished-bytes")
    # The partial was NOT deleted.
    assert partial.is_file()


def test_recover_partials_classifies_published_partial(tmp_path: Path) -> None:
    """A leftover partial whose object exists is classified published=True."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    hex_digest = out.digest.removeprefix("sha256:")
    # Plant a partial with the SAME digest as the published object.
    partial = tmp_path / "incoming" / f"partial-{hex_digest}.tmp"
    partial.write_bytes(_PAYLOAD)
    entries = store.recover_partials()
    matched = [e for e in entries if e.digest_hint == out.digest]
    assert len(matched) == 1
    assert matched[0].published is True


# ---------------------------------------------------------------------------
# Backward compatibility: plain put/fsck still work.
# ---------------------------------------------------------------------------


def test_plain_put_still_works(tmp_path: Path) -> None:
    """The WP-C20 plain put path still works alongside the engine."""
    store = LocalArtifactStore(tmp_path)
    desc = store.put(_PAYLOAD)
    assert store.has(desc.digest)
    assert store.get(desc.digest) == _PAYLOAD
    report = store.fsck()
    assert report.objects_checked == 1
    assert report.objects_passed == 1


def test_malformed_media_type_rejected(tmp_path: Path) -> None:
    """A malformed media_type is rejected before any write."""
    store = LocalArtifactStore(tmp_path)
    with pytest.raises(StoreError):
        store.ingest_bytes(_PAYLOAD, "not-a-media-type", created_utc=_TS)
    assert list((tmp_path / "objects").rglob("sha256:*")) == []


def test_empty_payload_ingests(tmp_path: Path) -> None:
    """An empty payload ingests and dedups like any other content."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(b"", "application/octet-stream", created_utc=_TS)
    assert out.size_bytes == 0
    assert store.get(out.digest) == b""
    out2 = store.ingest_bytes(b"", "application/octet-stream", created_utc=_TS)
    assert out2.deduplicated is True
