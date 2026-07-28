# P0 integration conformance corpus (WP-E45)

This directory documents the **synthetic conformance corpus** the WP-E45
integration gate (`scripts/checks/wp45-gate.py`) generates and measures. The
corpus is generated **inline** by the gate (not loaded from fixture files) so
the gate is self-contained and hermetic: no fixture file can drift out of sync
with the gate's assertions. This README is the human-readable manifest.

## Why inline?

The integration corpus is small, deterministic, and tightly coupled to the
gate's golden assertions (each run's expected output is checked in the same
function that generates the input). Generating the inputs inline keeps the
input and the assertion in one place, so a change to either is reviewable in a
single diff. The other P0 pack conformance families (units, smt, ripser,
pyriemann) ship `.input.json` / `.expected_error.json` vectors because their
pack gates load them generically; the integration gate's corpus is bespoke, so
inline generation is simpler and less error-prone.

## The corpus (20 measured runs: 5 per pack × 4 packs)

Each run publishes a REAL `wall_seconds` / `rss_bytes` / `expanded_bytes`
triple read off the running process. The runs are DISTINCT (different inputs).

### units (5 distinct coherent SI conversions)

1. `convert("1", "kg*m/s^2", "N")` → `"1"` (the canonical identity)
2. `convert("3", "N", "kg*m/s^2")` → `"3"` (the reverse)
3. `convert("1", "J", "N*m")` → `"1"` (the joule identity)
4. `convert("7", "Pa", "N/m^2")` → `"7"` (the pascal identity)
5. `convert("1", "W", "J/s")` → `"1"` (the watt identity)

### smt (5 distinct formulas over z3)

1. `x > 0` → `sat` (witness `x=1`)
2. `y < 0` → `sat` (witness `y=-1`)
3. `z > 5 ∧ z < 5` → `unsat`
4. `a = 7` → `sat` (witness `a=7`)
5. `b = 1 ∨ b = 2` → `sat` (witness `b=2`)

### ripser (5 distinct point clouds)

1. circle, 50 points, `maxdim=1` → one long-lived H1
2. circle, 80 points, `maxdim=1` → one long-lived H1
3. two-cluster, 40 points, `maxdim=1` → two long-lived H0
4. uniform square, 50 points, `maxdim=0` → connected-component structure
5. circle, 60 points, `maxdim=0` → connected-component structure

### pyriemann (5 distinct SPD-matrix operations)

1. log-Euclidean mean of `[[2,0.3],[0.3,1.5]]`, `[[3,-0.2],[-0.2,2]]`
2. log-Euclidean mean of `[[5,0.1],[0.1,4]]`, `[[1,0.5],[0.5,2]]`
3. Riemannian distance between two 2×2 SPD matrices
4. log-Euclidean distance between the same two matrices
5. log-Euclidean mean of two commuting diagonal matrices → closed-form check

## Honesty

The measurements are REAL — read off the process after each compute, never
hardcoded. They are not benchmarks: they vary across hosts and runs, and are
published so a reviewer can confirm the runs are distinct and the outputs are
genuine. See `docs/architecture/p0-integration.md` ("What the integration does
NOT prove").
