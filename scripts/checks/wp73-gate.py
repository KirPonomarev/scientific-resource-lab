#!/usr/bin/env python3
"""WP-H73 acceptance gate for the P2 discovery registry.

Runs the four WP-H73 checks, prints a single canonical ``GateReceipt/v1`` JSON
line to stdout, and exits 0 only if every check PASSes. The gate exercises the
P2 discovery registry in :mod:`srl.knowledge.registry` against the canonical
fixture at ``fixtures/conformance/registry/cards.v1.json`` and the malformed
fixture at ``fixtures/conformance/registry/cards.malformed.v1.json``.

Checks
------
H73-01 all 13 cards validate
    The canonical fixture loads through ``load_cards_from_doc`` and yields
    exactly 13 cards, matching the in-code ``DEFAULT_CARDS`` by identity.

H73-02 malformed card rejected typed
    The malformed fixture is rejected with ``DiscoveryRegistryError`` (a
    ``ContractError`` carrying ``fail_reason='CONTRACT_INVALID'``). No partial
    card set is emitted.

H73-03 every card is catalog_only
    Every default card and every fixture card carries
    ``admission_status == 'catalog_only'``. Registry presence never implies
    readiness.

H73-04 deterministic search
    ``search`` is deterministic across repeated calls and is independent of the
    input order of the card tuple; the same query always yields the same
    ``card_id``-sorted result.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp73-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON  # noqa: E402
from srl.knowledge.registry import (  # noqa: E402
    ADMISSION_STATUS_CATALOG_ONLY,
    DEFAULT_CARDS,
    DISCOVERY_CARD_SCHEMA_VERSION,
    DiscoveryRegistryError,
    load_cards_from_doc,
    search,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-H73"

# Canonical fixture paths.
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "registry"
_GOOD_FIXTURE: Final[Path] = _FIXTURES / "cards.v1.json"
_BAD_FIXTURE: Final[Path] = _FIXTURES / "cards.malformed.v1.json"

# The exact card count the canonical fixture must yield.
_EXPECTED_CARD_COUNT: Final[int] = 13


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_json(path: Path) -> Any:
    """Read and JSON-decode a fixture file, returning the raw object."""
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# H73-01: all 13 cards validate.
# ---------------------------------------------------------------------------


def _check_h73_01() -> dict[str, Any]:
    """H73-01: the canonical fixture yields exactly 13 validated cards.

    The loaded card set must equal the in-code ``DEFAULT_CARDS`` by identity, so
    the fixture is a faithful serialization of the authoritative registry and
    not a divergent copy.
    """
    try:
        cards = load_cards_from_doc(_load_json(_GOOD_FIXTURE))
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    errors: list[str] = []
    if len(cards) != _EXPECTED_CARD_COUNT:
        errors.append(f"card count={len(cards)}, expected {_EXPECTED_CARD_COUNT}")
    if cards != DEFAULT_CARDS:
        errors.append("fixture cards differ from in-code DEFAULT_CARDS")
    ids = [c.card_id for c in cards]
    if ids != sorted(ids):
        errors.append("fixture cards are not sorted by card_id")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": (
            f"canonical fixture yields {_EXPECTED_CARD_COUNT} validated cards, "
            "sorted by card_id, identical to DEFAULT_CARDS"
        ),
        "evidence": {"card_count": len(cards), "card_ids": ids},
    }


# ---------------------------------------------------------------------------
# H73-02: malformed card rejected typed.
# ---------------------------------------------------------------------------


def _check_h73_02() -> dict[str, Any]:
    """H73-02: the malformed fixture is rejected with a typed contract error.

    The malformed fixture carries a card with ``admission_status`` other than
    ``catalog_only``. ``load_cards_from_doc`` must raise
    :class:`DiscoveryRegistryError` (a ``ContractError`` with
    ``fail_reason='CONTRACT_INVALID'``). No partial card set is emitted.
    """
    try:
        load_cards_from_doc(_load_json(_BAD_FIXTURE))
    except DiscoveryRegistryError as exc:
        fail_reason = getattr(exc, "fail_reason", None)
        if fail_reason != CONTRACT_INVALID_FAIL_REASON:
            return {
                "status": "FAIL",
                "detail": (
                    f"rejected but fail_reason={fail_reason!r}, "
                    f"expected {CONTRACT_INVALID_FAIL_REASON!r}"
                ),
            }
        return {
            "status": "PASS",
            "detail": (
                "malformed card rejected with DiscoveryRegistryError "
                f"({fail_reason}); no partial card set emitted"
            ),
            "evidence": {"error_type": type(exc).__name__, "fail_reason": fail_reason},
        }
    except Exception as exc:  # a different exception type is a gate failure.
        return {
            "status": "FAIL",
            "detail": (
                f"rejected with {type(exc).__name__}, expected DiscoveryRegistryError: {exc}"
            ),
        }
    return {
        "status": "FAIL",
        "detail": "malformed fixture was not rejected",
    }


# ---------------------------------------------------------------------------
# H73-03: every card is catalog_only.
# ---------------------------------------------------------------------------


def _check_h73_03() -> dict[str, Any]:
    """H73-03: every default and fixture card carries admission_status='catalog_only'.

    The catalog-only invariant is structural: there is no code path that
    produces a card with a different status. This check asserts it on both the
    in-code defaults and the freshly-loaded fixture cards.
    """
    try:
        fixture_cards = load_cards_from_doc(_load_json(_GOOD_FIXTURE))
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    all_cards = (*DEFAULT_CARDS, *fixture_cards)
    violators = [
        c.card_id for c in all_cards if c.admission_status != ADMISSION_STATUS_CATALOG_ONLY
    ]
    if violators:
        return {
            "status": "FAIL",
            "detail": (f"catalog-only invariant violated by: {violators}"),
        }
    return {
        "status": "PASS",
        "detail": (
            f"all {len(all_cards)} default+fixture cards are {ADMISSION_STATUS_CATALOG_ONLY!r}"
        ),
        "evidence": {
            "admission_status": ADMISSION_STATUS_CATALOG_ONLY,
            "card_count": len(all_cards),
        },
    }


# ---------------------------------------------------------------------------
# H73-04: deterministic search.
# ---------------------------------------------------------------------------


def _check_h73_04() -> dict[str, Any]:
    """H73-04: search is deterministic and order-independent.

    Three properties must hold:
    - the same query returns the same result on repeated calls (stability);
    - the result is identical regardless of the input order of the card tuple
      (order-independence);
    - the result is always sorted by ``card_id``.

    A non-empty query (``logic``) and the empty query (full listing) are both
    exercised.
    """
    errors: list[str] = []
    cases: list[dict[str, Any]] = []

    for query in ("logic", ""):
        r1 = search(query)
        r2 = search(query)
        if r1 != r2:
            errors.append(f"query {query!r} not stable across calls")
        # Reverse the input order and confirm the result is unchanged.
        r_rev = search(query, tuple(reversed(DEFAULT_CARDS)))
        if r_rev != r1:
            errors.append(f"query {query!r} result depends on input order")
        ids = [c.card_id for c in r1]
        if ids != sorted(ids):
            errors.append(f"query {query!r} result not sorted by card_id")
        cases.append(
            {
                "query": query,
                "match_count": len(r1),
                "card_ids": ids,
                "stable": r1 == r2,
                "order_independent": r_rev == r1,
                "sorted": ids == sorted(ids),
            }
        )

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "search is deterministic, stable across calls, independent of input "
            "order, and always card_id-sorted"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the gate receipt."""
    checks = {
        "H73-01": _check_h73_01(),
        "H73-02": _check_h73_02(),
        "H73-03": _check_h73_03(),
        "H73-04": _check_h73_04(),
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
            "schema_version": DISCOVERY_CARD_SCHEMA_VERSION,
            "expected_card_count": _EXPECTED_CARD_COUNT,
            "admission_status": ADMISSION_STATUS_CATALOG_ONLY,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    if args and args[0] == "--check":
        receipt = _build_receipt()
        _emit(receipt)
        return 0 if receipt["overall"] == "PASS" else 1

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
