"""arXiv metadata source adapter (WP-E44).

Builds a bounded ``search_query`` request against the arXiv API and parses the
Atom XML response into normalized :class:`SourceRecord` objects. No live API
payload is persisted; only synthetic fixtures are used in tests.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
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

# Atom namespace used by the arXiv API response.
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _arxiv_uri(raw_id: str) -> str:
    """Normalize an arXiv entry id into a canonical HTTPS source URI."""
    if raw_id.startswith("https://"):
        return raw_id
    if raw_id.startswith("http://"):
        return "https://" + raw_id[len("http://") :]
    # If the id is just a short arXiv identifier, construct the canonical URL.
    return f"https://arxiv.org/abs/{raw_id}"


def build_query(query: str, limit: int) -> tuple[str, Mapping[str, Any]]:
    """Build an arXiv API query with a capped ``max_results`` per-page.

    Parameters
    ----------
    query:
        The free-text query string (used in an ``all:`` search).
    limit:
        Maximum number of results requested. ``max_results`` is always <= 25.

    Returns
    -------
    tuple[str, Mapping[str, Any]]
        The path ``/api/query`` and the query parameter mapping.
    """
    max_results = _cap_limit(limit)
    return "/api/query", {"search_query": f"all:{query}", "max_results": max_results}


def parse_arxiv(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
) -> list[SourceRecord]:
    """Parse a synthetic arXiv Atom feed into :class:`SourceRecord` objects.

    Raises
    ------
    SourceRecordError
        If the payload is not well-formed Atom XML, or if an entry lacks a usable
        id. No partial record is emitted.
    """
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        root = ET.fromstring(payload)  # noqa: S314 - synthetic fixtures only
    except ET.ParseError as exc:
        msg = f"arXiv payload is not well-formed XML: {exc}"
        raise SourceRecordError(msg) from exc

    entries = root.findall(f"{_ATOM_NS}entry")
    if not entries:
        msg = "arXiv payload contains no Atom entries"
        raise SourceRecordError(msg)

    payload_digest = sha256_digest(payload)
    license_note = policy.license_terms_sha256
    attribution = _attribution(policy)
    records: list[SourceRecord] = []
    for idx, entry in enumerate(entries):
        id_elem = entry.find(f"{_ATOM_NS}id")
        if id_elem is None or not id_elem.text:
            msg = f"arXiv entry at index {idx} is missing an 'id' element"
            raise SourceRecordError(msg)
        raw_id = id_elem.text.strip()
        source_uri = _arxiv_uri(raw_id)
        fields = {
            "source": "arxiv",
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
    """Search arXiv and return normalized records.

    The fetch is delegated to the D33 retriever, which enforces the endpoint's
    rate, byte, and cost budgets.
    """
    path, params = build_query(query, limit)
    payload, retrieved_utc = fetch_with_transport("arxiv", path, params, transport, policy)
    return parse_arxiv(payload, policy, retrieved_utc)


__all__ = ["build_query", "parse_arxiv", "search"]
