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
    search_github_corpus,
    search_lmfdb,
    search_oeis,
    search_openalex,
    search_opencitations,
    search_zbmath,
)
from srl.knowledge.sources.arxiv import build_query as build_arxiv_query
from srl.knowledge.sources.arxiv import parse_arxiv
from srl.knowledge.sources.crossref import build_query as build_crossref_query
from srl.knowledge.sources.crossref import parse_crossref
from srl.knowledge.sources.github_corpus import build_query as build_github_corpus_query
from srl.knowledge.sources.github_corpus import parse_github_commit
from srl.knowledge.sources.lmfdb import build_query as build_lmfdb_query
from srl.knowledge.sources.lmfdb import parse_lmfdb
from srl.knowledge.sources.oeis import parse_oeis
from srl.knowledge.sources.openalex import build_query as build_openalex_query
from srl.knowledge.sources.openalex import parse_openalex
from srl.knowledge.sources.opencitations import build_query as build_opencitations_query
from srl.knowledge.sources.opencitations import parse_opencitations
from srl.knowledge.sources.zbmath import build_query as build_zbmath_query
from srl.knowledge.sources.zbmath import parse_zbmath

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


# ---------------------------------------------------------------------------
# A11 added adapters.
# ---------------------------------------------------------------------------


def test_opencitations_build_query_uses_citation_count() -> None:
    """OpenCitations query builder uses the bounded citation-count endpoint."""
    path, params = build_opencitations_query("10.1108/jd-12-2013-0166", 10)
    assert path == "/citation-count/doi:10.1108/jd-12-2013-0166"
    assert params == {}


def test_opencitations_parse_normal_and_malformed() -> None:
    """OpenCitations normal payload parses and malformed payload is rejected."""
    policy = _policy("opencitations")
    records = parse_opencitations(_load("opencitations_normal_1.json"), policy)
    assert records[0].source == "opencitations"
    assert records[0].source_uri.startswith("https://api.opencitations.net/index/v2/")
    with pytest.raises(SourceRecordError) as exc_info:
        parse_opencitations(_load("opencitations_malformed.json"), policy)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_opencitations_search_with_fake_transport() -> None:
    """OpenCitations search fetches through the fake transport."""
    policy = _policy("opencitations")
    transport = fake_transport.FakeTransport(_load("opencitations_normal_1.json"))
    records = search_opencitations("10.1108/jd-12-2013-0166", 1, transport, policy)
    assert len(records) == 1


def test_zbmath_build_query_caps_results() -> None:
    """zbMATH query builder caps result count."""
    path, params = build_zbmath_query("graph", 100)
    assert path == "/document/_search"
    assert params["results_per_page"] == 25
    assert params["search_string"] == "graph"


def test_zbmath_parse_normal_and_malformed() -> None:
    """zbMATH normal payload parses and malformed payload is rejected."""
    policy = _policy("zbmath")
    records = parse_zbmath(_load("zbmath_normal_1.json"), policy)
    assert records[0].source == "zbmath"
    assert records[0].source_uri == "https://zbmath.org/?q=an:1234567"
    with pytest.raises(SourceRecordError) as exc_info:
        parse_zbmath(_load("zbmath_malformed.json"), policy)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_zbmath_search_with_fake_transport() -> None:
    """zbMATH search fetches through the fake transport."""
    policy = _policy("zbmath")
    transport = fake_transport.FakeTransport(_load("zbmath_normal_1.json"))
    records = search_zbmath("graph", 1, transport, policy)
    assert len(records) == 1


def test_lmfdb_build_query_uses_json_fields() -> None:
    """LMFDB query builder requests compact JSON fields."""
    path, params = build_lmfdb_query("rank 0", 100)
    assert path == "/ec_curvedata/"
    assert params["_format"] == "json"
    assert params["_fields"] == "lmfdb_label,rank"
    assert params["_limit"] == 25


def test_lmfdb_parse_normal_and_malformed() -> None:
    """LMFDB normal payload parses and malformed payload is rejected."""
    policy = _policy("lmfdb")
    records = parse_lmfdb(_load("lmfdb_normal_1.json"), policy)
    assert records[0].source == "lmfdb"
    assert records[0].source_uri == "https://www.lmfdb.org/EllipticCurve/Q/11.a1"
    with pytest.raises(SourceRecordError) as exc_info:
        parse_lmfdb(_load("lmfdb_malformed.json"), policy)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_lmfdb_search_with_fake_transport() -> None:
    """LMFDB search fetches through the fake transport."""
    policy = _policy("lmfdb")
    transport = fake_transport.FakeTransport(_load("lmfdb_normal_1.json"))
    records = search_lmfdb("rank 0", 1, transport, policy)
    assert len(records) == 1


def test_github_corpus_build_query_pins_public_repo() -> None:
    """GitHub corpus query builder stays on pinned public raw source blobs."""
    path, params = build_github_corpus_query("cslib", "93aa057", 1)
    assert path == "/93aa057/README.md"
    assert params == {}


def test_github_corpus_parse_normal_and_malformed() -> None:
    """GitHub corpus normal raw blob parses and malformed payload is rejected."""
    policy = _policy("cslib")
    records = parse_github_commit(
        b"# CSLib\n\nPinned public source metadata.\n",
        policy,
        revision="93aa05752a62ad3498e734d5b75fcbff965891ce",
    )
    assert records[0].source == "cslib"
    assert records[0].source_uri.endswith("/93aa05752a62ad3498e734d5b75fcbff965891ce/README.md")
    with pytest.raises(SourceRecordError) as exc_info:
        parse_github_commit(
            b"",
            policy,
            revision="93aa05752a62ad3498e734d5b75fcbff965891ce",
        )
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_github_corpus_search_with_fake_transport() -> None:
    """GitHub corpus search fetches pinned raw blobs through the fake transport."""
    policy = _policy("cslib")
    transport = fake_transport.FakeTransport(b"# CSLib\n\nPinned public source metadata.\n")
    records = search_github_corpus("93aa05752a62ad3498e734d5b75fcbff965891ce", 1, transport, policy)
    assert len(records) == 1
