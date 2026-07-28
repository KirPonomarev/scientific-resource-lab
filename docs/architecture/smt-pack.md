# SMT satisfiability pack (WP-E41)

The SMT (Satisfiability Modulo Theories) pack is the fabric's
satisfiability-checking layer. It checks whether a restricted first-order
formula over linear/nonlinear integer and real arithmetic is satisfiable,
returning a typed verdict (`sat` / `unsat` / `unknown`) and, for `sat`, a
witness model. It replaces any "is this always true?" guesswork with a real
decision procedure, and it does so under an **honest evidence ceiling**: a
`sat`/`unsat` answer yields at most `formal_check=checked`, never `proven`
without a verified certificate.

The implementation is `srl.packs.adapters.smt`, the second pack adapter. It is
backed by [Z3](https://github.com/z3prover/z3) and is the **only** module in
the SRL tree that imports z3 (see [ADR-0004](../adr/0004-smt-solvers.md) and
the isolation section below). cvc5 is structurally supported by the adapter's
dual-solver machinery but is **excluded on license grounds** (its wheels bundle
GPLv3/LGPLv3 components — see ADR-0004) and marked `WAIT_LICENSE`.

## Honesty: SAT/UNSAT is not empirical truth

This is the load-bearing property of the pack. A `sat` / `unsat` answer is a
*decision-procedure result over a model*, not a statement about the physical
world, and not a proof. The evidence ladder reflects this:

- `formal_check=checked` — a SMT solver returned `sat` or `unsat`. Honest.
- `formal_check=proven` — REQUIRES an independently checked exact certificate
  (an unsat core verified by replay, or a proof object checked by a trusted
  checker). **This pack does not mint certificates.** It exposes the
  `FORMAL_CHECK_CEILING = "checked"` constant so callers know the honest
  ceiling without importing the evidence module.

A solver `unsat` *is* correct in the model-theoretic sense (z3 is sound for
unsat), but the fabric refuses to call it `proven` until the certificate is
independently checkable. This is the "SAT/UNSAT ≠ empirical truth" honesty
collapse the evidence model exists to prevent (see
`docs/contracts/evidence-model.md`, "The SMT is not proven rule"). The WP-E41
gate (E41-04) scans every adapter output across the corpus and asserts no
`proven` marker leaks.

## Typed surface

The adapter exposes a small, typed surface. Every other consumer goes through
it; none touches z3 directly.

| Symbol                    | Kind      | Purpose                                                          |
| ------------------------- | --------- | ---------------------------------------------------------------- |
| `SmtResult`               | enum      | `sat` / `unsat` / `unknown` (never a free string).               |
| `SolverChoice`            | enum      | `z3` / `cvc5` / `both`.                                          |
| `SmtOutcome`              | type      | Frozen record: result, solver, model, wall_seconds, disagreement.|
| `SmtError`                | exception | Raised for any contract violation (`CONTRACT_INVALID`).          |
| `check(formula_spec, solver, timeout)` | function | Check a restricted S-expression formula for satisfiability. |
| `SUPPORTED_OPERATORS`     | constant  | The frozenset of admitted S-expression operators.                |
| `MAX_WALL_SECONDS`        | constant  | The wall-seconds timeout cap (bounded by the M1 policy).         |
| `MAX_FORMULA_NODES`       | constant  | The formula-size cap (AST node count).                           |
| `AVAILABLE_SOLVERS`       | constant  | `{z3}` — solvers with a cleared license.                         |
| `WAIT_LICENSE_SOLVERS`    | constant  | `{cvc5}` — held back on license grounds.                         |
| `FORMAL_CHECK_CEILING`    | constant  | `"checked"` — the honest evidence ceiling.                       |
| `z3_version()`            | function  | The resolved z3 version (for gate evidence).                     |

## The restricted S-expression grammar

`check` takes a `formula_spec`: a JSON S-expression `[operator, *operands]`
where each operand is an atom or a nested S-expression. The adapter validates
the shape and the operator, then builds z3 terms through the z3 Python API
**only** — it never calls `z3.parse_smt2_string` / `eval` / `exec` on
caller-supplied text. This is the security-relevant surface: the only formula
shapes a caller can express are the operators an SRL human has reviewed.

The operator table (see `SUPPORTED_OPERATORS`):

| Group                | Operators                                   | Arity  |
| -------------------- | ------------------------------------------- | ------ |
| Boolean connectives  | `and`, `or`, `not`, `implies`               | n / n / 1 / 2 |
| Equality             | `=`, `distinct`                             | n / n  |
| Comparison           | `<`, `<=`, `>`, `>=`                        | n (chained) |
| Arithmetic           | `+`, `-`, `*`, `/`                          | n / 2 / n / n |
| Constants/variables  | `int-const`, `real-const`, `int-var`, `real-var` | 1 |

A `int-const` operand is a JSON integer (a bool is rejected — a boolean is not
a quantity); `real-const` takes a JSON number; `int-var` / `real-var` take a
non-empty variable name string. Variable declarations are memoised by name so
a repeated `int-var "x"` yields the *same* z3 constant (otherwise two
separately-constructed consts of the same name are distinct and the solver
trivially reports `sat`).

An unknown operator, a bad arity, a malformed atom, or an oversized formula
(each node counted) is rejected with `SmtError` (`CONTRACT_INVALID`) *before*
the solver is constructed. There is no silent fallback path.

## Resource caps

`check` enforces two hard caps before any solver runs:

- a **wall-seconds timeout cap** (`MAX_WALL_SECONDS = 900`), bounded by the M1
  resource policy's exception envelope (`src/srl/execution/policy.py`,
  `_EXCEPTION_CAPS["wall_seconds"] = 900`). A requested timeout above this is
  *clamped* down (it is a cap, not a rejection — the caller asked for "at most"
  this many seconds); a negative timeout is a contract error. The clamped
  millisecond budget is handed to the solver.
- a **formula-size cap** (`MAX_FORMULA_NODES = 10_000`), bounding the number of
  AST nodes in the `formula_spec`. An oversized formula is rejected before the
  solver is constructed, so a caller cannot hand the solver an unbounded
  problem.

Both are module constants so the resource policy has one auditable home.

## Solver choice and the cvc5 license gap

- `z3` (default) — runs z3, the only solver with a cleared license (MIT).
- `cvc5` — **rejected as a sole solver**. cvc5's wheels bundle GPLv3/LGPLv3
  components (`gpl-3.0.txt`, `lgpl-3.0.txt` are in the PyPI `license_files`)
  and ship no resolvable license expression, so the CI license inventory
  would classify it `unknown` and fail. cvc5 may only appear as the second
  solver in a `both` run.
- `both` — runs z3, then (would run) cvc5. Since cvc5 is `WAIT_LICENSE`, z3
  runs alone and the outcome records cvc5 as unavailable. The comparison is
  preserved on `SmtOutcome.disagreement`.

## Disagreement preservation

When two solvers run on the same formula and disagree, the disagreement is
**preserved** and **never silently resolved**. `SmtOutcome.disagreement`
carries `{z3: <SmtOutcome>, cvc5: <SmtOutcome|null>, agreement: bool}`; when
`agreement` is `False`, the overall `result` is `unknown` (the adapter refuses
to pick a winner). A disagreement is a scientifically interesting signal.

In this package z3 is the only solver with a cleared license, so a real
two-solver disagreement cannot occur while cvc5 is license-blocked: a `both`
run records the cvc5 *gap* (agreement=False, `unknown_reason=cvc5_wait_license`)
rather than a disagreement, and explicitly notes it is a gap. The
disagreement-*preservation path* is nonetheless exercised end-to-end by the
gate (E41-03) via an injected stub result for z3: the stub forces `agreement=
False` and `result=unknown` with both sub-outcomes preserved, proving the
machinery works. This is the honest way to test the invariant — a stub, not a
fake real disagreement.

When a future work package clears a second solver's license (or a GPL-free
cvc5 build becomes available), a real disagreement will produce the same
preservation shape automatically.

## Model rendering

For a `sat` result, the witness is rendered as a `{var: value_string}` mapping
of decimal-string policy values (z3 integer witnesses via `as_long()`, real
witnesses via `as_decimal()`), so a rational witness like `3/4` survives a
round trip without float coercion. Only 0-arity constant declarations (the
variables) are rendered; the model also exposes interpretations for
uninterpreted/total functions (e.g. real division `/`, modelled by z3 as a
total function), which are not variable witnesses and are skipped.

## Why z3 is isolated

z3 is a compiled native dependency (it ships manylinux/macos wheels with a
prebuilt libz3). The SRL adapter hides it behind a typed boundary:

- `srl.packs.adapters.smt` is the **only** module that imports `z3`. An
  architecture test (`tests/packs/test_smt_adapter.py::TestZ3Isolation`) walks
  the `src/srl` tree with `ast` and asserts no other module imports it.
- The adapter treats all z3 objects (solver, term, model, value) as opaque
  `Any`; no z3 type leaks into the SRL type surface, so `mypy --strict` checks
  the adapter's own typed contract, not z3's.

This means removing z3 is a `pyproject.toml` change plus a rewrite of one
module's body behind the same typed surface (see ADR-0004, *Reversibility*).
Callers — the WP-E41 gate, future routers — never need to change.

## Fail-fast contract

Formula errors are raised **before** any solver runs:

- `check` validates the formula shape, operators, arity, atoms, and size cap
  *before* constructing a single z3 term.
- the timeout is clamped and validated *before* the solver is built.

Every contract error is an `SmtError` carrying `fail_reason = CONTRACT_INVALID`
(a terminal, non-retriable contract failure). There is no silent fallback: a
formula the adapter cannot build is always an error.

## Future work

- **Verified certificates (the path to `proven`).** The adapter exposes the
  honest ceiling (`checked`); reaching `proven` requires an unsat core
  verified by replay or a proof object checked by a trusted checker. z3 can
  produce unsat cores and proof objects (`solver.unsat_core()`,
  `solver.proof()`); a future work package would verify them independently
  and only then mint a `formal_certificate_ref`. This is documented but not
  implemented here.
- **A second cleared solver.** When a GPL-free cvc5 build (or another solver
  with a cleared license) is available, the dual-solver disagreement path
  gains a real two-solver disagreement corpus candidate.

## Evidence

- `scripts/checks/wp41-gate.py` emits a `GateReceipt/v1` with five checks
  (E41-01..E41-05) and the resolved z3 version.
- `fixtures/conformance/smt/` ships the corpus: 3 SAT, 3 UNSAT, 2 UNKNOWN,
  1 oversized generator, plus a README documenting the disagreement question.
- `tests/packs/test_smt_adapter.py` is the hermetic test suite including the
  z3-isolation architecture test and the honesty-ceiling assertions.
- `docs/adr/0004-smt-solvers.md` records the solver choice, the license
  review, and the cvc5 exclusion rationale.
