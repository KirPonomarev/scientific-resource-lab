"""Budgeted API retriever and P0 knowledge adapter descriptors (WP-D33).

This package encodes the knowledge-retrieval contract: a budgeted,
content-addressed retriever (:mod:`srl.knowledge.retriever`) that fetches bytes
from a declared HTTPS endpoint under an :class:`EndpointPolicy` allowlist and
records an immutable :class:`QueryReceipt`. The P0 endpoint descriptors
(:mod:`srl.knowledge.adapters`) declare the conservative policy for the four
launch endpoints (OpenAlex, Crossref, arXiv, OEIS).

Honesty model
-------------
A query receipt proves *retrieval*, not *truth*. The vintage (retrieval date)
is part of the receipt because a response's meaning can drift over time. The
retriever never carries credentials and never grants the authority to make a
scientific claim (``grants_authority`` is always ``False``).

It is intentionally standard library only (HTTP via :mod:`urllib`), mirroring
the autonomy primitives in :mod:`srl.autonomy`, so it runs in any environment
without coupling to the scientific contracts layer's ``jsonschema`` dependency.
"""

from __future__ import annotations

from srl.knowledge.adapters import (
    FORBIDDEN_SOURCES,
    P0_ENDPOINT_POLICY_REGISTRY,
    p0_registry,
)
from srl.knowledge.graph import (
    KNOWLEDGE_FACT_SCHEMA_VERSION,
    KNOWLEDGE_LAYER_MANIFEST_SCHEMA_VERSION,
    SOURCE_POLICY_CARD_SCHEMA_VERSION,
    KnowledgeLayerError,
    KnowledgeSourceStatus,
    SourcePolicyCard,
    build_knowledge_fact,
    build_knowledge_layer_manifest,
    default_source_policy_cards,
    detect_corpus_injection,
)
from srl.knowledge.retriever import (
    DEFAULT_TIMEOUT_SECONDS,
    ENDPOINT_POLICY_SCHEMA_VERSION,
    LICENSE_UNKNOWN_FAIL_REASON,
    MAX_RETRIES,
    NETWORK_POLICY_FAIL_REASON,
    QUERY_RECEIPT_SCHEMA_VERSION,
    RATE_LIMITED_FAIL_REASON,
    RESOURCE_LIMIT_FAIL_REASON,
    TIMEOUT_FAIL_REASON,
    ApiRetriever,
    EndpointPolicy,
    FetchResult,
    NetworkPolicyError,
    PolicyRegistry,
    QueryReceipt,
    RateLimitedError,
    ResourceLimitError,
    RetrievalTimeoutError,
    Transport,
    TransportResponse,
    UrllibTransport,
    construct_retriever,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ENDPOINT_POLICY_SCHEMA_VERSION",
    "FORBIDDEN_SOURCES",
    "KNOWLEDGE_FACT_SCHEMA_VERSION",
    "KNOWLEDGE_LAYER_MANIFEST_SCHEMA_VERSION",
    "LICENSE_UNKNOWN_FAIL_REASON",
    "MAX_RETRIES",
    "NETWORK_POLICY_FAIL_REASON",
    "P0_ENDPOINT_POLICY_REGISTRY",
    "QUERY_RECEIPT_SCHEMA_VERSION",
    "RATE_LIMITED_FAIL_REASON",
    "RESOURCE_LIMIT_FAIL_REASON",
    "SOURCE_POLICY_CARD_SCHEMA_VERSION",
    "TIMEOUT_FAIL_REASON",
    "ApiRetriever",
    "EndpointPolicy",
    "FetchResult",
    "KnowledgeLayerError",
    "KnowledgeSourceStatus",
    "NetworkPolicyError",
    "PolicyRegistry",
    "QueryReceipt",
    "RateLimitedError",
    "ResourceLimitError",
    "RetrievalTimeoutError",
    "SourcePolicyCard",
    "Transport",
    "TransportResponse",
    "UrllibTransport",
    "build_knowledge_fact",
    "build_knowledge_layer_manifest",
    "construct_retriever",
    "default_source_policy_cards",
    "detect_corpus_injection",
    "p0_registry",
]
