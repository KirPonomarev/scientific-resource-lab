# Budgeted API retriever and query receipts (WP-D33)

This document is the architecture reference for the SRL knowledge-retrieval plane
(`srl.knowledge`): a budgeted, content-addressed, credential-free HTTPS
retriever that records an immutable query receipt for every external fetch. The
machine-checkable contracts live in `src/srl/knowledge/`; this document is the
prose that explains *why* they are shaped the way they are.

> A query receipt proves *retrieval*, not *truth*. It records what was fetched,
> when, from which endpoint, and under which license terms. It never carries
> credentials, never mutates canonical state, and never grants the authority to
> make a scientific claim.

## Honesty model

The retriever is deliberately modest. Its job is to fetch a byte sequence from
a declared HTTPS endpoint under a declared policy, and to prove that the fetch
happened. The resulting `QueryReceipt/v1` is content-addressed and immutable,
with two safety constants that are never allowed to change:

- `canonical_writes` is always `0` — a retrieval never mutates canonical state.
- `grants_authority` is always `false` — a retrieval never grants the authority
  to assert a scientific claim.

The receipt includes a *vintage* (`retrieved_utc` and `vintage`) because the
meaning of a response can drift over time. It includes a `license_terms_sha256`
so the provenance of the license terms is verifiable. It records digests of the
request URL and parameters rather than the raw values, because query strings may
carry secrets or session identifiers that should not be committed to history.

## Threat model and credential ban

The retriever is credential-free by design. This is a hard boundary, not a
default:

- Constructor keywords that resemble auth headers or tokens (`authorization`,
  `x-api-key`, `cookie`, `api_key`, `token`, `secret`, `bearer`, and a small set
  of common variants) are rejected before the retriever exists.
- A `headers` mapping containing any forbidden header name is also rejected.
- The retriever never reads environment variables for credentials.

The P0 adapter set reflects this policy. OpenAlex, Crossref, arXiv, and OEIS are
included because they offer polite, credential-free access. FRED, ALFRED, and
Wolfram|Alpha are deliberately absent because they require an API key or AppID.
They are listed in `FORBIDDEN_SOURCES` so a future contributor cannot silently
add them without confronting the credential policy.

## Endpoint policy registry

Every egress target is described by an `EndpointPolicy/v1` and collected in a
`PolicyRegistry`. The registry is the allowlist: a fetch against an unknown
`endpoint_id` raises `NetworkPolicyError` (`NETWORK_POLICY_VIOLATION`) before any
network call.

Each policy pins:

| Field | Purpose |
|-------|---------|
| `endpoint_id` | Stable registry key (e.g. `openalex`). |
| `base_url` | HTTPS base URL only; `http://` is refused. |
| `rate_limit_per_minute` | Token-bucket capacity for per-endpoint politeness. |
| `byte_budget` | Total response bytes the mission may spend on this endpoint. |
| `cost_budget_units` | Abstract cost units for metered endpoints. |
| `license_terms_sha256` | Digest of the endpoint's license terms, carried on every receipt. |
| `attribution_required` | Whether an attribution string must be recorded. |
| `retention_days` | Cache retention for this endpoint's payloads. |

The registry is loaded from an in-repo JSON document, never from the network.

## Fetch flow

```
endpoint_id + path + params + policy_registry
        │
        ▼
 1. endpoint in allowlist? ──No──▶ NETWORK_POLICY_VIOLATION
        │
        ▼
 2. build URL and assert https:// ──No──▶ NETWORK_POLICY_VIOLATION
        │
        ▼
 3. content-addressed cache hit? ──Yes──▶ QueryReceipt(cached=true)
        │
        ▼
 4. acquire token-bucket rate limit ──No──▶ WAIT_RESOURCE
        │
        ▼
 5. fetch with bounded retry (429 / 5xx, max 2 retries)
        │
        ▼
 6. response size <= remaining byte budget? ──No──▶ RESOURCE_LIMIT, nothing cached
        │
        ▼
 7. deduct cost unit, write payload to content-addressed store
        │
        ▼
 8. emit QueryReceipt(cached=false)
```

The wall-clock budget for a single transport call is 30 seconds by default. A
timeout surfaces as `RetrievalTimeoutError` (`TIMEOUT`), not as a generic
connection failure.

## Content-addressed cache

The cache is a local content-addressed store keyed by the SHA-256 of the canonical
encoding of `{"endpoint_id": ..., "url": ..., "params": ...}`. Two requests
with the same endpoint, URL, and parameters produce the same key, so a cache hit
returns the identical payload and a receipt whose `response_sha256` matches.

Payloads are stored with a sidecar metadata file. The metadata records the
`response_sha256`, and the cache read path verifies the stored bytes still hash
to that digest. A corrupted or tampered payload is detected rather than silently
served.

## Rate limiter

The rate limiter is a persistent token bucket. Each endpoint has its own bucket
with capacity `rate_limit_per_minute` and refill rate `capacity / 60` tokens per
second. The bucket state is stored in the cache directory, so the limit is
enforced across process restarts. By default the retriever sleeps until a token
is available; the gate and tests pass `rate_limit_sleep=False` to assert that a
typed `RateLimitedError` (`WAIT_RESOURCE`) is raised instead.

## Budget accounting

The retriever tracks two per-endpoint budgets, also persisted in the cache
directory:

- **Byte budget**: a response larger than the remaining budget is refused with
  `ResourceLimitError` (`RESOURCE_LIMIT`). The oversized response is **not**
  cached and the budget is **not** deducted.
- **Cost budget**: each successful fetch consumes one abstract cost unit. An
  exhausted cost budget is also a `RESOURCE_LIMIT`.

This makes the retriever a bounded, mission-scoped resource consumer rather than
an open-ended client.

## Transport contract

The transport is injectable. The default implementation is a thin `urllib`
wrapper (`UrllibTransport`) that uses no third-party HTTP library. Tests and the
WP-D33 gate inject `FakeTransport` from `fixtures/conformance/knowledge/`, which
returns canned bytes and never makes a live request. The transport contract
returns the final (post-redirect) scheme and host, so the retriever can re-assert
HTTPS after a redirect.

## Receipt identity

A `QueryReceipt/v1` is a frozen dataclass with the following fields:

- `schema_version` — `QueryReceipt/v1`
- `receipt_id` — SHA-256 digest of the retrieval-defining fields
- `endpoint_id`, `request_url_digest`, `params_digest`, `response_sha256`
- `bytes`, `cached`, `retrieved_utc`, `license_terms_sha256`, `vintage`
- `canonical_writes` — always `0`
- `grants_authority` — always `false`
- `attribution` — optional attribution text from the endpoint policy

The `receipt_id` is stable: the same request and the same payload bytes yield
the same id for both a fresh fetch and a cache hit. The `cached` flag distinguishes
the two.

## Testing posture

The entire knowledge layer is hermetic. Tests live in `tests/knowledge/` and use
the fake transport; the WP-D33 gate uses the same fixtures. No CI job or test
case makes a live HTTP request. The knowledge workflow (`knowledge.yml`) runs the
hermetic tests and the gate on every pull request, push to `main`, and merge
group.

## Acceptance gates

WP-D33 is gated by `scripts/checks/wp33-gate.py` (six checks) and the
`tests/knowledge/` test suite:

- **D33-01** — unknown endpoint → `NETWORK_POLICY_VIOLATION`.
- **D33-02** — non-https URL or final scheme → `NETWORK_POLICY_VIOLATION`.
- **D33-03** — byte budget exceeded → `RESOURCE_LIMIT`, nothing cached.
- **D33-04** — rate limit exceeded → typed `WAIT_RESOURCE` with `retry_after_seconds`.
- **D33-05** — credential-like constructor keyword → `NETWORK_POLICY_VIOLATION`.
- **D33-06** — cache hit → `cached=true`, identical `receipt_id` and `response_sha256`,
  single transport call.

Run them with `uv run pytest tests/knowledge` and
`uv run python3 scripts/checks/wp33-gate.py`.
