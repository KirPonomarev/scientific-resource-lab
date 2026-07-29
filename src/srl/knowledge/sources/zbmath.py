"""zbMATH Open document-search source adapter for A11."""

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


def build_query(query: str, limit: int) -> tuple[str, Mapping[str, Any]]:
    """Build a bounded zbMATH document search query."""
    return "/document/_search", {
        "search_string": query,
        "page": 0,
        "results_per_page": _cap_limit(limit),
    }


def _item_identifier(item: dict[str, Any], idx: int) -> str:
    for key in ("id", "zbl_id", "document_id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int):
            return str(value)
    links = item.get("links")
    if isinstance(links, dict):
        for value in links.values():
            if isinstance(value, str) and value:
                return value.rsplit("/", 1)[-1]
    msg = f"zbMATH result at index {idx} is missing a stable identifier"
    raise SourceRecordError(msg)


def parse_zbmath(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
) -> list[SourceRecord]:
    """Parse a zbMATH Open search response into normalized records."""
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"zbMATH payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc
    if not isinstance(data, dict):
        msg = "zbMATH payload must be a JSON object"
        raise SourceRecordError(msg)
    results = data.get("result")
    if not isinstance(results, list) or not results:
        msg = "zbMATH payload must contain a non-empty 'result' list"
        raise SourceRecordError(msg)

    payload_digest = sha256_digest(payload)
    records: list[SourceRecord] = []
    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            msg = f"zbMATH result at index {idx} is not a JSON object"
            raise SourceRecordError(msg)
        item_id = _item_identifier(item, idx)
        source_uri = (
            item_id if item_id.startswith("https://") else f"https://zbmath.org/?q=an:{item_id}"
        )
        fields = {
            "source": "zbmath",
            "source_uri": source_uri,
            "retrieved_utc": retrieved_utc,
            "vintage": vintage,
            "license_note": policy.license_terms_sha256,
            "payload_digest": payload_digest,
            "attribution": _attribution(policy),
        }
        records.append(SourceRecord(record_id=make_record_id(fields), **fields))
    return records


def search(
    query: str,
    limit: int,
    transport: Transport,
    policy: EndpointPolicy,
) -> list[SourceRecord]:
    """Search zbMATH Open and return normalized records."""
    path, params = build_query(query, limit)
    payload, retrieved_utc = fetch_with_transport("zbmath", path, params, transport, policy)
    return parse_zbmath(payload, policy, retrieved_utc)


__all__ = ["build_query", "parse_zbmath", "search"]
