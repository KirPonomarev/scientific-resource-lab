# CVXPY bounded optimization pack (WP-H71b)

This document covers the bounded disciplined-convex-optimization capability
shipped in WP-H71b: the adapter surface, the solver/license matrix, the
honest-status discipline, and the resource bounds that keep the P1 candidate
bounded and safe to exercise in CI.

## The adapter

The CVXPY adapter (`src/srl/packs/adapters/cvxpy_adapter.py`) is the **only**
module in the SRL tree that imports `cvxpy`. Every other consumer goes through
its typed surface:

| Symbol | Purpose |
| --- | --- |
| `solve(problem_spec, solver=Solver.CLARABEL, max_wall=30.0)` | Solve a declarative bounded problem and return a typed `SolveResult`. |
| `Solver` | StrEnum selecting `clarabel` (Apache-2.0, default) or `osqp` (Apache-2.0, alternate). |
| `SolveStatus` | First-class statuses: `optimal`, `optimal_inaccurate`, `infeasible`, `unbounded`, `solver_error`. |
| `SolveResult` | Frozen bundle: schema version, status, objective decimal string, solution decimal strings, solution digest, duality gap decimal, solver name, license-verified flag. |
| `CvxpyLicenseError` | Raised before any solve when a GPL-family solver is requested (`LICENSE_INCOMPATIBLE`). |
| `CvxpySpecError` | Raised for malformed problem specs (`CONTRACT_INVALID`). |
| `CvxpyResourceError` | Raised when variable or constraint caps are exceeded (`RESOURCE_LIMIT`). |

The adapter accepts a small, declarative problem spec language:

- `problem_type`: one of `least_squares`, `ridge`, `lasso`, `lp`, `qp`.
- `A` / `b` for least-squares/ridge/lasso, `c` for LP, `P` / `q` for QP.
- `constraints`: a list of `box`, `leq`, `eq`, or `geq` constraints.

All numeric values are carried as plain JSON arrays; the adapter validates
shapes and converts to NumPy arrays internally.

## Solver/license matrix

The adapter enforces a strict solver matrix at the surface:

| Solver | License | Adapter treatment |
| --- | --- | --- |
| `clarabel` | Apache-2.0 | **Default**; always allowed. |
| `osqp` | Apache-2.0 | **Allowed alternate**; selectable via `Solver.OSQP`. |
| `glpk` | GPL-family | **Denied**; raises `CvxpyLicenseError` (`LICENSE_INCOMPATIBLE`) before any solve. |
| `cbc` | GPL-family | **Denied**; raises `CvxpyLicenseError` (`LICENSE_INCOMPATIBLE`) before any solve. |

The SRL license inventory (`scripts/checks/license_inventory.py`) classifies the
resolved solver stack as allowed. CVXPY itself is Apache-2.0; the locked
transitive closure includes only permissive licenses (`clarabel`, `osqp`,
`scs`, `highspy`, `qdldl`, etc.). GPL-family solvers are never imported,
installed, or invoked by this pack.

## Honest statuses

A CVXPY solve can terminate in three honest non-error states:

- **Optimal** (`optimal` / `optimal_inaccurate`) — a feasible solution was found.
- **Infeasible** — the constraints cannot all be satisfied.
- **Unbounded** — the objective can be driven to `-inf`.

The adapter treats `infeasible` and `unbounded` as **first-class statuses** in
`SolveResult`. They are returned, never swallowed or re-raised as generic
exceptions. This is important for scientific honesty: an infeasible model is a
real mathematical outcome, not a runtime failure. The gate checks both states
explicitly.

## Resource bounds

Two hard caps are enforced **before** any CVXPY object is built:

| Limit | Value | Rationale |
| --- | --- | --- |
| `MAX_VARIABLES` | 100 | Keeps the canonicalization/solve comfortably under a second. |
| `MAX_CONSTRAINTS` | 200 | Keeps memory and solver time bounded in CI. |

A spec exceeding either cap raises `CvxpyResourceError` with fail reason
`RESOURCE_LIMIT`. The adapter never silently truncates, samples, or downsizes
an oversized problem.

## A fit is not causality

The `least_squares`, `ridge`, and `lasso` problem types fit a coefficient
vector to data. The result is a **computation**, not a causal or scientific
validation. An optimization fit can be optimal and still be statistically
unstable, confounded, or overfit.

The SRL evidence model (`docs/contracts/evidence-model.md`) keeps the compute
axis orthogonal to the validation and empirical axes. The CVXPY pack can move
`statistical_support` on the planning surface only when downstream validators
add independent evidence; the adapter itself never implies that an optimal fit
is a validated causal claim.

## The pack

The pack (`packs/p1-cvxpy/`) declares:

- `manifest.json` — `ResourcePackManifest/v1`, `pack_id: "p1-cvxpy.0.1.0"`,
  `capability_profiles: ["optimization"]`, `license.spdx: "Apache-2.0"`,
  `canonical_writes: 0`, `grants_authority: false`. Two entrypoints:
  `runtime` (the adapter surface check) and `compute` (a tiny ridge solve).
- `LICENSE.txt` — the Apache-2.0 license text for the bundled manifest and
  adapter source; its sha256 is recorded in `license.texts_sha256`.
- `runtime_probe.py` — the runtime probe: imports the adapter, verifies the
  typed surface and solver/license matrix.
- `actual_compute_probe.py` — the actual-compute probe: runs a bounded ridge
  regression and prints a `SolveResult` line.

The capability profile `optimization` is already declared in the SRL
planning registry (`src/srl/planning/profiles.py`); this pack fills that slot.

## Conformance fixtures

The conformance vectors (`fixtures/conformance/cvxpy/`) are:

- `constrained-fit-golden.json` — ridge with inactive box constraints; the
  solution matches the closed-form normal equation within `1e-5`.
- `infeasible.json` — a contradictory LP returns `INFEASIBLE`.
- `unbounded.json` — an unbounded LP returns `UNBOUNDED`.
- `gpl-solver-rejection.json` — a `glpk` request is rejected with
  `LICENSE_INCOMPATIBLE` before any solve.

The acceptance gate `scripts/checks/wp71b-gate.py` runs five checks (H71b-01
through H71b-05) and emits a `GateReceipt/v1`. It exits non-zero on any
FAIL, ensuring the pack cannot be admitted unless the solver/license matrix
and honest-status contract are intact.
