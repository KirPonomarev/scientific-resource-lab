#!/usr/bin/env python3
"""WP-C21 acceptance gate for the CAS transaction engine.

Runs the six WP-C21 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp21``.

The checks
----------
C21-01 no overwrite
    Two ingests of the same bytes produce a single object file and a
    deduplicated receipt (``deduplicated=True``, same ``receipt_id``). The
    engine never overwrites a published object; a re-ingest of identical
    content is a no-op publish.

C21-02 typed corruption
    Flipping one byte in a published object (out-of-band) is detected by
    :func:`~srl.cas.fsck.run_fsck` as ``ISSUE_HASH_MISMATCH``, and
    :meth:`~srl.cas.store.LocalArtifactStore.get` raises
    :class:`~srl.cas.store.StoreIntegrityError` with
    ``fail_reason='CAS_INTEGRITY_FAILURE'``.

C21-03 interrupted ingest publishes no final receipt
    An ingest interrupted at the publish boundary (``os.replace`` monkeypatched
    to raise) publishes no object, no descriptor, and no receipt. A partial
    remains in ``incoming/`` and is reported by
    :func:`~srl.cas.engine.recover_partials` (the engine never auto-deletes
    partials).

C21-04 1,000 repeated deduplicating ingests produce one object file
    1,000 ingests of a 256-byte payload produce exactly one object file, one
    descriptor, and one receipt (zero overwrites). The file counts are
    asserted directly.

C21-05 crash at every publish boundary
    Failure injection at ALL SEVEN durability boundaries of the transaction
    (tmp write, tmp fsync, read-back verify, os.replace publish, directory
    fsync, descriptor write, receipt write) each leaves the store in old-or-new
    valid state: no receipt is ever written on failure (the receipt is the
    commit marker, written last), and no partial is ever visible as an object.
    The seven boundaries are the explicit, single source of truth shared by
    ``docs/architecture/cas-engine.md``, the gate, and the unit tests.

C21-06 read-back corruption injection detected
    Patching the first read-back to return bytes that hash differently from the
    source makes the ingest fail with
    :class:`~srl.cas.engine.CasIntegrityError`
    (``CAS_INTEGRITY_FAILURE``) and publish nothing.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as ``python3 scripts/checks/wp21-gate.py``
without a prior ``uv run``, and also works under ``uv run`` (idempotent path
insertion). It is hermetic: it uses temporary directories and ``unittest.mock``
for failure injection; it never touches a real disk.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp21-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.cas import (  # noqa: E402  (path setup must precede import)
    ISSUE_HASH_MISMATCH,
    CasIntegrityError,
    LocalArtifactStore,
    StoreIntegrityError,
    recover_partials,
)
from srl.contracts import dumps  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-C21"

# Pinned timestamp so the gate is reproducible (no wall-clock dependence).
_TS: Final[str] = "2026-07-28T12:00:00Z"

# The fail reason surfaced in the gate receipt, mirrored from the registry.
CAS_INTEGRITY_FAILURE_REF: Final[str] = "CAS_INTEGRITY_FAILURE"

# ---------------------------------------------------------------------------
# C21-05 crash matrix: the seven durability boundaries of the transaction.
# ---------------------------------------------------------------------------
# These seven boundaries are the single source of truth shared by this gate,
# ``docs/architecture/cas-engine.md`` (## Crash matrix), and
# ``tests/cas/test_engine_crash.py``. Each maps an injectable failure point to
# the old-or-new valid state the store must be left in. The boundaries cover
# every durability step of the receipt-last transaction documented in
# ``srl/cas/descriptors.py`` (the 7-step condensed list) and ``srl/cas/engine.py``
# (the 10-step expanded list): they are the same steps, grouped by injectable
# boundary.
#
#   boundary          | injection                         | object | desc | receipt
#   ------------------+-----------------------------------+--------+------+--------
#   tmp_write         | os.replace #1 (staging) raises    | absent |  -   | absent
#   tmp_fsync         | os.fsync #1 (partial) raises      | absent |  -   | absent
#   readback_verify   | read-back returns wrong bytes     | absent |  -   | absent
#   replace_publish   | os.replace #2 (publish) raises    | absent |  -   | absent
#   dir_fsync         | _fsync_dir (post-publish) raises  | present| absent| absent
#   descriptor_write  | os.replace #3 (descriptor) raises | present| absent| absent
#   receipt_write     | os.replace #4 (receipt) raises    | present|present| absent
#
# os.replace call indices within a single ingest transaction (1-based):
#   1 = staging rename (incoming/.ingest-* -> partial-*)
#   2 = publish rename (partial-* -> objects/<shard>/<digest>)
#   3 = atomic descriptor write (descriptors/<digest>.json)
#   4 = atomic receipt write (receipts/<receipt_id>.json)
# os.fsync call index within the transaction (1-based):
#   1 = partial file fsync (step 5); subsequent fsyncs are descriptor/receipt
#       file fsyncs and best-effort directory fsyncs (not injected here).
REPLACE_STAGING: Final[int] = 1
REPLACE_PUBLISH: Final[int] = 2
REPLACE_DESCRIPTOR: Final[int] = 3
REPLACE_RECEIPT: Final[int] = 4
FSYNC_PARTIAL: Final[int] = 1

# The canonical, ordered list of the seven crash-matrix boundaries. Order
# matches the transaction step order so the gate receipt reads top-to-bottom.
CRASH_BOUNDARIES: Final[tuple[str, ...]] = (
    "tmp_write",
    "tmp_fsync",
    "readback_verify",
    "replace_publish",
    "dir_fsync",
    "descriptor_write",
    "receipt_write",
)


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _object_count(root: Path) -> int:
    """Count published object files under <root>/objects/."""
    return len(list((root / "objects").rglob("sha256:*")))


def _receipt_count(root: Path) -> int:
    """Count receipt files under <root>/receipts/."""
    return len(list((root / "receipts").glob("*.json")))


def _descriptor_count(root: Path) -> int:
    """Count descriptor files under <root>/descriptors/."""
    return len(list((root / "descriptors").glob("*.json")))


# ---------------------------------------------------------------------------
# C21-01 no overwrite.
# ---------------------------------------------------------------------------


def _check_c21_01() -> dict[str, Any]:
    """C21-01: two ingests of the same bytes produce one object and a dedup receipt."""
    cases: list[dict[str, Any]] = []
    payload = b"c21-01-no-overwrite"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root)
        out1 = store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
        out2 = store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
        n_obj = _object_count(root)
        n_rec = _receipt_count(root)
        cases.append(
            {
                "case": "two-ingests-one-object",
                "first_digest": out1.digest,
                "second_deduplicated": out2.deduplicated,
                "same_receipt_id": out1.receipt_id == out2.receipt_id,
                "object_files": n_obj,
                "receipt_files": n_rec,
            }
        )

    failures = []
    if n_obj != 1:
        failures.append(f"expected exactly 1 object file, got {n_obj}")
    if n_rec != 1:
        failures.append(f"expected exactly 1 receipt file, got {n_rec}")
    if not out2.deduplicated:
        failures.append("second ingest was not marked deduplicated")
    if out1.receipt_id != out2.receipt_id:
        failures.append("dedup did not carry forward the original receipt_id")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "two ingests of identical bytes produced exactly one object file and "
            "one receipt; the second ingest was a dedup (deduplicated=true, same "
            "receipt_id); no overwrite"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C21-02 typed corruption.
# ---------------------------------------------------------------------------


def _check_c21_02() -> dict[str, Any]:
    """C21-02: a flipped byte in a published object is detected by fsck + get."""
    cases: list[dict[str, Any]] = []
    payload = b"c21-02-typed-corruption"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root)
        out = store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
        # Flip one byte out-of-band in the published object.
        obj_path = root / "objects" / out.digest[7:9] / out.digest
        raw = bytearray(obj_path.read_bytes())
        raw[0] ^= 0xFF
        obj_path.write_bytes(bytes(raw))

        report = store.fsck_full()
        kinds = sorted({i.kind for i in report.issues})
        fsck_ok = report.ok

        get_raised = False
        get_reason = ""
        try:
            store.get(out.digest)
        except StoreIntegrityError as exc:
            get_raised = True
            get_reason = exc.fail_reason
        cases.append(
            {
                "case": "corruption-detected",
                "fsck_ok": fsck_ok,
                "fsck_issue_kinds": kinds,
                "get_raised": get_raised,
                "get_fail_reason": get_reason,
            }
        )

    failures = []
    if fsck_ok:
        failures.append("fsck reported ok=True after corruption")
    if ISSUE_HASH_MISMATCH not in kinds:
        failures.append(f"fsck did not report {ISSUE_HASH_MISMATCH!r}")
    if not get_raised or get_reason != CAS_INTEGRITY_FAILURE_REF:
        failures.append("get did not raise CAS_INTEGRITY_FAILURE on the corrupted object")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "flipping one byte in a published object was detected by fsck "
            f"(issue kind {ISSUE_HASH_MISMATCH!r}) and by get "
            f"(raised {CAS_INTEGRITY_FAILURE_REF!r})"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C21-03 interrupted ingest publishes no final receipt.
# ---------------------------------------------------------------------------


def _publish_boom(real_replace: Any) -> Any:
    """Build an os.replace side effect that fails at the publish rename.

    The staging rename (1st replace) succeeds; the publish rename (2nd replace)
    raises OSError, simulating a crash at the publish boundary.
    """
    state = {"replaces": 0}

    def boom(src: Path | str, dst: Path | str) -> None:
        state["replaces"] += 1
        if state["replaces"] == REPLACE_PUBLISH:
            raise OSError("simulated crash at publish")
        real_replace(src, dst)

    return boom


def _check_c21_03() -> dict[str, Any]:
    """C21-03: an interrupted ingest publishes no receipt; partial is reported."""
    cases: list[dict[str, Any]] = []
    payload = b"c21-03-interrupted"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root)
        boom = _publish_boom(os.replace)
        raised = False
        with patch("srl.cas.engine.os.replace", side_effect=boom):
            try:
                store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
            except OSError:
                raised = True

        n_obj = _object_count(root)
        n_desc = _descriptor_count(root)
        n_rec = _receipt_count(root)
        parts = recover_partials(root)
        cases.append(
            {
                "case": "interrupted-no-receipt",
                "raised": raised,
                "object_files": n_obj,
                "descriptor_files": n_desc,
                "receipt_files": n_rec,
                "partials_reported": len(parts),
                "partial_published": parts[0].published if parts else None,
            }
        )

    failures = []
    if not raised:
        failures.append("interrupted ingest did not raise")
    if n_obj != 0:
        failures.append(f"interrupted ingest published an object ({n_obj})")
    if n_desc != 0:
        failures.append(f"interrupted ingest wrote a descriptor ({n_desc})")
    if n_rec != 0:
        failures.append(f"interrupted ingest wrote a receipt ({n_rec})")
    if len(parts) != 1:
        failures.append(f"expected 1 partial reported, got {len(parts)}")
    elif parts[0].published:
        failures.append("the partial was mis-classified as published")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "an ingest interrupted at publish raised, published no object, no "
            "descriptor, and no receipt; the leftover partial was reported by "
            "recover_partials (never auto-deleted)"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C21-04 1,000 repeated deduplicating ingests produce one object file.
# ---------------------------------------------------------------------------


def _check_c21_04() -> dict[str, Any]:
    """C21-04: 1,000 deduplicating ingests produce exactly one object, zero overwrites."""
    cases: list[dict[str, Any]] = []
    payload = b"k" * 256  # 256-byte payload; stays well within the CI budget.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root)
        out_first = store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
        all_dedup = True
        for _ in range(999):
            out = store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
            if not out.deduplicated or out.receipt_id != out_first.receipt_id:
                all_dedup = False
        n_obj = _object_count(root)
        n_desc = _descriptor_count(root)
        n_rec = _receipt_count(root)
        cases.append(
            {
                "case": "thousand-ingests-one-object",
                "ingests": 1000,
                "all_deduplicated": all_dedup,
                "object_files": n_obj,
                "descriptor_files": n_desc,
                "receipt_files": n_rec,
            }
        )

    failures = []
    if not all_dedup:
        failures.append("not all 1,000 ingests were deduplicating")
    if n_obj != 1:
        failures.append(f"expected exactly 1 object file, got {n_obj}")
    if n_desc != 1:
        failures.append(f"expected exactly 1 descriptor file, got {n_desc}")
    if n_rec != 1:
        failures.append(f"expected exactly 1 receipt file, got {n_rec}")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "1,000 deduplicating ingests of a 256-byte payload produced exactly "
            "one object file, one descriptor, and one receipt (zero overwrites)"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C21-05 crash at every publish boundary.
# ---------------------------------------------------------------------------


def _replace_boom_at(fail_at: int, real_replace: Any, label: str) -> Any:
    """Build an os.replace side effect that raises on the ``fail_at``-th call.

    Counts every ``os.replace`` in the transaction and raises ``OSError`` on the
    ``fail_at``-th call (1-based: 1=staging, 2=publish, 3=descriptor, 4=receipt).
    Used for the tmp_write / replace_publish / descriptor_write / receipt_write
    boundaries.
    """
    state = {"replaces": 0}

    def boom(src: Path | str, dst: Path | str) -> None:
        state["replaces"] += 1
        if state["replaces"] == fail_at:
            raise OSError(f"boundary {label!r}: replace #{state['replaces']}")
        real_replace(src, dst)

    return boom


def _fsync_boom_at(fail_at: int, real_fsync: Any, label: str) -> Any:
    """Build an os.fsync side effect that raises on the ``fail_at``-th call.

    The transaction's first fsync is the partial-file fsync (step 5). Later
    fsyncs are descriptor/receipt file fsyncs and best-effort directory fsyncs.
    The ``dir_fsync`` boundary fails a post-publish directory fsync, so it is
    handled by patching ``_fsync_dir`` directly instead of this counter.
    """
    state = {"fsyncs": 0}

    def boom(fd: int) -> None:
        state["fsyncs"] += 1
        if state["fsyncs"] == fail_at:
            raise OSError(f"boundary {label!r}: fsync #{state['fsyncs']}")
        real_fsync(fd)

    return boom


def _readback_corrupter(real_read_bytes: Any) -> Any:
    """Build a Path.read_bytes side effect that corrupts the partial read-back.

    Only reads of files under ``incoming/`` (the partial) are corrupted; all
    other reads pass through unchanged. The corruption flips the last byte so
    the read-back hash disagrees with the source hash (triggers the verify
    boundary with ``CAS_INTEGRITY_FAILURE``).
    """

    def corrupt(self: Path) -> bytes:
        data = real_read_bytes(self)
        if "incoming" in str(self) and data:
            return data[:-1] + bytes([data[-1] ^ 0xFF])
        return data

    return corrupt


def _dir_fsync_boom(real_fsync_dir: Any, label: str) -> Any:
    """Build a ``_fsync_dir`` side effect that raises on the first post-publish call.

    The directory-fsync boundary runs *after* the publish (step 8), so by the
    time ``_fsync_dir`` is first reached the object is already visible. Raising
    here models a crash after the publish but before the directory entry is
    durable. The engine's ``_fsync_dir`` normally tolerates OSError, so this
    injection replaces the whole function to force the raise.
    """

    def boom(path: Path) -> None:
        raise OSError(f"boundary {label!r}: directory fsync failed")

    return boom


# The expected old-or-new state for each boundary: (object_present, descriptor_present).
# receipt is ALWAYS absent on failure (the commit marker is written last).
_BOUNDARY_EXPECTED: Final[dict[str, tuple[bool, bool]]] = {
    "tmp_write": (False, False),
    "tmp_fsync": (False, False),
    "readback_verify": (False, False),
    "replace_publish": (False, False),
    "dir_fsync": (True, False),
    "descriptor_write": (True, False),
    "receipt_write": (True, True),
}


def _replace_patch_for(boundary: str) -> Any:
    """Build the os.replace patch for a replace-indexed boundary (or None)."""
    index = {
        "tmp_write": REPLACE_STAGING,
        "replace_publish": REPLACE_PUBLISH,
        "descriptor_write": REPLACE_DESCRIPTOR,
        "receipt_write": REPLACE_RECEIPT,
    }.get(boundary)
    if index is None:
        return None
    return patch(
        "srl.cas.engine.os.replace",
        side_effect=_replace_boom_at(index, os.replace, boundary),
    )


def _boundary_patches(boundary: str) -> list[Any]:
    """Build the (not-yet-started) failure-injection patches for ``boundary``.

    Each boundary maps to exactly one injection: the four ``os.replace``
    boundaries raise at their 1-based call index; ``tmp_fsync`` raises at the
    partial-file fsync; ``readback_verify`` corrupts the read-back; ``dir_fsync``
    raises inside ``_fsync_dir`` (the engine normally swallows OSError there, so
    the whole function is replaced to force the raise).
    """
    replace_patch = _replace_patch_for(boundary)
    if replace_patch is not None:
        return [replace_patch]
    if boundary == "tmp_fsync":
        return [
            patch(
                "srl.cas.engine.os.fsync",
                side_effect=_fsync_boom_at(FSYNC_PARTIAL, os.fsync, boundary),
            )
        ]
    if boundary == "readback_verify":
        return [patch("srl.cas.engine.Path.read_bytes", _readback_corrupter(Path.read_bytes))]
    if boundary == "dir_fsync":
        return [patch("srl.cas.engine._fsync_dir", side_effect=_dir_fsync_boom(None, boundary))]
    raise AssertionError(f"unknown boundary {boundary!r}")  # pragma: no cover


def _run_boundary(boundary: str, payload: bytes) -> dict[str, Any]:
    """Run one C21-05 boundary case; return its case dict (with status keys).

    Installs the boundary-specific failure injection, runs an ingest, and
    records whether it raised and what records remain. Returns a dict with the
    record counts and the derived ``receipt_absent`` / ``state_ok`` booleans.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root)
        patches = _boundary_patches(boundary)
        for p in patches:
            p.start()
        raised = False
        raised_kind = ""
        try:
            try:
                store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
            except (OSError, CasIntegrityError) as exc:
                raised = True
                raised_kind = type(exc).__name__
        finally:
            for p in patches:
                p.stop()

        n_obj = _object_count(root)
        n_desc = _descriptor_count(root)
        n_rec = _receipt_count(root)
        expect_obj, expect_desc = _BOUNDARY_EXPECTED[boundary]
        return {
            "case": f"boundary-{boundary}",
            "raised": raised,
            "raised_kind": raised_kind,
            "object_files": n_obj,
            "descriptor_files": n_desc,
            "receipt_files": n_rec,
            "receipt_absent": n_rec == 0,
            "object_state_ok": n_obj == (1 if expect_obj else 0),
            "descriptor_state_ok": n_desc == (1 if expect_desc else 0),
        }


def _check_c21_05() -> dict[str, Any]:
    """C21-05: crash injection at all seven boundaries leaves old-or-new valid state.

    The seven boundaries (``CRASH_BOUNDARIES``) are the single source of truth
    shared with ``docs/architecture/cas-engine.md`` and the unit tests. Each is
    injected in its own hermetic temp dir, and the store is asserted to end in
    the old-or-new valid state for that boundary: receipt ALWAYS absent, object
    and descriptor present only for the post-publish boundaries.
    """
    cases: list[dict[str, Any]] = []
    payload = b"c21-05-crash-boundary"

    for boundary in CRASH_BOUNDARIES:
        case = _run_boundary(boundary, payload)
        cases.append(case)
        if not case["raised"]:
            return {
                "status": "FAIL",
                "detail": f"boundary {boundary!r} did not raise",
                "cases": cases,
            }
        if not case["receipt_absent"]:
            return {
                "status": "FAIL",
                "detail": f"boundary {boundary!r} wrote a receipt on failure",
                "cases": cases,
            }
        if not case["object_state_ok"]:
            return {
                "status": "FAIL",
                "detail": (
                    f"boundary {boundary!r} left an unexpected object count "
                    f"({case['object_files']})"
                ),
                "cases": cases,
            }
        if not case["descriptor_state_ok"]:
            return {
                "status": "FAIL",
                "detail": (
                    f"boundary {boundary!r} left an unexpected descriptor count "
                    f"({case['descriptor_files']})"
                ),
                "cases": cases,
            }

    return {
        "status": "PASS",
        "detail": (
            "crash injection at all seven durability boundaries (tmp write, tmp "
            "fsync, read-back verify, os.replace publish, directory fsync, "
            "descriptor write, receipt write) each left old-or-new valid state: "
            "no receipt was written on any failure (commit marker written last), "
            "and no partial was ever visible as an object"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C21-06 read-back corruption injection detected.
# ---------------------------------------------------------------------------


def _check_c21_06() -> dict[str, Any]:
    """C21-06: a wrong-hash read-back fails the ingest with CAS_INTEGRITY_FAILURE."""
    cases: list[dict[str, Any]] = []
    payload = b"c21-06-readback-injection"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root)
        real_read_bytes = Path.read_bytes

        def wrong_readback(self: Path) -> bytes:
            data = real_read_bytes(self)
            # Return wrong bytes only for the partial read-back (in incoming/).
            if "incoming" in str(self):
                return b"completely-wrong-readback"
            return data

        raised = False
        raised_reason = ""
        with patch("srl.cas.engine.Path.read_bytes", wrong_readback):
            try:
                store.ingest_bytes(payload, "application/octet-stream", created_utc=_TS)
            except CasIntegrityError as exc:
                raised = True
                raised_reason = exc.fail_reason
        n_obj = _object_count(root)
        n_rec = _receipt_count(root)
        cases.append(
            {
                "case": "readback-injection-fails",
                "raised": raised,
                "fail_reason": raised_reason,
                "object_files": n_obj,
                "receipt_files": n_rec,
            }
        )

    failures = []
    if not raised or raised_reason != CAS_INTEGRITY_FAILURE_REF:
        failures.append(
            f"read-back injection did not raise {CAS_INTEGRITY_FAILURE_REF!r} "
            f"(raised={raised}, reason={raised_reason!r})"
        )
    if n_obj != 0:
        failures.append(f"read-back injection published an object ({n_obj})")
    if n_rec != 0:
        failures.append(f"read-back injection wrote a receipt ({n_rec})")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "patching the first read-back to return wrong bytes made the ingest "
            f"fail with {CAS_INTEGRITY_FAILURE_REF!r} and publish nothing"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: inline payload sizes and the crash-matrix rationale."""
    return {
        "payload_c21_01_bytes": len(b"c21-01-no-overwrite"),
        "payload_c21_04_bytes": 256,
        "boundaries_checked": len(CRASH_BOUNDARIES),
        "crash_boundaries": list(CRASH_BOUNDARIES),
        "binary_fixture_files": 0,
        # Hermetic-monkeypatch rationale (red-team cycle-1, finding 2): the
        # crash matrix injects failures by patching engine-internal symbols
        # (``srl.cas.engine.os.replace``, ``os.fsync``, ``Path.read_bytes``,
        # ``_fsync_dir``) inside a per-boundary ``tempfile.TemporaryDirectory``.
        # This is hermetic and deterministic: no real disk is touched, no wall
        # clock drives the outcome (the timestamp is pinned), and every patch is
        # scoped to the single ingest under test and torn down in ``finally``.
        # Monkeypatching (rather than, say, SIGBUS injection or a FUSE fault
        # layer) is the right tool here because the invariant under test is the
        # transaction's *step ordering*, not the kernel's durability guarantees
        # — we assert that a failure at boundary N leaves exactly the records
        # that steps < N wrote, which is a property of the code, not the OS.
        "hermetic_monkeypatch_rationale": (
            "failures are injected by patching engine-internal os.replace/fsync/"
            "read_bytes/_fsync_dir symbols inside a per-boundary temp dir; the "
            "timestamp is pinned and every patch is scoped + torn down in finally. "
            "The matrix tests the transaction's step ordering (a crash at boundary "
            "N leaves exactly the records steps < N wrote), which is a code "
            "property, not a kernel-durability property, so monkeypatching — not "
            "SIGBUS or a FUSE fault layer — is the correct injection tool."
        ),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all six checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "C21-01": _check_c21_01(),
        "C21-02": _check_c21_02(),
        "C21-03": _check_c21_03(),
        "C21-04": _check_c21_04(),
        "C21-05": _check_c21_05(),
        "C21-06": _check_c21_06(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            **_evidence(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "C21-01": _check_c21_01,
            "C21-02": _check_c21_02,
            "C21-03": _check_c21_03,
            "C21-04": _check_c21_04,
            "C21-05": _check_c21_05,
            "C21-06": _check_c21_06,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "error": f"unknown check {cid}"})
            return 2
        result = runner()
        _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "check": cid, **result})
        return 0 if result["status"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
