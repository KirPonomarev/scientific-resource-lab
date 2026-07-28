"""Shared record shape and contract errors for knowledge source adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from srl.contracts.canonical import dumps as canonical_dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError


class SourceRecordError(ContractError):
    """A source payload cannot be parsed into a valid :class:`SourceRecord`.

    This is a typed contract failure: the bytes violate the structural contract
    expected by the adapter. No partial record is emitted; the whole payload is
    rejected.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


@dataclass(frozen=True)
class SourceRecord:
    """A normalized, content-addressed knowledge record from an external source.

    A :class:`SourceRecord` deliberately carries *identity and provenance*, not
    the raw API payload. The payload itself is content-addressed by its digest
    and may be retrieved from the content-addressed store when needed.
    """

    record_id: str
    source: str
    source_uri: str
    retrieved_utc: str
    vintage: str
    license_note: str
    payload_digest: str
    attribution: str


def make_record_id(fields: dict[str, Any]) -> str:
    """Return a stable ``sha256:<hex>`` identity for the record fields."""
    blob = canonical_dumps(fields)
    return "sha256:" + hashlib.sha256(blob).hexdigest()


__all__ = ["SourceRecord", "SourceRecordError", "make_record_id"]
