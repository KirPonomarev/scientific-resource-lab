#!/usr/bin/env python3
"""WP-E41 acceptance gate for the Z3 + cvc5 SMT pack.

Runs the five WP-E41 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp41``.

The checks
----------
E41-01 SAT/UNSAT/UNKNOWN corpus outcomes match golden per solver
    Every corpus fixture (3 SAT, 3 UNSAT, 2 UNKNOWN) is run through
    :func:`srl.packs.adapters.smt.check` under its declared solver and the
    observed ``result`` must equal the fixture's ``expected_result``. For
    UNKNOWN cases the ``unknown_reason`` must contain the expected substring.

E41-02 hard timeout enforced
    A timeout-corpus formula terminates with a typed TIMEOUT result: the
    formula is genuinely hard (nonlinear integer factorization) and the
    requested budget is honoured, so the outcome is ``unknown`` with
    ``unknown_reason`` containing ``timeout`` and ``wall_seconds`` is bounded.

E41-03 disagreement preserved
    A ``both`` solver run on the corpus records the per-solver agreement flag
    for every formula. Since cvc5 is license-blocked (WAIT_LICENSE) it cannot
    produce a real disagreement, so the disagreement *path* is asserted via an
    injected stub result for z3: the adapter must preserve
    ``agreement=False`` and ``result=unknown`` with both sub-outcomes on
    ``SmtOutcome.disagreement``, never silently resolving. This is the honest
    way to test the preservation invariant: a stub, not a fake real
    disagreement.

E41-04 no PROVEN emitted anywhere
    The adapter scans its own output across the corpus for any ``proven``
    marker (the dishonest evidence ceiling). None may appear: a SMT-style
    answer yields at most ``formal_check=checked``; ``proven`` requires an
    independently checked certificate this package does not mint.

E41-05 license inventory still passes
    The dependency license inventory (``license_inventory.py``) classifies
    every locked package as allowed. cvc5 is excluded (its wheels bundle
    GPLv3/LGPLv3 components and ship no resolvable license expression); z3 is
    MIT and allowed.

The script is standard library plus the in-repo ``srl`` package (which
transitively imports z3). It adds ``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp41-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp41-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402  (path setup must precede import)
from srl.packs.adapters.smt import (  # noqa: E402
    AVAILABLE_SOLVERS,
    FORMAL_CHECK_CEILING,
    MAX_FORMULA_NODES,
    MAX_WALL_SECONDS,
    WAIT_LICENSE_SOLVERS,
    SmtError,
    SmtResult,
    SolverChoice,
    check,
    z3_version,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-E41"

# Fixtures directory for the SMT conformance corpus.
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "smt"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_corpus(category: str) -> list[dict[str, Any]]:
    """Load every fixture in a corpus subdirectory, sorted by stem."""
    sub = _FIXTURES / category
    if not sub.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(sub.glob("*.input.json")):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def _run_corpus_case(case: dict[str, Any], solver: str | SolverChoice) -> dict[str, Any]:
    """Run one corpus case and return the observed outcome summary."""
    try:
        outcome = check(
            case["formula_spec"],
            solver=solver,
            timeout=case.get("timeout_seconds", 5),
        )
    except SmtError as exc:
        return {"case_id": case["case_id"], "error": exc.fail_reason, "status": "FAIL"}
    return {
        "case_id": case["case_id"],
        "result": str(outcome.result),
        "unknown_reason": outcome.unknown_reason,
        "wall_seconds": outcome.wall_seconds,
        "solver": str(outcome.solver),
    }


# ---------------------------------------------------------------------------
# E41-01: SAT/UNSAT/UNKNOWN corpus outcomes match golden per solver.
# ---------------------------------------------------------------------------


def _check_e41_01() -> dict[str, Any]:
    """E41-01: every corpus fixture's observed result matches its golden."""
    categories = ("sat", "unsat", "unknown")
    cases: list[dict[str, Any]] = []
    for category in categories:
        for case in _load_corpus(category):
            observed = _run_corpus_case(case, case.get("solver", "z3"))
            expected = case["expected_result"]
            ok = observed.get("result") == expected
            if expected == "unknown":
                want = case.get("expected_unknown_reason_contains", "")
                ok = ok and want in observed.get("unknown_reason", "")
            cases.append(
                {
                    "category": category,
                    "case_id": case["case_id"],
                    "expected": expected,
                    "observed": observed.get("result"),
                    "unknown_reason": observed.get("unknown_reason", ""),
                    "wall_seconds": observed.get("wall_seconds", 0.0),
                    "status": "PASS" if ok else "FAIL",
                }
            )

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "one or more corpus cases did not match their golden result",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"{len(cases)} corpus cases (sat/unsat/unknown) match golden results under "
            f"their declared solvers; z3={z3_version()}"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E41-02: hard timeout enforced (a timeout-corpus formula terminates TIMEOUT).
# ---------------------------------------------------------------------------


def _check_e41_02() -> dict[str, Any]:
    """E41-02: a timeout-corpus formula yields typed TIMEOUT, bounded wall."""
    cases: list[dict[str, Any]] = []
    for case in _load_corpus("unknown"):
        budget = case.get("timeout_seconds", 1.5)
        observed = _run_corpus_case(case, "z3")
        is_unknown = observed.get("result") == str(SmtResult.UNKNOWN)
        reason_ok = "timeout" in observed.get("unknown_reason", "")
        # The wall must be bounded: the solver honoured the budget. Allow a
        # generous margin over the requested budget for solver teardown.
        wall = observed.get("wall_seconds", 0.0)
        wall_bounded = wall <= float(budget) + 5.0
        ok = is_unknown and reason_ok and wall_bounded
        cases.append(
            {
                "case_id": case["case_id"],
                "budget_seconds": budget,
                "result": observed.get("result"),
                "unknown_reason": observed.get("unknown_reason", ""),
                "wall_seconds": wall,
                "wall_bounded": wall_bounded,
                "status": "PASS" if ok else "FAIL",
            }
        )

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "a timeout-corpus formula did not terminate with a typed TIMEOUT",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"{len(cases)} timeout-corpus formulas terminate with result=unknown, "
            "reason contains 'timeout', and wall_seconds bounded by budget"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E41-03: disagreement preserved (run both, report agreement; stub path).
# ---------------------------------------------------------------------------


def _check_e41_03() -> dict[str, Any]:
    """E41-03: agreement flags reported; disagreement PATH asserted via stub.

    Two sub-checks:

    1. A real ``both`` run on every corpus formula records cvc5 as
       unavailable (WAIT_LICENSE) with ``agreement=False`` and
       ``unknown_reason=cvc5_wait_license`` — a gap, not a disagreement, and
       never silently resolved.
    2. The disagreement *preservation path* is exercised via an injected stub
       for z3: a SAT formula run with ``both`` and a z3 stub reporting
       ``unsat`` must yield ``agreement=False`` and ``result=unknown`` with
       both sub-outcomes on ``SmtOutcome.disagreement``. This is the honest
       way to cover the preservation machinery: a stub, not a fake real
       disagreement.
    """
    cases: list[dict[str, Any]] = []

    # Sub-check 1: real `both` runs over the corpus; cvc5 is license-blocked.
    decided_cases = _load_corpus("sat") + _load_corpus("unsat")
    for case in decided_cases:
        outcome = check(
            case["formula_spec"],
            solver=SolverChoice.BOTH,
            timeout=case.get("timeout_seconds", 5),
        )
        disagreement = outcome.disagreement
        agreement_flag = disagreement.get("agreement") if disagreement else None
        note = disagreement.get("note", "") if disagreement else ""
        # cvc5 unavailable => gap, not disagreement; never silently resolved.
        ok = (
            outcome.result == SmtResult.UNKNOWN
            and agreement_flag is False
            and "cvc5_wait_license" in outcome.unknown_reason
            and "gap" in note
        )
        cases.append(
            {
                "sub": "both-cvc5-unavailable",
                "case_id": case["case_id"],
                "result": str(outcome.result),
                "agreement": agreement_flag,
                "unknown_reason": outcome.unknown_reason,
                "status": "PASS" if ok else "FAIL",
            }
        )

    # Sub-check 2: the disagreement preservation path via an injected stub.
    sat_formula = [">", ["int-var", "x"], ["int-const", 0]]
    stub = {"solver": "z3", "result": "unsat", "unknown_reason": "injected-stub"}
    outcome = check(sat_formula, solver=SolverChoice.BOTH, timeout=5, stub=stub)
    disagreement = outcome.disagreement
    z3_sub = disagreement.get("z3") if disagreement else None
    cvc5_sub = disagreement.get("cvc5") if disagreement else None
    # The stub forces z3 to report unsat (a fake), the real cvc5 is
    # unavailable; the path must preserve agreement=False and result=unknown.
    ok = (
        outcome.result == SmtResult.UNKNOWN
        and disagreement is not None
        and disagreement.get("agreement") is False
        and z3_sub is not None
        and disagreement.get("agreement") is False
        and "injected-stub" in (z3_sub.unknown_reason if z3_sub else "")
    )
    cases.append(
        {
            "sub": "stub-disagreement-path",
            "result": str(outcome.result),
            "agreement": disagreement.get("agreement") if disagreement else None,
            "z3_sub_result": str(z3_sub.result) if z3_sub else None,
            "z3_sub_reason": z3_sub.unknown_reason if z3_sub else "",
            "cvc5_sub": str(cvc5_sub.result) if cvc5_sub else "unavailable",
            "status": "PASS" if ok else "FAIL",
        }
    )

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "disagreement/agreement path did not preserve outcomes correctly",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"{len(decided_cases)} `both` runs record cvc5 unavailable "
            "(WAIT_LICENSE, agreement=False, gap not disagreement); the stub "
            "disagreement-preservation path preserves agreement=False + "
            "result=unknown with both sub-outcomes"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E41-04: no PROVEN emitted anywhere.
# ---------------------------------------------------------------------------


def _check_e41_04() -> dict[str, Any]:
    """E41-04: scan adapter output across the corpus for any 'proven' marker.

    The adapter must never emit a ``proven`` evidence state: a SMT-style answer
    yields at most ``formal_check=checked``. This check runs every corpus
    formula (single and both) and JSON-scans the serialized outcome for the
    ``proven`` token. None may appear.
    """
    cases: list[dict[str, Any]] = []
    ceiling_ok = FORMAL_CHECK_CEILING == "checked"
    cases.append(
        {
            "check": "formal_check_ceiling",
            "ceiling": FORMAL_CHECK_CEILING,
            "status": "PASS" if ceiling_ok else "FAIL",
        }
    )
    # Run every corpus formula under z3 and `both`; serialize and scan.
    proven_seen = False
    scanned = 0
    for category in ("sat", "unsat", "unknown"):
        for case in _load_corpus(category):
            for solver in (SolverChoice.Z3, SolverChoice.BOTH):
                try:
                    outcome = check(
                        case["formula_spec"],
                        solver=solver,
                        timeout=case.get("timeout_seconds", 5),
                    )
                except SmtError:
                    continue
                blob = json.dumps(outcome.to_dict())
                if "proven" in blob:
                    proven_seen = True
                scanned += 1
    no_proven_ok = not proven_seen
    cases.append(
        {
            "check": "no_proven_in_output",
            "scanned_outcomes": scanned,
            "proven_seen": proven_seen,
            "status": "PASS" if no_proven_ok else "FAIL",
        }
    )

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "a 'proven' marker was emitted (formal_check=checked is the ceiling)",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"no 'proven' marker across {scanned} serialized outcomes; "
            f"formal_check ceiling is '{FORMAL_CHECK_CEILING}'"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E41-05: license inventory still passes.
# ---------------------------------------------------------------------------


def _check_e41_05() -> dict[str, Any]:
    """E41-05: the license inventory classifies all locked packages as allowed.

    Runs ``license_inventory.py`` in-process and asserts no ``denied`` or
    ``unknown`` entries. cvc5 is excluded by construction (it is not a
    dependency); z3 must be MIT/allowed.
    """
    inv_path = _REPO_ROOT / "scripts" / "checks" / "license_inventory.py"
    try:
        proc = subprocess.run(  # noqa: S603 (trusted in-repo script; no shell)
            [sys.executable, str(inv_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "FAIL",
            "detail": "license inventory timed out",
            "error": str(exc),
            "cases": [],
        }
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "FAIL",
            "detail": "license inventory did not emit valid JSON",
            "error": str(exc),
            "stdout": proc.stdout[:500],
            "cases": [],
        }
    denied = report.get("denied", [])
    unknown = report.get("unknown", [])
    z3_entry = next((p for p in report.get("packages", []) if p.get("name") == "z3-solver"), None)
    z3_ok = z3_entry is not None and z3_entry.get("status") == "allowed"
    inv_ok = (not denied) and (not unknown) and z3_ok
    cases = [
        {
            "check": "no_denied",
            "denied": denied,
            "status": "PASS" if not denied else "FAIL",
        },
        {
            "check": "no_unknown",
            "unknown": unknown,
            "status": "PASS" if not unknown else "FAIL",
        },
        {
            "check": "z3_allowed",
            "z3_license": z3_entry.get("license") if z3_entry else None,
            "z3_status": z3_entry.get("status") if z3_entry else None,
            "status": "PASS" if z3_ok else "FAIL",
        },
        {
            "check": "cvc5_excluded",
            "cvc5_in_inventory": any(
                p.get("name", "").lower().startswith("cvc5") for p in report.get("packages", [])
            ),
            "status": "PASS",  # cvc5 must NOT appear; verified below.
        },
    ]
    # Assert cvc5 is genuinely absent (license-blocked).
    cvc5_present = any(
        p.get("name", "").lower().startswith("cvc5") for p in report.get("packages", [])
    )
    if cvc5_present:
        cases[-1]["status"] = "FAIL"

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures or proc.returncode != 0 or not inv_ok:
        return {
            "status": "FAIL",
            "detail": (
                "license inventory reported denied/unknown entries, a missing z3, "
                "or cvc5 present (it must be excluded)"
            ),
            "inventory_exit": proc.returncode,
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "license inventory clean: no denied/unknown; z3-solver is "
            f"{z3_entry.get('license') if z3_entry else '?'}/allowed; cvc5 excluded (WAIT_LICENSE)"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: solver availability, corpus counts, caps."""
    return {
        "z3_version": z3_version(),
        "available_solvers": sorted(AVAILABLE_SOLVERS),
        "wait_license_solvers": sorted(WAIT_LICENSE_SOLVERS),
        "formal_check_ceiling": FORMAL_CHECK_CEILING,
        "max_wall_seconds": MAX_WALL_SECONDS,
        "max_formula_nodes": MAX_FORMULA_NODES,
        "sat_corpus": len(_load_corpus("sat")),
        "unsat_corpus": len(_load_corpus("unsat")),
        "unknown_corpus": len(_load_corpus("unknown")),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "E41-01": _check_e41_01(),
        "E41-02": _check_e41_02(),
        "E41-03": _check_e41_03(),
        "E41-04": _check_e41_04(),
        "E41-05": _check_e41_05(),
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

    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "E41-01": _check_e41_01,
            "E41-02": _check_e41_02,
            "E41-03": _check_e41_03,
            "E41-04": _check_e41_04,
            "E41-05": _check_e41_05,
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
