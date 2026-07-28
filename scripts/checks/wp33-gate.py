#!/usr/bin/env python3
"""WP-D33 acceptance gate for the budgeted API retriever.

Runs the six required WP-D33 checks using a deterministic fake transport and
prints a single canonical ``GateReceipt/v1`` JSON line to stdout. Exits 0 only
if every check PASSes; any FAIL makes the exit code non-zero so the gate can be
wired into CI and the knowledge workflow.

The checks are purely hermetic: no live HTTP request is made. The fake
transport is loaded from the in-repo conformance fixtures so the gate and the
tests share the same transport contract.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package and the knowledge fixture module importable when
# run as a bare script (``python3 scripts/checks/wp33-gate.py``).
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp33-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
_FX_KNOWLEDGE = _REPO_ROOT / "fixtures" / "conformance" / "knowledge"

for _path in (_SRC, _FX_KNOWLEDGE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import fake_transport  # noqa: E402

from srl.contracts import dumps  # noqa: E402
from srl.knowledge.retriever import (  # noqa: E402
    NETWORK_POLICY_FAIL_REASON,
    RATE_LIMITED_FAIL_REASON,
    RESOURCE_LIMIT_FAIL_REASON,
    ApiRetriever,
    NetworkPolicyError,
    PolicyRegistry,
    RateLimitedError,
    ResourceLimitError,
    construct_retriever,
)

# ---------------------------------------------------------------------------
# Receipt identity.
# ---------------------------------------------------------------------------

GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-D33"

# A stable synthetic license digest for the gate endpoints.
_LICENSE_SHA256: Final[str] = "sha256:" + "ab" * 32


def _make_registry(**kwargs: Any) -> PolicyRegistry:
    """Build a one-endpoint policy registry from overrides.

    Defaults are generous enough for the gate tests except where a check
    deliberately overrides ``byte_budget`` or ``rate_limit_per_minute``.
    """
    endpoint = {
        "endpoint_id": "openalex",
        "base_url": "https://api.openalex.org",
        "rate_limit_per_minute": 10,
        "byte_budget": 1024,
        "cost_budget_units": 10,
        "license_terms_sha256": _LICENSE_SHA256,
        "attribution_required": True,
        "attribution_text": "Synthetic attribution for WP-D33 gate.",
        "retention_days": 30,
    }
    endpoint.update(kwargs)
    return PolicyRegistry.from_dict(
        {"schema_version": "EndpointPolicy/v1", "endpoints": [endpoint]}
    )


def _cache_dir() -> str:
    """Return a fresh temporary cache directory path string."""
    return tempfile.mkdtemp(prefix="wp33-gate-")


def _cleanup(cache_dir: str) -> None:
    """Remove the temporary cache directory."""
    shutil.rmtree(cache_dir, ignore_errors=True)


def _payload(name: str) -> bytes:
    """Return a canned synthetic payload from the fixture payloads directory."""
    return fake_transport.canned_payload(name)


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# D33-01: unknown endpoint rejected with NETWORK_POLICY_VIOLATION.
# ---------------------------------------------------------------------------


def _check_d33_01() -> dict[str, Any]:
    """D33-01: a fetch against an endpoint not in the registry is refused."""
    registry = _make_registry()
    cache_dir = _cache_dir()
    try:
        retriever = ApiRetriever()
        retriever.fetch(
            "crossref",  # not in the one-endpoint registry
            "/works",
            {"q": "test"},
            cache_dir,
            registry,
            transport=fake_transport.FakeTransport(),
        )
    except NetworkPolicyError as exc:
        if exc.fail_reason == NETWORK_POLICY_FAIL_REASON:
            return {
                "status": "PASS",
                "detail": (
                    "fetch against endpoint 'crossref' not in the registry raised "
                    "NetworkPolicyError with fail_reason NETWORK_POLICY_VIOLATION"
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
    finally:
        _cleanup(cache_dir)
    return {"status": "FAIL", "detail": "unknown endpoint was accepted without error"}


# ---------------------------------------------------------------------------
# D33-02: non-https URL rejected with NETWORK_POLICY_VIOLATION.
# ---------------------------------------------------------------------------


def _check_d33_02() -> dict[str, Any]:
    """D33-02: a redirect or final URL to a non-https scheme is refused."""
    registry = _make_registry()
    payload = _payload("openalex_works.json")
    # Simulate a transport that follows a redirect to http:// (forbidden).
    transport = fake_transport.FakeTransport(payload, scheme="http")
    cache_dir = _cache_dir()
    try:
        retriever = ApiRetriever()
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "test"},
            cache_dir,
            registry,
            transport=transport,
        )
    except NetworkPolicyError as exc:
        if exc.fail_reason == NETWORK_POLICY_FAIL_REASON:
            return {
                "status": "PASS",
                "detail": (
                    "transport returning final_scheme='http' raised NetworkPolicyError "
                    "with fail_reason NETWORK_POLICY_VIOLATION"
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
    finally:
        _cleanup(cache_dir)
    return {"status": "FAIL", "detail": "non-https final URL was accepted without error"}


# ---------------------------------------------------------------------------
# D33-03: byte budget enforced with RESOURCE_LIMIT; nothing is cached.
# ---------------------------------------------------------------------------


def _check_d33_03() -> dict[str, Any]:
    """D33-03: a response larger than the remaining byte budget is refused."""
    registry = _make_registry(byte_budget=10)
    oversized = b"x" * 200
    transport = fake_transport.FakeTransport(oversized)
    cache_dir = _cache_dir()
    try:
        retriever = ApiRetriever()
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "test"},
            cache_dir,
            registry,
            transport=transport,
        )
    except ResourceLimitError as exc:
        if exc.fail_reason != RESOURCE_LIMIT_FAIL_REASON:
            return {
                "status": "FAIL",
                "detail": f"wrong fail_reason: {exc.fail_reason!r}",
            }
        # The failure must not leave a cached payload or a budget deduction.
        cache_path = Path(cache_dir)
        payloads = list(cache_path.rglob("*.bin"))
        budget_files = list(cache_path.glob("budget-*"))
        if payloads or budget_files:
            return {
                "status": "FAIL",
                "detail": (
                    f"oversized response leaked state: {len(payloads)} payload(s), "
                    f"{len(budget_files)} budget file(s)"
                ),
            }
        return {
            "status": "PASS",
            "detail": (
                "200-byte response against 10-byte budget raised ResourceLimitError "
                "with fail_reason RESOURCE_LIMIT and left no cached payload or budget file"
            ),
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }
    finally:
        _cleanup(cache_dir)
    return {"status": "FAIL", "detail": "oversized response was accepted without error"}


# ---------------------------------------------------------------------------
# D33-04: rate limit enforced with a typed WAIT_RESOURCE / retry_after.
# ---------------------------------------------------------------------------


def _check_d33_04() -> dict[str, Any]:
    """D33-04: a second request past the rate limit raises a typed wait."""
    # One request per minute: first fetch consumes the only token.
    registry = _make_registry(rate_limit_per_minute=1, cost_budget_units=2)
    payload = _payload("openalex_works.json")
    cache_dir = _cache_dir()
    try:
        retriever = ApiRetriever()
        # First request succeeds.
        first = retriever.fetch(
            "openalex",
            "/works",
            {"q": "first"},
            cache_dir,
            registry,
            transport=fake_transport.FakeTransport(payload),
        )
        # Second, different request must hit the rate limit (not the cache).
        retriever.fetch(
            "openalex",
            "/works",
            {"q": "second"},
            cache_dir,
            registry,
            transport=fake_transport.FakeTransport(payload),
            rate_limit_sleep=False,
        )
    except RateLimitedError as exc:
        if exc.fail_reason == RATE_LIMITED_FAIL_REASON and exc.retry_after_seconds > 0:
            return {
                "status": "PASS",
                "detail": (
                    "second request with rate_limit_per_minute=1 raised RateLimitedError "
                    f"with fail_reason WAIT_RESOURCE and retry_after_seconds="
                    f"{exc.retry_after_seconds:.2f}"
                ),
                "first_cached": first.receipt.cached,
            }
        return {
            "status": "FAIL",
            "detail": (
                f"RateLimitedError raised but wrong typing: "
                f"fail_reason={exc.fail_reason!r}, retry_after={exc.retry_after_seconds}"
            ),
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }
    finally:
        _cleanup(cache_dir)
    return {
        "status": "FAIL",
        "detail": "second request past the rate limit was accepted without error",
    }


# ---------------------------------------------------------------------------
# D33-05: credential-like constructor keyword rejected.
# ---------------------------------------------------------------------------


def _check_d33_05() -> dict[str, Any]:
    """D33-05: a credential-like keyword is refused before the retriever exists."""
    try:
        construct_retriever(api_key="super-secret-key")
    except NetworkPolicyError as exc:
        if exc.fail_reason == NETWORK_POLICY_FAIL_REASON:
            return {
                "status": "PASS",
                "detail": (
                    "construct_retriever(api_key=...) raised NetworkPolicyError "
                    "with fail_reason NETWORK_POLICY_VIOLATION before any network call"
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
        "detail": "credential-like constructor keyword was accepted without error",
    }


# ---------------------------------------------------------------------------
# D33-06: cache hit returns cached=true and an identical content hash.
# ---------------------------------------------------------------------------


def _check_d33_06() -> dict[str, Any]:
    """D33-06: a repeated fetch returns the cached receipt with the same hash."""
    registry = _make_registry(cost_budget_units=2)
    payload = _payload("openalex_works.json")
    transport = fake_transport.FakeTransport(payload)
    cache_dir = _cache_dir()
    try:
        retriever = ApiRetriever()
        first = retriever.fetch(
            "openalex",
            "/works",
            {"q": "cache"},
            cache_dir,
            registry,
            transport=transport,
        )
        second = retriever.fetch(
            "openalex",
            "/works",
            {"q": "cache"},
            cache_dir,
            registry,
            transport=transport,
        )
        if not first.receipt.cached and second.receipt.cached:
            same_id = first.receipt.receipt_id == second.receipt.receipt_id
            same_hash = first.receipt.response_sha256 == second.receipt.response_sha256
            one_network_call = len(transport.calls) == 1
            if same_id and same_hash and one_network_call:
                return {
                    "status": "PASS",
                    "detail": (
                        "second fetch was a cache hit (cached=true) with the same "
                        "receipt_id and response_sha256; the fake transport was only "
                        "invoked once"
                    ),
                    "receipt_id": first.receipt.receipt_id,
                    "response_sha256": first.receipt.response_sha256,
                }
            return {
                "status": "FAIL",
                "detail": (
                    f"cache semantics mismatch: same_id={same_id}, "
                    f"same_hash={same_hash}, one_network_call={one_network_call}"
                ),
            }
        return {
            "status": "FAIL",
            "detail": (
                f"expected cached=False then cached=True, got "
                f"first.cached={first.receipt.cached}, second.cached={second.receipt.cached}"
            ),
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }
    finally:
        _cleanup(cache_dir)


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: payload sizes and fixture counts."""
    fx_payloads = _FX_KNOWLEDGE / "payloads"
    sizes: dict[str, int] = {}
    if fx_payloads.is_dir():
        for path in sorted(fx_payloads.iterdir()):
            if path.is_file():
                sizes[path.name] = path.stat().st_size
    return {
        "payload_sizes": sizes,
        "license_sha256_prefix": _LICENSE_SHA256[:14],
    }


def _build_receipt() -> dict[str, Any]:
    """Run all six checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "D33-01": _check_d33_01(),
        "D33-02": _check_d33_02(),
        "D33-03": _check_d33_03(),
        "D33-04": _check_d33_04(),
        "D33-05": _check_d33_05(),
        "D33-06": _check_d33_06(),
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
            **_evidence(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "D33-01": _check_d33_01,
            "D33-02": _check_d33_02,
            "D33-03": _check_d33_03,
            "D33-04": _check_d33_04,
            "D33-05": _check_d33_05,
            "D33-06": _check_d33_06,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "error": f"unknown check {cid}"})
            return 2
        result = runner()
        _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "check": cid, **result})
        return 0 if result["status"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
