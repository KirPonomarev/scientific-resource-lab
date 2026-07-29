"""LMFDB API source adapter for A11."""

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
    """Build a bounded elliptic-curve metadata query."""
    del query
    return "/ec_curvedata/", {
        "rank": "i0",
        "_format": "json",
        "_fields": "lmfdb_label,rank",
        "_limit": _cap_limit(limit),
    }


def parse_lmfdb(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
) -> list[SourceRecord]:
    """Parse an LMFDB collection response into normalized records."""
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"LMFDB payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc
    if not isinstance(data, dict):
        msg = "LMFDB payload must be a JSON object"
        raise SourceRecordError(msg)
    results = data.get("data")
    if not isinstance(results, list) or not results:
        msg = "LMFDB payload must contain a non-empty 'data' list"
        raise SourceRecordError(msg)

    payload_digest = sha256_digest(payload)
    records: list[SourceRecord] = []
    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            msg = f"LMFDB result at index {idx} is not a JSON object"
            raise SourceRecordError(msg)
        label = item.get("lmfdb_label") or item.get("label")
        if not isinstance(label, str) or not label:
            msg = f"LMFDB result at index {idx} is missing 'lmfdb_label'"
            raise SourceRecordError(msg)
        fields = {
            "source": "lmfdb",
            "source_uri": f"https://www.lmfdb.org/EllipticCurve/Q/{label}",
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
    """Search LMFDB and return normalized records."""
    path, params = build_query(query, limit)
    payload, retrieved_utc = fetch_with_transport("lmfdb", path, params, transport, policy)
    return parse_lmfdb(payload, policy, retrieved_utc)


__all__ = ["build_query", "parse_lmfdb", "search"]
