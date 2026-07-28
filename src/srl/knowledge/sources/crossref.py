"""Crossref DOI metadata source adapter (WP-E44).

Builds a bounded query against the Crossref works endpoint and parses the
response into normalized :class:`SourceRecord` objects. No live API payload is
persisted; only synthetic fixtures are used in tests.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from srl.knowledge.retriever import EndpointPolicy, Transport
from srl.knowledge.sources._record import SourceRecord, SourceRecordError, make_record_id
from srl.knowledge.sources._utils import (
    _attribution,
    _cap_limit,
    _utc_now,
    fetch_with_transport,
    sha256_digest,
)


def _first_title(title: Any) -> str:
    """Return the first title string from a Crossref title field."""
    if isinstance(title, str):
        return title
    if isinstance(title, list) and title and isinstance(title[0], str):
        return title[0]
    if title is None:
        return ""
    msg = f"Crossref title field has unexpected type {type(title).__name__}"
    raise SourceRecordError(msg)


def _crossref_uri(doi: str) -> str:
    """Return the canonical DOI URI for a Crossref record."""
    if doi.startswith("https://doi.org/") or doi.startswith("http://doi.org/"):
        return f"https://doi.org/{doi.split('doi.org/', 1)[1]}"
    return f"https://doi.org/{doi}"


def build_query(query: str, limit: int) -> tuple[str, Mapping[str, Any]]:
    """Build a Crossref works query with a capped ``rows`` per-page parameter.

    Parameters
    ----------
    query:
        The free-text query string sent to the works endpoint.
    limit:
        Maximum number of results requested. ``rows`` is always <= 25.

    Returns
    -------
    tuple[str, Mapping[str, Any]]
        The path ``/works`` and the query parameter mapping.
    """
    rows = _cap_limit(limit)
    return "/works", {"query": query, "rows": rows}


def parse_crossref(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
) -> list[SourceRecord]:
    """Parse a synthetic Crossref works response into :class:`SourceRecord` objects.

    Supports both ``work-list`` (with ``message.items``) and single-work
    (``message`` containing a ``DOI``) shapes. Raises :class:`SourceRecordError`
    for malformed payloads; no partial record is emitted.
    """
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"Crossref payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc
    if not isinstance(data, dict):
        msg = "Crossref payload must be a JSON object"
        raise SourceRecordError(msg)

    message = data.get("message")
    if not isinstance(message, dict):
        msg = "Crossref payload must contain a 'message' object"
        raise SourceRecordError(msg)

    items: list[Any]
    if isinstance(message.get("items"), list):
        items = message["items"]
    elif isinstance(message.get("DOI"), str):
        items = [message]
    else:
        msg = "Crossref payload missing 'message.items' or a single work DOI"
        raise SourceRecordError(msg)

    payload_digest = sha256_digest(payload)
    license_note = policy.license_terms_sha256
    attribution = _attribution(policy)
    records: list[SourceRecord] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            msg = f"Crossref result at index {idx} is not a JSON object"
            raise SourceRecordError(msg)
        doi = item.get("DOI")
        if not isinstance(doi, str) or not doi:
            msg = f"Crossref result at index {idx} has missing or empty 'DOI'"
            raise SourceRecordError(msg)
        source_uri = _crossref_uri(doi)
        fields = {
            "source": "crossref",
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
    """Search Crossref works and return normalized records.

    The fetch is delegated to the D33 retriever, which enforces the endpoint's
    rate, byte, and cost budgets.
    """
    path, params = build_query(query, limit)
    payload, retrieved_utc = fetch_with_transport("crossref", path, params, transport, policy)
    return parse_crossref(payload, policy, retrieved_utc)


__all__ = ["build_query", "parse_crossref", "search"]
