# Knowledge source adapters (WP-E44/A11)

This document describes the P0 and A11 knowledge source adapters in
`src/srl/knowledge/sources/`. The adapters sit on top of the budgeted,
content-addressed API retriever defined in WP-D33 (`srl.knowledge.retriever`)
and turn raw API responses into normalized, provenance-carrying records.

## Supported sources

The active adapter set includes the original four credential-free P0 sources
plus the A11 public mathematical knowledge sources:

| Source | Endpoint | Shape | Record URI |
|--------|----------|-------|------------|
| OpenAlex | `https://api.openalex.org/works` | JSON, filter/select | `https://openalex.org/works/<id>` |
| Crossref | `https://api.crossref.org/works` | JSON, DOI metadata | `https://doi.org/<DOI>` |
| arXiv | `https://export.arxiv.org/api/query` | Atom XML | `https://arxiv.org/abs/<id>` |
| OEIS | `https://oeis.org/search` | JSON, compact | `https://oeis.org/<number>` |
| OpenCitations | `https://api.opencitations.net/index/v2/citation-count/<id>` | JSON, citation count | OpenCitations API URI |
| zbMATH Open | `https://api.zbmath.org/v1/document/_search` | JSON, document metadata | `https://zbmath.org/?q=an:<id>` |
| LMFDB | `https://www.lmfdb.org/api/ec_curvedata/` | JSON, mathematical-object metadata | `https://www.lmfdb.org/EllipticCurve/Q/<label>` |
| CSLib | `https://api.github.com/repos/leanprover/cslib/commits/<rev>` | JSON, pinned commit metadata | GitHub commit URI |
| Erdos Problems | `https://api.github.com/repos/teorth/erdosproblems/commits/<rev>` | JSON, pinned commit metadata | GitHub commit URI |
| Formal Conjectures | `https://api.github.com/repos/google-deepmind/formal-conjectures/commits/<rev>` | JSON, pinned commit metadata | GitHub commit URI |

FRED, ALFRED, and Wolfram|Alpha are deliberately absent. They require an API
key or AppID, and the retriever is credential-free by design. Their names are
listed in `srl.knowledge.adapters.FORBIDDEN_SOURCES` so a future contributor
cannot add them silently.

## Adapter contract

Each source module exposes:

- `build_query(query, limit, ...)` returning `(path, params)` for the D33
  retriever.
- `parse_<source>(payload, policy, retrieved_utc=None)` returning a list of
  `SourceRecord` objects.
- `search(query, limit, transport, policy)` fetching through the D33 retriever
  and returning parsed records.

`SourceRecord` carries only identity and provenance fields:

```text
record_id        sha256 digest of the normalized fields
source           endpoint identifier (e.g. "openalex")
source_uri       canonical HTTPS URI for the record
retrieved_utc    RFC 3339 UTC timestamp of the retrieval
vintage          YYYY-MM-DD date of the retrieval
license_note     license-terms digest carried by the endpoint policy
payload_digest   sha256 digest of the raw API response bytes
attribution      attribution text required by the endpoint
```

The raw API response is never persisted in a public fixture unless it is
hand-authored, marked synthetic, and redistribution-clear. The response itself
is content-addressed by its digest and can be recovered from the local
content-addressed store when needed.

## Budgets and vintage

Every fetch is performed by the D33 retriever under an `EndpointPolicy`. The
policy enforces:

- **Rate limit**: a per-endpoint token bucket (default 10 requests/minute).
- **Byte budget**: a total response-byte budget per endpoint (default 50 MiB).
- **Cost budget**: abstract cost units for metered endpoints (default 1000).
- **Retention**: cached responses are retained for a declared number of days.

The adapter never duplicates budget logic and never bypasses it. It also never
carries credentials, never adds a default identity, and never requests a full
snapshot. OpenAlex queries use `filter` and `select`, and every per-page
parameter (`per-page`, `rows`, `max_results`) is capped at 25.

`retrieved_utc` and the `vintage` (its date component) are recorded because a
response's meaning can drift over time. The vintage is part of the record
identity, so the same logical query on a different day produces a different
record id.

## Attribution discipline

Every `SourceRecord` carries a non-empty `attribution` string. The text comes
from the endpoint policy (`attribution_text`) and reflects the provider's
license terms. For the active sources the attribution strings cover:

- OpenAlex: CC0 1.0 Universal (Public Domain Dedication).
- Crossref: Crossref Metadata Plus terms.
- arXiv: CC0 1.0 where applicable.
- OEIS: CC BY-NC 3.0.
- OpenCitations, zbMATH Open and LMFDB: public API attribution.
- CSLib and Formal Conjectures: pinned public GitHub repository metadata with
  Apache-2.0 source identity.
- Erdos Problems: pinned public GitHub repository metadata.

The attribution is present even when the downstream consumer only needs the
record id; provenance is not optional.

## Honesty: retrieval is not evidence of truth

A source record proves that a particular byte sequence was retrieved from a
named endpoint at a particular vintage. It does **not** prove that the content
is true, authoritative, or appropriate for a scientific claim. A record's mere
existence in the cache is a retrieval event, not evidence. Any later claim must be
supported by the normal SRL evidence and review workflow, not by the retrieval
receipt or source record alone.

## Synthetic fixture policy

The fixtures under `fixtures/conformance/knowledge/sources/` are hand-authored
and are not live API responses. They exist to make the WP-E44 gate and the
hermetic tests deterministic and CI-safe. Every fixture is marked with:

```json
{ "synthetic": true, "redistribution": "clear" }
```

and contains no credentials, no secrets, and no personally identifiable
information. The malformed fixtures deliberately violate the structural contract
expected by the adapter so the gate can assert that no partial record is
emitted.

## Acceptance gates

WP-E44 remains gated by `scripts/checks/wp44-gate.py` and the hermetic tests
under `tests/knowledge/sources/`:

- **E44-01**: each source parses its two normal fixtures into valid
  `SourceRecord` objects.
- **E44-02**: each malformed fixture raises a typed `CONTRACT_INVALID` error
  without emitting a partial record.
- **E44-03**: the D33 retriever refuses a response that exceeds the byte budget.
- **E44-04**: no FRED, ALFRED, or Wolfram adapter exists.
- **E44-05**: every generated record carries a non-empty attribution.
- **E44-06**: per-page parameters are capped at 25 in the query builder.

Run them with `uv run pytest tests/knowledge/sources` and
`uv run python3 scripts/checks/wp44-gate.py`.

A11 is gated by `scripts/checks/srf-v37-a11-gate.py`. That gate performs one
bounded live query to every active public source, stores the response in a
content-addressed session cache, and then replays the same request with a
transport that raises on any network access. A11 closes only when every live
receipt is `cached=false`, every replay receipt is `cached=true`, and the live
and replay response hashes match.

## S14 knowledge graph and taint layer

`srl.knowledge.graph` builds a `KnowledgeLayerManifest/v1` above the active
retriever and source adapters. It records:

- ACTIVE source cards for OpenAlex, Crossref, arXiv, OEIS, OpenCitations,
  zbMATH Open, LMFDB, CSLib, Erdos Problems and Formal Conjectures.
- Content-addressed fact nodes with offsets, payload digests, attribution,
  taint labels and citation edges.
- Prompt-injection findings for untrusted corpus spans.

The manifest keeps `raw_corpus_in_privileged_prompt=0`, performs no live network
calls in tests, grants no authority and never treats retrieval as truth.
