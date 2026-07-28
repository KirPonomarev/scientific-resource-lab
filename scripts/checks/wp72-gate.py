#!/usr/bin/env python3
"""WP-H72 acceptance gate for the semantic future profile registry.

Runs the four WP-H72 checks, prints a single canonical ``GateReceipt/v1`` JSON
line to stdout, and exits 0 only if every check PASSes. The gate exercises the
future profile registry in :mod:`srl.planning.future_profiles` and its router
integration in :mod:`srl.planning.router`.

Checks
------
H72-01 all 6 cards validate
    The canonical fixture at ``fixtures/conformance/future_profiles/cards.v1.json``
    loads through ``load_cards_from_doc`` and yields exactly 6 cards, identical
    to the in-code ``DEFAULT_CARDS`` and sorted by ``profile_id``.

H72-02 dreal/other future profile request -> exact WAIT_CAPABILITY
    A request that explicitly names any future profile is routed to
    ``WAIT_CAPABILITY`` with no adapter. The router's unknown/future capability
    path covers the profile; it never fabricates success or silently substitutes
    a local adapter.

H72-03 no card claims readiness
    Every future profile card carries a status in
    ``{registry_only, bounded_experimental}``. No card uses an installed/ready
    status.

H72-04 router integration deterministic
    Repeated routing of the same future-profile request yields identical
    decisions and classifier traces.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp72-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.planning import default_policy, load_default_catalog  # noqa: E402
from srl.planning.future_profiles import (  # noqa: E402
    DEFAULT_CARDS,
    FUTURE_PROFILE_CARD_SCHEMA_VERSION,
    FUTURE_PROFILE_NAMES,
    FUTURE_PROFILE_STATUSES,
    load_cards_from_doc,
)
from srl.planning.router import (  # noqa: E402
    SELECTION_WAIT_CAPABILITY,
    route,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-H72"

# Canonical fixture paths.
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "future_profiles"
_GOOD_FIXTURE: Final[Path] = _FIXTURES / "cards.v1.json"
_DREAL_CLAIM: Final[Path] = _FIXTURES / "dreal-claim.json"

# The exact card count the canonical fixture must yield.
_EXPECTED_CARD_COUNT: Final[int] = 6

# The forbidden readiness statuses. A future profile card must never claim to be
# installed or ready.
_FORBIDDEN_STATUSES: Final[frozenset[str]] = frozenset({"installed", "ready"})


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_json(path: Path) -> Any:
    """Read and JSON-decode a fixture file, returning the raw object."""
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# H72-01: all 6 cards validate.
# ---------------------------------------------------------------------------


def _check_h72_01() -> dict[str, Any]:
    """H72-01: the canonical fixture yields exactly 6 validated cards.

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
    ids = [c.profile_id for c in cards]
    if ids != sorted(ids):
        errors.append("fixture cards are not sorted by profile_id")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": (
            f"canonical fixture yields {_EXPECTED_CARD_COUNT} validated cards, "
            "sorted by profile_id, identical to DEFAULT_CARDS"
        ),
        "evidence": {"card_count": len(cards), "profile_ids": ids},
    }


# ---------------------------------------------------------------------------
# H72-02: future profile request -> exact WAIT_CAPABILITY.
# ---------------------------------------------------------------------------


def _dreal_claim() -> dict[str, Any]:
    """Return the canonical dreal claim fixture as a dict."""
    return _load_json(_DREAL_CLAIM)


def _route_future_profile(profile_id: str) -> Any:
    """Route a request that explicitly names a single future profile."""
    catalog = load_default_catalog()
    policy = default_policy()
    request: dict[str, Any] = {"requested_profiles": [profile_id]}
    return route(request, _dreal_claim(), catalog, policy)


def _future_wait_errors(
    profile_id: str,
    decision: Any,
) -> tuple[list[str], Any]:
    """Return (errors, routing) for a future profile WAIT_CAPABILITY check."""
    routing = decision.profiles.get(profile_id)
    if routing is None:
        return ([f"profile {profile_id!r} missing from routing decision"], None)

    errors: list[str] = []
    if routing.selection != SELECTION_WAIT_CAPABILITY:
        errors.append(f"selection={routing.selection!r}, expected {SELECTION_WAIT_CAPABILITY!r}")
    if routing.adapter_id is not None:
        errors.append(f"adapter_id={routing.adapter_id!r}, expected None")
    if routing.capability_id != f"cap.{profile_id}":
        errors.append(f"capability_id={routing.capability_id!r}, expected 'cap.{profile_id}'")
    if routing.availability != "unknown":
        errors.append(f"availability={routing.availability!r}, expected 'unknown'")
    return (errors, routing)


def _check_h72_02() -> dict[str, Any]:
    """H72-02: any future profile request is routed to WAIT_CAPABILITY.

    The router covers the future profile through its unknown/future capability
    path: the capability_id is ``cap.<profile_id>``, the availability is
    ``unknown``, and the adapter_id is ``None``. No profile is SELECTED.
    """
    cases: list[dict[str, Any]] = []
    for profile_id in FUTURE_PROFILE_NAMES:
        try:
            decision = _route_future_profile(profile_id)
        except Exception as exc:
            cases.append(
                {
                    "profile_id": profile_id,
                    "pass": False,
                    "reason": f"unexpected {type(exc).__name__}: {exc}",
                }
            )
            continue

        errors, routing = _future_wait_errors(profile_id, decision)
        ok = not errors and len(decision.selected_profiles()) == 0
        cases.append(
            {
                "profile_id": profile_id,
                "selection": routing.selection if routing is not None else None,
                "capability_id": routing.capability_id if routing is not None else None,
                "availability": routing.availability if routing is not None else None,
                "pass": ok,
            }
        )
        if not ok and not errors:
            errors.append("a profile was unexpectedly SELECTED")
        if errors:
            cases[-1]["errors"] = errors

    failures = [c["profile_id"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"future profile WAIT_CAPABILITY checks failed for: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "every future profile request routes to WAIT_CAPABILITY with unknown "
            "availability and no adapter"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# H72-03: no card claims readiness.
# ---------------------------------------------------------------------------


def _check_h72_03() -> dict[str, Any]:
    """H72-03: every future profile card is registry-only or bounded-experimental.

    The registry-only/bounded-experimental invariant is structural: no card is
    ever emitted with an installed or ready status. The gate asserts this on
    both the in-code defaults and the freshly-loaded fixture cards.
    """
    try:
        fixture_cards = load_cards_from_doc(_load_json(_GOOD_FIXTURE))
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    all_cards = (*DEFAULT_CARDS, *fixture_cards)
    violators = [
        c.profile_id
        for c in all_cards
        if c.status in _FORBIDDEN_STATUSES or c.status not in FUTURE_PROFILE_STATUSES
    ]
    if violators:
        return {
            "status": "FAIL",
            "detail": f"readiness invariant violated by: {violators}",
        }
    return {
        "status": "PASS",
        "detail": (
            f"all {len(all_cards)} default+fixture cards are registry-only or "
            "bounded-experimental; none claims readiness"
        ),
        "evidence": {
            "allowed_statuses": list(FUTURE_PROFILE_STATUSES),
            "card_count": len(all_cards),
        },
    }


# ---------------------------------------------------------------------------
# H72-04: router integration deterministic.
# ---------------------------------------------------------------------------


def _check_h72_04() -> dict[str, Any]:
    """H72-04: routing a future profile request is deterministic.

    The same request + claim + catalog + policy yields the same decision dict and
    the same classifier trace on repeated calls.
    """
    request: dict[str, Any] = {"requested_profiles": list(FUTURE_PROFILE_NAMES)}
    catalog = load_default_catalog()
    policy = default_policy()
    claim = _dreal_claim()

    try:
        d1 = route(request, claim, catalog, policy)
        d2 = route(request, claim, catalog, policy)
    except Exception as exc:
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    stable = d1.to_dict() == d2.to_dict()
    trace_stable = d1.classifier_trace == d2.classifier_trace
    if not stable or not trace_stable:
        return {
            "status": "FAIL",
            "detail": (
                f"routing not deterministic: decision_stable={stable}, trace_stable={trace_stable}"
            ),
        }
    return {
        "status": "PASS",
        "detail": "future-profile routing is deterministic across repeated calls",
        "evidence": {
            "decision_stable": stable,
            "trace_stable": trace_stable,
            "profile_count": len(FUTURE_PROFILE_NAMES),
        },
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the gate receipt."""
    checks = {
        "H72-01": _check_h72_01(),
        "H72-02": _check_h72_02(),
        "H72-03": _check_h72_03(),
        "H72-04": _check_h72_04(),
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
            "schema_version": FUTURE_PROFILE_CARD_SCHEMA_VERSION,
            "expected_card_count": _EXPECTED_CARD_COUNT,
            "allowed_statuses": list(FUTURE_PROFILE_STATUSES),
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
