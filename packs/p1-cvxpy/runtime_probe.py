#!/usr/bin/env python3
"""Runtime probe for the p1-cvxpy pack.

Verifies that the CVXPY adapter surface is present, the allowed/denied solver
sets match the license matrix, and a denied solver request is rejected before
any compute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.packs.adapters.cvxpy_adapter import (  # noqa: E402
    CvxpyLicenseError,
    Solver,
    clarabel_version,
    cvxpy_version,
    is_solver_allowed,
    osqp_version,
    solve,
)


def main() -> int:
    """Run the runtime probe and return 0 on success."""
    if not is_solver_allowed(Solver.CLARABEL.value):
        raise SystemExit("default solver clarabel is not allowed")
    if not is_solver_allowed(Solver.OSQP.value):
        raise SystemExit("alternate solver osqp is not allowed")
    if is_solver_allowed("glpk") or is_solver_allowed("cbc"):
        raise SystemExit("GPL-family solvers are unexpectedly allowed")

    try:
        solve({"problem_type": "lp", "c": [1.0]}, solver="glpk")
    except CvxpyLicenseError:
        pass
    else:
        raise SystemExit("glpk request was not rejected before solve")

    print(
        json.dumps(
            {
                "status": "ok",
                "cvxpy_version": cvxpy_version(),
                "clarabel_version": clarabel_version(),
                "osqp_version": osqp_version(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
