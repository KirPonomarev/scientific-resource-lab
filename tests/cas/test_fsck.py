"""Unit tests for the rich CAS fsck sweep (srl.cas.fsck.run_fsck).

Pins the five issue classes the sweep detects:

- **hash mismatch (corruption)** — flip a byte in a published object; the sweep
  reports ``ISSUE_HASH_MISMATCH`` and ``ok=False``.
- **missing descriptor** — delete an object's descriptor; the sweep reports
  ``ISSUE_MISSING_DESCRIPTOR``.
- **orphan descriptor** — delete the object but leave its descriptor; the sweep
  reports ``ISSUE_ORPHAN_DESCRIPTOR``.
- **size drift** — edit the descriptor's ``size_bytes`` to disagree with the
  object; the sweep reports ``ISSUE_SIZE_DRIFT``.
- **bad receipt** — tamper a receipt so its id no longer matches its content; the
  sweep reports ``ISSUE_BAD_RECEIPT``.

Plus the clean case (a freshly-ingested store sweeps to ``ok=True`` with zero
issues), and the report's canonical-JSON render.
"""

from __future__ import annotations

import json
from pathlib import Path

from srl.cas import (
    ISSUE_BAD_RECEIPT,
    ISSUE_HASH_MISMATCH,
    ISSUE_MISSING_DESCRIPTOR,
    ISSUE_ORPHAN_DESCRIPTOR,
    ISSUE_SIZE_DRIFT,
    LocalArtifactStore,
)
from srl.cas.fsck import CAS_FSCK_REPORT_SCHEMA_VERSION, CasFsckReport
from srl.contracts.canonical import dumps, loads

_TS = "2026-07-28T12:00:00Z"
_PAYLOAD = b"fsck-sweep-deterministic-payload"


def _ingest_one(store: LocalArtifactStore) -> str:
    """Ingest one object and return its digest."""
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    return out.digest


def _issue_kinds(report: CasFsckReport) -> set[str]:
    return {issue.kind for issue in report.issues}


def test_clean_store_sweeps_ok(tmp_path: Path) -> None:
    """A freshly-ingested store sweeps to ok=True with zero issues."""
    store = LocalArtifactStore(tmp_path)
    digest = _ingest_one(store)
    report = store.fsck_full()
    assert report.ok is True
    assert report.objects_checked == 1
    assert report.objects_passed == 1
    assert report.descriptors_checked == 1
    assert report.receipts_checked == 1
    assert report.issues == []
    assert report.schema_version == CAS_FSCK_REPORT_SCHEMA_VERSION
    # The report's redacted token never leaks the raw path.
    assert report.store_root_redacted.startswith("redacted:")
    assert str(tmp_path) not in report.store_root_redacted
    del digest  # fixture helper return not asserted here


# ---------------------------------------------------------------------------
# hash mismatch (corruption)
# ---------------------------------------------------------------------------


def test_detects_hash_mismatch_corruption(tmp_path: Path) -> None:
    """A flipped byte in a published object is detected as hash_mismatch."""
    store = LocalArtifactStore(tmp_path)
    digest = _ingest_one(store)
    obj_path = tmp_path / "objects" / digest[7:9] / digest
    raw = bytearray(obj_path.read_bytes())
    raw[0] ^= 0xFF
    obj_path.write_bytes(bytes(raw))

    report = store.fsck_full()
    assert report.ok is False
    assert ISSUE_HASH_MISMATCH in _issue_kinds(report)
    assert report.objects_passed == 0
    hm = [i for i in report.issues if i.kind == ISSUE_HASH_MISMATCH]
    assert hm[0].digest == digest


# ---------------------------------------------------------------------------
# missing descriptor
# ---------------------------------------------------------------------------


def test_detects_missing_descriptor(tmp_path: Path) -> None:
    """An object without a descriptor is detected as missing_descriptor."""
    store = LocalArtifactStore(tmp_path)
    digest = _ingest_one(store)
    desc_path = tmp_path / "descriptors" / f"{digest}.json"
    desc_path.unlink()

    report = store.fsck_full()
    assert report.ok is False
    assert ISSUE_MISSING_DESCRIPTOR in _issue_kinds(report)
    md = [i for i in report.issues if i.kind == ISSUE_MISSING_DESCRIPTOR]
    assert md[0].digest == digest


# ---------------------------------------------------------------------------
# orphan descriptor
# ---------------------------------------------------------------------------


def test_detects_orphan_descriptor(tmp_path: Path) -> None:
    """A descriptor without an object is detected as orphan_descriptor."""
    store = LocalArtifactStore(tmp_path)
    digest = _ingest_one(store)
    obj_path = tmp_path / "objects" / digest[7:9] / digest
    obj_path.unlink()

    report = store.fsck_full()
    assert report.ok is False
    assert ISSUE_ORPHAN_DESCRIPTOR in _issue_kinds(report)
    od = [i for i in report.issues if i.kind == ISSUE_ORPHAN_DESCRIPTOR]
    assert od[0].digest == digest


# ---------------------------------------------------------------------------
# size drift
# ---------------------------------------------------------------------------


def test_detects_size_drift(tmp_path: Path) -> None:
    """A descriptor whose size_bytes disagrees with the object is detected."""
    store = LocalArtifactStore(tmp_path)
    digest = _ingest_one(store)
    desc_path = tmp_path / "descriptors" / f"{digest}.json"
    parsed = json.loads(desc_path.read_text(encoding="utf-8"))
    parsed["size_bytes"] = len(_PAYLOAD) + 999  # drift
    desc_path.write_text(json.dumps(parsed), encoding="utf-8")

    report = store.fsck_full()
    assert report.ok is False
    assert ISSUE_SIZE_DRIFT in _issue_kinds(report)


# ---------------------------------------------------------------------------
# bad receipt (tampered id / absent receipt)
# ---------------------------------------------------------------------------


def test_detects_bad_receipt_tampered_id(tmp_path: Path) -> None:
    """A receipt whose id no longer matches its content is detected as bad_receipt."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    rec_path = tmp_path / "receipts" / f"{out.receipt_id}.json"
    parsed = json.loads(rec_path.read_text(encoding="utf-8"))
    # Tamper with a field so the content hash no longer matches the stored id.
    parsed["size_bytes"] = len(_PAYLOAD) + 1
    rec_path.write_text(json.dumps(parsed), encoding="utf-8")

    report = store.fsck_full()
    assert report.ok is False
    assert ISSUE_BAD_RECEIPT in _issue_kinds(report)


def test_detects_descriptor_references_absent_receipt(tmp_path: Path) -> None:
    """A descriptor referencing an absent receipt is detected as bad_receipt."""
    store = LocalArtifactStore(tmp_path)
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    # Delete the receipt but keep the descriptor (which references it).
    rec_path = tmp_path / "receipts" / f"{out.receipt_id}.json"
    rec_path.unlink()

    report = store.fsck_full()
    assert report.ok is False
    assert ISSUE_BAD_RECEIPT in _issue_kinds(report)


# ---------------------------------------------------------------------------
# Report rendering.
# ---------------------------------------------------------------------------


def test_report_to_dict_is_canonical_friendly(tmp_path: Path) -> None:
    """The report's to_dict() renders a stable, canonical-friendly dict."""
    store = LocalArtifactStore(tmp_path)
    _ingest_one(store)
    report = store.fsck_full()
    rendered = report.to_dict()
    assert rendered["schema_version"] == CAS_FSCK_REPORT_SCHEMA_VERSION
    assert rendered["ok"] is True
    assert rendered["issues"] == []
    assert rendered["objects_checked"] == 1
    # The rendered dict round-trips through canonical JSON.
    parsed = loads(dumps(rendered))
    assert parsed["schema_version"] == CAS_FSCK_REPORT_SCHEMA_VERSION


def test_report_no_raw_path_in_issues(tmp_path: Path) -> None:
    """No issue detail or path_redacted leaks the raw tmp_path."""
    store = LocalArtifactStore(tmp_path)
    digest = _ingest_one(store)
    obj_path = tmp_path / "objects" / digest[7:9] / digest
    raw = bytearray(obj_path.read_bytes())
    raw[0] ^= 0xFF
    obj_path.write_bytes(bytes(raw))

    report = store.fsck_full()
    for issue in report.issues:
        assert str(tmp_path) not in issue.detail
        assert str(tmp_path) not in issue.path_redacted
        assert issue.path_redacted.startswith("redacted:")


def test_run_fsck_on_empty_store(tmp_path: Path) -> None:
    """run_fsck on a store with no objects returns ok=True with zero counts."""
    store = LocalArtifactStore(tmp_path)
    report = store.fsck_full()
    assert report.ok is True
    assert report.objects_checked == 0
    assert report.descriptors_checked == 0
    assert report.receipts_checked == 0
    assert report.issues == []


def test_fsck_full_and_plain_fsck_agree_on_clean_store(tmp_path: Path) -> None:
    """The rich sweep and the plain fsck agree on a clean store's pass count."""
    store = LocalArtifactStore(tmp_path)
    _ingest_one(store)
    plain = store.fsck()
    full = store.fsck_full()
    assert plain.objects_passed == full.objects_passed == 1
    assert plain.failed_digests == []
    assert full.ok is True
