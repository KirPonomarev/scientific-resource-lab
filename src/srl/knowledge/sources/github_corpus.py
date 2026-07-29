"""Pinned GitHub corpus metadata adapters for A11."""

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

_CORPUS_REPOS: dict[str, tuple[str, str]] = {
    "cslib": ("leanprover", "cslib"),
    "erdos_problems": ("teorth", "erdosproblems"),
    "formal_conjectures": ("google-deepmind", "formal-conjectures"),
}
_MIN_COMMIT_SHA_LENGTH = 7


def build_query(endpoint_id: str, revision: str, limit: int) -> tuple[str, Mapping[str, Any]]:
    """Build a pinned commit metadata query for a public GitHub corpus."""
    del limit
    repo = _CORPUS_REPOS.get(endpoint_id)
    if repo is None:
        msg = f"unknown GitHub corpus endpoint {endpoint_id!r}"
        raise SourceRecordError(msg)
    owner, name = repo
    return f"/repos/{owner}/{name}/commits/{revision}", {}


def parse_github_commit(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
) -> list[SourceRecord]:
    """Parse a GitHub commit response into one normalized source record."""
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"GitHub corpus payload is not valid UTF-8 JSON: {exc}"
        raise SourceRecordError(msg) from exc
    if not isinstance(data, dict):
        msg = "GitHub corpus payload must be a JSON object"
        raise SourceRecordError(msg)
    sha = data.get("sha")
    html_url = data.get("html_url")
    if not isinstance(sha, str) or len(sha) < _MIN_COMMIT_SHA_LENGTH:
        msg = "GitHub corpus payload is missing a commit sha"
        raise SourceRecordError(msg)
    if not isinstance(html_url, str) or not html_url.startswith("https://github.com/"):
        msg = "GitHub corpus payload is missing a canonical html_url"
        raise SourceRecordError(msg)

    fields = {
        "source": policy.endpoint_id,
        "source_uri": html_url,
        "retrieved_utc": retrieved_utc,
        "vintage": vintage,
        "license_note": policy.license_terms_sha256,
        "payload_digest": sha256_digest(payload),
        "attribution": _attribution(policy),
    }
    return [SourceRecord(record_id=make_record_id(fields), **fields)]


def search(
    revision: str,
    limit: int,
    transport: Transport,
    policy: EndpointPolicy,
) -> list[SourceRecord]:
    """Fetch pinned GitHub commit metadata and return normalized records."""
    path, params = build_query(policy.endpoint_id, revision, limit)
    payload, retrieved_utc = fetch_with_transport(
        policy.endpoint_id, path, params, transport, policy
    )
    return parse_github_commit(payload, policy, retrieved_utc)


__all__ = ["build_query", "parse_github_commit", "search"]
