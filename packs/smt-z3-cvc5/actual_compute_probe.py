"""Actual-compute probe for the smt-z3-cvc5 pack (WP-E41).

The actual-compute probe runs a deterministic satisfiability computation and
prints a checkable result. It is the ``actual_compute_probe`` entrypoint named
in the pack manifest and is invoked by the admission pipeline's
``ACTUAL_COMPUTE_PROBED`` stage.

The probe is hermetic: it exercises the SMT adapter on tiny in-memory
formulas (a SAT case, an UNSAT case, and a disagreement-preservation case),
never touching the network. The printed result is deterministic so the
admission gate can compare it byte-for-byte.

Exit code 0 on success; non-zero on any compute failure.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Run the deterministic compute and print the checkable result."""
    from srl.packs.adapters.smt import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        FORMAL_CHECK_CEILING,
        SmtResult,
        SolverChoice,
        check,
        z3_version,
    )

    # 1. SAT: x > 0 is satisfiable, with a witness.
    sat = check([">", ["int-var", "x"], ["int-const", 0]], solver=SolverChoice.Z3)
    if sat.result != SmtResult.SAT or sat.model is None:
        return 1  # pragma: no cover (probe failure path)

    # 2. UNSAT: (x > 0) and (x < 0) is unsatisfiable.
    unsat = check(
        [
            "and",
            [">", ["int-var", "x"], ["int-const", 0]],
            ["<", ["int-var", "x"], ["int-const", 0]],
        ],
        solver=SolverChoice.Z3,
    )
    if unsat.result != SmtResult.UNSAT:
        return 1  # pragma: no cover (probe failure path)

    # 3. Disagreement preservation: a `both` run records cvc5 as unavailable
    #    (WAIT_LICENSE) and preserves the gap rather than silently resolving.
    both = check([">", ["int-var", "x"], ["int-const", 0]], solver=SolverChoice.BOTH)
    if both.disagreement is None or both.disagreement["agreement"] is not False:
        return 1  # pragma: no cover (probe failure path)
    if both.unknown_reason != "cvc5_wait_license":
        return 1  # pragma: no cover (probe failure path)

    # Deterministic checkable result for the admission gate.
    print(
        "smt-z3-cvc5 compute probe OK; "
        f"sat={sat.result}; unsat={unsat.result}; "
        f"both_unknown_reason={both.unknown_reason}; "
        f"ceiling={FORMAL_CHECK_CEILING}; z3={z3_version()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
