"""Crash-safety tests for the CAS transaction engine.

Pins the receipt-last invariant under failure injection: a crash at any
transaction boundary leaves the store in either the old valid state (no object,
no descriptor, no receipt) or the new valid state (object + descriptor +
receipt). A partial tmp file may remain in ``incoming/`` but is **never visible
as an object**.

The crash matrix (parametrized) injects failures at four publish boundaries:

- after tmp write (the staging rename to ``partial-<digest>.tmp`` fails);
- after fsync (the read-back fails);
- after replace (the publish rename to ``objects/<shard>/<digest>`` fails);
- after descriptor (the receipt write fails).

Each yields old-or-new valid state, never a partial visible object.

Additionally:

- read-back corruption injection (the read-back returns wrong bytes) -> the
  ingest fails with ``CasIntegrityError`` and publishes nothing;
- an interrupted ingest (``os.replace`` patched to raise) publishes no final
  receipt, no object, no descriptor, and the partial is reported by
  ``recover_partials``.

All tests are hermetic (``tmp_path``) and use ``unittest.mock.patch`` for the
failure injection.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from srl.cas import CasIntegrityError, LocalArtifactStore

_TS = "2026-07-28T12:00:00Z"
_PAYLOAD = b"crash-safety-deterministic-payload"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_count(root: Path) -> int:
    return len(list((root / "objects").rglob("sha256:*")))


def _receipt_count(root: Path) -> int:
    return len(list((root / "receipts").glob("*.json")))


def _descriptor_count(root: Path) -> int:
    return len(list((root / "descriptors").glob("*.json")))


# ---------------------------------------------------------------------------
# Crash matrix: failure injection at every publish boundary.
# ---------------------------------------------------------------------------


def _make_boundary_injector(boundary: str, real_replace: object) -> tuple[object, bool]:
    """Build the (replace_side_effect, needs_readback_injection) pair for ``boundary``.

    The injector raises ``OSError`` at the boundary-specific ``os.replace`` call
    number (1 = staging rename, 2 = publish, 3 = descriptor write). The
    ``after_fsync`` boundary uses read-back corruption instead (no replace
    raise), so ``needs_readback_injection`` is True for it.
    """
    state = {"replaces": 0}

    def replace_boom(src: Path | str, dst: Path | str) -> None:
        state["replaces"] += 1
        if boundary == "after_tmp_write" and state["replaces"] == 1:
            raise OSError("injected: staging rename failed")
        if boundary == "after_replace" and state["replaces"] == 2:
            raise OSError("injected: publish rename failed")
        if boundary == "after_descriptor" and state["replaces"] == 3:
            raise OSError("injected: descriptor write failed")
        real_replace(src, dst)  # type: ignore[operator]

    return replace_boom, boundary == "after_fsync"


def _assert_boundary_invariant(tmp_path: Path, boundary: str) -> None:
    """Assert the receipt-last old-or-new invariant for ``boundary``.

    On any failure the receipt is never written (it is the commit marker, last
    step). Per-boundary, the object/descriptor presence reflects how far the
    transaction got. No partial is ever visible as an object.
    """
    n_obj = _object_count(tmp_path)
    n_desc = _descriptor_count(tmp_path)
    n_rec = _receipt_count(tmp_path)
    assert n_rec == 0, f"boundary={boundary} wrote a receipt on failure"
    if boundary == "after_descriptor":
        # Object published (step 7), dirs fsynced (step 8), descriptor write
        # (step 9) failed -> object present, no descriptor, no receipt.
        assert n_obj == 1, f"boundary={boundary} should have published the object"
        assert n_desc == 0, f"boundary={boundary} should not have a descriptor"
    else:
        # after_tmp_write / after_fsync / after_replace raise before the publish.
        assert n_obj == 0, f"boundary={boundary} published an object on failure"
        assert n_desc == 0, f"boundary={boundary} wrote a descriptor on failure"
    # No partial is ever visible as an object: every entry under objects/ (if
    # any) is a full sha256: digest; partials live only under incoming/.
    objects_dir = tmp_path / "objects"
    if objects_dir.is_dir():
        for shard in objects_dir.iterdir():
            if shard.is_dir():
                for entry in shard.iterdir():
                    assert entry.name.startswith("sha256:"), (
                        f"boundary={boundary}: non-object visible: {entry.name}"
                    )


@pytest.mark.parametrize(
    "boundary",
    ["after_tmp_write", "after_fsync", "after_replace", "after_descriptor"],
)
def test_crash_at_publish_boundary_leaves_valid_state(tmp_path: Path, boundary: str) -> None:
    """A crash at any publish boundary leaves old-or-new valid state.

    The store ends with either zero records (old state) or the new state minus
    the receipt (commit marker); it never ends with a partial visible as an
    object, and the receipt is never written without the object preceding it.
    """
    store = LocalArtifactStore(tmp_path)
    real_replace = os.replace
    replace_boom, needs_readback = _make_boundary_injector(boundary, real_replace)
    real_read_bytes = Path.read_bytes

    def readback_boom(self: Path) -> bytes:
        data = real_read_bytes(self)
        if needs_readback and "incoming" in str(self) and data:
            # Corrupt only the read-back of the partial; triggers the mismatch
            # path AFTER the fsync succeeded.
            return data[:-1] + bytes([data[-1] ^ 0xFF])
        return data

    patches = [patch("srl.cas.engine.os.replace", side_effect=replace_boom)]
    if needs_readback:
        patches.append(patch("srl.cas.engine.Path.read_bytes", readback_boom))

    raised: bool = False
    for p in patches:
        p.start()
    try:
        try:
            store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
        except (OSError, CasIntegrityError):
            raised = True
    finally:
        for p in patches:
            p.stop()

    assert raised, f"boundary={boundary} did not raise"
    _assert_boundary_invariant(tmp_path, boundary)


def test_after_fsync_readback_mismatch_deletes_partial(tmp_path: Path) -> None:
    """A read-back mismatch after fsync deletes the partial (no corrupt state)."""
    store = LocalArtifactStore(tmp_path)
    real_read_bytes = Path.read_bytes

    def bad_readback(self: Path) -> bytes:
        data = real_read_bytes(self)
        if "incoming" in str(self) and data:
            return data + b"X"  # different bytes -> different hash
        return data

    with patch("srl.cas.engine.Path.read_bytes", bad_readback):
        with pytest.raises(CasIntegrityError) as exc_info:
            store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    assert exc_info.value.fail_reason == "CAS_INTEGRITY_FAILURE"
    # No object published, and no partial left behind (the mismatch path deletes it).
    assert _object_count(tmp_path) == 0
    assert _receipt_count(tmp_path) == 0
    partials = list((tmp_path / "incoming").glob("partial-*"))
    assert partials == [], "read-back mismatch should delete the partial"


# ---------------------------------------------------------------------------
# Interrupted ingest: os.replace patched to raise -> no receipt, partial reported.
# ---------------------------------------------------------------------------


def test_interrupted_ingest_publishes_no_receipt(tmp_path: Path) -> None:
    """An interrupted ingest (publish rename fails) publishes no final receipt.

    The store ends with no object, no descriptor, no receipt. A partial remains
    in ``incoming/`` and is reported by ``recover_partials`` (never auto-deleted).
    """
    store = LocalArtifactStore(tmp_path)
    real_replace = os.replace
    state = {"replaces": 0}

    def boom(src: Path | str, dst: Path | str) -> None:
        state["replaces"] += 1
        # Fail the publish rename (2nd replace); let the staging rename succeed.
        if state["replaces"] == 2:
            raise OSError("simulated crash at publish")
        real_replace(src, dst)

    with patch("srl.cas.engine.os.replace", side_effect=boom):
        with pytest.raises(OSError):
            store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)

    # No object, no descriptor, no receipt.
    assert _object_count(tmp_path) == 0
    assert _descriptor_count(tmp_path) == 0
    assert _receipt_count(tmp_path) == 0
    # The partial is present and reported.
    entries = store.recover_partials()
    assert len(entries) == 1
    hex_digest = _sha256_hex(_PAYLOAD)
    assert entries[0].digest_hint == "sha256:" + hex_digest
    assert entries[0].published is False
    # The partial is NOT auto-deleted by recover_partials.
    assert (tmp_path / "incoming" / f"partial-{hex_digest}.tmp").is_file()


# ---------------------------------------------------------------------------
# Read-back corruption injection: patch the read-back to return wrong bytes.
# ---------------------------------------------------------------------------


def test_readback_corruption_injection_detected(tmp_path: Path) -> None:
    """If the read-back returns wrong bytes, the ingest fails and publishes nothing."""
    store = LocalArtifactStore(tmp_path)
    real_read_bytes = Path.read_bytes

    def wrong_readback(self: Path) -> bytes:
        data = real_read_bytes(self)
        if "incoming" in str(self):
            # Return bytes that hash differently from the source.
            return b"completely-wrong-readback"
        return data

    with patch("srl.cas.engine.Path.read_bytes", wrong_readback):
        with pytest.raises(CasIntegrityError):
            store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    assert _object_count(tmp_path) == 0
    assert _receipt_count(tmp_path) == 0


# ---------------------------------------------------------------------------
# Successful ingest after a prior interrupted attempt resumes cleanly.
# ---------------------------------------------------------------------------


def test_resume_after_interrupted_ingest(tmp_path: Path) -> None:
    """After an interrupted ingest, a fresh ingest of the same bytes succeeds.

    The leftover partial does not block the retry: the engine re-ingests the
    bytes, publishes the object, and writes the receipt. The old partial may
    remain (the engine does not auto-delete it), but the new publish is clean.
    """
    store = LocalArtifactStore(tmp_path)
    real_replace = os.replace
    state = {"replaces": 0}

    def boom_once(src: Path | str, dst: Path | str) -> None:
        state["replaces"] += 1
        if state["replaces"] == 2:
            raise OSError("one-shot crash at publish")
        real_replace(src, dst)

    with patch("srl.cas.engine.os.replace", side_effect=boom_once):
        with pytest.raises(OSError):
            store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    # Retry without the injection.
    out = store.ingest_bytes(_PAYLOAD, "application/octet-stream", created_utc=_TS)
    assert out.deduplicated is False
    assert store.has(out.digest)
    assert store.get(out.digest) == _PAYLOAD
    assert _receipt_count(tmp_path) == 1
