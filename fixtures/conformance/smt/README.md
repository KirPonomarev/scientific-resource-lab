# SMT conformance corpus (WP-E41)

This directory holds the conformance corpus for the SMT satisfiability adapter
(`src/srl/packs/adapters/smt.py`). Every fixture is a canonical JSON document
carrying a restricted S-expression `formula_spec` and the expected
`result` under the named `solver`. The corpus is exercised by
`scripts/checks/wp41-gate.py` (E41-01 ... E41-05) and the hermetic test suite
in `tests/packs/test_smt_adapter.py`.

> A `sat` / `unsat` answer is **not** empirical truth. It yields at most
> `formal_check=checked` on the evidence ladder; `proven` requires an
> independently checked exact certificate, which this package does not mint
> (see `docs/contracts/evidence-model.md` and
> `docs/architecture/smt-pack.md`).

## Layout

| Subdir       | Count | Cases                                                                |
| ------------ | ----- | ------------------------------------------------------------------- |
| `sat/`       | 3     | `s01` linear integer, `s02` conjunction, `s03` real arithmetic      |
| `unsat/`     | 3     | `u01` contradiction, `u02` equality conflict, `u03` linear infeasible |
| `unknown/`   | 2     | `k01` integer factorization (6 vars, timeout), `k02` integer factorization (5 vars, timeout) |
| `oversized/` | 1     | `o01` generator for a formula exceeding `MAX_FORMULA_NODES`         |

### SAT corpus (`sat/`)

Three satisfiable formulas, each with a known witness. `s01` is the minimal
one-variable case; `s02` adds a conjunction; `s03` exercises real-variable
unification across a linear equality and a strict bound.

### UNSAT corpus (`unsat/`)

Three unsatisfiable formulas. `u01` is the direct contradiction; `u02` is an
equality conflict decided by the congruence closure; `u03` is a
three-constraint infeasible linear system (x >= 1, y >= 0, x + y <= 0)
exercising the simplex/Farkas path.

### UNKNOWN / timeout corpus (`unknown/`)

Two genuinely hard nonlinear integer formulas that z3 cannot decide within a
1.5 s budget, so the adapter returns `unknown` with `unknown_reason`
containing `timeout`. Both are integer-factorization obligations: the product
of N integers each > 1 is constrained to equal a prime (1000003 / 2000003),
which is unsatisfiable but expensive to prove. `k01` uses six variables;
`k02` uses five variables (same prime target, smaller search). These are
honest `unknown` results (the solver hit its bound), not failures. z3's
nonlinear *integer* arithmetic is substantially weaker than its real
arithmetic, which is why a real-arithmetic analogue of these cases solves
trivially and is not a reliable timeout — hence the two integer cases.

### Oversized corpus (`oversized/`)

`o01` carries a *generator* (`formula_spec_generator`) rather than an inflated
spec: the gate materializes a formula exceeding `MAX_FORMULA_NODES` (10000)
by repeating a small operand under an `and` 12000 times, then asserts
`check()` raises `SmtError` (`CONTRACT_INVALID`) before the solver is
constructed. The committed fixture stays reviewable.

## The z3-vs-cvc5 disagreement question

The task asked for *one deliberate z3-vs-cvc5 disagreement candidate if
findable quickly, else document the absence*. **No such candidate is shipped,
by construction.** cvc5 is excluded from this package on license grounds: its
PyPI wheels bundle GPLv3/LGPLv3 components (`gpl-3.0.txt`, `lgpl-3.0.txt` are
in the `license_files`) and ship no resolvable license expression (the
`license`/`license_expression`/classifier fields are all `None`), so the CI
license inventory (`scripts/checks/license_inventory.py`) would classify it
`unknown` and fail. cvc5 therefore **cannot run at all** in this package
(`solver=cvc5` alone is rejected by `check()`; in a `both` run cvc5 is
recorded as `WAIT_LICENSE`-unavailable). A real disagreement between two
solvers that have both run is impossible to observe while one of them is
license-blocked.

The **disagreement-preservation path** is nonetheless exercised end-to-end:
the WP-E41 gate (E41-03) injects a stub result for z3 in a `both` run so that
the adapter's disagreement machinery (`agreement=False`, `result=unknown`,
per-solver sub-outcomes preserved, never silently resolved) is covered
**without** fabricating a real disagreement. This is the honest way to test
the preservation invariant: the gate asserts the *path* exists via an injected
stub, not a fake real disagreement (per the gate contract).

When a future work package clears a second solver's license (or a
GPL-free cvc5 build becomes available), the disagreement corpus will gain a
real two-solver disagreement candidate. The adapter is ready for it: a genuine
disagreement produces `agreement=False` and `result=unknown` with both
sub-outcomes on `SmtOutcome.disagreement`.
