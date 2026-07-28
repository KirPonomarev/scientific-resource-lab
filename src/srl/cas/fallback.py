"""Local fallback store for public tiny fixtures only.

The T7 volume is the authoritative home for T7-bound content (pack images, run
receipts, datasets, source blobs, pilot runs, catalog/SBOM, quarantine). When
the T7 is unavailable the store *waits* (``WAIT_STORAGE``); it never falls back
to a local volume for T7-bound content, because a local copy is not the
authoritative record.

The one exception is **public tiny fixtures**: small, public, reproducible test
vectors that are not T7-bound (they are public inputs to conformance checks, not
mission outputs). These may live in a local fallback store so a CI run on a
machine without the T7 can still exercise the conformance path.

This module enforces the fallback policy with hard limits:

- **single-object max 1 MiB** — a fixture larger than this is refused with
  ``WAIT_STORAGE`` (it is not "tiny" and should not fall back);
- **total max 25 MiB** — the fallback store's aggregate usage is capped at a
  small fraction of the T7 ceiling so it cannot silently become a shadow store;
- **T7-bound object classes refused** — any object whose class is T7-bound
  (everything except :attr:`~srl.cas.capacity.ObjectClass.FIXTURE`) is refused
  with ``WAIT_STORAGE`` regardless of size;
- **root must be inside an explicitly passed directory** — the fallback never
  invents its own root (no home, no temp default); the caller owns the location.

The fallback is a thin policy layer over :class:`~srl.cas.store.LocalArtifactStore`:
it validates the ingest against the policy, then delegates the byte path to the
local store. This keeps one writer (the local store) and one policy (here).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from srl.cas.capacity import ObjectClass
from srl.cas.store import (
    ArtifactDescriptor,
    ArtifactStore,
    FsckReport,
    LocalArtifactStore,
    StoreWaitError,
)
from srl.cas.t7_identity import WAIT_STORAGE_FAIL_REASON

# Single-object limit: 1 MiB. A fixture above this is not "tiny" and must not
# fall back; it waits for the T7 (or is reconsidered for the catalog).
_FALLBACK_SINGLE_OBJECT_MAX_BYTES: Final[int] = 1024 * 1024  # 1 MiB

# Aggregate limit: 25 MiB. The fallback store may never hold more than this in
# total, so it cannot silently become a shadow T7.
_FALLBACK_TOTAL_MAX_BYTES: Final[int] = 25 * 1024 * 1024  # 25 MiB

# Re-exported for callers that want the limit symbols.
FALLBACK_SINGLE_OBJECT_MAX_BYTES: Final[int] = _FALLBACK_SINGLE_OBJECT_MAX_BYTES
FALLBACK_TOTAL_MAX_BYTES: Final[int] = _FALLBACK_TOTAL_MAX_BYTES

# The refusal fail reason is WAIT_STORAGE: a fallback refusal means the object
# should live on the T7 (which is unavailable), so the caller waits. Expressed
# as an explicit raise (not ``assert``) so the guard survives ``python -O`` and
# does not trip the bandit S101 rule that fires on bare ``assert``.
if WAIT_STORAGE_FAIL_REASON != "WAIT_STORAGE":  # pragma: no cover
    raise RuntimeError("WAIT_STORAGE_FAIL_REASON constant has drifted")


def _refuse_wait(message: str, *, reason: str) -> None:
    """Raise a StoreWaitError carrying the WAIT_STORAGE fail reason."""
    raise StoreWaitError(message, reason=reason)


class LocalFallbackStore(ArtifactStore):
    """A local fallback store for public tiny fixtures only.

    Wraps a :class:`~srl.cas.store.LocalArtifactStore` and enforces the fallback
    policy on every ``put``: the object class must be
    :attr:`~srl.cas.capacity.ObjectClass.FIXTURE`, the size must be at or below
    :data:`FALLBACK_SINGLE_OBJECT_MAX_BYTES`, and the store's aggregate usage
    (including the new object) must stay at or below
    :data:`FALLBACK_TOTAL_MAX_BYTES`.

    Parameters
    ----------
    root:
        The directory to root the fallback store at. Must be explicitly passed;
        the fallback never invents its own root.

    Notes
    -----
    The fallback delegates ``has`` / ``get`` / ``fsck`` to the underlying local
    store unchanged — those operations do not change usage and the policy is
    about *ingest*, not reads.
    """

    def __init__(self, root: str | Path) -> None:
        if root is None or (isinstance(root, (str, Path)) and str(root) == ""):
            msg = "LocalFallbackStore root must be an explicitly passed non-empty path"
            raise StoreWaitError(msg, reason="fallback_root_not_explicit")
        self._store = LocalArtifactStore(root)

    @property
    def store_root_redacted(self) -> str:
        """The redacted token for this store's root (never a raw path)."""
        return self._store.store_root_redacted

    def _current_usage_bytes(self) -> int:
        """Return the aggregate byte usage of the underlying local store."""
        # Walk the objects dir once and sum file sizes. The fallback is bounded
        # at 25 MiB so this is cheap and acceptable on every put.
        total = 0
        objects_dir = self._store.objects_dir
        if objects_dir.is_dir():
            for shard in objects_dir.iterdir():
                if not shard.is_dir():
                    continue
                for obj in shard.iterdir():
                    if obj.is_file():
                        total += obj.stat().st_size
        return total

    def put(
        self,
        data: bytes,
        *,
        object_class: ObjectClass = ObjectClass.FIXTURE,
    ) -> ArtifactDescriptor:
        """Store ``data`` iff it satisfies the fallback policy.

        Parameters
        ----------
        data:
            The bytes to store.
        object_class:
            The object class of ``data``. Must be
            :attr:`~srl.cas.capacity.ObjectClass.FIXTURE`; any T7-bound class is
            refused with ``WAIT_STORAGE``.

        Raises
        ------
        StoreWaitError
            If ``object_class`` is T7-bound, if ``data`` exceeds the
            single-object limit, or if the ingest would exceed the total limit.
        """
        if object_class.t7_bound:
            msg = (
                f"LocalFallbackStore refuses T7-bound object class "
                f"{object_class.value!r}; WAIT_STORAGE for the T7 volume"
            )
            _refuse_wait(msg, reason="t7_bound_class_refused")
        size = len(data)
        if size > _FALLBACK_SINGLE_OBJECT_MAX_BYTES:
            msg = (
                f"LocalFallbackStore refuses object of {size} bytes (single-object "
                f"limit {_FALLBACK_SINGLE_OBJECT_MAX_BYTES} bytes); WAIT_STORAGE"
            )
            _refuse_wait(msg, reason="single_object_limit_exceeded")
        # Check the digest first so we can test presence (a re-put of the same
        # object does not grow usage). This avoids rejecting an idempotent
        # re-put that would keep usage flat.
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if not self._store.has(digest):
            usage = self._current_usage_bytes()
            if usage + size > _FALLBACK_TOTAL_MAX_BYTES:
                msg = (
                    f"LocalFallbackStore refuses object of {size} bytes: aggregate "
                    f"{usage + size} bytes would exceed total limit "
                    f"{_FALLBACK_TOTAL_MAX_BYTES} bytes; WAIT_STORAGE"
                )
                _refuse_wait(msg, reason="total_limit_exceeded")
        return self._store.put(data)

    def has(self, digest: str) -> bool:
        return self._store.has(digest)

    def get(self, digest: str) -> bytes:
        return self._store.get(digest)

    def fsck(self) -> FsckReport:
        return self._store.fsck()


__all__ = [
    "FALLBACK_SINGLE_OBJECT_MAX_BYTES",
    "FALLBACK_TOTAL_MAX_BYTES",
    "LocalFallbackStore",
]
