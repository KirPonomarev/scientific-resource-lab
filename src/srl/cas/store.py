"""Content-addressed storage abstraction and T7 volume store.

This module defines :class:`ArtifactStore`, the abstract interface every SRL
content-addressed store implements, plus two concrete backends:

- :class:`LocalArtifactStore` — a directory-rooted store that is the **only**
  implementation permitted to write in WP-C20. It is content-addressed (the
  SHA-256 of the bytes is the key), verifies integrity on read (``fsck``), and
  is used for public tiny fixtures and as the test backend.
- :class:`T7ArtifactStore` — a stub bound to the T7 volume identity guard. Its
  constructor accepts a volume-identity provider and the expected identity, but
  it **refuses every operation** with ``WAIT_STORAGE`` until WP-C21 implements
  the transaction engine. It is documented, not half-implemented: the guard,
  the capacity policy, and the mount state are real (and exercised in tests),
  but the byte path raises rather than writing.

Content addressing
------------------
Every ``put`` returns an :class:`ArtifactDescriptor` keyed by the SHA-256 of the
bytes (``sha256:<64 lowercase hex>``), mirroring the digest policy in
:mod:`srl.contracts.artifact_refs`. The store never trusts a caller-supplied
digest: the descriptor's digest is computed from the bytes the store actually
received, so the key is a function of content, not of a claim.

Integrity
---------
:class:`LocalArtifactStore` writes each object to a path derived from its
digest and verifies the digest on every ``get`` and ``fsck``. A mismatch raises
:class:`StoreIntegrityError` (``CAS_INTEGRITY_FAILURE``, hard stop) so a
corrupted object is never silently returned.
"""

from __future__ import annotations

import abc
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn

from srl.cas.capacity import (
    CapacityDecision,
    ObjectClass,
    check_capacity,
)
from srl.cas.privacy import redact_store_path
from srl.cas.t7_identity import (
    WAIT_STORAGE_FAIL_REASON,
    MountInfoProvider,
    default_mount_info_provider,
    load_expected_identity,
    verify_t7_identity,
)
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Schema identity for the artifact descriptor. Bumped on a descriptor shape
# change.
ARTIFACT_DESCRIPTOR_SCHEMA_VERSION: Final[str] = "ArtifactDescriptor/v1"

# Digest policy: "sha256:" + 64 lowercase hex. Mirrors artifact_refs so a
# descriptor's digest is interchangeable with an ArtifactRef digest.
_DIGEST_PATTERN: Final[str] = r"^sha256:[0-9a-f]{64}$"
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(_DIGEST_PATTERN)

# The typed fail reason for a CAS integrity failure. Mirrors the
# ``CAS_INTEGRITY_FAILURE`` entry in ``automation/fail-reasons.json`` (class
# ``canonical``, ``hard_stop=true``, ``retriable=false``).
CAS_INTEGRITY_FAIL_REASON: Final[str] = "CAS_INTEGRITY_FAILURE"

# The typed fail reason emitted by the abstract store for a contract-structural
# failure (bad digest argument, bad root). Reuses CONTRACT_INVALID so the
# storage contract family shares the canonical contract reason.
STORE_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON


class StoreError(ContractError):
    """Typed base for all content-addressed store failures.

    Every store operation failure derives from this class so a caller can catch
    the store family with one ``except StoreError``. Each subclass pins its
    ``fail_reason`` at construction; the default is ``CONTRACT_INVALID`` for
    structural failures (bad digest, bad root).
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = STORE_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


class StoreIntegrityError(StoreError):
    """Raised when a stored object's bytes do not match its content digest.

    A content-addressed store keys objects by their SHA-256; on read (and on
    ``fsck``) it recomputes the digest and compares. A mismatch means the stored
    bytes were corrupted (bit rot, partial write, concurrent mutation). This is
    a hard stop: a corrupted object is never silently returned.
    """

    def __init__(self, message: str, *, digest: str = "") -> None:
        super().__init__(message, fail_reason=CAS_INTEGRITY_FAIL_REASON)
        self.digest: str = digest


class StoreWaitError(StoreError):
    """Raised when a store operation must wait for an unavailable resource.

    The T7 volume is absent, ambiguous, or (for the stub) unimplemented. The
    store raises this rather than failing the mission so the autonomy machinery
    can retry once the resource appears. Carries
    ``fail_reason='WAIT_STORAGE'``.
    """

    def __init__(self, message: str, *, reason: str = "") -> None:
        super().__init__(message, fail_reason=WAIT_STORAGE_FAIL_REASON)
        self.reason: str = reason


@dataclass(frozen=True)
class ArtifactDescriptor:
    """A content-addressed descriptor for stored bytes.

    The descriptor is what ``put`` returns and what ``get``/``has`` key on. It
    carries the digest (the authoritative key), the byte size, and a redacted
    store-location token (never a raw path). The ``store_root_redacted`` field
    lets a receipt identify which store holds the object without leaking the
    operator's filesystem layout.

    Attributes
    ----------
    schema_version:
        Const ``"ArtifactDescriptor/v1"`` identity anchor.
    digest:
        ``sha256:<64 lowercase hex>`` — the SHA-256 of the stored bytes.
    size_bytes:
        Non-negative integer byte count of the stored bytes.
    store_root_redacted:
        ``redacted:<16 hex>`` token for the store root (see
        :func:`~srl.cas.privacy.redact_store_path`). Never a raw path.
    """

    schema_version: str
    digest: str
    size_bytes: int
    store_root_redacted: str


@dataclass(frozen=True)
class FsckReport:
    """The result of an :class:`ArtifactStore` integrity sweep (``fsck``).

    A content-addressed store is self-verifying: every object's path is derived
    from its digest, and the bytes must hash back to that digest. ``fsck`` walks
    the store, recomputes each digest, and reports the count of objects checked,
    the count that passed, and the digests of any that failed.

    Attributes
    ----------
    objects_checked:
        Number of objects found and hashed.
    objects_passed:
        Number whose recomputed digest matched their key.
    failed_digests:
        Digests of objects whose bytes did not hash back to their key. A
        non-empty list means the store is corrupt; the caller treats this as a
        hard stop (``CAS_INTEGRITY_FAILURE``).
    """

    objects_checked: int
    objects_passed: int
    failed_digests: list[str]


def _digest_of(data: bytes) -> str:
    """Return the canonical ``sha256:<hex>`` digest for ``data``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _validate_digest_argument(digest: str) -> None:
    """Validate a caller-supplied digest argument; raise :class:`StoreError`.

    ``get``/``has`` take a digest key. A malformed key is a caller bug, not a
    storage failure, so it raises the contract-structural ``StoreError``.
    """
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        msg = f"digest argument must match {_DIGEST_PATTERN!r}, got {digest!r}"
        raise StoreError(msg)


class ArtifactStore(abc.ABC):
    """Abstract interface for a content-addressed byte store.

    Every SRL store implements four operations:

    - :meth:`put` — store bytes, return an :class:`ArtifactDescriptor` keyed by
      the SHA-256 of the bytes;
    - :meth:`has` — test whether a digest is present;
    - :meth:`get` — return the bytes for a digest, verifying integrity;
    - :meth:`fsck` — sweep the store and report integrity.

    The interface is deliberately minimal: it is a byte store, not an object
    store. Object identity (the scientific fabric's ``object_id``) is layered
    above this via :mod:`srl.contracts.ids`; the CAS layer only promises that the
    bytes keyed by a digest are the bytes that hash to that digest.
    """

    @abc.abstractmethod
    def put(self, data: bytes) -> ArtifactDescriptor:
        """Store ``data`` and return its content-addressed descriptor.

        The descriptor's digest is the SHA-256 of ``data`` (never a
        caller-supplied value). Implementations may refuse the ingest (e.g. the
        T7 stub raises ``WAIT_STORAGE``; a capacity-exceeded store raises
        ``T7_QUOTA_EXCEEDED``).
        """

    @abc.abstractmethod
    def has(self, digest: str) -> bool:
        """Return True iff an object with ``digest`` is present in the store."""

    @abc.abstractmethod
    def get(self, digest: str) -> bytes:
        """Return the bytes keyed by ``digest``, verifying integrity on read.

        Raises :class:`StoreError` if ``digest`` is absent or malformed, and
        :class:`StoreIntegrityError` if the stored bytes do not hash back to
        ``digest``.
        """

    @abc.abstractmethod
    def fsck(self) -> FsckReport:
        """Sweep the store and return an :class:`FsckReport`."""


class LocalArtifactStore(ArtifactStore):
    """A directory-rooted content-addressed store (the only WP-C20 writer).

    Objects are stored at ``<root>/objects/<dd>/<digest>`` where ``dd`` is the
    first two hex characters of the digest (a sharded layout that keeps any one
    directory small). Writes are atomic: each object is written to a temporary
    file and renamed into place, so a reader never observes a partial write.

    The store is integrity-checked on every :meth:`get` and on :meth:`fsck`: the
    bytes are re-hashed and compared to the key digest. A mismatch raises
    :class:`StoreIntegrityError` (hard stop).

    Parameters
    ----------
    root:
        The directory to root the store at. Must be explicitly passed (never
        defaulted to a home or temp location). The directory is created if it
        does not exist (the ``objects`` shard tree along with it).

    Notes
    -----
    This is the **only** store implementation permitted to write in WP-C20. It
    is used for public tiny fixtures (via the fallback) and as the test backend.
    """

    def __init__(self, root: str | Path) -> None:
        root_path = Path(root)
        if root_path.is_absolute() and str(root_path).startswith(("/Volumes/", "/Users/")):
            # The store root must be explicitly passed; if it happens to be a
            # host-local path we accept it (a T7-backed LocalArtifactStore is a
            # legitimate test configuration) but we never echo it unredacted.
            pass
        self._root: Path = root_path
        (self._root / "objects").mkdir(parents=True, exist_ok=True)
        self._store_root_redacted = redact_store_path(self._root)

    @property
    def store_root_redacted(self) -> str:
        """The redacted token for this store's root (never a raw path)."""
        return self._store_root_redacted

    @property
    def objects_dir(self) -> Path:
        """The sharded objects directory (``<root>/objects``).

        Exposed (not underscore-prefixed) so the fallback policy layer can sum
        aggregate usage without reaching into the store's internals. The path
        itself is not a public-API string output (receipts use
        :attr:`store_root_redacted`); this accessor is for byte accounting only.
        """
        return self._root / "objects"

    def _object_path(self, digest: str) -> Path:
        """Return the on-disk path for ``digest`` (sharded by first two hex)."""
        # digest is "sha256:<64 hex>"; the shard is the first two hex after the
        # prefix, the filename is the full digest.
        hex_part = digest.removeprefix("sha256:")
        shard = hex_part[:2]
        return self._root / "objects" / shard / digest

    def put(self, data: bytes) -> ArtifactDescriptor:
        digest = _digest_of(data)
        target = self._object_path(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: write to a temp file in the same directory, fsync,
            # then rename into place. rename is atomic on POSIX, so a concurrent
            # reader never sees a partial object.
            fd, tmp_name = tempfile.mkstemp(prefix=".put-", dir=target.parent)
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, target)
            except BaseException:
                # Clean up the temp file on any failure (including
                # KeyboardInterrupt) so the shard dir is not littered.
                tmp_path.unlink(missing_ok=True)
                raise
        return ArtifactDescriptor(
            schema_version=ARTIFACT_DESCRIPTOR_SCHEMA_VERSION,
            digest=digest,
            size_bytes=len(data),
            store_root_redacted=self._store_root_redacted,
        )

    def has(self, digest: str) -> bool:
        _validate_digest_argument(digest)
        return self._object_path(digest).is_file()

    def get(self, digest: str) -> bytes:
        _validate_digest_argument(digest)
        path = self._object_path(digest)
        if not path.is_file():
            msg = f"no object with digest {digest!r} in store {self._store_root_redacted}"
            raise StoreError(msg)
        data = path.read_bytes()
        actual = _digest_of(data)
        if actual != digest:
            msg = (
                f"integrity failure: object {digest!r} stored bytes hash to {actual!r} "
                f"(store {self._store_root_redacted})"
            )
            raise StoreIntegrityError(msg, digest=digest)
        return data

    def fsck(self) -> FsckReport:
        checked = 0
        passed = 0
        failed: list[str] = []
        objects_dir = self._root / "objects"
        if objects_dir.is_dir():
            for shard in sorted(objects_dir.iterdir()):
                if not shard.is_dir():
                    continue
                for obj in sorted(shard.iterdir()):
                    if not obj.is_file():
                        continue
                    checked += 1
                    data = obj.read_bytes()
                    if _digest_of(data) == obj.name:
                        passed += 1
                    else:
                        failed.append(obj.name)
        return FsckReport(
            objects_checked=checked,
            objects_passed=passed,
            failed_digests=failed,
        )


class T7ArtifactStore(ArtifactStore):
    """A T7-volume content-addressed store — **stub, refuses all operations**.

    The T7 store is the eventual home for T7-bound content (pack images, run
    receipts, datasets). Its identity guard, capacity policy, and mount-state
    probe are real (and exercised in tests), but the byte path is **not**
    implemented in WP-C20: every ``put`` / ``get`` / ``has`` raises
    :class:`StoreWaitError` (``WAIT_STORAGE``) so callers fail-fast toward the
    wait path rather than discovering a silent no-op.

    WP-C21 implements the transaction engine that makes the byte path safe
    (atomic cross-object writes with a write-ahead log). Until then this stub
    exists to make the contract explicit: the store is *known* and *named*, its
    identity and capacity are *verified*, but it does not write.

    Parameters
    ----------
    expected_uuid:
        The expected T7 Volume UUID. Either pass it directly or load it via
        :func:`~srl.cas.t7_identity.load_expected_identity` from an out-of-repo
        config.
    mount_point:
        The absolute path the T7 volume is expected at.
    provider:
        Injectable volume-identity provider. Tests pass a fake; production wires
        :func:`~srl.cas.t7_identity.default_mount_info_provider`.
    identity_config_path:
        Optional path to an out-of-repo identity config JSON. If given,
        ``expected_uuid`` is loaded from it (and an explicit ``expected_uuid``
        argument is rejected to avoid two sources of truth).
    """

    # The reason every operation refuses: the transaction engine is not yet
    # implemented (WP-C21). Surfaced in the StoreWaitError so a receipt records
    # the wait cause.
    _UNIMPLEMENTED_REASON: Final[str] = "t7_transaction_engine_unimplemented"

    def __init__(
        self,
        *,
        mount_point: str,
        provider: MountInfoProvider | None = None,
        expected_uuid: str | None = None,
        identity_config_path: str | Path | None = None,
    ) -> None:
        if expected_uuid is not None and identity_config_path is not None:
            msg = "pass either expected_uuid or identity_config_path, not both"
            raise StoreError(msg)
        if identity_config_path is not None:
            # Load (and validate) the expected identity up front so a missing or
            # malformed config fails at construction, not on first use.
            expected_uuid = load_expected_identity(identity_config_path)
        if expected_uuid is None:
            msg = "T7ArtifactStore requires expected_uuid or identity_config_path"
            raise StoreError(msg)
        self._expected_uuid: str = expected_uuid
        self._mount_point: str = mount_point
        self._provider: MountInfoProvider = (
            provider if provider is not None else default_mount_info_provider
        )
        # Verify the volume identity at construction so a wrong-volume or
        # unavailable T7 is surfaced immediately (fail closed / wait early),
        # rather than on the first refused operation. The result is retained so
        # tests can assert the guard ran.
        self._identity_receipt = verify_t7_identity(
            expected_uuid=self._expected_uuid,
            mount_point=self._mount_point,
            provider=self._provider,
        )

    @property
    def identity_receipt(self) -> dict[str, str]:
        """The receipt from the construction-time identity verification."""
        return dict(self._identity_receipt)

    def _refuse(self, op: str) -> NoReturn:
        msg = (
            f"T7ArtifactStore.{op} refused: the T7 transaction engine is not "
            f"implemented (WAIT_STORAGE until WP-C21)"
        )
        raise StoreWaitError(msg, reason=self._UNIMPLEMENTED_REASON)

    def put(self, data: bytes) -> ArtifactDescriptor:
        del data  # unused: the stub never reads the bytes
        self._refuse("put")

    def has(self, digest: str) -> bool:
        del digest  # unused: the stub never consults the digest
        self._refuse("has")

    def get(self, digest: str) -> bytes:
        del digest  # unused: the stub never consults the digest
        self._refuse("get")

    def fsck(self) -> FsckReport:
        self._refuse("fsck")

    def check_capacity_for(self, used_bytes: int) -> CapacityDecision:
        """Consult the capacity policy (real, even on the stub).

        The capacity policy is real so a caller can ask "would this ingest fit?"
        without the transaction engine. ``EXCEEDED`` means the caller should
        raise ``T7_QUOTA_EXCEEDED``; the stub itself does not ingest either way.
        """
        return check_capacity(used_bytes)

    def object_class_bound(self, object_class: ObjectClass) -> bool:
        """Return True iff ``object_class`` is T7-bound (must use this store)."""
        return object_class.t7_bound


__all__ = [
    "ARTIFACT_DESCRIPTOR_SCHEMA_VERSION",
    "CAS_INTEGRITY_FAIL_REASON",
    "STORE_FAIL_REASON",
    "ArtifactDescriptor",
    "ArtifactStore",
    "FsckReport",
    "LocalArtifactStore",
    "StoreError",
    "StoreIntegrityError",
    "StoreWaitError",
    "T7ArtifactStore",
]
