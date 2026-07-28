#!/usr/bin/env python3
"""WP-H71b acceptance gate for the CVXPY bounded optimization P1 candidate.

Runs five checks, prints a single canonical ``GateReceipt/v1`` JSON line to
stdout, and exits 0 only if every check PASSes. The gate exercises the
adapter in ``srl.packs.adapters.cvxpy_adapter`` against the conformance
fixtures under ``fixtures/conformance/cvxpy/``.

Checks
------
H71b-01 constrained-fit golden within tolerance
    Ridge regression with inactive box constraints matches the closed-form
    normal-equation reference within ``1e-5`` and reports ``OPTIMAL``.

H71b-02 infeasible status honest
    A contradictory box-bounds LP returns ``INFEASIBLE`` as a first-class
    status, with null objective and solution, and never raises an exception.

H71b-03 unbounded status honest
    An unbounded LP returns ``UNBOUNDED`` as a first-class status, with null
    objective and solution, and never raises an exception.

H71b-04 GPL solver rejected typed
    A request for ``glpk`` raises :class:`CvxpyLicenseError` with fail reason
    ``LICENSE_INCOMPATIBLE`` before any CVXPY solve.

H71b-05 solver/license matrix enforced
    The allowed solver set is exactly ``{clarabel, osqp}``, the denied set is
    exactly ``{glpk, cbc}``, and the denied request is rejected before solve.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp71b-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.packs.adapters.cvxpy_adapter import (  # noqa: E402
    CvxpyLicenseError,
    Solver,
    SolveStatus,
    clarabel_version,
    cvxpy_version,
    is_solver_allowed,
    osqp_version,
    solve,
)
from srl.packs.manifest import LICENSE_INCOMPATIBLE_REASON  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-H71b"

# Conformance fixtures directory.
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "cvxpy"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture from the CVXPY conformance directory."""
    path = _FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# H71b-01: constrained-fit golden within tolerance.
# ---------------------------------------------------------------------------


def _check_h71b_01() -> dict[str, Any]:
    """H71b-01: ridge golden solution matches the closed-form reference."""
    fixture = _load_fixture("constrained-fit-golden.json")
    spec = fixture["problem_spec"]
    expected = np.asarray(fixture["expected_solution"], dtype=float)
    tolerance = float(fixture["tolerance"])

    try:
        result = solve(spec)
    except Exception as exc:  # gate must capture any unexpected failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    errors: list[str] = []
    if result.status != SolveStatus.OPTIMAL:
        errors.append(f"status={result.status!r}, expected OPTIMAL")
    if not result.license_verified:
        errors.append("license_verified is false")
    if result.solution is None:
        errors.append("solution is null")
    else:
        actual = np.asarray([float(v) for v in result.solution], dtype=float)
        if not np.allclose(actual, expected, atol=tolerance, rtol=tolerance):
            errors.append(
                f"solution {actual.tolist()} not within {tolerance} of {expected.tolist()}"
            )
    if result.objective_decimal is None:
        errors.append("objective_decimal is null")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": "ridge golden solution within tolerance of closed-form reference",
        "objective_decimal": result.objective_decimal,
    }


# ---------------------------------------------------------------------------
# H71b-02: infeasible status honest.
# ---------------------------------------------------------------------------


def _check_h71b_02() -> dict[str, Any]:
    """H71b-02: an infeasible LP returns INFEASIBLE without raising."""
    fixture = _load_fixture("infeasible.json")

    try:
        result = solve(fixture["problem_spec"])
    except Exception as exc:
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    errors: list[str] = []
    if result.status != SolveStatus.INFEASIBLE:
        errors.append(f"status={result.status!r}, expected INFEASIBLE")
    if not result.license_verified:
        errors.append("license_verified is false")
    if result.objective_decimal is not None:
        errors.append("objective_decimal should be null for infeasible")
    if result.solution is not None:
        errors.append("solution should be null for infeasible")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {"status": "PASS", "detail": "infeasible LP returned INFEASIBLE as a first-class status"}


# ---------------------------------------------------------------------------
# H71b-03: unbounded status honest.
# ---------------------------------------------------------------------------


def _check_h71b_03() -> dict[str, Any]:
    """H71b-03: an unbounded LP returns UNBOUNDED without raising."""
    fixture = _load_fixture("unbounded.json")

    try:
        result = solve(fixture["problem_spec"])
    except Exception as exc:
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    errors: list[str] = []
    if result.status != SolveStatus.UNBOUNDED:
        errors.append(f"status={result.status!r}, expected UNBOUNDED")
    if not result.license_verified:
        errors.append("license_verified is false")
    if result.objective_decimal is not None:
        errors.append("objective_decimal should be null for unbounded")
    if result.solution is not None:
        errors.append("solution should be null for unbounded")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {"status": "PASS", "detail": "unbounded LP returned UNBOUNDED as a first-class status"}


# ---------------------------------------------------------------------------
# H71b-04: GPL solver rejected typed.
# ---------------------------------------------------------------------------


def _check_h71b_04() -> dict[str, Any]:
    """H71b-04: a request for glpk raises CvxpyLicenseError before solve."""
    fixture = _load_fixture("gpl-solver-rejection.json")
    spec = fixture["problem_spec"]
    solver = fixture["solver"]
    expected_reason = fixture["expected_fail_reason"]

    try:
        solve(spec, solver=solver)
        return {
            "status": "FAIL",
            "detail": f"solver={solver!r} was accepted; expected CvxpyLicenseError",
        }
    except CvxpyLicenseError as exc:
        if exc.fail_reason == expected_reason:
            return {
                "status": "PASS",
                "detail": f"solver={solver!r} rejected before solve with {expected_reason!r}",
            }
        return {
            "status": "FAIL",
            "detail": f"fail_reason={exc.fail_reason!r}, expected {expected_reason!r}",
        }
    except Exception as exc:
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# H71b-05: solver/license matrix enforced.
# ---------------------------------------------------------------------------


def _check_h71b_05() -> dict[str, Any]:
    """H71b-05: allowed/denied solver sets match the license matrix."""
    allowed = {Solver.CLARABEL.value, Solver.OSQP.value}
    denied = {"glpk", "cbc"}

    errors: list[str] = []
    for solver in allowed:
        if not is_solver_allowed(solver):
            errors.append(f"allowed solver {solver!r} rejected")
    for solver in denied:
        if is_solver_allowed(solver):
            errors.append(f"denied solver {solver!r} accepted")

    # Re-verify the denied cases raise the typed license error before any solve.
    denied_cases: list[dict[str, Any]] = []
    for solver in denied:
        try:
            solve({"problem_type": "lp", "c": [1.0]}, solver=solver)
            denied_cases.append({"solver": solver, "outcome": "NOT rejected"})
            errors.append(f"denied solver {solver!r} not rejected")
        except CvxpyLicenseError as exc:
            denied_cases.append(
                {
                    "solver": solver,
                    "outcome": "rejected",
                    "fail_reason": exc.fail_reason,
                }
            )
            if exc.fail_reason != LICENSE_INCOMPATIBLE_REASON:
                errors.append(f"denied solver {solver!r} rejected with wrong fail reason")
        except Exception as exc:
            denied_cases.append({"solver": solver, "outcome": f"unexpected {type(exc).__name__}"})
            errors.append(f"denied solver {solver!r} raised unexpected {type(exc).__name__}")

    if errors:
        return {
            "status": "FAIL",
            "detail": "; ".join(errors),
            "allowed": sorted(allowed),
            "denied": sorted(denied),
            "denied_cases": denied_cases,
        }
    return {
        "status": "PASS",
        "detail": "allowed Apache-2.0 solvers accepted; GPL-family solvers rejected before solve",
        "allowed": sorted(allowed),
        "denied": sorted(denied),
        "denied_cases": denied_cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: dependency versions and solver matrix."""
    return {
        "cvxpy_version": cvxpy_version(),
        "clarabel_version": clarabel_version(),
        "osqp_version": osqp_version(),
        "allowed_solvers": sorted([Solver.CLARABEL.value, Solver.OSQP.value]),
        "denied_solvers": sorted(["glpk", "cbc"]),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "H71b-01": _check_h71b_01(),
        "H71b-02": _check_h71b_02(),
        "H71b-03": _check_h71b_03(),
        "H71b-04": _check_h71b_04(),
        "H71b-05": _check_h71b_05(),
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
            "H71b-01": _check_h71b_01,
            "H71b-02": _check_h71b_02,
            "H71b-03": _check_h71b_03,
            "H71b-04": _check_h71b_04,
            "H71b-05": _check_h71b_05,
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
