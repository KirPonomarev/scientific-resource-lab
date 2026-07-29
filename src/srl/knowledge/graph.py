"""Source-grounded, taint-safe knowledge graph layer."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.knowledge.sources import SourceRecord

KNOWLEDGE_LAYER_MANIFEST_SCHEMA_VERSION: Final[str] = "KnowledgeLayerManifest/v1"
KNOWLEDGE_FACT_SCHEMA_VERSION: Final[str] = "KnowledgeFact/v1"
SOURCE_POLICY_CARD_SCHEMA_VERSION: Final[str] = "KnowledgeSourcePolicyCard/v1"

_INJECTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"exfiltrat(e|ion)", re.IGNORECASE),
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
)


class KnowledgeLayerError(ContractError):
    """Raised when a knowledge-layer object violates its contract."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class KnowledgeSourceStatus(StrEnum):
    """Admission state for a knowledge source."""

    ACTIVE = "ACTIVE"
    WAIT_ADAPTER = "WAIT_ADAPTER"
    WAIT_TERMS = "WAIT_TERMS"
    FORBIDDEN = "FORBIDDEN"


@dataclass(frozen=True)
class SourcePolicyCard:
    """Policy card for one literature or mathematical knowledge source."""

    source_id: str
    display_name: str
    status: KnowledgeSourceStatus
    endpoint_or_uri: str
    allowed_use: str
    terms_state: str
    attribution_required: bool
    adapter_module_or_null: str | None
    reason: str

    def __post_init__(self) -> None:
        for field in (
            "source_id",
            "display_name",
            "endpoint_or_uri",
            "allowed_use",
            "terms_state",
            "reason",
        ):
            _require_non_empty(getattr(self, field), field)
        if self.adapter_module_or_null is not None:
            _require_non_empty(self.adapter_module_or_null, "adapter_module_or_null")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible policy card."""
        return {
            "schema_version": SOURCE_POLICY_CARD_SCHEMA_VERSION,
            "source_id": self.source_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "endpoint_or_uri": self.endpoint_or_uri,
            "allowed_use": self.allowed_use,
            "terms_state": self.terms_state,
            "attribution_required": self.attribution_required,
            "adapter_module_or_null": self.adapter_module_or_null,
            "reason": self.reason,
            "raw_corpus_in_privileged_prompt": 0,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def default_source_policy_cards() -> tuple[SourcePolicyCard, ...]:
    """Return S14 source policy cards in deterministic order."""
    active = KnowledgeSourceStatus.ACTIVE
    return (
        SourcePolicyCard(
            "openalex",
            "OpenAlex",
            active,
            "https://api.openalex.org/works",
            "metadata lookup with attribution and byte/rate budgets",
            "CC0 metadata policy recorded by existing endpoint descriptor",
            True,
            "srl.knowledge.sources.openalex",
            "existing bounded adapter",
        ),
        SourcePolicyCard(
            "crossref",
            "Crossref",
            active,
            "https://api.crossref.org/works",
            "metadata lookup with attribution and byte/rate budgets",
            "Crossref metadata terms digest recorded by existing endpoint descriptor",
            True,
            "srl.knowledge.sources.crossref",
            "existing bounded adapter",
        ),
        SourcePolicyCard(
            "arxiv",
            "arXiv",
            active,
            "https://export.arxiv.org/api/query",
            "metadata and abstract lookup through bounded public API",
            "arXiv metadata policy recorded by existing endpoint descriptor",
            True,
            "srl.knowledge.sources.arxiv",
            "existing bounded adapter",
        ),
        SourcePolicyCard(
            "oeis",
            "OEIS",
            active,
            "https://oeis.org/search",
            "compact integer-sequence metadata lookup",
            "CC BY-NC terms recorded by existing endpoint descriptor",
            True,
            "srl.knowledge.sources.oeis",
            "existing bounded adapter",
        ),
        SourcePolicyCard(
            "opencitations",
            "OpenCitations",
            active,
            "https://api.opencitations.net/index/v2",
            "citation-count lookup with attribution and byte/rate budgets",
            "public API terms digest recorded by A11 endpoint descriptor",
            True,
            "srl.knowledge.sources.opencitations",
            "A11 bounded adapter",
        ),
        SourcePolicyCard(
            "zbmath",
            "zbMATH Open",
            active,
            "https://api.zbmath.org/v1/document/_search",
            "mathematical bibliographic metadata lookup with attribution and byte/rate budgets",
            "public API terms digest recorded by A11 endpoint descriptor",
            True,
            "srl.knowledge.sources.zbmath",
            "A11 bounded adapter",
        ),
        SourcePolicyCard(
            "lmfdb",
            "LMFDB",
            active,
            "https://www.lmfdb.org/api",
            "mathematical object metadata lookup with attribution and byte/rate budgets",
            "public API terms digest recorded by A11 endpoint descriptor",
            True,
            "srl.knowledge.sources.lmfdb",
            "A11 bounded adapter",
        ),
        SourcePolicyCard(
            "cslib",
            "CSLib",
            active,
            "https://raw.githubusercontent.com/leanprover/cslib/<rev>/README.md",
            "pinned public formal-library source blob lookup",
            "Apache-2.0 source identity pinned in Lean corpus pins and A11 endpoint descriptor",
            True,
            "srl.knowledge.sources.github_corpus",
            "A11 bounded adapter over pinned GitHub raw blob",
        ),
        SourcePolicyCard(
            "erdos_problems",
            "Erdos Problems",
            active,
            "https://raw.githubusercontent.com/teorth/erdosproblems/<rev>/README.md",
            "pinned public problem-list source blob lookup",
            "public repository metadata pinned in Lean corpus pins and A11 endpoint descriptor",
            True,
            "srl.knowledge.sources.github_corpus",
            "A11 bounded adapter over pinned GitHub raw blob",
        ),
        SourcePolicyCard(
            "formal_conjectures",
            "Formal Conjectures",
            active,
            "https://raw.githubusercontent.com/google-deepmind/formal-conjectures/<rev>/FormalConjectures/ErdosProblems/12.lean",
            "pinned public conjecture source blob lookup",
            "Apache-2.0 source identity pinned in Lean corpus pins and A11 endpoint descriptor",
            True,
            "srl.knowledge.sources.github_corpus",
            "A11 bounded adapter over pinned GitHub raw blob",
        ),
    )


def detect_corpus_injection(text: str) -> tuple[str, ...]:
    """Return prompt-injection findings for untrusted corpus text."""
    _require_non_empty(text, "text")
    return tuple(pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(text))


def build_knowledge_fact(
    record: SourceRecord,
    *,
    extracted_text: str,
    start_offset: int,
    end_offset: int,
) -> dict[str, object]:
    """Build a content-addressed fact node from a source record and text span."""
    _require_non_empty(extracted_text, "extracted_text")
    if isinstance(start_offset, bool) or isinstance(end_offset, bool):
        raise KnowledgeLayerError("offsets must be integers")
    if not isinstance(start_offset, int) or not isinstance(end_offset, int):
        raise KnowledgeLayerError("offsets must be integers")
    if start_offset < 0 or end_offset < start_offset or end_offset > len(extracted_text):
        raise KnowledgeLayerError("offsets must bound the extracted text")
    findings = detect_corpus_injection(extracted_text)
    taint_labels = ["untrusted_corpus"]
    if findings:
        taint_labels.append("prompt_injection_suspect")
    fact: dict[str, object] = {
        "schema_version": KNOWLEDGE_FACT_SCHEMA_VERSION,
        "record_id": record.record_id,
        "source": record.source,
        "source_uri": record.source_uri,
        "retrieved_utc": record.retrieved_utc,
        "vintage": record.vintage,
        "license_note": record.license_note,
        "payload_digest": record.payload_digest,
        "attribution": record.attribution,
        "span": {"start_offset": start_offset, "end_offset": end_offset},
        "text_sha256": "sha256:" + hashlib.sha256(extracted_text.encode("utf-8")).hexdigest(),
        "injection_findings": list(findings),
        "taint_labels": taint_labels,
        "raw_corpus_in_privileged_prompt": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    fact["fact_id"] = "sha256:" + hashlib.sha256(dumps(fact)).hexdigest()
    return fact


def build_knowledge_layer_manifest(
    *,
    facts: tuple[dict[str, object], ...],
    citation_edges: tuple[tuple[str, str], ...] = (),
    source_cards: tuple[SourcePolicyCard, ...] | None = None,
) -> dict[str, object]:
    """Build a deterministic knowledge-layer manifest."""
    cards = source_cards or default_source_policy_cards()
    fact_ids = _fact_ids(facts)
    edges = [_edge(source, target, fact_ids) for source, target in citation_edges]
    body: dict[str, object] = {
        "schema_version": KNOWLEDGE_LAYER_MANIFEST_SCHEMA_VERSION,
        "source_cards": [card.to_dict() for card in cards],
        "active_source_ids": [
            card.source_id for card in cards if card.status is KnowledgeSourceStatus.ACTIVE
        ],
        "wait_source_ids": [
            card.source_id
            for card in cards
            if card.status in {KnowledgeSourceStatus.WAIT_ADAPTER, KnowledgeSourceStatus.WAIT_TERMS}
        ],
        "forbidden_source_ids": [
            card.source_id for card in cards if card.status is KnowledgeSourceStatus.FORBIDDEN
        ],
        "facts": list(facts),
        "citation_edges": edges,
        "taint_policy": "raw_corpus_never_enters_privileged_prompt",
        "prompt_injection_fact_ids": [
            str(fact["fact_id"]) for fact in facts if _has_prompt_injection_taint(fact)
        ],
        "live_network_calls": 0,
        "raw_corpus_in_privileged_prompt": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["manifest_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def _fact_ids(facts: tuple[dict[str, object], ...]) -> frozenset[str]:
    ids: list[str] = []
    for fact in facts:
        fact_id = fact.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id:
            raise KnowledgeLayerError("facts must carry non-empty fact_id values")
        ids.append(fact_id)
    if len(set(ids)) != len(ids):
        raise KnowledgeLayerError("fact_id values must be unique")
    return frozenset(ids)


def _edge(source: str, target: str, fact_ids: frozenset[str]) -> dict[str, str]:
    if source not in fact_ids or target not in fact_ids:
        raise KnowledgeLayerError("citation edge endpoints must reference known fact_id values")
    return {"source_fact_id": source, "target_fact_id": target, "relation": "cites"}


def _has_prompt_injection_taint(fact: dict[str, object]) -> bool:
    labels = fact.get("taint_labels", [])
    return isinstance(labels, list) and "prompt_injection_suspect" in labels


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise KnowledgeLayerError(f"{field} must be a non-empty string")


__all__ = [
    "KNOWLEDGE_FACT_SCHEMA_VERSION",
    "KNOWLEDGE_LAYER_MANIFEST_SCHEMA_VERSION",
    "SOURCE_POLICY_CARD_SCHEMA_VERSION",
    "KnowledgeLayerError",
    "KnowledgeSourceStatus",
    "SourcePolicyCard",
    "build_knowledge_fact",
    "build_knowledge_layer_manifest",
    "default_source_policy_cards",
    "detect_corpus_injection",
]
