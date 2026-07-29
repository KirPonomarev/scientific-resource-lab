"""OEIS (On-Line Encyclopedia of Integer Sequences) source adapter (WP-E44).

Builds a compact, bounded query against the OEIS search endpoint and parses the
JSON response into normalized :class:`SourceRecord` objects. No live API payload
is persisted; only synthetic fixtures are used in tests.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from srl.knowledge.retriever import EndpointPolicy, Transport
from srl.knowledge.sources._record import SourceRecord, SourceRecordError, make_record_id
from srl.knowledge.sources._utils import (
    _attribution,
    _utc_now,
    fetch_with_transport,
    sha256_digest,
)

# OEIS sequence numbers are an 'A' followed by six digits.
_OEIS_NUMBER_RE: re.Pattern[str] = re.compile(r"^A[0-9]{6}$")


def _oeis_number(item: dict[str, Any]) -> str:
    """Return the OEIS sequence number from an item, or raise SourceRecordError."""
    number = item.get("number")
    if isinstance(number, str) and _OEIS_NUMBER_RE.match(number):
        return number
    if isinstance(number, int) and number >= 0:
        return f"A{number:06d}"
    # Fall back to parsing the number from the name, e.g. "A000045 Fibonacci numbers".
    name = item.get("name")
    if isinstance(name, str):
        match = _OEIS_NUMBER_RE.match(name.split()[0] if name else "")
        if match:
            return match.group(0)
    msg = "OEIS result has missing or malformed sequence number"
    raise SourceRecordError(msg)


def build_query(query: str, limit: int) -> tuple[str, Mapping[str, Any]]:
    """Build an OEIS search query.

    Parameters
    ----------
    query:
        The free-text query string (sequence number, keyword, or terms).
    limit:
        Maximum number of results requested. OEIS does not expose a per-page
        parameter in this compact adapter; the limit is documented as a polite
        cap and the adapter returns whatever results the (synthetic) response
        contains.

    Returns
    -------
    tuple[str, Mapping[str, Any]]
        The path ``/search`` and the query parameter mapping.
    """
    del limit  # OEIS query shape is compact; no per-page knob to cap here.
    return "/search", {"q": query, "fmt": "json"}


def parse_oeis(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
) -> list[SourceRecord]:
    """Parse a synthetic OEIS search response into :class:`SourceRecord` objects.

    Raises
    ------
    SourceRecordError
        If the payload is not valid JSON, does not contain a ``results`` list, or
        any result lacks a usable sequence number. No partial record is emitted.
    """
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"OEIS payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc
    results_obj: Any
    if isinstance(data, list):
        results_obj = data
    elif isinstance(data, dict):
        results_obj = data.get("results")
    else:
        msg = "OEIS payload must be a JSON object or compact result list"
        raise SourceRecordError(msg)
    if not isinstance(results_obj, list):
        msg = "OEIS payload must contain a 'results' list"
        raise SourceRecordError(msg)
    results: list[Any] = results_obj

    payload_digest = sha256_digest(payload)
    license_note = policy.license_terms_sha256
    attribution = _attribution(policy)
    records: list[SourceRecord] = []
    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            msg = f"OEIS result at index {idx} is not a JSON object"
            raise SourceRecordError(msg)
        try:
            number = _oeis_number(item)
        except SourceRecordError as exc:
            msg = f"OEIS result at index {idx}: {exc}"
            raise SourceRecordError(msg) from exc
        source_uri = f"https://oeis.org/{number}"
        fields = {
            "source": "oeis",
            "source_uri": source_uri,
            "retrieved_utc": retrieved_utc,
            "vintage": vintage,
            "license_note": license_note,
            "payload_digest": payload_digest,
            "attribution": attribution,
        }
        records.append(
            SourceRecord(
                record_id=make_record_id(fields),
                **fields,
            )
        )
    return records


def search(
    query: str,
    limit: int,
    transport: Transport,
    policy: EndpointPolicy,
) -> list[SourceRecord]:
    """Search OEIS and return normalized records.

    The fetch is delegated to the D33 retriever, which enforces the endpoint's
    rate, byte, and cost budgets.
    """
    path, params = build_query(query, limit)
    payload, retrieved_utc = fetch_with_transport("oeis", path, params, transport, policy)
    return parse_oeis(payload, policy, retrieved_utc)


__all__ = ["build_query", "parse_oeis", "search"]
