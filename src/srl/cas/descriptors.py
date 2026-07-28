"""Canonical descriptors and ingest receipts for the CAS transaction engine.

This module owns the two canonical JSON records a content-addressed store writes
when it ingests bytes (see :mod:`srl.cas.engine` for the transaction that
produces them):

- :class:`ObjectDescriptor` — an ``ObjectDescriptor/v1`` record describing a
  published object: its content digest, byte size, media type, creation time, and
  the id of the ingest receipt that published it. It is written to
  ``<root>/descriptors/<digest>.json`` *after* the object bytes are durably
  published.
- :class:`IngestReceipt` — an ``IngestReceipt/v1`` record that is the **final**
  artifact of a successful ingest. It carries the digest, byte size, and the
  three integrity flags a reader needs to trust the published object
  (``source_hash_verified``, ``readback_hash_verified``, ``fsynced``).

Receipt-last invariant
----------------------
The transaction engine writes records in a strict order so a crash at any point
leaves either the old valid state or the new valid state — never a half-published
object:

1. write object bytes to a temp file in ``incoming/``;
2. ``fsync`` the temp file;
3. read the temp back, re-hash, and compare to the source hash;
4. ``os.replace`` the temp into ``objects/<shard>/<digest>`` (atomic publish);
5. ``fsync`` the containing directories;
6. write the descriptor;
7. write the ingest receipt **last**, and ``fsync`` it.

The descriptor's ``ingest_receipt_id`` is set from the receipt's id, but the
descriptor is only *durable* once the receipt exists: a reader that finds a
descriptor without a matching receipt treats the object as a candidate orphan
(see :mod:`srl.cas.fsck`). The receipt is therefore the commit marker: its
presence is the proof the ingest completed.

Identity policy
---------------
Both records carry a ``schema_version`` identity anchor and a content digest of
the form ``sha256:<64 lowercase hex>``. The digest is the content-addressed key;
it is computed by the store from the bytes, never supplied by the caller. The
``ingest_receipt_id`` is the SHA-256 of the canonical encoding of the receipt
*without* its own ``receipt_id`` field (see :func:`build_ingest_receipt`), so the
id is a pure function of the receipt's content — two independent stores that
ingest the same bytes at the same instant compute the same id.

Standard library only
---------------------
This module imports :mod:`srl.contracts` (which pulls ``jsonschema``) for the
canonical JSON encoding and the shared digest/byte-count validators. The CAS
engine is a control-plane component, so the dependency is acceptable; the
canonical encoding is never used in a hot byte loop (the hashes are computed
directly from the bytes in :mod:`srl.cas.engine`).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Final

from srl.contracts.artifact_refs import validate_digest, validate_media_type
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.numbers import validate_integer_byte_count
from srl.contracts.timestamps import validate as validate_timestamp

# Schema identity anchors. Bumped only on a record-shape change.
OBJECT_DESCRIPTOR_SCHEMA_VERSION: Final[str] = "ObjectDescriptor/v1"
INGEST_RECEIPT_SCHEMA_VERSION: Final[str] = "IngestReceipt/v1"

# The strict key sets for each record. A record with extra or missing keys is a
# structural failure (CONTRACT_INVALID), so the wire forms stay unambiguous.
_OBJECT_DESCRIPTOR_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "digest",
        "size_bytes",
        "media_type",
        "created_utc",
        "ingest_receipt_id",
    }
)
_INGEST_RECEIPT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "receipt_id",
        "digest",
        "size_bytes",
        "source_hash_verified",
        "readback_hash_verified",
        "fsynced",
        "created_utc",
    }
)

# Receipt id shape: "sha256:" + 64 lowercase hex (same policy as object ids).
_RECEIPT_ID_PATTERN: Final[str] = r"^sha256:[0-9a-f]{64}$"
_RECEIPT_ID_RE: Final[re.Pattern[str]] = re.compile(_RECEIPT_ID_PATTERN)


class DescriptorError(ContractError):
    """Typed base for descriptor/receipt structural failures.

    Carries ``fail_reason='CONTRACT_INVALID'`` and the offending ``field`` for
    diagnostics. Raised by :func:`validate_object_descriptor` and
    :func:`validate_ingest_receipt` when a record is malformed.
    """

    def __init__(
        self,
        message: str,
        *,
        field: str = "",
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.field: str = field


def _validate_receipt_id(value: Any, *, field: str = "receipt_id") -> str:
    """Validate ``value`` as a ``sha256:<64 hex>`` receipt id.

    The receipt id is the content-addressed identity of the receipt record. It
    uses the same shape as an object digest so the canonical-encoding machinery
    is reused, but it is kept as a distinct field name for readability.
    """
    if not isinstance(value, str):
        msg = f"field {field!r} must be a string, got {type(value).__name__}"
        raise DescriptorError(msg, field=field)
    if not _RECEIPT_ID_RE.fullmatch(value):
        msg = (
            f"field {field!r}={value!r} must match {_RECEIPT_ID_PATTERN!r} "
            "(sha256 + 64 lowercase hex)"
        )
        raise DescriptorError(msg, field=field)
    return value


def _require_str(value: Any, *, field: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise DescriptorError."""
    if not isinstance(value, str) or not value:
        msg = f"field {field!r} must be a non-empty string, got {type(value).__name__}"
        raise DescriptorError(msg, field=field)
    return value


def build_object_descriptor(
    *,
    digest: str,
    size_bytes: int,
    media_type: str,
    created_utc: str,
    ingest_receipt_id: str | None,
) -> dict[str, Any]:
    """Build an ``ObjectDescriptor/v1`` dict from its fields.

    The descriptor is the durable record describing a published object. It is
    written *after* the object bytes are published and *before* the ingest
    receipt. ``ingest_receipt_id`` is the id of the ingest receipt that
    published this object; it may be ``None`` only for a descriptor constructed
    before the receipt id is known (the engine always fills it in before
    writing the descriptor to disk).

    Parameters
    ----------
    digest:
        ``sha256:<64 hex>`` content digest of the object bytes.
    size_bytes:
        Non-negative integer byte count of the object bytes.
    media_type:
        IANA-style media type of the object bytes.
    created_utc:
        Canonical RFC 3339 UTC timestamp (seconds precision) marking the
        descriptor's creation.
    ingest_receipt_id:
        The id of the ingest receipt that published this object, or ``None``.

    Returns
    -------
    dict[str, Any]
        A plain dict in the ``ObjectDescriptor/v1`` shape, ready to canonicalize.

    Raises
    ------
    DescriptorError
        If any field is malformed.
    """
    validate_digest(digest, field="digest")
    try:
        validate_integer_byte_count(size_bytes, field="size_bytes")
    except ContractError as exc:
        raise DescriptorError(str(exc), field="size_bytes") from exc
    # validate_media_type raises ArtifactRefError (a ContractError); translate to
    # the descriptor family so a caller validating a descriptor gets one error
    # family with the offending field name.
    try:
        validate_media_type(media_type, field="media_type")
    except ContractError as exc:
        raise DescriptorError(str(exc), field="media_type") from exc
    try:
        validate_timestamp(created_utc)
    except ContractError as exc:
        raise DescriptorError(str(exc), field="created_utc") from exc
    if ingest_receipt_id is not None:
        _validate_receipt_id(ingest_receipt_id, field="ingest_receipt_id")
    return {
        "schema_version": OBJECT_DESCRIPTOR_SCHEMA_VERSION,
        "digest": digest,
        "size_bytes": size_bytes,
        "media_type": media_type,
        "created_utc": created_utc,
        "ingest_receipt_id": ingest_receipt_id,
    }


def validate_object_descriptor(value: Any) -> dict[str, Any]:
    """Validate ``value`` as an ``ObjectDescriptor/v1`` record.

    Parameters
    ----------
    value:
        Candidate descriptor (a JSON-decoded dict).

    Returns
    -------
    dict[str, Any]
        The validated descriptor.

    Raises
    ------
    DescriptorError
        If ``value`` is not a dict, has missing/extra keys, ``schema_version``
        is wrong, or any field fails its validator.
    """
    if not isinstance(value, dict):
        msg = f"ObjectDescriptor must be a JSON object, got {type(value).__name__}"
        raise DescriptorError(msg, field="")
    actual = set(value.keys())
    missing = sorted(_OBJECT_DESCRIPTOR_KEYS - actual)
    if missing:
        msg = f"ObjectDescriptor missing required key(s): {missing}"
        raise DescriptorError(msg, field=missing[0])
    extra = sorted(actual - _OBJECT_DESCRIPTOR_KEYS)
    if extra:
        msg = f"ObjectDescriptor has unexpected key(s): {extra}"
        raise DescriptorError(msg, field=extra[0])
    if value["schema_version"] != OBJECT_DESCRIPTOR_SCHEMA_VERSION:
        msg = (
            f"ObjectDescriptor.schema_version is {value['schema_version']!r}, "
            f"expected {OBJECT_DESCRIPTOR_SCHEMA_VERSION!r}"
        )
        raise DescriptorError(msg, field="schema_version")
    validate_digest(value["digest"], field="digest")
    try:
        validate_integer_byte_count(value["size_bytes"], field="size_bytes")
    except ContractError as exc:
        raise DescriptorError(str(exc), field="size_bytes") from exc
    try:
        validate_media_type(value["media_type"], field="media_type")
    except ContractError as exc:
        raise DescriptorError(str(exc), field="media_type") from exc
    _require_str(value["created_utc"], field="created_utc")
    try:
        validate_timestamp(value["created_utc"])
    except ContractError as exc:
        raise DescriptorError(str(exc), field="created_utc") from exc
    rid = value["ingest_receipt_id"]
    if rid is not None:
        _validate_receipt_id(rid, field="ingest_receipt_id")
    return value


def build_ingest_receipt(  # noqa: PLR0913 (kw-only set IS the receipt's field set)
    *,
    digest: str,
    size_bytes: int,
    source_hash_verified: bool,
    readback_hash_verified: bool,
    fsynced: bool,
    created_utc: str,
) -> tuple[dict[str, Any], str]:
    """Build an ``IngestReceipt/v1`` dict and compute its ``receipt_id``.

    The receipt is the **final** artifact of a successful ingest. Its
    ``receipt_id`` is the SHA-256 of the canonical encoding of the receipt
    *without* its own ``receipt_id`` field (a content-addressed self-hash would
    be a fixed point; see :mod:`srl.contracts.ids`). The id is returned
    alongside the receipt dict so the caller can set the descriptor's
    ``ingest_receipt_id`` before writing either record.

    Parameters
    ----------
    digest:
        ``sha256:<64 hex>`` content digest of the ingested bytes.
    size_bytes:
        Non-negative integer byte count of the ingested bytes.
    source_hash_verified:
        True iff the source bytes were hashed before writing (always True for a
        successful engine ingest; the flag records the invariant explicitly).
    readback_hash_verified:
        True iff the published bytes were read back and re-hashed to confirm
        they match the source hash.
    fsynced:
        True iff the object file and its containing directories were fsynced.
    created_utc:
        Canonical RFC 3339 UTC timestamp marking the receipt's creation.

    Returns
    -------
    tuple[dict[str, Any], str]
        ``(receipt, receipt_id)`` where ``receipt`` is the plain dict in the
        ``IngestReceipt/v1`` shape (with ``receipt_id`` populated) and
        ``receipt_id`` is ``sha256:<64 hex>``.

    Raises
    ------
    DescriptorError
        If any field is malformed.
    """
    validate_digest(digest, field="digest")
    try:
        validate_integer_byte_count(size_bytes, field="size_bytes")
    except ContractError as exc:
        raise DescriptorError(str(exc), field="size_bytes") from exc
    # bool is the only accepted type for the flags; an int 0/1 is rejected so a
    # caller cannot confuse a count for a flag. The annotation is ``bool`` but we
    # re-check at runtime (defense-in-depth) via an ``Any``-typed view so mypy
    # does not narrow the check away.
    for name, flag in (
        ("source_hash_verified", source_hash_verified),
        ("readback_hash_verified", readback_hash_verified),
        ("fsynced", fsynced),
    ):
        flag_any: Any = flag
        if not isinstance(flag_any, bool):
            msg = f"field {name!r} must be a bool, got {type(flag_any).__name__}"
            raise DescriptorError(msg, field=name)
    try:
        validate_timestamp(created_utc)
    except ContractError as exc:
        raise DescriptorError(str(exc), field="created_utc") from exc
    # Build the receipt without receipt_id, hash the canonical bytes, then set
    # the id on a copy. This is the content-addressed-identity pattern from
    # srl.contracts.ids (no self-hash).
    seed = {
        "schema_version": INGEST_RECEIPT_SCHEMA_VERSION,
        "digest": digest,
        "size_bytes": size_bytes,
        "source_hash_verified": source_hash_verified,
        "readback_hash_verified": readback_hash_verified,
        "fsynced": fsynced,
        "created_utc": created_utc,
    }
    receipt_id = "sha256:" + hashlib.sha256(dumps(seed)).hexdigest()
    receipt = dict(seed)
    receipt["receipt_id"] = receipt_id
    return receipt, receipt_id


def validate_ingest_receipt(value: Any) -> dict[str, Any]:
    """Validate ``value`` as an ``IngestReceipt/v1`` record.

    Raises
    ------
    DescriptorError
        If ``value`` is not a dict, has missing/extra keys, ``schema_version``
        is wrong, or any field fails its validator.
    """
    if not isinstance(value, dict):
        msg = f"IngestReceipt must be a JSON object, got {type(value).__name__}"
        raise DescriptorError(msg, field="")
    actual = set(value.keys())
    missing = sorted(_INGEST_RECEIPT_KEYS - actual)
    if missing:
        msg = f"IngestReceipt missing required key(s): {missing}"
        raise DescriptorError(msg, field=missing[0])
    extra = sorted(actual - _INGEST_RECEIPT_KEYS)
    if extra:
        msg = f"IngestReceipt has unexpected key(s): {extra}"
        raise DescriptorError(msg, field=extra[0])
    if value["schema_version"] != INGEST_RECEIPT_SCHEMA_VERSION:
        msg = (
            f"IngestReceipt.schema_version is {value['schema_version']!r}, "
            f"expected {INGEST_RECEIPT_SCHEMA_VERSION!r}"
        )
        raise DescriptorError(msg, field="schema_version")
    _validate_receipt_id(value["receipt_id"], field="receipt_id")
    validate_digest(value["digest"], field="digest")
    try:
        validate_integer_byte_count(value["size_bytes"], field="size_bytes")
    except ContractError as exc:
        raise DescriptorError(str(exc), field="size_bytes") from exc
    for name in ("source_hash_verified", "readback_hash_verified", "fsynced"):
        if not isinstance(value[name], bool):
            msg = f"field {name!r} must be a bool, got {type(value[name]).__name__}"
            raise DescriptorError(msg, field=name)
    _require_str(value["created_utc"], field="created_utc")
    try:
        validate_timestamp(value["created_utc"])
    except ContractError as exc:
        raise DescriptorError(str(exc), field="created_utc") from exc
    return value


def canonical_receipt_id(receipt: dict[str, Any]) -> str:
    """Recompute the ``receipt_id`` for a receipt dict (idempotent check).

    Hashes the canonical encoding of ``receipt`` with its ``receipt_id`` field
    stripped, and returns the recomputed id. Used by :mod:`srl.cas.fsck` to
    confirm a stored receipt's id matches its content (a tampered receipt fails
    this check).
    """
    if "receipt_id" not in receipt:
        msg = "receipt is missing 'receipt_id'"
        raise DescriptorError(msg, field="receipt_id")
    seed = {k: v for k, v in receipt.items() if k != "receipt_id"}
    return "sha256:" + hashlib.sha256(dumps(seed)).hexdigest()


__all__ = [
    "INGEST_RECEIPT_SCHEMA_VERSION",
    "OBJECT_DESCRIPTOR_SCHEMA_VERSION",
    "DescriptorError",
    "build_ingest_receipt",
    "build_object_descriptor",
    "canonical_receipt_id",
    "validate_ingest_receipt",
    "validate_object_descriptor",
]
