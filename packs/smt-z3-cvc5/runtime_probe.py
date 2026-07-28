"""Runtime probe for the smt-z3-cvc5 pack (WP-E41).

The runtime probe verifies the SMT adapter loads, Z3 is importable, and the
typed surface is reachable. It is the ``runtime_probe`` entrypoint named in
the pack manifest and is invoked by the admission pipeline's
``RUNTIME_PROBED`` stage.

Exit code 0 on success; non-zero on any import or surface failure. The probe
is hermetic: it imports only the in-repo ``srl`` package (which transitively
imports z3) and exercises a tiny in-memory formula, never touching the
network.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Load the SMT adapter and verify its typed surface is reachable."""
    from srl.packs.adapters.smt import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        AVAILABLE_SOLVERS,
        FORMAL_CHECK_CEILING,
        SUPPORTED_OPERATORS,
        WAIT_LICENSE_SOLVERS,
        SmtError,
        SmtResult,
        SolverChoice,
        check,
        z3_version,
    )

    # Static guards: the operator grammar is populated, z3 is available, cvc5
    # is held back on license grounds, and the honest evidence ceiling is
    # `checked` (never `proven` without a verified certificate). Combined into
    # one check so the probe has a single failure path for its invariants.
    invariants_ok = (
        bool(SUPPORTED_OPERATORS)
        and "z3" in AVAILABLE_SOLVERS
        and "cvc5" in WAIT_LICENSE_SOLVERS
        and FORMAL_CHECK_CEILING == "checked"
    )
    if not invariants_ok:
        return 1  # pragma: no cover (probe failure path)

    # z3 must decide a trivial SAT formula (x > 0) and return a witness.
    outcome = check([">", ["int-var", "x"], ["int-const", 0]], solver=SolverChoice.Z3)
    if outcome.result != SmtResult.SAT or outcome.model is None:
        return 1  # pragma: no cover (probe failure path)

    # cvc5 alone must be rejected (no cleared license).
    try:
        check([">", ["int-var", "x"], ["int-const", 0]], solver=SolverChoice.CVC5)
    except SmtError:
        pass
    else:
        return 1  # pragma: no cover (probe failure path)

    print(f"smt-z3-cvc5 runtime probe OK; z3={z3_version()}; ceiling={FORMAL_CHECK_CEILING}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
