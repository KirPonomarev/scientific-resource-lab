"""Hermetic tests for the budgeted API retriever (WP-D33).

All tests use the fake transport and canned fixtures under
``fixtures/conformance/knowledge/``; no test makes a live HTTP request.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import Any

import fake_transport
import pytest

from srl.knowledge.adapters import FORBIDDEN_SOURCES, p0_registry
from srl.knowledge.retriever import (
    NETWORK_POLICY_FAIL_REASON,
    RATE_LIMITED_FAIL_REASON,
    RESOURCE_LIMIT_FAIL_REASON,
    TIMEOUT_FAIL_REASON,
    ApiRetriever,
    NetworkPolicyError,
    PolicyRegistry,
    QueryReceipt,
    RateLimitedError,
    ResourceLimitError,
    RetrievalTimeoutError,
    TransportResponse,
    construct_retriever,
)

# A stable synthetic license digest for tests that build their own policies.
_LICENSE_SHA256 = "sha256:" + "ab" * 32


def _make_policy(**kwargs: Any) -> PolicyRegistry:
    """Return a single-endpoint policy registry with generous defaults."""
    endpoint = {
        "endpoint_id": "openalex",
        "base_url": "https://api.openalex.org",
        "rate_limit_per_minute": 10,
        "byte_budget": 1024,
        "cost_budget_units": 10,
        "license_terms_sha256": _LICENSE_SHA256,
        "attribution_required": True,
        "attribution_text": "Synthetic attribution for tests.",
        "retention_days": 30,
    }
    endpoint.update(kwargs)
    return PolicyRegistry.from_dict(
        {"schema_version": "EndpointPolicy/v1", "endpoints": [endpoint]}
    )


class _ErrorThenSuccessTransport:
    """A fake transport that raises HTTPError statuses, then returns success."""

    def __init__(
        self,
        errors: list[int],
        payload: bytes,
        *,
        final_host: str = "api.openalex.org",
    ) -> None:
        self._errors = list(errors)
        self._payload = payload
        self.final_host = final_host
        self.calls: list[tuple[str, int]] = []

    def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:
        """Return the next error or the final success payload."""
        self.calls.append((url, timeout_seconds))
        if self._errors:
            status = self._errors.pop(0)
            raise urllib.error.HTTPError(url, status, f"HTTP {status}", {}, None)
        return TransportResponse(
            payload=self._payload,
            final_scheme="https",
            final_host=self.final_host,
            status=200,
        )


# ---------------------------------------------------------------------------
# Adapter / registry policy pins.
# ---------------------------------------------------------------------------


def test_p0_registry_has_a11_https_endpoints() -> None:
    """The registry contains the A11 public-source HTTPS allowlist."""
    registry = p0_registry()
    assert set(registry.policies) == {
        "openalex",
        "crossref",
        "arxiv",
        "oeis",
        "opencitations",
        "zbmath",
        "lmfdb",
        "cslib",
        "erdos_problems",
        "formal_conjectures",
    }
    for policy in registry.policies.values():
        assert policy.base_url.startswith("https://")
        assert policy.rate_limit_per_minute == 10
        assert policy.byte_budget == 50 * 1024 * 1024
        assert policy.cost_budget_units == 1000
        assert policy.attribution_required is True
        assert policy.attribution_text
        assert policy.retention_days == 30


def test_forbidden_sources_exclude_credential_endpoints() -> None:
    """FRED, ALFRED, and Wolfram are deliberately absent from the P0 set."""
    assert {"fred", "alfred", "wolfram", "wolframalpha"} <= FORBIDDEN_SOURCES


def test_policy_registry_rejects_unknown_endpoint() -> None:
    """An unknown endpoint raises a typed network policy error."""
    registry = _make_policy()
    with pytest.raises(NetworkPolicyError) as exc_info:
        registry.get("crossref")
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON


def test_policy_registry_rejects_http_base_url() -> None:
    """A policy with an http:// base URL is refused at registry construction."""
    with pytest.raises(NetworkPolicyError) as exc_info:
        _make_policy(base_url="http://api.openalex.org")
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON


# ---------------------------------------------------------------------------
# Core fetch behavior.
# ---------------------------------------------------------------------------


def test_fetch_unknown_endpoint_raises_network_policy(tmp_path: Path) -> None:
    """A fetch against an endpoint not in the registry is refused."""
    registry = _make_policy()
    retriever = ApiRetriever()
    with pytest.raises(NetworkPolicyError) as exc_info:
        retriever.fetch(
            "crossref",
            "/works",
            {"q": "test"},
            tmp_path,
            registry,
            transport=fake_transport.FakeTransport(),
        )
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON


def test_fetch_non_https_redirect_raises_network_policy(tmp_path: Path) -> None:
    """A final URL scheme that is not https is refused."""
    registry = _make_policy()
    payload = fake_transport.canned_payload("openalex_works.json")
    transport = fake_transport.FakeTransport(payload, scheme="http")
    retriever = ApiRetriever()
    with pytest.raises(NetworkPolicyError) as exc_info:
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "test"},
            tmp_path,
            registry,
            transport=transport,
        )
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON


def test_fetch_byte_budget_refuses_oversize_and_leaks_nothing(
    tmp_path: Path,
) -> None:
    """An oversized response is refused and nothing is cached or deducted."""
    registry = _make_policy(byte_budget=10)
    oversized = b"x" * 200
    transport = fake_transport.FakeTransport(oversized)
    retriever = ApiRetriever()
    with pytest.raises(ResourceLimitError) as exc_info:
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "test"},
            tmp_path,
            registry,
            transport=transport,
        )
    assert exc_info.value.fail_reason == RESOURCE_LIMIT_FAIL_REASON
    assert exc_info.value.endpoint_id == "openalex"
    assert not list(tmp_path.rglob("*.bin"))
    assert not list(tmp_path.glob("budget-*"))


def test_fetch_rate_limit_returns_typed_wait(tmp_path: Path) -> None:
    """A second request past the limit returns a typed WAIT_RESOURCE error."""
    registry = _make_policy(rate_limit_per_minute=1, cost_budget_units=2)
    payload = fake_transport.canned_payload("openalex_works.json")
    transport = fake_transport.FakeTransport(payload)
    retriever = ApiRetriever()
    first = retriever.fetch(
        "openalex",
        "/works",
        {"q": "first"},
        tmp_path,
        registry,
        transport=transport,
    )
    assert first.receipt.cached is False
    with pytest.raises(RateLimitedError) as exc_info:
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "second"},
            tmp_path,
            registry,
            transport=transport,
            rate_limit_sleep=False,
        )
    assert exc_info.value.fail_reason == RATE_LIMITED_FAIL_REASON
    assert exc_info.value.endpoint_id == "openalex"
    assert exc_info.value.retry_after_seconds > 0


def test_fetch_cache_hit_is_cached_with_same_identity(tmp_path: Path) -> None:
    """A repeated fetch returns the cached receipt with the same content hash."""
    registry = _make_policy(cost_budget_units=2)
    payload = fake_transport.canned_payload("openalex_works.json")
    transport = fake_transport.FakeTransport(payload)
    retriever = ApiRetriever()
    first = retriever.fetch(
        "openalex",
        "/works",
        {"q": "cache"},
        tmp_path,
        registry,
        transport=transport,
    )
    second = retriever.fetch(
        "openalex",
        "/works",
        {"q": "cache"},
        tmp_path,
        registry,
        transport=transport,
    )
    assert first.receipt.cached is False
    assert second.receipt.cached is True
    assert first.receipt.receipt_id == second.receipt.receipt_id
    assert first.receipt.response_sha256 == second.receipt.response_sha256
    assert len(transport.calls) == 1


def test_fetch_retries_429_then_succeeds(tmp_path: Path) -> None:
    """A 429 followed by a 200 is retried and succeeds."""
    payload = fake_transport.canned_payload("openalex_works.json")
    transport = _ErrorThenSuccessTransport([429], payload)
    registry = _make_policy()
    retriever = ApiRetriever()
    result = retriever.fetch(
        "openalex",
        "/works",
        {"q": "retry-429"},
        tmp_path,
        registry,
        transport=transport,
    )
    assert result.receipt.cached is False
    assert result.payload == payload
    assert len(transport.calls) == 2


def test_fetch_retries_500_then_succeeds(tmp_path: Path) -> None:
    """A 500 followed by a 200 is retried and succeeds."""
    payload = fake_transport.canned_payload("crossref_works.json")
    transport = _ErrorThenSuccessTransport([500], payload, final_host="api.crossref.org")
    registry = _make_policy(endpoint_id="crossref", base_url="https://api.crossref.org")
    retriever = ApiRetriever()
    result = retriever.fetch(
        "crossref",
        "/works",
        {"q": "retry-500"},
        tmp_path,
        registry,
        transport=transport,
    )
    assert result.receipt.cached is False
    assert len(transport.calls) == 2


def test_fetch_retry_exhausts_on_persistent_500(tmp_path: Path) -> None:
    """Persistent 500 responses are retried up to 2 times, then refused."""
    payload = fake_transport.canned_payload("openalex_works.json")
    transport = _ErrorThenSuccessTransport([500, 500, 500], payload)
    registry = _make_policy()
    retriever = ApiRetriever()
    with pytest.raises(NetworkPolicyError) as exc_info:
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "exhaust"},
            tmp_path,
            registry,
            transport=transport,
        )
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON
    assert len(transport.calls) == 3


def test_fetch_timeout_is_typed_timeout(tmp_path: Path) -> None:
    """A transport timeout surfaces as a typed TIMEOUT error."""

    class TimeoutTransport:
        def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:
            raise RetrievalTimeoutError("simulated timeout")

    registry = _make_policy()
    retriever = ApiRetriever()
    with pytest.raises(RetrievalTimeoutError) as exc_info:
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "timeout"},
            tmp_path,
            registry,
            transport=TimeoutTransport(),
        )
    assert exc_info.value.fail_reason == TIMEOUT_FAIL_REASON


# ---------------------------------------------------------------------------
# Credential rejection.
# ---------------------------------------------------------------------------


def test_construct_retriever_rejects_api_key_kwarg() -> None:
    """A credential-like constructor keyword is refused before any network call."""
    with pytest.raises(NetworkPolicyError) as exc_info:
        construct_retriever(api_key="super-secret-key")
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON


def test_construct_retriever_rejects_authorization_header() -> None:
    """A forbidden Authorization header is refused."""
    with pytest.raises(NetworkPolicyError) as exc_info:
        construct_retriever(headers={"Authorization": "Bearer secret"})
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON


def test_construct_retriever_rejects_x_api_key_header() -> None:
    """A forbidden x-api-key header is refused."""
    with pytest.raises(NetworkPolicyError) as exc_info:
        construct_retriever(headers={"x-api-key": "secret"})
    assert exc_info.value.fail_reason == NETWORK_POLICY_FAIL_REASON


# ---------------------------------------------------------------------------
# Receipt safety / shape pins.
# ---------------------------------------------------------------------------


def test_query_receipt_safety_consts_and_schema(tmp_path: Path) -> None:
    """A receipt carries the right schema, safety consts, and required fields."""
    registry = _make_policy()
    payload = fake_transport.canned_payload("oeis_b000045.json")
    retriever = ApiRetriever()
    result = retriever.fetch(
        "openalex",
        "/works",
        {"q": "receipt-shape"},
        tmp_path,
        registry,
        transport=fake_transport.FakeTransport(payload),
    )
    receipt: QueryReceipt = result.receipt
    assert receipt.schema_version == "QueryReceipt/v1"
    assert receipt.endpoint_id == "openalex"
    assert receipt.request_url_digest.startswith("sha256:")
    assert receipt.params_digest.startswith("sha256:")
    assert receipt.response_sha256.startswith("sha256:")
    assert receipt.bytes == len(payload)
    assert receipt.cached is False
    assert receipt.retrieved_utc.endswith("Z")
    assert receipt.license_terms_sha256 == _LICENSE_SHA256
    assert receipt.vintage == receipt.retrieved_utc[:10]
    assert receipt.canonical_writes == 0
    assert receipt.grants_authority is False
    assert receipt.receipt_id.startswith("sha256:")


def test_query_receipt_to_dict_roundtrips() -> None:
    """Receipt.to_dict exposes all public fields."""
    receipt = QueryReceipt(
        schema_version="QueryReceipt/v1",
        receipt_id="sha256:" + "00" * 32,
        endpoint_id="openalex",
        request_url_digest="sha256:" + "11" * 32,
        params_digest="sha256:" + "22" * 32,
        response_sha256="sha256:" + "33" * 32,
        bytes=42,
        cached=True,
        retrieved_utc="2026-07-28T00:00:00Z",
        license_terms_sha256="sha256:" + "44" * 32,
        vintage="2026-07-28",
        canonical_writes=0,
        grants_authority=False,
        attribution="Data from OpenAlex.",
    )
    data = receipt.to_dict()
    assert data["schema_version"] == "QueryReceipt/v1"
    assert data["endpoint_id"] == "openalex"
    assert data["bytes"] == 42
    assert data["cached"] is True
    assert data["canonical_writes"] == 0
    assert data["grants_authority"] is False
    assert data["attribution"] == "Data from OpenAlex."
