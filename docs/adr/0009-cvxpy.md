# ADR 0009: CVXPY for bounded disciplined convex optimization

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-H71b (CVXPY bounded optimization P1 candidate)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

WP-H71b introduces a bounded optimization adapter for disciplined convex
programs. The adapter must:

1. Solve small, declarative least-squares, ridge, lasso, LP, and QP problems.
2. Enforce a strict solver/license matrix at the surface, before any numerical
   solver is invoked.
3. Return honest first-class statuses (`infeasible`, `unbounded`) rather than
   swallowing them as exceptions.
4. Cap the problem size to stay within CI resource budgets.
5. Remain isolated behind a typed adapter surface so no other SRL module
   imports the underlying optimization library.

## Alternatives considered

### 1. `cvxpy` (chosen)

- The standard Python disciplined convex programming library, maintained at
  `cvxpy/cvxpy` since 2014.
- Ships a declarative DSL that maps exactly to the problem types WP-H71b needs
  (least squares, ridge, lasso, LP, QP, box/linear constraints).
- Distributed under **Apache-2.0**, compatible with the project's license and
  the SRL pack allowlist.
- Default solver is `clarabel` (Apache-2.0), an allowed alternate is `osqp`
  (Apache-2.0). The resolved transitive closure contains only permissive
  licenses (verified by `scripts/checks/license_inventory.py`).

### 2. `scipy.optimize` only

- `scipy.optimize.linprog` and `minimize` can solve LP/QP-like problems.
- SciPy is already a dependency; this would avoid adding a new package.
- However, `linprog` exposes a lower-level, less uniform API, does not have a
  first-class disciplined convex model, and SciPy's `linprog` historically
  depends on the optional HiGHS solver (which is MIT-licensed, but mixing the
  two APIs would make the license matrix harder to audit). CVXPY provides a
  cleaner, auditable surface for the exact problem types we need.

### 3. Hand-rolled LP/QP solvers

- A small custom implementation would avoid any new dependency.
- But disciplined convex modeling, sparse constraint handling, and numerical
  robustness for ridge/lasso would duplicate well-tested reference code. The
  SRL policy is to delegate to peer-reviewed reference implementations and
  verify them with golden fixtures, not to reimplement numerical optimizers.

## Decision

Adopt **`cvxpy>=1.9.2`** and **`clarabel>=0.11.1`** as the bounded
optimization engine for WP-H71b, fully isolated behind the adapter
`src/srl/packs/adapters/cvxpy_adapter.py`. The adapter is the only SRL module
that imports `cvxpy`.

Configuration (see `pyproject.toml`):

```toml
[project]
dependencies = [
    "clarabel>=0.11.1",
    "cvxpy>=1.9.2",
    ...
]
```

The adapter:

- Exposes a `Solver` enum with `clarabel` (default) and `osqp` (allowed
  alternate). Any other solver string, including `glpk` and `cbc`, raises
  `CvxpyLicenseError` with fail reason `LICENSE_INCOMPATIBLE` before any
  CVXPY solve.
- Returns `SolveStatus` values `optimal`, `optimal_inaccurate`, `infeasible`,
  `unbounded`, and `solver_error`. `infeasible` and `unbounded` are honest,
  first-class outcomes, never exceptions to swallow.
- Enforces `MAX_VARIABLES=100` and `MAX_CONSTRAINTS=200` before building a
  CVXPY problem.
- Renders objective values and solution components to the SRL decimal-string
  policy via `srl.contracts.canonical.decimal_to_str`, and records a content
  digest of the solution for reproducibility.

## Solver/license matrix

| Solver | License | Treatment in WP-H71b | Rationale |
|---|---|---|---|
| `clarabel` | Apache-2.0 | **Default, allowed** | Default CVXPY conic solver; permissive license. |
| `osqp` | Apache-2.0 | **Allowed alternate** | Quadratic-program solver; permissive license. |
| `glpk` | GPL-2.0-or-later | **Denied** | GPL family; raises `LICENSE_INCOMPATIBLE` before solve. |
| `cbc` | EPL-2.0 with GPL optional / GPL-family | **Denied** | Treated as GPL-family for the SRL matrix; raises `LICENSE_INCOMPATIBLE` before solve. |
| `highspy` (HiGHS) | MIT | **Not exposed** | Pulled in by CVXPY as a transitive dependency for internal LP solves, but not selectable at the adapter surface. |
| `scs` | MIT | **Not exposed** | Transitive conic solver; not selectable at the adapter surface. |

The adapter only exposes `clarabel` and `osqp`. All other solvers are rejected
before CVXPY can invoke them, so the license matrix is enforced at the SRL
surface rather than relying on downstream CVXPY defaults.

## Consequences

### Positive

- A uniform, declarative problem spec covers the four target problem types with
  a single solve entry point.
- The solver/license matrix is machine-checkable at the adapter surface and in
  the WP-H71b gate.
- Honest `infeasible`/`unbounded` statuses prevent the pack from silently
  treating a mathematical outcome as a runtime failure.
- The variable/constraint caps bound the compute surface for CI and sandbox use.

### Negative

- Adds `cvxpy` and its transitive solver stack to the dependency closure. The
  locked closure is audited by `license_inventory.py`; GPL-family solvers are
  excluded by the adapter matrix.
- The pack imports compiled extensions indirectly via NumPy/SciPy (already
  present) and the solver native code. Platform support is declared in the pack
  manifest as linux/macOS x86_64/arm64.

### Security impact

`cvxpy` is imported only inside the adapter and operates on in-memory NumPy
arrays. The adapter performs no network I/O, no shell execution, and no
deserialization of untrusted formats. Input specs are validated for shape,
bounds, and solver license before any compute.

### Resource impact

Moderate. The bounded caps keep problems small enough for a 15-minute CI job.
The 240-second gate budget is comfortable for the four conformance fixtures.

### License impact

`cvxpy` is Apache-2.0. The resolved solver stack includes `clarabel`
(Apache-2.0), `osqp` (Apache-2.0), `qdldl` (Apache-2.0), `highspy` (MIT), and
`scs` (MIT). The CI license inventory classifies all of them as allowed; no
`denied` or `unknown` entries are introduced. The GPL-family solvers `glpk` and
`cbc` are explicitly rejected by the adapter and never installed.

The pack manifest (`packs/p1-cvxpy/manifest.json`) declares the license as
`Apache-2.0` for the bundled adapter source and manifest.

## Reversibility

Reversible. `cvxpy` is isolated behind
`src/srl/packs/adapters/cvxpy_adapter.py`: that module is the only import site
of `cvxpy` in the SRL tree (asserted by an architecture test in
`tests/packs/test_cvxpy_adapter.py`). Removing CVXPY is:

1. a `pyproject.toml` change (drop `cvxpy>=1.9.2` and `clarabel>=0.11.1`);
2. a `uv lock` to drop the transitive closure;
3. replacing the body of `cvxpy_adapter.py` with an alternative bounded
   optimization implementation behind the same typed surface (`solve`,
   `Solver`, `SolveStatus`, `SolveResult`, `Cvxpy*Error` classes).

Because the public surface is stable and is the only consumer, callers
(`wp71b-gate.py`, the pack probes, future routers) would not need to change.

## Evidence

- `pyproject.toml` declares `cvxpy>=1.9.2` and `clarabel>=0.11.1` in
  `[project].dependencies`.
- `uv.lock` pins `cvxpy`, `clarabel`, and their permissive transitive closure.
- `src/srl/packs/adapters/cvxpy_adapter.py` is the sole `cvxpy` import site;
  the architecture test `tests/packs/test_cvxpy_adapter.py` asserts no other
  module imports `cvxpy`.
- `scripts/checks/wp71b-gate.py` verifies the solver/license matrix, honest
  statuses, and constrained-fit golden.
- The CI license inventory (`scripts/checks/license_inventory.py`) classifies
  the new dependencies as allowed.
- `docs/architecture/p1-cvxpy.md` documents the honest-status discipline, the
  solver/license matrix, and the "a fit is not causality" note.
