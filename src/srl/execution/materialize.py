"""Run materialization: stage exact content-addressed refs for execution (WP-D32).

The materializer turns a content-addressed run specification into a private,
verified staging tree. Every input is referenced by a ``sha256:<64 hex>`` digest
and is resolved from the supplied store before it is copied into the staging tree.
After the copy, the staged bytes are re-hashed and compared to the declared
digest: a mismatch is a ``CAS_INTEGRITY_FAILURE`` and aborts the run before any
adapter is invoked. Unpinned or malformed references are ``CONTRACT_INVALID``.

The staged tree is owned by the execution layer: inputs are made read-only
(``0o400``) so a misbehaving adapter cannot mutate its own inputs. The pack
reference (if any) is staged as an immutable blob; the staging directory itself
is fresh for every run so concurrent runs cannot collide.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from srl.cas.engine import CasIntegrityError
from srl.cas.store import ArtifactStore
from srl.contracts.artifact_refs import validate_digest
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Schema identity for receipts produced by the materializer.
STAGING_RECEIPT_SCHEMA_VERSION: Final[str] = "MaterializationReceipt/v1"

# Canonical JSON separators and newline contract, mirroring the contracts pkg.
_SEP: Final[tuple[str, str]] = (",", ":")
_NEWLINE: Final[str] = "\n"
_ENCODING: Final[str] = "utf-8"

# The name used for the staged pack blob when a run references a pack digest.
_PACK_BLOB_NAME: Final[str] = "pack.blob"

# Input file mode: read-only for the owner (no write, no execute).
_INPUT_MODE: Final[int] = 0o400


class MaterializationError(ContractError):
    """Raised when a run specification or staging operation violates a contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` for structural errors
    (malformed digests, missing run-spec keys, unpinned references). CAS
    integrity failures are raised as :class:`~srl.cas.engine.CasIntegrityError`
    directly so they keep the ``CAS_INTEGRITY_FAILURE`` reason.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


@dataclass(frozen=True)
class StagedRun:
    """A run whose inputs and optional pack are staged and hash-verified.

    Attributes
    ----------
    adapter_id:
        The adapter that will execute the run.
    staging_path:
        The private staging directory containing the inputs and optional pack.
    input_digests:
        Mapping from input name to the verified ``sha256:<64 hex>`` digest. The
        digests are the exact references bound by the run receipt in the sealer.
    pack_digest:
        The verified ``sha256:<64 hex>`` pack digest, or ``None`` if the run does
        not reference a pack.
    """

    adapter_id: str
    staging_path: Path
    input_digests: dict[str, str]
    pack_digest: str | None


@dataclass(frozen=True)
class MaterializationReceipt:
    """MaterializationReceipt/v1: evidence that a run was staged and verified."""

    schema_version: str
    adapter_id: str
    staging_path: str
    input_digests: dict[str, str]
    pack_digest: str | None
    verified: bool
    materialized_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        """Return the receipt as a plain JSON-serializable dict."""
        return {
            "schema_version": self.schema_version,
            "adapter_id": self.adapter_id,
            "staging_path": self.staging_path,
            "input_digests": dict(self.input_digests),
            "pack_digest": self.pack_digest,
            "verified": self.verified,
            "materialized_at_utc": self.materialized_at_utc,
        }

    def canonical_dumps(self) -> bytes:
        """Return canonical JSON bytes for the receipt."""
        return dumps(self.to_dict())


def _sha256_hex(data: bytes) -> str:
    """Return the bare 64-hex SHA-256 of ``data`` (no ``sha256:`` prefix)."""
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    """Return an ISO 8601 UTC timestamp string with a trailing ``Z``."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _require_safe_digest(digest: str, *, label: str) -> str:
    """Validate ``digest`` as ``sha256:<64 hex>``; raise MaterializationError on mismatch.

    A malformed digest is treated as an unpinned reference (``CONTRACT_INVALID``).
    """
    try:
        return validate_digest(digest, field=label)
    except ContractError as exc:
        raise MaterializationError(f"invalid {label}: {exc}") from exc


def _resolve_ref(store: ArtifactStore, digest: str, *, label: str) -> bytes:
    """Resolve a pinned digest from ``store``; raise if unpinned or corrupt.

    An unpinned reference (not present in the store) is a ``CONTRACT_INVALID``
    contract error. A corrupt object is surfaced by the store as a CAS integrity
    failure and is allowed to propagate unchanged.
    """
    _require_safe_digest(digest, label=label)
    if not store.has(digest):
        raise MaterializationError(f"unpinned {label}: {digest!r} not in store")
    return store.get(digest)


def _verify_and_stage(
    data: bytes,
    declared_digest: str,
    dest: Path,
    *,
    mode: int | None = None,
) -> None:
    """Write ``data`` to ``dest`` and verify it hashes to ``declared_digest``.

    If the read-back hash does not match the declared digest, delete the staged
    file and raise :class:`~srl.cas.engine.CasIntegrityError` with the typed
    reason ``CAS_INTEGRITY_FAILURE``.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    if mode is not None:
        os.chmod(dest, mode)
    readback = dest.read_bytes()
    actual = "sha256:" + _sha256_hex(readback)
    if actual != declared_digest:
        dest.unlink(missing_ok=True)
        msg = (
            f"post-copy hash mismatch for {dest.name!r}: declared {declared_digest!r}, "
            f"observed {actual!r}"
        )
        raise CasIntegrityError(
            msg,
            expected_digest=declared_digest,
            observed_digest=actual,
        )


def _validate_run_spec(run_spec: object) -> dict[str, Any]:
    """Validate the shape of ``run_spec``; return it as a confirmed dict.

    Required keys: ``adapter_id`` (str), ``input_payloads`` (dict), and
    ``pack_ref`` (str or None). Any structural deviation raises
    :class:`MaterializationError` (``CONTRACT_INVALID``).
    """
    if not isinstance(run_spec, dict):
        raise MaterializationError("run_spec must be a dict")
    missing = sorted({"adapter_id", "input_payloads", "pack_ref"} - set(run_spec.keys()))
    if missing:
        raise MaterializationError(f"run_spec missing key(s): {missing}")

    adapter_id = run_spec["adapter_id"]
    if not isinstance(adapter_id, str) or not adapter_id:
        raise MaterializationError("run_spec.adapter_id must be a non-empty string")

    input_payloads = run_spec["input_payloads"]
    if not isinstance(input_payloads, dict):
        raise MaterializationError("run_spec.input_payloads must be a dict")
    for key, value in input_payloads.items():
        if not isinstance(key, str):
            raise MaterializationError("run_spec.input_payloads keys must be strings")
        if not isinstance(value, str):
            raise MaterializationError(
                f"run_spec.input_payloads[{key!r}] must be a sha256 digest string"
            )

    pack_ref = run_spec["pack_ref"]
    if pack_ref is not None and not isinstance(pack_ref, str):
        raise MaterializationError("run_spec.pack_ref must be a sha256 digest string or None")

    return run_spec


def materialize_run(
    run_spec: dict[str, Any],
    store: ArtifactStore,
    staging_root: str | Path,
) -> StagedRun:
    """Materialize a content-addressed run specification into a fresh staging tree.

    The flow is exactly: resolve exact references from the store, copy the bytes
    into a fresh staging directory, post-copy SHA-256 verification, and make the
    inputs read-only. Any integrity mismatch aborts with
    ``CAS_INTEGRITY_FAILURE``; any unpinned or malformed reference aborts with
    ``CONTRACT_INVALID``.

    Parameters
    ----------
    run_spec:
        A dict with keys ``adapter_id`` (str), ``input_payloads`` (dict mapping
        input name to ``sha256:<64 hex>`` digest), and ``pack_ref`` (digest or
        ``None``).
    store:
        The content-addressed store used to resolve the input and pack digests.
    staging_root:
        A directory under which a fresh per-run staging directory will be
        created. Created if it does not exist.

    Returns
    -------
    StagedRun
        The verified run with the staging path and bound digests.

    Raises
    ------
    MaterializationError
        If the run spec is malformed or a reference is unpinned
        (``CONTRACT_INVALID``).
    CasIntegrityError
        If the staged bytes do not hash to the declared digest
        (``CAS_INTEGRITY_FAILURE``).
    """
    spec = _validate_run_spec(run_spec)
    adapter_id = spec["adapter_id"]
    input_payloads: dict[str, str] = spec["input_payloads"]
    pack_ref: str | None = spec["pack_ref"]

    root_path = Path(staging_root)
    root_path.mkdir(parents=True, exist_ok=True)
    staging_str = tempfile.mkdtemp(prefix="srl-run-", dir=root_path)
    staging_path = Path(staging_str)

    try:
        input_digests: dict[str, str] = {}
        for name, digest in input_payloads.items():
            data = _resolve_ref(store, digest, label=f"input_payloads[{name!r}]")
            dest = staging_path / name
            _verify_and_stage(data, digest, dest, mode=_INPUT_MODE)
            input_digests[name] = digest

        staged_pack_digest: str | None = None
        if pack_ref is not None:
            data = _resolve_ref(store, pack_ref, label="pack_ref")
            dest = staging_path / _PACK_BLOB_NAME
            _verify_and_stage(data, pack_ref, dest)
            staged_pack_digest = pack_ref

        return StagedRun(
            adapter_id=adapter_id,
            staging_path=staging_path,
            input_digests=input_digests,
            pack_digest=staged_pack_digest,
        )
    except Exception:
        # On any failure before the StagedRun is handed back, remove the fresh
        # staging tree so the caller is not left with a half-staged run.
        shutil.rmtree(staging_path, ignore_errors=True)
        raise


__all__ = [
    "STAGING_RECEIPT_SCHEMA_VERSION",
    "MaterializationError",
    "MaterializationReceipt",
    "StagedRun",
    "materialize_run",
]
