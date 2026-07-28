#!/usr/bin/env python3
"""WP-E44 acceptance gate for the P0 knowledge source adapters.

Runs the six required WP-E44 checks using synthetic fixtures and a fake
transport, then prints a single canonical ``GateReceipt/v1`` JSON line to stdout.
Exits 0 only if every check PASSes.

The checks are purely hermetic: no live HTTP request is made.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package and the WP-E44 fixture module importable when
# run as a bare script (``python3 scripts/checks/wp44-gate.py``).
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp44-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
_FX_E44 = _REPO_ROOT / "fixtures" / "conformance" / "knowledge"

for _path in (_SRC, _FX_E44, _FX_E44 / "sources"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import canned_payloads  # noqa: E402
import fake_transport  # noqa: E402

from srl.contracts import dumps  # noqa: E402
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON  # noqa: E402
from srl.knowledge.retriever import (  # noqa: E402
    RESOURCE_LIMIT_FAIL_REASON,
    EndpointPolicy,
    ResourceLimitError,
)
from srl.knowledge.sources import (  # noqa: E402
    SourceRecord,
    SourceRecordError,
    search_openalex,
)
from srl.knowledge.sources.arxiv import build_query as build_arxiv_query  # noqa: E402
from srl.knowledge.sources.arxiv import parse_arxiv  # noqa: E402
from srl.knowledge.sources.crossref import build_query as build_crossref_query  # noqa: E402
from srl.knowledge.sources.crossref import parse_crossref  # noqa: E402
from srl.knowledge.sources.oeis import build_query as build_oeis_query  # noqa: E402
from srl.knowledge.sources.oeis import parse_oeis  # noqa: E402
from srl.knowledge.sources.openalex import build_query as build_openalex_query  # noqa: E402
from srl.knowledge.sources.openalex import parse_openalex  # noqa: E402

# ---------------------------------------------------------------------------
# Receipt identity.
# ---------------------------------------------------------------------------

GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-E44"
_LICENSE_SHA256: Final[str] = "sha256:" + "ab" * 32
_PER_PAGE_CAP: Final[int] = 25


def _policy(endpoint_id: str, byte_budget: int = 1024) -> EndpointPolicy:
    """Return a synthetic endpoint policy for the gate."""
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


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# E44-01: each source parses its normal canned payloads into valid records.
# ---------------------------------------------------------------------------


def _check_e44_01() -> dict[str, Any]:
    """E44-01: every source parses its two normal fixtures into SourceRecords."""
    sources = {
        "openalex": (
            _load("openalex_normal_1.json"),
            _load("openalex_normal_2.json"),
        ),
        "crossref": (
            _load("crossref_normal_1.json"),
            _load("crossref_normal_2.json"),
        ),
        "arxiv": (
            _load("arxiv_normal_1.xml"),
            _load("arxiv_normal_2.xml"),
        ),
        "oeis": (
            _load("oeis_normal_1.json"),
            _load("oeis_normal_2.json"),
        ),
    }
    parsers = {
        "openalex": parse_openalex,
        "crossref": parse_crossref,
        "arxiv": parse_arxiv,
        "oeis": parse_oeis,
    }
    counts: dict[str, int] = {}
    for source, (payload_a, payload_b) in sources.items():
        policy = _policy(source)
        records_a = parsers[source](payload_a, policy)
        records_b = parsers[source](payload_b, policy)
        for records in (records_a, records_b):
            if not records or not all(isinstance(r, SourceRecord) for r in records):
                return {
                    "status": "FAIL",
                    "detail": f"{source} normal payload did not produce SourceRecords",
                }
            for record in records:
                if not record.record_id.startswith("sha256:"):
                    return {
                        "status": "FAIL",
                        "detail": f"{source} record has no sha256 record_id",
                    }
                if not record.source_uri.startswith("https://"):
                    return {
                        "status": "FAIL",
                        "detail": f"{source} record source_uri is not HTTPS",
                    }
        counts[source] = len(records_a) + len(records_b)
    return {
        "status": "PASS",
        "detail": "all normal fixtures parsed into valid SourceRecords",
        "record_counts": counts,
    }


# ---------------------------------------------------------------------------
# E44-02: malformed payload -> CONTRACT_INVALID, no partial record.
# ---------------------------------------------------------------------------


def _check_e44_02() -> dict[str, Any]:
    """E44-02: every malformed fixture raises a typed CONTRACT_INVALID error."""
    fixtures = {
        "openalex": _load("openalex_malformed.json"),
        "crossref": _load("crossref_malformed.json"),
        "arxiv": _load("arxiv_malformed.xml"),
        "oeis": _load("oeis_malformed.json"),
    }
    parsers = {
        "openalex": parse_openalex,
        "crossref": parse_crossref,
        "arxiv": parse_arxiv,
        "oeis": parse_oeis,
    }
    for source, payload in fixtures.items():
        policy = _policy(source)
        try:
            parsers[source](payload, policy)
        except SourceRecordError as exc:
            if exc.fail_reason == CONTRACT_INVALID_FAIL_REASON:
                continue
            return {
                "status": "FAIL",
                "detail": f"{source} malformed raised wrong fail_reason: {exc.fail_reason!r}",
            }
        except Exception as exc:
            return {
                "status": "FAIL",
                "detail": f"{source} malformed raised unexpected {type(exc).__name__}: {exc}",
            }
        return {
            "status": "FAIL",
            "detail": f"{source} malformed payload did not raise an error",
        }
    return {
        "status": "PASS",
        "detail": "all malformed payloads raised CONTRACT_INVALID without partial records",
    }


# ---------------------------------------------------------------------------
# E44-03: byte budget enforcement via the D33 retriever.
# ---------------------------------------------------------------------------


def _check_e44_03() -> dict[str, Any]:
    """E44-03: an oversized response is refused by the retriever with RESOURCE_LIMIT."""
    policy = _policy("openalex", byte_budget=10)
    oversized = b"x" * 200
    transport = fake_transport.FakeTransport(oversized)
    try:
        search_openalex("synthetic", 5, transport, policy)
    except ResourceLimitError as exc:
        if exc.fail_reason == RESOURCE_LIMIT_FAIL_REASON:
            return {
                "status": "PASS",
                "detail": (
                    "200-byte response against 10-byte budget raised ResourceLimitError "
                    "with fail_reason RESOURCE_LIMIT"
                ),
            }
        return {
            "status": "FAIL",
            "detail": f"wrong fail_reason: {exc.fail_reason!r}",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }
    return {
        "status": "FAIL",
        "detail": "oversized response was accepted without error",
    }


# ---------------------------------------------------------------------------
# E44-04: no FRED/ALFRED/Wolfram adapter exists in the sources package.
# ---------------------------------------------------------------------------


def _check_e44_04() -> dict[str, Any]:
    """E44-04: scan the sources package for forbidden credential-requiring adapters."""
    sources_dir = _REPO_ROOT / "src" / "srl" / "knowledge" / "sources"
    forbidden = {"fred", "alfred", "wolfram", "wolframalpha"}
    found: list[str] = []
    for path in sorted(sources_dir.glob("*.py")):
        stem = path.stem
        if stem in forbidden or stem.startswith(tuple(f"{f}_" for f in forbidden)):
            found.append(stem)
    if found:
        return {
            "status": "FAIL",
            "detail": f"forbidden source adapter files found: {found}",
        }
    return {
        "status": "PASS",
        "detail": "no FRED, ALFRED, or Wolfram adapter exists in src/srl/knowledge/sources",
    }


# ---------------------------------------------------------------------------
# E44-05: attribution is present on every generated record.
# ---------------------------------------------------------------------------


def _check_e44_05() -> dict[str, Any]:
    """E44-05: every parsed record carries a non-empty attribution string."""
    fixtures = {
        "openalex": ("openalex_normal_1.json", "openalex_normal_2.json"),
        "crossref": ("crossref_normal_1.json", "crossref_normal_2.json"),
        "arxiv": ("arxiv_normal_1.xml", "arxiv_normal_2.xml"),
        "oeis": ("oeis_normal_1.json", "oeis_normal_2.json"),
    }
    parsers = {
        "openalex": parse_openalex,
        "crossref": parse_crossref,
        "arxiv": parse_arxiv,
        "oeis": parse_oeis,
    }
    for source, names in fixtures.items():
        policy = _policy(source)
        for name in names:
            records = parsers[source](_load(name), policy)
            for record in records:
                if not record.attribution:
                    return {
                        "status": "FAIL",
                        "detail": f"{source} record from {name} lacks attribution",
                    }
    return {
        "status": "PASS",
        "detail": "attribution is present on every generated SourceRecord",
    }


# ---------------------------------------------------------------------------
# E44-06: per-page cap is enforced in the query builder.
# ---------------------------------------------------------------------------


def _check_e44_06() -> dict[str, Any]:
    """E44-06: per-page parameters are capped at 25 (or absent for OEIS)."""
    checks = [
        ("openalex", build_openalex_query("test", 100), "per-page"),
        ("crossref", build_crossref_query("test", 100), "rows"),
        ("arxiv", build_arxiv_query("test", 100), "max_results"),
    ]
    for source, (_, params), key in checks:
        if params.get(key) != _PER_PAGE_CAP:  # type: ignore[index]
            return {
                "status": "FAIL",
                "detail": (
                    f"{source} {key} cap is not {_PER_PAGE_CAP}: got {params.get(key)!r}"  # type: ignore[index]
                ),
            }
    # OEIS does not have a per-page parameter; the query is compact.
    _, oeis_params = build_oeis_query("A000045", 100)
    if any(key in oeis_params for key in ("per-page", "rows", "max_results")):
        return {
            "status": "FAIL",
            "detail": "OEIS compact query unexpectedly contains a per-page parameter",
        }
    return {
        "status": "PASS",
        "detail": "per-page cap <= 25 enforced (or not present for OEIS compact queries)",
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all six checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "E44-01": _check_e44_01(),
        "E44-02": _check_e44_02(),
        "E44-03": _check_e44_03(),
        "E44-04": _check_e44_04(),
        "E44-05": _check_e44_05(),
        "E44-06": _check_e44_06(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    del argv  # unused
    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
