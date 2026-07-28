"""Materialize a verified resource pack into a mutable staging area.

Materialization is the bridge between the immutable pack store and execution: it
verifies the pack tree hash, refuses to execute directly from an immutable store
(marked by a ``.srl_immutable`` flag file), copies the contents into a staging
area, and re-verifies the hash after the copy. The result is a
``MaterializationReceipt/v1`` that records both source and destination tree
hashes for later audit.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.packs.manifest import (
    PACK_INTEGRITY_FAILURE_REASON,
    ResourcePackManifest,
    build_manifest,
    compute_tree_sha256,
)

# Flag file that marks an immutable CAS / pack store root.
_IMMUTABLE_FLAG: Final[str] = ".srl_immutable"


class MaterializationError(ContractError):
    """Raised when materialization fails an integrity check.

    Carries the typed fail reason ``PACK_INTEGRITY_FAILURE``.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = PACK_INTEGRITY_FAILURE_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    """MaterializationReceipt/v1: evidence that a pack was copied and verified."""

    schema_version: str
    pack_id: str
    from_tree_sha256: str
    to_tree_sha256: str
    verified: bool
    staging_path: str
    materialized_at_utc: str
    canonical_writes: int
    grants_authority: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the receipt as a plain JSON-serializable dict."""
        return {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "from_tree_sha256": self.from_tree_sha256,
            "to_tree_sha256": self.to_tree_sha256,
            "verified": self.verified,
            "staging_path": self.staging_path,
            "materialized_at_utc": self.materialized_at_utc,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }

    def canonical_dumps(self) -> bytes:
        """Return canonical JSON bytes for the receipt."""
        return dumps(self.to_dict())


RECEIPT_SCHEMA_VERSION: Final[str] = "MaterializationReceipt/v1"


def _utc_now() -> str:
    """Return an ISO 8601 UTC timestamp string with a trailing Z."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _is_immutable_root(path: Path) -> bool:
    """Return True if ``path`` or any ancestor up to filesystem root is immutable.

    An immutable store is marked by a ``.srl_immutable`` flag file. Checking
    ancestors ensures we refuse to run from a directory that is itself inside a
    CAS store.
    """
    current = path.resolve()
    while True:
        if (current / _IMMUTABLE_FLAG).exists():
            return True
        parent = current.parent
        if parent == current:
            break
        current = parent
    return False


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy a directory tree from ``src`` to ``dst`` preserving only content.

    Permissions are reset to the deterministic normalized values: directories
    ``0o755``, regular files ``0o644``. The destination is created fresh.
    """
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False, copy_function=shutil.copy2)
    # Reset permissions deterministically. copy2 may preserve source modes;
    # we normalize them so the receipt is independent of source mode.
    for dirpath, dirnames, filenames in os.walk(dst):
        for dirname in dirnames:
            (Path(dirpath) / dirname).chmod(0o755)
        for filename in filenames:
            (Path(dirpath) / filename).chmod(0o644)


def materialize(
    manifest: ResourcePackManifest | dict[str, Any],
    pack_root: str | Path,
    staging: str | Path,
) -> MaterializationReceipt:
    """Materialize ``pack_root`` into ``staging`` after integrity checks.

    Parameters
    ----------
    manifest:
        A validated :class:`ResourcePackManifest` or raw dict.
    pack_root:
        Directory containing the already-extracted pack contents.
    staging:
        Destination directory that will be created fresh with the verified pack.

    Returns
    -------
    MaterializationReceipt
        A receipt recording the before/after tree hashes.

    Raises
    ------
    MaterializationError
        With fail reason ``PACK_INTEGRITY_FAILURE`` if the pack root is marked
        immutable, the tree hash does not match, or post-copy verification fails.
    PackManifestError
        If ``manifest`` is a raw dict that fails validation.
    """
    if isinstance(manifest, dict):
        manifest = build_manifest(manifest)

    pack_root_path = Path(pack_root)
    staging_path = Path(staging)

    if not pack_root_path.is_dir():
        raise MaterializationError(f"pack_root is not a directory: {pack_root_path}")

    if _is_immutable_root(pack_root_path):
        raise MaterializationError(
            "mutable T7 execution forbidden: pack_root is inside an immutable store"
        )

    observed_tree = compute_tree_sha256(pack_root_path)
    if observed_tree != manifest.tree_sha256:
        raise MaterializationError(
            f"tree hash mismatch for pack {manifest.pack_id!r}: "
            f"manifest={manifest.tree_sha256!r}, observed={observed_tree!r}"
        )

    _copy_tree(pack_root_path, staging_path)
    copied_tree = compute_tree_sha256(staging_path)
    if copied_tree != manifest.tree_sha256:
        raise MaterializationError(
            f"post-copy tree hash mismatch for pack {manifest.pack_id!r}: "
            f"manifest={manifest.tree_sha256!r}, copied={copied_tree!r}"
        )

    return MaterializationReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        pack_id=manifest.pack_id,
        from_tree_sha256=observed_tree,
        to_tree_sha256=copied_tree,
        verified=True,
        staging_path=str(staging_path.resolve()),
        materialized_at_utc=_utc_now(),
        canonical_writes=0,
        grants_authority=False,
    )


__all__ = [
    "RECEIPT_SCHEMA_VERSION",
    "MaterializationError",
    "MaterializationReceipt",
    "materialize",
]
