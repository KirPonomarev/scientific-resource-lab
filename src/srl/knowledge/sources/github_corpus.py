"""Pinned GitHub corpus raw-blob adapters for A11."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from srl.knowledge.retriever import EndpointPolicy, Transport
from srl.knowledge.sources._record import SourceRecord, SourceRecordError, make_record_id
from srl.knowledge.sources._utils import (
    _attribution,
    _utc_now,
    fetch_with_transport,
    sha256_digest,
)


@dataclass(frozen=True)
class GitHubCorpusPin:
    owner: str
    repo: str
    source_path: str


_CORPUS_REPOS: dict[str, GitHubCorpusPin] = {
    "cslib": GitHubCorpusPin("leanprover", "cslib", "README.md"),
    "erdos_problems": GitHubCorpusPin("teorth", "erdosproblems", "README.md"),
    "formal_conjectures": GitHubCorpusPin(
        "google-deepmind",
        "formal-conjectures",
        "FormalConjectures/ErdosProblems/12.lean",
    ),
}
_MIN_COMMIT_SHA_LENGTH = 7
_MAX_PREVIEW_BYTES = 512


def build_query(endpoint_id: str, revision: str, limit: int) -> tuple[str, Mapping[str, Any]]:
    """Build a pinned raw-blob query for a public GitHub corpus."""
    del limit
    pin = _CORPUS_REPOS.get(endpoint_id)
    if pin is None:
        msg = f"unknown GitHub corpus endpoint {endpoint_id!r}"
        raise SourceRecordError(msg)
    return f"/{revision}/{pin.source_path}", {}


def source_uri(endpoint_id: str, revision: str) -> str:
    """Return the canonical GitHub blob URI for a pinned corpus source file."""
    pin = _CORPUS_REPOS.get(endpoint_id)
    if pin is None:
        msg = f"unknown GitHub corpus endpoint {endpoint_id!r}"
        raise SourceRecordError(msg)
    return f"https://github.com/{pin.owner}/{pin.repo}/blob/{revision}/{pin.source_path}"


def parse_github_commit(
    payload: bytes,
    policy: EndpointPolicy,
    retrieved_utc: str | None = None,
    *,
    revision: str,
    source_uri_override: str | None = None,
) -> list[SourceRecord]:
    """Parse a pinned GitHub raw blob into one normalized source record."""
    if retrieved_utc is None:
        retrieved_utc = _utc_now()
    vintage = retrieved_utc[:10]
    if not isinstance(revision, str) or len(revision) < _MIN_COMMIT_SHA_LENGTH:
        msg = "GitHub corpus revision must be a pinned commit sha"
        raise SourceRecordError(msg)
    if not payload:
        msg = "GitHub corpus raw blob payload is empty"
        raise SourceRecordError(msg)
    try:
        text_preview = payload[:_MAX_PREVIEW_BYTES].decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"GitHub corpus raw blob is not valid UTF-8 text: {exc}"
        raise SourceRecordError(msg) from exc
    if not text_preview.strip():
        msg = "GitHub corpus raw blob preview is blank"
        raise SourceRecordError(msg)
    uri = source_uri_override or source_uri(policy.endpoint_id, revision)

    fields = {
        "source": policy.endpoint_id,
        "source_uri": uri,
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
    """Fetch a pinned GitHub raw source blob and return normalized records."""
    path, params = build_query(policy.endpoint_id, revision, limit)
    payload, retrieved_utc = fetch_with_transport(
        policy.endpoint_id, path, params, transport, policy
    )
    return parse_github_commit(payload, policy, retrieved_utc, revision=revision)


__all__ = ["build_query", "parse_github_commit", "search", "source_uri"]
