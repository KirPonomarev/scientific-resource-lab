"""OpenAlex works source adapter (WP-E44).

Builds a bounded, filter/select query against the OpenAlex works endpoint and
parses the response into normalized :class:`SourceRecord` objects. No live API
payload is persisted; only synthetic fixtures are used in tests.
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
    _cap_limit,
    _utc_now,
    fetch_with_transport,
    sha256_digest,
)

# OpenAlex work identifiers look like "W" followed by digits.
_OPENALEX_WORK_ID_RE: re.Pattern[str] = re.compile(r"^W[0-9]+$")

# The fields we ask OpenAlex to return. Never request a full snapshot.
_OPENALEX_SELECT_FIELDS: str = "id,doi,title,authorships,publication_year,cited_by_count"


def _openalex_uri(work_id: str) -> str:
    """Normalize a raw OpenAlex work id into a canonical HTTPS source URI."""
    if work_id.startswith("https://"):
        return work_id
    if work_id.startswith("http://"):
        return "https://" + work_id[len("http://") :]
    if work_id.startswith("openalex:"):
        work_id = work_id[len("openalex:") :]
    if _OPENALEX_WORK_ID_RE.match(work_id):
        return f"https://openalex.org/works/{work_id}"
    msg = f"cannot construct OpenAlex source URI from work id {work_id!r}"
    raise SourceRecordError(msg)


def _authorship_count(item: dict[str, Any]) -> int:
    """Return the authorship count from a result item, accepting int or list."""
    authorships = item.get("authorships")
    if isinstance(authorships, list):
        return len(authorships)
    if isinstance(authorships, int):
        return authorships
    if authorships is None:
        return 0
    msg = f"OpenAlex authorships has unexpected type {type(authorships).__name__}"
    raise SourceRecordError(msg)


def build_query(
    query: str,
    limit: int,
    *,
    mailto: str | None = None,
) -> tuple[str, Mapping[str, Any]]:
    """Build an OpenAlex works query with filter/select and a capped per-page.

    Parameters
    ----------
    query:
        The free-text query string (used in a title search filter).
    limit:
        Maximum number of results requested. The per-page cap is always <= 25.
    mailto:
        Optional courtesy ``mailto`` parameter supplied by the operator. No default
        identity is ever added.

    Returns
    -------
    tuple[str, Mapping[str, Any]]
        The path ``/works`` and the query parameter mapping.
    """
    per_page = _cap_limit(limit)
    params: dict[str, Any] = {
        "filter": f"title.search:{query}",
        "select": _OPENALEX_SELECT_FIELDS,
        "per-page": per_page,
    }
    if mailto:
        params["mailto"] = mailto
    return "/works", params


def parse_openalex(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
) -> list[SourceRecord]:
    """Parse a synthetic OpenAlex works response into :class:`SourceRecord` objects.

    Raises
    ------
    SourceRecordError
        If the payload is not valid JSON, does not contain a ``results`` list, or
        any result lacks a usable work id. No partial record is emitted.
    """
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"OpenAlex payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc
    if not isinstance(data, dict):
        msg = "OpenAlex payload must be a JSON object"
        raise SourceRecordError(msg)
    results = data.get("results")
    if not isinstance(results, list):
        msg = "OpenAlex payload must contain a 'results' list"
        raise SourceRecordError(msg)

    payload_digest = sha256_digest(payload)
    license_note = policy.license_terms_sha256
    attribution = _attribution(policy)
    records: list[SourceRecord] = []
    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            msg = f"OpenAlex result at index {idx} is not a JSON object"
            raise SourceRecordError(msg)
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            msg = f"OpenAlex result at index {idx} has missing or empty 'id'"
            raise SourceRecordError(msg)
        source_uri = _openalex_uri(raw_id)
        fields = {
            "source": "openalex",
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
    *,
    mailto: str | None = None,
) -> list[SourceRecord]:
    """Search OpenAlex works and return normalized records.

    The actual HTTP fetch is performed by the D33 retriever under the supplied
    ``policy`` and ``transport``. Rate, byte, and cost budgets are enforced by the
    retriever.
    """
    path, params = build_query(query, limit, mailto=mailto)
    payload, retrieved_utc = fetch_with_transport("openalex", path, params, transport, policy)
    return parse_openalex(payload, policy, retrieved_utc)


__all__ = ["build_query", "parse_openalex", "search"]
