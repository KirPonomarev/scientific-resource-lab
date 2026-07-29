"""OpenCitations Index source adapter for A11."""

from __future__ import annotations

import json
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


def _normalize_identifier(identifier: str) -> str:
    if identifier.startswith("doi:"):
        return identifier
    if identifier.startswith("https://doi.org/"):
        return "doi:" + identifier.rsplit("/", 1)[1]
    return f"doi:{identifier}"


def build_query(identifier: str, limit: int) -> tuple[str, Mapping[str, Any]]:
    """Build a citation-count query for one DOI-like identifier."""
    del limit
    return f"/citation-count/{_normalize_identifier(identifier)}", {}


def parse_opencitations(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
    *,
    identifier: str = "doi:10.1108/jd-12-2013-0166",
) -> list[SourceRecord]:
    """Parse an OpenCitations citation-count response into source records."""
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"OpenCitations payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc
    if not isinstance(data, list) or not data:
        msg = "OpenCitations payload must be a non-empty JSON list"
        raise SourceRecordError(msg)

    payload_digest = sha256_digest(payload)
    records: list[SourceRecord] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            msg = f"OpenCitations result at index {idx} is not a JSON object"
            raise SourceRecordError(msg)
        count = item.get("count")
        if not isinstance(count, str) or not count.isdigit():
            msg = f"OpenCitations result at index {idx} has missing numeric 'count'"
            raise SourceRecordError(msg)
        normalized = _normalize_identifier(identifier)
        fields = {
            "source": "opencitations",
            "source_uri": f"https://api.opencitations.net/index/v2/citation-count/{normalized}",
            "retrieved_utc": retrieved_utc,
            "vintage": vintage,
            "license_note": policy.license_terms_sha256,
            "payload_digest": payload_digest,
            "attribution": _attribution(policy),
        }
        records.append(SourceRecord(record_id=make_record_id(fields), **fields))
    return records


def search(
    identifier: str,
    limit: int,
    transport: Transport,
    policy: EndpointPolicy,
) -> list[SourceRecord]:
    """Fetch one citation-count payload and return normalized records."""
    path, params = build_query(identifier, limit)
    payload, retrieved_utc = fetch_with_transport("opencitations", path, params, transport, policy)
    return parse_opencitations(payload, policy, retrieved_utc, identifier=identifier)


__all__ = ["build_query", "parse_opencitations", "search"]
