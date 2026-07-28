"""The CAS transaction engine: atomic, receipt-last content-addressed ingest.

This module implements the transaction that turns bytes into a published,
content-addressed object inside a :class:`~srl.cas.store.LocalArtifactStore`.
The engine's job is to make a single ingest **crash-safe**: a crash at any point
during the transaction leaves the store in either the old valid state (the
object was not published) or the new valid state (the object was published with
a durable descriptor and receipt). A crash never leaves a partial object
visible to readers.

The transaction
---------------
``ingest`` performs the following steps in a strict order, with ``fsync`` at
each durability boundary so a crash produces one of the two valid states:

1. **Source hash.** Compute ``sha256(source_bytes)``. This is the content
   address; it is never supplied by the caller.
2. **Dedup check.** If the final object path already exists, return the existing
   descriptor reference with ``deduplicated=True``. **No bytes are written** — a
   re-ingest of identical content is a no-op publish.
3. **Capacity policy.** Consult the (optional) capacity hook *before* any byte is
   written. If the hook raises :class:`QuotaExceededError`
   (``T7_QUOTA_EXCEEDED``), the ingest is refused and nothing is written.
4. **Write the partial.** Write the bytes to ``incoming/partial-<digest>.tmp``.
5. **fsync the partial.** Flush + ``fsync`` the partial file so its contents are
   durable before the publish.
6. **Read-back re-hash.** Read the partial back, re-hash, and compare to the
   source hash. Also confirm the byte size matches. A mismatch raises
   :class:`~srl.cas.store.StoreIntegrityError`
   (``CAS_INTEGRITY_FAILURE``, hard stop) and deletes the partial so the store
   is not left in a known-corrupt state.
7. **Exclusive publish.** ``os.replace`` the partial into
   ``objects/<shard>/<digest>``. ``os.replace`` is atomic on POSIX, so a reader
   either sees the old state or the new state, never a half-written object. If
   the final path now exists (a concurrent publish won between the dedup check
   and the publish), the partial is deleted and the ingest is treated as a
   dedup (no overwrite).
8. **fsync the directories.** ``fsync`` the object shard dir, the ``objects``
   dir, and the store root so the new directory entry is durable.
9. **Write the descriptor.** Write ``descriptors/<digest>.json`` (the
   ``ObjectDescriptor/v1``) and ``fsync`` it.
10. **Write the receipt.** Write ``receipts/<receipt_id>.json`` (the
    ``IngestReceipt/v1``) **last**, and ``fsync`` it. The receipt is the commit
    marker: its presence is the proof the ingest completed.

Path safety
-----------
The digest (the content address) is validated against ``^[0-9a-f]{64}$`` *before*
it is ever joined to a path, so a malicious or malformed digest cannot traverse
out of the store root. Even though the digest is computed internally (a caller
cannot supply it), the check is a defense-in-depth against a future code path
that might.

Crash recovery
--------------
A crash before step 10 leaves no receipt; a crash before step 7 leaves no
published object. A partial ``incoming/partial-<digest>.tmp`` file may remain,
but it is **never visible as an object** (the object path only exists after the
atomic ``os.replace``). :func:`recover_partials` lists stale partials at startup
so an operator can decide whether to delete them; the engine **never
auto-deletes** them — a partial is evidence, and deletion is an explicit choice.

Standard library only
---------------------
The engine uses only the standard library plus the in-repo ``srl.contracts``
package (for canonical encoding and the digest/byte-count validators). The
canonical encoding is used only for the descriptor and receipt records (control
plane); the byte-path hashes are computed directly from the bytes, not through
canonical JSON, so the hot path stays cheap.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json as _json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from srl.cas.capacity import T7_QUOTA_EXCEEDED_FAIL_REASON
from srl.cas.descriptors import (
    INGEST_RECEIPT_SCHEMA_VERSION,
    OBJECT_DESCRIPTOR_SCHEMA_VERSION,
    DescriptorError,
    build_ingest_receipt,
    build_object_descriptor,
    validate_object_descriptor,
)
from srl.cas.privacy import redact_store_path
from srl.contracts.artifact_refs import validate_media_type
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.timestamps import validate as validate_timestamp

# The path-safety shape a raw digest must match before any path join. The digest
# is the 64-hex content address (without the "sha256:" prefix, which is stripped
# before this check). Defense-in-depth: the digest is computed internally, but
# validating it before a path join makes a traversal impossible even if a future
# code path lets a caller influence it.
_HEX64_PATTERN: Final[str] = r"^[0-9a-f]{64}$"
_HEX64_RE: Final[re.Pattern[str]] = re.compile(_HEX64_PATTERN)

# The prefix the engine uses for partial files in incoming/. "partial-" (not a
# leading dot) so they are easy to enumerate; the digest makes them unique.
_PARTIAL_PREFIX: Final[str] = "partial-"
_PARTIAL_SUFFIX: Final[str] = ".tmp"


class QuotaExceededError(ContractError):
    """Raised when the capacity policy refuses an ingest before any byte is written.

    Carries ``fail_reason='T7_QUOTA_EXCEEDED'`` (a soft stop per the fail-reason
    registry: ``hard_stop=false``, ``retriable=false``). The engine consults the
    capacity hook *before* writing any bytes, so a refused ingest leaves the
    store untouched.
    """

    def __init__(
        self,
        message: str,
        *,
        used_bytes: int = 0,
        size_bytes: int = 0,
        fail_reason: str = T7_QUOTA_EXCEEDED_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.used_bytes: int = used_bytes
        self.size_bytes: int = size_bytes


class CasIntegrityError(ContractError):
    """Raised when a read-back re-hash disagrees with the source hash.

    The bytes written to the partial did not read back to the same digest, or the
    size drifted. This is a hard stop (``CAS_INTEGRITY_FAILURE``): the store
    deletes the partial so it is not left in a known-corrupt state, and the
    ingest fails. Carries the expected (source) and observed (read-back)
    digests for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        expected_digest: str = "",
        observed_digest: str = "",
        fail_reason: str = "CAS_INTEGRITY_FAILURE",
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.expected_digest: str = expected_digest
        self.observed_digest: str = observed_digest


# A capacity policy hook. The engine calls it with (used_bytes, size_bytes)
# before writing any bytes; the hook raises QuotaExceededError to refuse the
# ingest, or returns silently to admit it. Returning the decision (rather than
# raising) is intentionally not supported: the hook is the single place the
# refusal happens, so the fail_reason is pinned at the hook.
CapacityHook = Callable[[int, int], None]


@dataclass(frozen=True)
class IngestOutcome:
    """The result of a successful :func:`ingest`.

    Attributes
    ----------
    digest:
        ``sha256:<64 hex>`` content digest of the published object.
    size_bytes:
        Byte count of the published object.
    descriptor:
        The ``ObjectDescriptor/v1`` dict written to ``descriptors/``.
    receipt:
        The ``IngestReceipt/v1`` dict written to ``receipts/`` (the commit
        marker).
    receipt_id:
        ``sha256:<64 hex>`` id of the ingest receipt.
    deduplicated:
        True iff the object already existed and the ingest wrote nothing (the
        descriptor/receipt reference the existing object).
    store_root_redacted:
        ``redacted:<16 hex>`` token for the store root (never a raw path).
    """

    digest: str
    size_bytes: int
    descriptor: dict[str, Any]
    receipt: dict[str, Any]
    receipt_id: str
    deduplicated: bool
    store_root_redacted: str


@dataclass(frozen=True)
class PartialEntry:
    """A stale partial file discovered by :func:`recover_partials`.

    Attributes
    ----------
    path:
        The path to the partial file (under ``incoming/``). Reported for an
        operator to inspect; never auto-deleted.
    digest_hint:
        The digest parsed from the partial filename (``sha256:<64 hex>``), or
        ``""`` if the filename does not carry a parseable digest.
    size_bytes:
        The current size of the partial file in bytes.
    published:
        True iff the object path for ``digest_hint`` already exists (the partial
        is a leftover from a publish that completed but whose partial cleanup
        was interrupted). Such a partial is safe to delete.
    """

    path: Path
    digest_hint: str
    size_bytes: int
    published: bool


def _now_utc_seconds() -> str:
    """Return the current UTC time as a canonical RFC 3339 seconds-precision stamp.

    Centralized so the engine and the tests share one timestamp source. The
    canonical timestamp policy (see :mod:`srl.contracts.timestamps`) is
    seconds-precision UTC with a trailing ``Z``; we format directly to avoid the
    ``datetime.isoformat`` fractional/microsecond output.
    """
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_hex(data: bytes) -> str:
    """Return the bare 64-hex SHA-256 of ``data`` (no ``sha256:`` prefix)."""
    return hashlib.sha256(data).hexdigest()


def _require_safe_hex_digest(hex_digest: str) -> None:
    """Validate ``hex_digest`` as 64 lowercase hex before any path join.

    This is the path-safety defense. Even though the digest is computed
    internally, joining an unvalidated string to a path is a traversal hazard;
    the regex makes ``../``-style digests impossible.
    """
    if not isinstance(hex_digest, str) or not _HEX64_RE.fullmatch(hex_digest):
        msg = f"digest hex must match {_HEX64_PATTERN!r}, got {hex_digest!r}"
        raise ContractError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def _validate_inputs(media_type: str, created_utc: str) -> None:
    """Validate the caller-supplied ``media_type`` and ``created_utc`` up front.

    A malformed media_type or timestamp must fail the ingest *before* any byte is
    written. Without this check, the bad value would only surface inside
    ``build_object_descriptor`` / ``build_ingest_receipt`` (step 9), after the
    object is already published — leaving a published object with no receipt.
    Validating here keeps bad input from touching the store.
    """
    try:
        validate_media_type(media_type, field="media_type")
    except ContractError as exc:
        raise ContractError(str(exc), fail_reason=CONTRACT_INVALID_FAIL_REASON) from exc
    try:
        validate_timestamp(created_utc)
    except ContractError as exc:
        raise ContractError(str(exc), fail_reason=CONTRACT_INVALID_FAIL_REASON) from exc


def _fsync_dir(path: Path) -> None:
    """``fsync`` the directory at ``path`` (durability of directory entries).

    On POSIX, renaming a file into a directory is not durable until the
    directory itself is fsynced. We open the directory read-only and fsync the
    fd. Errors are tolerated on filesystems that do not support directory fsync
    (some network FS): a failure to fsync a directory is reported but does not
    fail the ingest, matching the durability-best-effort contract of the local
    store.
    """
    if not path.is_dir():
        return
    fd = _open_dir_readonly(path)
    if fd < 0:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Best-effort: a filesystem that cannot fsync a directory still got the
        # atomic rename; the object is visible, just not fsync-durable. We do
        # not fail the ingest over a directory-fsync refusal.
        pass
    finally:
        os.close(fd)


def _open_dir_readonly(path: Path) -> int:
    """Open a directory read-only, returning the fd (or -1 on failure).

    Uses ``os.open`` with ``O_RDONLY`` on POSIX. Wrapped so a platform without
    directory-open (or a permission error) degrades to "no fsync" rather than
    failing the ingest.
    """
    try:
        return os.open(path, os.O_RDONLY)
    except OSError:
        return -1


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via a same-dir temp + fsync + replace.

    Used for the descriptor and receipt records (small control-plane files). The
    temp is created in the same directory so the rename is atomic on the same
    filesystem. The file is fsynced before the rename, and the containing
    directory is fsynced after.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".atomic-", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def ingest(  # noqa: PLR0913 (the kw-only set IS the ingest transaction's inputs)
    *,
    root: Path,
    source_bytes: bytes,
    media_type: str,
    capacity_hook: CapacityHook | None = None,
    used_bytes: int = 0,
    created_utc: str | None = None,
) -> IngestOutcome:
    """Ingest ``source_bytes`` into the store rooted at ``root``.

    Implements the transaction documented in this module's docstring. Returns an
    :class:`IngestOutcome` carrying the published digest, the descriptor, and
    the commit-marker receipt. On dedup (the object already exists) the outcome
    is returned with ``deduplicated=True`` and **no bytes are written**.

    Parameters
    ----------
    root:
        The store root directory. The ``objects/``, ``descriptors/``,
        ``receipts/``, and ``incoming/`` subtrees are created as needed.
    source_bytes:
        The bytes to ingest.
    media_type:
        IANA-style media type recorded on the descriptor.
    capacity_hook:
        Optional callable ``(used_bytes, size_bytes) -> None`` consulted before
        any byte is written. It raises :class:`QuotaExceededError` to refuse the
        ingest; otherwise it returns ``None``.
    used_bytes:
        Current aggregate usage in bytes, passed to ``capacity_hook``. The
        engine does not recompute usage (the caller owns the accounting); it
        only forwards the value to the hook.
    created_utc:
        Optional canonical timestamp override (tests pin it for determinism).
        If ``None``, the current UTC time at seconds precision is used.

    Returns
    -------
    IngestOutcome
        The result of the ingest (descriptor, receipt, dedup flag).

    Raises
    ------
    QuotaExceededError
        If the capacity hook refuses the ingest (before any byte is written).
    CasIntegrityError
        If the read-back re-hash disagrees with the source hash.
    ContractError
        If ``media_type`` is malformed or a path-safety check fails.
    """
    # Defense-in-depth: reject a non-bytes ``source_bytes`` at runtime even
    # though the annotation is ``bytes``. The ``Any`` view keeps mypy from
    # narrowing the check away.
    source_any: Any = source_bytes
    if not isinstance(source_any, (bytes, bytearray)):
        msg = f"source_bytes must be bytes, got {type(source_any).__name__}"
        raise ContractError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)
    source_bytes = bytes(source_any)
    size_bytes = len(source_bytes)
    created = created_utc if created_utc is not None else _now_utc_seconds()

    # Validate inputs BEFORE any write: a malformed media_type or timestamp must
    # fail the ingest without publishing a partial object. These checks run ahead
    # of the dedup check so a bad-input ingest never touches the store.
    _validate_inputs(media_type, created)

    # Step 1: source hash (the content address). Computed internally; the caller
    # never supplies it.
    hex_digest = _sha256_hex(source_bytes)
    _require_safe_hex_digest(hex_digest)  # defense-in-depth before any path join
    digest = "sha256:" + hex_digest

    # Lay out the subtrees.
    paths = _store_paths(root, hex_digest)
    for d in (paths.objects, paths.descriptors, paths.receipts, paths.incoming):
        d.mkdir(parents=True, exist_ok=True)

    # Step 2: dedup check. If the object already exists, return the existing
    # descriptor reference and do NOT write any bytes (no overwrite).
    if paths.object.is_file():
        return _dedup_outcome(
            paths,
            digest=digest,
            size_bytes=size_bytes,
            media_type=media_type,
            created=created,
        )

    # Step 3: capacity policy. Consulted BEFORE any byte is written, so a
    # refused ingest leaves the store untouched.
    if capacity_hook is not None:
        capacity_hook(used_bytes, size_bytes)

    # Steps 4-6: write + fsync the partial, then read-back re-hash + size check.
    partial_path = _write_partial_and_verify(
        paths,
        source_bytes=source_bytes,
        hex_digest=hex_digest,
        digest=digest,
        size_bytes=size_bytes,
    )

    # Step 7: exclusive publish. If a concurrent ingest won, dedup instead.
    if paths.object.is_file():
        partial_path.unlink(missing_ok=True)
        return _dedup_outcome(
            paths,
            digest=digest,
            size_bytes=size_bytes,
            media_type=media_type,
            created=created,
        )
    os.replace(partial_path, paths.object)

    # Step 8: fsync the containing directories so the new entry is durable.
    _fsync_dir(paths.object.parent)
    _fsync_dir(paths.objects)
    _fsync_dir(root)

    # Steps 9-10: write the descriptor, then the receipt LAST (the commit marker).
    return _write_descriptor_and_receipt(
        paths,
        digest=digest,
        size_bytes=size_bytes,
        media_type=media_type,
        created=created,
    )


@dataclass(frozen=True)
class _StorePaths:
    """The on-disk paths a single ingest touches, derived from the root + digest.

    Collected into a dataclass so the engine helpers take one argument instead
    of five, keeping the public :func:`ingest` under the argument-count budget.
    """

    root: Path
    objects: Path
    descriptors: Path
    receipts: Path
    incoming: Path
    object: Path
    descriptor_file: Path


def _store_paths(root: Path, hex_digest: str) -> _StorePaths:
    """Build the :class:`_StorePaths` for ``root`` and ``hex_digest``."""
    shard = hex_digest[:2]
    digest = "sha256:" + hex_digest
    objects = root / "objects"
    return _StorePaths(
        root=root,
        objects=objects,
        descriptors=root / "descriptors",
        receipts=root / "receipts",
        incoming=root / "incoming",
        object=objects / shard / digest,
        descriptor_file=(root / "descriptors") / f"{digest}.json",
    )


def _dedup_outcome(
    paths: _StorePaths,
    *,
    digest: str,
    size_bytes: int,
    media_type: str,
    created: str,
) -> IngestOutcome:
    """Build the :class:`IngestOutcome` for a dedup (object already published).

    Reads the existing descriptor if present (carrying forward its receipt id);
    no bytes are written. Used at both the pre-write dedup check and the
    post-read-back concurrent-win dedup.
    """
    descriptor = _read_descriptor_or_build(
        paths.descriptor_file,
        digest=digest,
        size_bytes=size_bytes,
        media_type=media_type,
        created_utc=created,
    )
    receipt_id = descriptor.get("ingest_receipt_id") or ""
    receipt = _build_synthetic_receipt_for_dedup(
        digest=digest,
        size_bytes=size_bytes,
        receipt_id=receipt_id,
        created_utc=created,
    )
    return IngestOutcome(
        digest=digest,
        size_bytes=size_bytes,
        descriptor=descriptor,
        receipt=receipt,
        receipt_id=receipt_id,
        deduplicated=True,
        store_root_redacted=redact_store_path(paths.root),
    )


def _write_partial_and_verify(
    paths: _StorePaths,
    *,
    source_bytes: bytes,
    hex_digest: str,
    digest: str,
    size_bytes: int,
) -> Path:
    """Write + fsync the partial, then read-back re-hash + size check.

    Steps 4-6 of the transaction. Returns the canonical partial path on
    success. On a read-back mismatch raises :class:`CasIntegrityError` after
    deleting the partial so the store is not left in a known-corrupt state.
    """
    paths.object.parent.mkdir(parents=True, exist_ok=True)
    partial_name = f"{_PARTIAL_PREFIX}{hex_digest}{_PARTIAL_SUFFIX}"
    partial_path = paths.incoming / partial_name
    fd, tmp_name = tempfile.mkstemp(prefix=".ingest-", dir=paths.incoming)
    tmp_stage = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(source_bytes)
            fh.flush()
            # Step 5: fsync the partial file.
            os.fsync(fh.fileno())
        # Stage the fsynced bytes into the canonical partial name (atomic,
        # intra-directory rename in incoming/).
        os.replace(tmp_stage, partial_path)
        tmp_stage = partial_path  # canonical partial now staged

        # Step 6: read-back re-hash + size check.
        readback = partial_path.read_bytes()
        readback_hex = _sha256_hex(readback)
        if readback_hex != hex_digest or len(readback) != size_bytes:
            partial_path.unlink(missing_ok=True)
            msg = (
                f"read-back integrity failure: object {digest!r} read back as "
                f"sha256:{readback_hex} (size {len(readback)} != {size_bytes})"
            )
            raise CasIntegrityError(
                msg,
                expected_digest=digest,
                observed_digest="sha256:" + readback_hex,
            )
    except BaseException:
        # Clean up any stray stage temp on failure (CasIntegrityError already
        # unlinked its partial). The published object is never reached here, so
        # there is no half-published state to recover.
        if tmp_stage != partial_path:
            tmp_stage.unlink(missing_ok=True)
        raise
    return partial_path


def _write_descriptor_and_receipt(
    paths: _StorePaths,
    *,
    digest: str,
    size_bytes: int,
    media_type: str,
    created: str,
) -> IngestOutcome:
    """Write the descriptor (step 9) then the receipt LAST (step 10).

    The receipt is the commit marker: its presence is the proof the ingest
    completed. The descriptor references the receipt id, so the receipt is built
    first; both are written via atomic write + fsync.
    """
    # Build the receipt first so the descriptor can reference its id.
    receipt, receipt_id = build_ingest_receipt(
        digest=digest,
        size_bytes=size_bytes,
        source_hash_verified=True,
        readback_hash_verified=True,
        fsynced=True,
        created_utc=created,
    )
    descriptor = build_object_descriptor(
        digest=digest,
        size_bytes=size_bytes,
        media_type=media_type,
        created_utc=created,
        ingest_receipt_id=receipt_id,
    )
    # Step 9: write the descriptor and fsync it.
    _atomic_write_bytes(paths.descriptor_file, dumps(descriptor))
    # Step 10: write the receipt LAST and fsync it (the commit marker).
    receipt_path = paths.receipts / f"{receipt_id}.json"
    _atomic_write_bytes(receipt_path, dumps(receipt))
    return IngestOutcome(
        digest=digest,
        size_bytes=size_bytes,
        descriptor=descriptor,
        receipt=receipt,
        receipt_id=receipt_id,
        deduplicated=False,
        store_root_redacted=redact_store_path(paths.root),
    )


def _read_descriptor_or_build(
    descriptor_path: Path,
    *,
    digest: str,
    size_bytes: int,
    media_type: str,
    created_utc: str,
) -> dict[str, Any]:
    """Return the descriptor at ``descriptor_path``, or build a fresh one.

    On a dedup the existing object's descriptor is carried forward if it is
    present and valid (so the outcome's descriptor matches the durable record).
    If the descriptor is missing or unreadable (a store in a partially-recovered
    state), a fresh descriptor is built so the caller still gets a well-formed
    record; the fresh descriptor's ``ingest_receipt_id`` is ``None``.
    """
    if descriptor_path.is_file():
        try:
            raw = descriptor_path.read_text(encoding="utf-8")
            parsed = _json.loads(raw)
            return validate_object_descriptor(parsed)
        except (OSError, ValueError, DescriptorError):
            # Fall through to build a fresh descriptor; the store is in a
            # partially-recovered state and the caller asked for a descriptor.
            pass
    return build_object_descriptor(
        digest=digest,
        size_bytes=size_bytes,
        media_type=media_type,
        created_utc=created_utc,
        ingest_receipt_id=None,
    )


def _build_synthetic_receipt_for_dedup(
    *,
    digest: str,
    size_bytes: int,
    receipt_id: str,
    created_utc: str,
) -> dict[str, Any]:
    """Build a receipt dict describing a dedup (no new write occurred).

    A dedup does not create a new receipt (the original ingest's receipt is the
    commit marker). The outcome carries a receipt-shaped dict so callers always
    see a uniform shape; its ``receipt_id`` is the original receipt's id when
    known, and a freshly-computed content-addressed id otherwise. The dict is
    marked ``schema_version=IngestReceipt/v1`` but is not written to disk.
    """
    if receipt_id:
        # Reuse the original receipt id; the dict is for the outcome shape only.
        return {
            "schema_version": INGEST_RECEIPT_SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "digest": digest,
            "size_bytes": size_bytes,
            "source_hash_verified": True,
            "readback_hash_verified": True,
            "fsynced": True,
            "created_utc": created_utc,
        }
    receipt, _ = build_ingest_receipt(
        digest=digest,
        size_bytes=size_bytes,
        source_hash_verified=True,
        readback_hash_verified=True,
        fsynced=True,
        created_utc=created_utc,
    )
    return receipt


def recover_partials(root: Path) -> list[PartialEntry]:
    """List stale partial files in ``<root>/incoming/``.

    A partial is a file named ``partial-<digest>.tmp`` left over from an
    interrupted ingest. The engine **never auto-deletes** partials: a partial is
    evidence of an interrupted transaction, and deletion is an explicit operator
    choice. This function reports every partial, classifying each as:

    - ``published=True`` — the object path for the partial's digest already
      exists; the publish completed but the partial cleanup was interrupted.
      Such a partial is safe to delete.
    - ``published=False`` — the object path does not exist; the ingest was
      interrupted before the publish. The partial may be resumed (re-ingesting
      the same bytes produces the same digest and completes the publish) or
      deleted.

    Partials whose filenames do not parse to a digest (``digest_hint=""``) are
    reported as-is so an operator can inspect them; they are not classified.

    Parameters
    ----------
    root:
        The store root directory.

    Returns
    -------
    list[PartialEntry]
        One entry per file in ``incoming/``, sorted by path.
    """
    incoming = root / "incoming"
    if not incoming.is_dir():
        return []
    entries: list[PartialEntry] = []
    for child in sorted(incoming.iterdir()):
        if not child.is_file():
            continue
        name = child.name
        digest_hint = ""
        published = False
        if name.startswith(_PARTIAL_PREFIX) and name.endswith(_PARTIAL_SUFFIX):
            hex_part = name[len(_PARTIAL_PREFIX) : len(name) - len(_PARTIAL_SUFFIX)]
            if _HEX64_RE.fullmatch(hex_part):
                digest_hint = "sha256:" + hex_part
                shard = hex_part[:2]
                published = (root / "objects" / shard / digest_hint).is_file()
        try:
            size = child.stat().st_size
        except OSError:
            size = -1
        entries.append(
            PartialEntry(
                path=child,
                digest_hint=digest_hint,
                size_bytes=size,
                published=published,
            )
        )
    return entries


def default_capacity_hook(table_bytes: int) -> CapacityHook:
    """Build a capacity hook that refuses ingests past ``table_bytes``.

    The hook is the single place the ``T7_QUOTA_EXCEEDED`` refusal happens. It
    closes over the hard ceiling (in bytes) and raises
    :class:`QuotaExceededError` when the projected usage
    (``used_bytes + size_bytes``) would reach the ceiling. The engine calls it
    before writing any byte, so a refused ingest leaves the store untouched.
    """

    def _hook(used_bytes: int, size_bytes: int) -> None:
        if used_bytes + size_bytes > table_bytes:
            msg = (
                f"ingest of {size_bytes} bytes would exceed capacity ceiling "
                f"{table_bytes} bytes (used {used_bytes})"
            )
            raise QuotaExceededError(
                msg,
                used_bytes=used_bytes,
                size_bytes=size_bytes,
            )

    return _hook


__all__ = [
    "INGEST_RECEIPT_SCHEMA_VERSION",
    "OBJECT_DESCRIPTOR_SCHEMA_VERSION",
    "CapacityHook",
    "CasIntegrityError",
    "IngestOutcome",
    "PartialEntry",
    "QuotaExceededError",
    "default_capacity_hook",
    "ingest",
    "recover_partials",
]
