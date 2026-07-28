"""Full integrity sweep for a CAS store: corruption, descriptor, and size checks.

:mfunc:`srl.cas.store.LocalArtifactStore.fsck` (WP-C20) reports only the
per-object hash pass/fail. WP-C21 adds a richer sweep that walks the whole store
and detects five classes of trouble:

- **hash mismatch (corruption)** — an object's bytes do not hash back to the
  digest encoded in its path (bit rot, partial write, concurrent mutation).
  Typed ``CAS_INTEGRITY_FAILURE`` (hard stop).
- **missing descriptor** — an object exists in ``objects/`` but has no
  ``descriptors/<digest>.json``. The object was published but its descriptor
  write was interrupted (the receipt-last invariant means the object may still
  be valid; the sweep reports it for reconciliation).
- **orphan descriptor** — a descriptor exists in ``descriptors/`` but its object
  is absent from ``objects/``. The object was deleted out-of-band, or the
  descriptor write completed but the publish did not.
- **size drift** — an object's on-disk byte size does not match the
  ``size_bytes`` recorded in its descriptor. The bytes were truncated or
  extended after publish.
- **bad receipt** — a receipt's ``receipt_id`` does not match the content hash
  of the rest of the receipt, or a descriptor's ``ingest_receipt_id`` points at
  a receipt that is absent or tampered.

The sweep is read-only: it never writes, deletes, or repairs. It produces a
:class:`CasFsckReport` (canonical JSON) with one typed entry per issue, and an
exit-code-friendly ``ok`` flag (True iff there are zero issues). The
:meth:`srl.cas.store.LocalArtifactStore.fsck` method (WP-C20) is preserved
unchanged for backward compatibility; this module is the richer sweep the
engine's invariant demands.

Standard library only; the canonical encoding is used only for the small
descriptor/receipt records, never in a byte loop.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from srl.cas.descriptors import (
    canonical_receipt_id,
    validate_ingest_receipt,
    validate_object_descriptor,
)
from srl.cas.privacy import redact_store_path
from srl.contracts.errors import ContractError

# Schema identity for the fsck report. Bumped only on a report-shape change.
CAS_FSCK_REPORT_SCHEMA_VERSION: Final[str] = "CasFsckReport/v1"

# The typed issue kinds. Kept as a string-literal set so the report entries are
# self-describing and a reader can group by kind without importing the enum.
ISSUE_HASH_MISMATCH: Final[str] = "hash_mismatch"
ISSUE_MISSING_DESCRIPTOR: Final[str] = "missing_descriptor"
ISSUE_ORPHAN_DESCRIPTOR: Final[str] = "orphan_descriptor"
ISSUE_SIZE_DRIFT: Final[str] = "size_drift"
ISSUE_BAD_RECEIPT: Final[str] = "bad_receipt"
ISSUE_MALFORMED_RECORD: Final[str] = "malformed_record"

# Digest shape for object paths and descriptor filenames.
_DIGEST_PATTERN: Final[str] = r"^sha256:[0-9a-f]{64}$"
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(_DIGEST_PATTERN)


@dataclass(frozen=True)
class FsckIssue:
    """A single typed issue found by :func:`run_fsck`.

    Attributes
    ----------
    kind:
        One of the ``ISSUE_*`` constants (e.g. ``hash_mismatch``).
    digest:
        The digest of the object the issue concerns (``sha256:<64 hex>``), or
        ``""`` if the issue is not object-specific (e.g. a malformed record whose
        digest could not be parsed).
    detail:
        Human-readable explanation of the issue.
    path_redacted:
        ``redacted:<16 hex>`` token for the store root (never a raw path).
    """

    kind: str
    digest: str
    detail: str
    path_redacted: str


@dataclass(frozen=True)
class CasFsckReport:
    """The result of a full CAS integrity sweep (:func:`run_fsck`).

    Attributes
    ----------
    schema_version:
        Const ``"CasFsckReport/v1"`` identity anchor.
    objects_checked:
        Number of objects found in ``objects/`` and hashed.
    objects_passed:
        Number whose recomputed digest matched their path.
    descriptors_checked:
        Number of descriptor records read from ``descriptors/``.
    receipts_checked:
        Number of receipt records read from ``receipts/``.
    issues:
        Typed :class:`FsckIssue` entries, one per problem found.
    ok:
        True iff ``issues`` is empty (the store is clean). Exit-code-friendly.
    store_root_redacted:
        ``redacted:<16 hex>`` token for the store root.
    """

    schema_version: str
    objects_checked: int
    objects_passed: int
    descriptors_checked: int
    receipts_checked: int
    issues: list[FsckIssue] = field(default_factory=list)
    ok: bool = True
    store_root_redacted: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Render the report as a canonical-JSON-friendly dict.

        The dict is sorted-key friendly (callers pass it through
        :func:`srl.contracts.canonical.dumps`). Issues are rendered as a list of
        dicts so the wire form is a stable array.
        """
        return {
            "schema_version": self.schema_version,
            "objects_checked": self.objects_checked,
            "objects_passed": self.objects_passed,
            "descriptors_checked": self.descriptors_checked,
            "receipts_checked": self.receipts_checked,
            "ok": self.ok,
            "store_root_redacted": self.store_root_redacted,
            "issues": [
                {
                    "kind": issue.kind,
                    "digest": issue.digest,
                    "detail": issue.detail,
                }
                for issue in self.issues
            ],
        }


def _sha256_hex(data: bytes) -> str:
    """Return the bare 64-hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _load_json_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load a JSON record from ``path``.

    Returns ``(parsed_dict, error_str)``. On any failure (missing file, bad JSON,
    non-object) returns ``(None, error_message)`` so the caller can record a
    malformed-record issue rather than raising.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"could not read {path.name}: {exc}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"{path.name} is not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, f"{path.name} is not a JSON object"
    return parsed, None


def run_fsck(root: Path) -> CasFsckReport:
    """Run a full integrity sweep of the CAS store rooted at ``root``.

    Walks ``objects/``, ``descriptors/``, and ``receipts/``, recomputes every
    object's hash, cross-checks descriptor and receipt presence and consistency,
    and returns a :class:`CasFsckReport` with one typed issue per problem. The
    sweep is read-only.

    Parameters
    ----------
    root:
        The store root directory.

    Returns
    -------
    CasFsckReport
        The sweep result. ``report.ok`` is True iff there are zero issues.
    """
    root_redacted = redact_store_path(root)
    issues: list[FsckIssue] = []

    # Index descriptors and receipts first (so the object sweep can cross-check).
    descriptors_by_digest, desc_issues, descriptors_checked = _index_descriptors(
        root / "descriptors", root_redacted
    )
    issues.extend(desc_issues)
    receipts_by_id, rec_issues, receipts_checked = _index_receipts(root / "receipts", root_redacted)
    issues.extend(rec_issues)

    # Walk objects/, re-hash each, and cross-check descriptor/receipt consistency.
    object_digests, obj_issues, objects_checked, objects_passed = _sweep_objects(
        root / "objects", descriptors_by_digest, receipts_by_id, root_redacted
    )
    issues.extend(obj_issues)

    # Orphan descriptors: a descriptor whose object is absent.
    for digest in descriptors_by_digest:
        if digest not in object_digests:
            issues.append(
                FsckIssue(
                    kind=ISSUE_ORPHAN_DESCRIPTOR,
                    digest=digest,
                    detail=f"descriptor for {digest!r} has no object in objects/",
                    path_redacted=root_redacted,
                )
            )

    return CasFsckReport(
        schema_version=CAS_FSCK_REPORT_SCHEMA_VERSION,
        objects_checked=objects_checked,
        objects_passed=objects_passed,
        descriptors_checked=descriptors_checked,
        receipts_checked=receipts_checked,
        issues=issues,
        ok=len(issues) == 0,
        store_root_redacted=root_redacted,
    )


def _index_descriptors(
    descriptors_dir: Path,
    root_redacted: str,
) -> tuple[dict[str, dict[str, Any]], list[FsckIssue], int]:
    """Read and validate every descriptor; return the digest-keyed index.

    A descriptor whose filename does not match its digest, or which fails
    validation, is reported as ``ISSUE_MALFORMED_RECORD`` and skipped.
    """
    by_digest: dict[str, dict[str, Any]] = {}
    issues: list[FsckIssue] = []
    checked = 0
    if not descriptors_dir.is_dir():
        return by_digest, issues, checked
    for desc_file in sorted(descriptors_dir.iterdir()):
        if not desc_file.is_file() or not desc_file.name.endswith(".json"):
            continue
        checked += 1
        parsed, err = _load_json_record(desc_file)
        if parsed is None:
            issues.append(
                FsckIssue(
                    ISSUE_MALFORMED_RECORD,
                    "",
                    detail=f"descriptor {desc_file.name}: {err}",
                    path_redacted=root_redacted,
                )
            )
            continue
        try:
            validated = validate_object_descriptor(parsed)
        except ContractError as exc:
            issues.append(
                FsckIssue(
                    ISSUE_MALFORMED_RECORD,
                    str(parsed.get("digest", "")),
                    f"descriptor {desc_file.name} failed validation: {exc}",
                    root_redacted,
                )
            )
            continue
        digest = validated["digest"]
        if desc_file.name != f"{digest}.json":
            issues.append(
                FsckIssue(
                    ISSUE_MALFORMED_RECORD,
                    digest,
                    f"descriptor filename {desc_file.name!r} does not match its digest {digest!r}",
                    root_redacted,
                )
            )
        by_digest[digest] = validated
    return by_digest, issues, checked


def _index_receipts(
    receipts_dir: Path,
    root_redacted: str,
) -> tuple[dict[str, dict[str, Any]], list[FsckIssue], int]:
    """Read and validate every receipt; return the receipt_id-keyed index.

    A receipt whose ``receipt_id`` does not match the content hash of the rest of
    the record is reported as ``ISSUE_BAD_RECEIPT`` (tampered) and skipped.
    """
    by_id: dict[str, dict[str, Any]] = {}
    issues: list[FsckIssue] = []
    checked = 0
    if not receipts_dir.is_dir():
        return by_id, issues, checked
    for rec_file in sorted(receipts_dir.iterdir()):
        if not rec_file.is_file() or not rec_file.name.endswith(".json"):
            continue
        checked += 1
        parsed, err = _load_json_record(rec_file)
        if parsed is None:
            issues.append(
                FsckIssue(
                    ISSUE_MALFORMED_RECORD,
                    "",
                    detail=f"receipt {rec_file.name}: {err}",
                    path_redacted=root_redacted,
                )
            )
            continue
        try:
            validated = validate_ingest_receipt(parsed)
        except ContractError as exc:
            issues.append(
                FsckIssue(
                    ISSUE_MALFORMED_RECORD,
                    str(parsed.get("digest", "")),
                    f"receipt {rec_file.name} failed validation: {exc}",
                    root_redacted,
                )
            )
            continue
        rid = validated["receipt_id"]
        try:
            recomputed = canonical_receipt_id(dict(validated))
        except ContractError as exc:
            issues.append(
                FsckIssue(
                    ISSUE_BAD_RECEIPT,
                    str(validated.get("digest", "")),
                    f"receipt {rec_file.name} id recomputation failed: {exc}",
                    root_redacted,
                )
            )
            continue
        if recomputed != rid:
            issues.append(
                FsckIssue(
                    ISSUE_BAD_RECEIPT,
                    str(validated.get("digest", "")),
                    detail=(
                        f"receipt {rec_file.name} id {rid!r} does not match its "
                        f"content hash {recomputed!r}"
                    ),
                    path_redacted=root_redacted,
                )
            )
        by_id[rid] = validated
    return by_id, issues, checked


def _check_object_consistency(
    digest: str,
    data: bytes,
    descriptors_by_digest: dict[str, dict[str, Any]],
    receipts_by_id: dict[str, dict[str, Any]],
    root_redacted: str,
) -> list[FsckIssue]:
    """Cross-check one object against its descriptor and receipt.

    Reports ``ISSUE_MISSING_DESCRIPTOR`` (no descriptor), ``ISSUE_SIZE_DRIFT``
    (size mismatch), or ``ISSUE_BAD_RECEIPT`` (descriptor references an absent
    receipt).
    """
    issues: list[FsckIssue] = []
    descriptor = descriptors_by_digest.get(digest)
    if descriptor is None:
        issues.append(
            FsckIssue(
                ISSUE_MISSING_DESCRIPTOR,
                digest,
                f"object {digest!r} has no descriptor record",
                root_redacted,
            )
        )
        return issues
    declared_size = descriptor.get("size_bytes")
    if not isinstance(declared_size, int) or declared_size != len(data):
        issues.append(
            FsckIssue(
                ISSUE_SIZE_DRIFT,
                digest,
                f"object {digest!r} size {len(data)} != descriptor size_bytes {declared_size!r}",
                root_redacted,
            )
        )
    rid = descriptor.get("ingest_receipt_id")
    if isinstance(rid, str) and rid and rid not in receipts_by_id:
        issues.append(
            FsckIssue(
                ISSUE_BAD_RECEIPT,
                digest,
                f"descriptor for {digest!r} references receipt {rid!r} which is absent",
                root_redacted,
            )
        )
    return issues


def _sweep_objects(
    objects_dir: Path,
    descriptors_by_digest: dict[str, dict[str, Any]],
    receipts_by_id: dict[str, dict[str, Any]],
    root_redacted: str,
) -> tuple[set[str], list[FsckIssue], int, int]:
    """Re-hash every object and cross-check its descriptor/receipt.

    Returns ``(object_digests, issues, checked, passed)``. Reports
    ``ISSUE_MALFORMED_RECORD`` for a non-digest path, ``ISSUE_HASH_MISMATCH``
    for corruption, plus any consistency issues from
    :func:`_check_object_consistency`.
    """
    object_digests: set[str] = set()
    issues: list[FsckIssue] = []
    checked = 0
    passed = 0
    if not objects_dir.is_dir():
        return object_digests, issues, checked, passed
    for shard in sorted(objects_dir.iterdir()):
        if not shard.is_dir():
            continue
        for obj in sorted(shard.iterdir()):
            if not obj.is_file():
                continue
            checked += 1
            digest = obj.name
            object_digests.add(digest)
            if not _DIGEST_RE.fullmatch(digest):
                issues.append(
                    FsckIssue(
                        ISSUE_MALFORMED_RECORD,
                        "",
                        f"object path {obj.name!r} is not a valid digest",
                        root_redacted,
                    )
                )
                continue
            try:
                data = obj.read_bytes()
            except OSError as exc:
                issues.append(
                    FsckIssue(
                        ISSUE_HASH_MISMATCH,
                        digest,
                        f"could not read object {digest!r}: {exc}",
                        root_redacted,
                    )
                )
                continue
            actual = "sha256:" + _sha256_hex(data)
            if actual == digest:
                passed += 1
            else:
                issues.append(
                    FsckIssue(
                        ISSUE_HASH_MISMATCH,
                        digest,
                        f"object {digest!r} bytes hash to {actual!r} (corruption)",
                        root_redacted,
                    )
                )
            issues.extend(
                _check_object_consistency(
                    digest, data, descriptors_by_digest, receipts_by_id, root_redacted
                )
            )
    return object_digests, issues, checked, passed


__all__ = [
    "CAS_FSCK_REPORT_SCHEMA_VERSION",
    "ISSUE_BAD_RECEIPT",
    "ISSUE_HASH_MISMATCH",
    "ISSUE_MALFORMED_RECORD",
    "ISSUE_MISSING_DESCRIPTOR",
    "ISSUE_ORPHAN_DESCRIPTOR",
    "ISSUE_SIZE_DRIFT",
    "CasFsckReport",
    "FsckIssue",
    "run_fsck",
]
