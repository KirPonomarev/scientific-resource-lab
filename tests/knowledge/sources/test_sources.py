"""Hermetic tests for the P0 knowledge source adapters (WP-E44).

All tests use the synthetic fixtures under ``fixtures/conformance/knowledge/sources/``
and the fake transport from the D33 conformance directory; no test makes a live
HTTP request.
"""

from __future__ import annotations

import canned_payloads
import fake_transport
import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.knowledge.retriever import EndpointPolicy
from srl.knowledge.sources import (
    SourceRecord,
    SourceRecordError,
    search_arxiv,
    search_crossref,
    search_oeis,
    search_openalex,
)
from srl.knowledge.sources.arxiv import build_query as build_arxiv_query
from srl.knowledge.sources.arxiv import parse_arxiv
from srl.knowledge.sources.crossref import build_query as build_crossref_query
from srl.knowledge.sources.crossref import parse_crossref
from srl.knowledge.sources.oeis import parse_oeis
from srl.knowledge.sources.openalex import build_query as build_openalex_query
from srl.knowledge.sources.openalex import parse_openalex

_LICENSE_SHA256 = "sha256:" + "ab" * 32


def _policy(endpoint_id: str, byte_budget: int = 1024) -> EndpointPolicy:
    """Return a synthetic endpoint policy for ``endpoint_id``."""
    return EndpointPolicy(
        endpoint_id=endpoint_id,
        base_url=f"https://{endpoint_id}.example.org",
        rate_limit_per_minute=10,
        byte_budget=byte_budget,
        cost_budget_units=10,
        license_terms_sha256=_LICENSE_SHA256,
        attribution_required=True,
        attribution_text=f"Synthetic attribution for {endpoint_id}.",
        retention_days=30,
    )


def _load(name: str) -> bytes:
    """Load a canned synthetic payload by name."""
    return canned_payloads.canned_payload(name)


# ---------------------------------------------------------------------------
# OpenAlex adapter.
# ---------------------------------------------------------------------------


def test_openalex_build_query_caps_per_page_and_uses_filter_select() -> None:
    """OpenAlex query builder uses filter/select and caps per-page at 25."""
    path, params = build_openalex_query("test query", 100)
    assert path == "/works"
    assert params["filter"] == "title.search:test query"
    assert params["select"] == "id,doi,title,authorships,publication_year,cited_by_count"
    assert params["per-page"] == 25


def test_openalex_build_query_includes_mailto_only_when_supplied() -> None:
    """OpenAlex query builder never adds a default mailto identity."""
    _, params_without = build_openalex_query("test", 5)
    assert "mailto" not in params_without
    _, params_with = build_openalex_query("test", 5, mailto="operator@example.org")
    assert params_with["mailto"] == "operator@example.org"


def test_openalex_parse_normal_1() -> None:
    """OpenAlex normal fixture 1 parses into a valid SourceRecord."""
    policy = _policy("openalex")
    records = parse_openalex(_load("openalex_normal_1.json"), policy, "2026-07-28T00:00:00Z")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SourceRecord)
    assert record.source == "openalex"
    assert record.source_uri == "https://openalex.org/works/W1234567890"
    assert record.retrieved_utc == "2026-07-28T00:00:00Z"
    assert record.vintage == "2026-07-28"
    assert record.license_note == _LICENSE_SHA256
    assert record.attribution == "Synthetic attribution for openalex."
    assert record.payload_digest.startswith("sha256:")
    assert record.record_id.startswith("sha256:")


def test_openalex_parse_normal_2() -> None:
    """OpenAlex normal fixture 2 (bare URL id) parses into a valid SourceRecord."""
    policy = _policy("openalex")
    records = parse_openalex(_load("openalex_normal_2.json"), policy)
    assert len(records) == 1
    assert records[0].source_uri == "https://openalex.org/works/W9876543210"


def test_openalex_parse_malformed() -> None:
    """Malformed OpenAlex payload raises a typed CONTRACT_INVALID error."""
    policy = _policy("openalex")
    with pytest.raises(SourceRecordError) as exc_info:
        parse_openalex(_load("openalex_malformed.json"), policy)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_openalex_search_with_fake_transport() -> None:
    """OpenAlex search fetches via the fake transport and returns records."""
    policy = _policy("openalex")
    transport = fake_transport.FakeTransport(_load("openalex_normal_1.json"))
    records = search_openalex("synthetic", 10, transport, policy)
    assert len(records) == 1
    assert records[0].source == "openalex"
    assert records[0].source_uri == "https://openalex.org/works/W1234567890"


# ---------------------------------------------------------------------------
# Crossref adapter.
# ---------------------------------------------------------------------------


def test_crossref_build_query_caps_per_page() -> None:
    """Crossref query builder uses query/rows and caps rows at 25."""
    path, params = build_crossref_query("synthetic", 50)
    assert path == "/works"
    assert params["query"] == "synthetic"
    assert params["rows"] == 25


def test_crossref_parse_normal_1() -> None:
    """Crossref work-list fixture parses into a valid SourceRecord."""
    policy = _policy("crossref")
    records = parse_crossref(_load("crossref_normal_1.json"), policy)
    assert len(records) == 1
    assert records[0].source == "crossref"
    assert records[0].source_uri == "https://doi.org/10.1234/synthetic.crossref.1"
    assert records[0].attribution == "Synthetic attribution for crossref."


def test_crossref_parse_normal_2_single_work() -> None:
    """Crossref single-work fixture parses into a valid SourceRecord."""
    policy = _policy("crossref")
    records = parse_crossref(_load("crossref_normal_2.json"), policy)
    assert len(records) == 1
    assert records[0].source_uri == "https://doi.org/10.5678/synthetic.crossref.2"


def test_crossref_parse_malformed() -> None:
    """Malformed Crossref payload raises a typed CONTRACT_INVALID error."""
    policy = _policy("crossref")
    with pytest.raises(SourceRecordError) as exc_info:
        parse_crossref(_load("crossref_malformed.json"), policy)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_crossref_search_with_fake_transport() -> None:
    """Crossref search fetches via the fake transport and returns records."""
    policy = _policy("crossref")
    transport = fake_transport.FakeTransport(_load("crossref_normal_1.json"))
    records = search_crossref("synthetic", 5, transport, policy)
    assert len(records) == 1
    assert records[0].source_uri == "https://doi.org/10.1234/synthetic.crossref.1"


# ---------------------------------------------------------------------------
# arXiv adapter.
# ---------------------------------------------------------------------------


def test_arxiv_build_query_caps_per_page() -> None:
    """arXiv query builder uses search_query/max_results and caps at 25."""
    path, params = build_arxiv_query("synthetic", 100)
    assert path == "/api/query"
    assert params["search_query"] == "all:synthetic"
    assert params["max_results"] == 25


def test_arxiv_parse_normal_1() -> None:
    """arXiv normal fixture 1 parses into a valid SourceRecord."""
    policy = _policy("arxiv")
    records = parse_arxiv(_load("arxiv_normal_1.xml"), policy)
    assert len(records) == 1
    assert records[0].source == "arxiv"
    assert records[0].source_uri == "https://arxiv.org/abs/synthetic.2024.00001"
    assert records[0].attribution == "Synthetic attribution for arxiv."


def test_arxiv_parse_normal_2() -> None:
    """arXiv normal fixture 2 (https id) parses into a valid SourceRecord."""
    policy = _policy("arxiv")
    records = parse_arxiv(_load("arxiv_normal_2.xml"), policy)
    assert len(records) == 1
    assert records[0].source_uri == "https://arxiv.org/abs/2101.99999"


def test_arxiv_parse_malformed() -> None:
    """Malformed arXiv payload raises a typed CONTRACT_INVALID error."""
    policy = _policy("arxiv")
    with pytest.raises(SourceRecordError) as exc_info:
        parse_arxiv(_load("arxiv_malformed.xml"), policy)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_arxiv_search_with_fake_transport() -> None:
    """arXiv search fetches via the fake transport and returns records."""
    policy = _policy("arxiv")
    transport = fake_transport.FakeTransport(_load("arxiv_normal_1.xml"))
    records = search_arxiv("synthetic", 5, transport, policy)
    assert len(records) == 1
    assert records[0].source_uri == "https://arxiv.org/abs/synthetic.2024.00001"


# ---------------------------------------------------------------------------
# OEIS adapter.
# ---------------------------------------------------------------------------


def test_oeis_parse_normal_1() -> None:
    """OEIS normal fixture 1 parses into a valid SourceRecord."""
    policy = _policy("oeis")
    records = parse_oeis(_load("oeis_normal_1.json"), policy)
    assert len(records) == 1
    assert records[0].source == "oeis"
    assert records[0].source_uri == "https://oeis.org/A000045"
    assert records[0].attribution == "Synthetic attribution for oeis."


def test_oeis_parse_normal_2() -> None:
    """OEIS normal fixture 2 parses into a valid SourceRecord."""
    policy = _policy("oeis")
    records = parse_oeis(_load("oeis_normal_2.json"), policy)
    assert len(records) == 1
    assert records[0].source_uri == "https://oeis.org/A000027"


def test_oeis_parse_malformed() -> None:
    """Malformed OEIS payload raises a typed CONTRACT_INVALID error."""
    policy = _policy("oeis")
    with pytest.raises(SourceRecordError) as exc_info:
        parse_oeis(_load("oeis_malformed.json"), policy)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_oeis_search_with_fake_transport() -> None:
    """OEIS search fetches via the fake transport and returns records."""
    policy = _policy("oeis")
    transport = fake_transport.FakeTransport(_load("oeis_normal_1.json"))
    records = search_oeis("A000045", 5, transport, policy)
    assert len(records) == 1
    assert records[0].source_uri == "https://oeis.org/A000045"
