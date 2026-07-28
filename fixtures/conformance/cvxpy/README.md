# CVXPY bounded optimization conformance fixtures (WP-H71b)

This directory contains four worked conformance vectors for the bounded CVXPY
adapter. They exercise the solver/license matrix, honest status reporting, and
a constrained-fit golden case.

| Fixture | Purpose | Expected outcome |
|---|---|---|
| `constrained-fit-golden.json` | Ridge regression with inactive box constraints | `OPTIMAL` solution within `1e-5` of the closed-form normal equation |
| `infeasible.json` | Contradictory box bounds (`x >= 1` and `x <= 0`) | `INFEASIBLE` status returned, never raised as an exception |
| `unbounded.json` | Minimise `-x` with no upper bound (`x >= 0`) | `UNBOUNDED` status returned, never raised as an exception |
| `gpl-solver-rejection.json` | Request solver `glpk` | `LICENSE_INCOMPATIBLE` before any CVXPY solve |

All fixtures are deterministic, hermetic, and small enough to run comfortably
inside the 240-second gate budget.
