# ADR 0004: Z3 and cvc5 for the SMT satisfiability pack

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-E41 (SMT satisfiability pack)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

WP-E41 introduces the SMT satisfiability pack: a real satisfiability-checking
layer for the fabric. The adapter (`src/srl/packs/adapters/smt.py`) must:

1. **Check** a restricted first-order formula over linear/nonlinear integer and
   real arithmetic for satisfiability, returning a typed verdict
   (`sat` / `unsat` / `unknown`) and a witness model for `sat`.
2. **Preserve disagreements**: when two solvers run on the same formula and
   disagree, the disagreement is recorded (`agreement=false`,
   `result=unknown`) and never silently resolved.
3. **Stay honest**: a `sat`/`unsat` answer yields at most
   `formal_check=checked`; `proven` requires an independently checked
   certificate (unsat core replay or a checked proof object), which this pack
   does NOT implement (documented as future work).
4. **Bound the resource surface**: a hard wall-seconds timeout cap (bounded by
   the M1 policy exception envelope) and a formula-size cap, both enforced
   before any solver runs.

Satisfiability modulo theories is intricate (simplex, CDCL(T), nlsat/CAD,
congruence closure), exactly the kind of code where a hand-rolled procedure
silently corrupts every downstream claim, and where a real, well-tested solver
is the responsible choice. The decision affects:

1. Whether SAT/UNSAT/UNKNOWN verdicts are sound (z3 is sound for `unsat`).
2. The supply-chain surface (a SMT solver is a compiled native dependency
   imported wherever the adapter runs).
3. The license posture (a solver bundled into a redistributable pack must be
   license-compatible; GPL-family licenses are incompatible with the SRL pack
   allowlist).
4. Lockfile and reproducibility (`uv.lock` must pin the solver and its
   closure; the solver must ship wheels for linux/macos x86_64/arm64).

## Alternatives considered

### 1. `z3-solver` (chosen, MIT)

- The de-facto SMT solver for Python, distributed as the `z3-solver` wheel
  (prebuilt libz3 + Python bindings) under the **MIT License**. Maintained by
  Microsoft Research under `z3prover/z3`, in continuous development since
  2007.
- Ships manylinux/macos wheels for x86_64 and arm64, no source build required,
  no transitive runtime dependencies (the wheel is self-contained).
- Full SMT: linear/nonlinear integer and real arithmetic, bitvectors,
  quantifiers, and sound `unsat` (a z3 `unsat` is correct in the
  model-theoretic sense). Produces unsat cores and proof objects (the raw
  material for a future `proven` certificate path).
- The resolved `z3-solver==5.0.0.0` PyPI metadata records `License: MIT
  License`; the CI license inventory
  (`scripts/checks/license_inventory.py`) classifies it `MIT` / `allowed`.
- MIT is compatible with the project's Apache-2.0 license and the SRL pack
  allowlist.

### 2. `cvc5` (REJECTED on license grounds — `WAIT_LICENSE`)

- cvc5 (`cvc5/cvc5`) is a leading SMT solver with strong nonlinear and proof
  support. The `cvc5==1.3.4` PyPI wheel bundles the solver + Python bindings.
- **License blocker.** The PyPI metadata records `license: None`,
  `license_expression: None`, and no license classifier. The `license_files`
  include `COPYING`, `licenses/gpl-3.0.txt`, `licenses/lgpl-3.0.txt`,
  `licenses/minisat-LICENSE`, `licenses/pythonic-LICENSE`, plus
  `GCC-exception-3.1` and `apache-2.0-with-llvm-exceptions` texts. cvc5's
  source is under a modified BSD license *by default* (`--no-gpl`, which
  avoids GPL libraries), but the **published 1.3.4 wheel ships the GPL/LGPL
  license texts in its metadata**, indicating the wheel may bundle GPL-linked
  components (CryptoMiniSat under a permissive license is fine; **GLPK is
  GPLv3**). The cvc5 `COPYING` explicitly states: *"the following libraries
  are covered under the GPLv3 license ... if you choose to link cvc5 against
  one of these libraries, the resulting combined work is also covered under
  the GPLv3."*
- The SRL license inventory extractor reads `License-Expression → License →
  Classifier` in that order; for cvc5 all three are `None`/absent, so the
  inventory classifies cvc5 `unknown` and exits non-zero. Even if a license
  expression were present, the bundled `gpl-3.0.txt`/`lgpl-3.0.txt` files are
  a hard signal that a redistributable pack cannot carry cvc5 without a GPL
  compliance review the SRL project will not undertake for a pre-Alpha pack.
- **Decision: EXCLUDE cvc5.** Ship z3-only. cvc5 is marked `WAIT_LICENSE`:
  structurally supported by the adapter's dual-solver machinery (so the
  disagreement-preservation path is built and tested), but never imported and
  never added to `uv.lock`. When a GPL-free cvc5 build (or another solver
  with a cleared license) is available, the dual-solver path activates
  automatically.

### 3. `pysmt` (a solver-agnostic front-end)

- A Python SMT front-end that wraps z3, cvc5, MathSAT, Yices, etc. behind one
  API. Attractive for the disagreement-preservation feature (it would make
  `both` a one-liner).
- But: pysmt is a *meta-package* — it does not bundle the solvers; each
  backend is an optional install the caller wires. Adding pysmt adds a layer
  without removing the per-solver license decision, and the SRL adapter's
  restricted S-expression grammar already abstracts over the solver API. The
  indirection is pure overhead for a two-solver (z3 now, cvc5 later) pack.
- BSD-2-Clause licensed, but rejected on the design grounds above.

### 4. Hand-rolled decision procedure

- Implement a DPLL(T) / simplex / nlsat procedure by hand.
- Utterly infeasible for sound SMT over nonlinear arithmetic; a hand-rolled
  procedure is exactly the silent-bug-corrupts-everything risk a solver
  exists to remove. Rejected without further consideration.

## Decision

Adopt **`z3-solver`** as the SMT engine for the satisfiability pack, **fully
isolated behind the adapter** `src/srl/packs/adapters/smt.py`. z3 is the only
module in the SRL tree that imports `z3`; every other consumer goes through the
adapter's typed surface (`check`, `SmtOutcome`, `SmtResult`, `SolverChoice`,
`SmtError`). **cvc5 is excluded** on license grounds and marked `WAIT_LICENSE`:
the adapter's dual-solver and disagreement-preservation machinery is built and
tested for it, but cvc5 is never imported and never in `uv.lock`.

Configuration (see `pyproject.toml`):

```toml
[project]
dependencies = [
    "jsonschema>=4.23",
    "pint>=0.25.3",
    "z3-solver>=4.13.0",
]
```

The lower bound `>=4.13.0` admits the 5.0.0.0 release (the resolved version)
and recent 4.x releases; `uv.lock` pins the exact `5.0.0.0`.

The adapter builds z3 terms from a **restricted S-expression JSON encoding**
(`formula_spec`) through the z3 Python API only — never
`z3.parse_smt2_string` / `eval` / `exec` on caller text. The operator grammar
(`SUPPORTED_OPERATORS`) is a small, auditable set of boolean connectives,
arithmetic comparisons, arithmetic operators, and typed leaf producers. An
unknown operator, a bad arity, a malformed atom, or an oversized formula
(`> MAX_FORMULA_NODES`) raises `SmtError` (`CONTRACT_INVALID`) before the
solver is constructed.

The wall-seconds timeout is clamped to `MAX_WALL_SECONDS = 900` (the M1 policy
exception envelope) and handed to the solver in milliseconds; a negative
timeout is a contract error.

### The honest ceiling

A `sat` / `unsat` answer yields at most `formal_check=checked`. The adapter
exposes `FORMAL_CHECK_CEILING = "checked"` and never mints a certificate.
Reaching `proven` requires an unsat core verified by replay or a proof object
checked by a trusted checker; z3 can *produce* these (`solver.unsat_core()`,
`solver.proof()`), but *verifying* them independently is future work. The
WP-E41 gate (E41-04) scans every adapter output across the corpus and asserts
no `proven` marker leaks.

### Disagreement preservation

When two solvers run (`solver=both`) and disagree, the outcome carries
`disagreement = {z3: ..., cvc5: ..., agreement: false}` and `result=unknown`;
the adapter never picks a winner. Since cvc5 is license-blocked, a `both` run
records the cvc5 *gap* (agreement=false, `unknown_reason=cvc5_wait_license`)
rather than a real disagreement. The disagreement-*preservation path* is
exercised end-to-end by the gate (E41-03) via an injected stub result for z3,
which is the honest way to test the invariant without fabricating a real
disagreement.

## Consequences

### Positive

- Sound `unsat` for the supported theories (linear/nonlinear integer and real
  arithmetic): a z3 `unsat` is correct in the model-theoretic sense.
- The restricted S-expression grammar bounds the solver-input surface to a
  reviewed operator set; no raw SMT-LIB text is ever evaluated.
- The disagreement-preservation machinery is built and tested, so a future
  second-solver (GPL-free cvc5 or another cleared solver) activates the
  dual-solver path with no adapter rewrite.
- `mypy --strict` covers the adapter end-to-end (z3 treated as opaque `Any`).

### Negative

- Adds `z3-solver` as the third runtime third-party dependency. The wheel is
  ~30–40 MB (it bundles the prebuilt libz3 for each platform). All platforms
  SRL targets (linux/macos, x86_64/arm64) have wheels.
- The `srl.packs.adapters` layer depends on a compiled native library; the
  WP-E41 gate runs under `uv run python` (the WP-A03 autonomy gate remains
  stdlib-only under bare `python3`).
- cvc5 is unavailable: the dual-solver disagreement path cannot observe a
  real two-solver disagreement yet. This is an honest gap, documented and
  covered by the stub-driven gate check.

### Security impact

z3 is imported only inside the SMT adapter. The adapter builds terms through
the z3 API from a validated, restricted S-expression — it never evaluates
caller-supplied SMT-LIB text, so a formula cannot smuggle arbitrary solver
input or a directive injection. The solver runs with a bounded wall timeout
and only on formulas under the size cap; it performs no I/O of its own in
SRL's usage (no file reads, no network). It does not touch the runner
boundary, the content-addressed store, pack materialization, or the disclosure
sanitizer. Pinning a lower bound (`>=4.13.0`) and recording the resolved
`5.0.0.0` in `uv.lock` bounds the supply-chain surface. Reversibility is
covered below.

### Resource impact

Small for the corpus. The SAT/UNSAT formulas solve in milliseconds; the two
UNKNOWN cases (nonlinear integer factorization) run the full 1.5 s budget by
design (they are the timeout corpus). The adapter builds one z3 `Solver` per
`check` call (no process-wide solver state), so the memory surface is bounded
by the formula size. Well within the 15-minute CI budget.

### License impact

`z3-solver` is distributed under the **MIT License**. The resolved
`5.0.0.0` PyPI metadata records `License: MIT License`; the CI license
inventory classifies it `MIT` / `allowed`. MIT is compatible with the
project's Apache-2.0 license and the SRL pack allowlist. The z3 wheel is
self-contained (no transitive runtime dependencies), so the license closure
is exactly `{z3-solver: MIT}`.

**cvc5 is excluded.** The `cvc5==1.3.4` PyPI metadata records no resolvable
license expression/classifier (all `None`) and ships `gpl-3.0.txt` /
`lgpl-3.0.txt` in its `license_files`, indicating bundled GPL/LGPL components.
The SRL license inventory would classify it `unknown` (no license expression
to read) and exit non-zero; and even with an expression, the bundled GPL texts
are a hard signal that a redistributable pack cannot carry cvc5 without a GPL
compliance review. cvc5 is therefore `WAIT_LICENSE`: never imported, never in
`uv.lock`, never in the license inventory. The pack manifest
(`packs/smt-z3-cvc5/manifest.json`) declares the pack license as `MIT`
(reflecting the z3 distribution it bundles) and carries the z3 LICENSE text
sha256.

The cvc5 `--no-gpl` build option (which produces a modified-BSD-only binary)
exists upstream, but the *published PyPI wheel* does not expose it and ships
the GPL license texts; building a GPL-free cvc5 from source is out of scope for
a pre-Alpha pack and would reintroduce a native build step the SRL
reproducibility posture avoids.

## GPL components of cvc5

The cvc5 `COPYING` document names the libraries whose inclusion makes a cvc5
binary GPLv3-covered:

- **GLPK** (GNU Linear Programming Kit) — GPLv3. cvc5 optionally links a
  modified fork (`glpk-cut-log`). A cvc5 binary linked against GLPK is a GPLv3
  combined work.
- **CryptoMiniSat** — listed as an optional dependency, but under a permissive
  license (`minisat-LICENSE` family), so it does *not* GPL-contaminate a
  build. Not a blocker on its own.

The published `cvc5==1.3.4` wheel ships `licenses/gpl-3.0.txt` and
`licenses/lgpl-3.0.txt`, consistent with a build that links GLPK (or at least
reserves the right to). Because the wheel metadata does not distinguish a
GPL-free build from a GPL-linked build, the SRL project treats the wheel as
GPL-bundled and excludes it. A future GPL-free cvc5 wheel (no `gpl-3.0.txt` in
its `license_files`, with a resolvable `license_expression`) would be
re-evaluated.

## Reversibility

Reversible. z3 is isolated behind `src/srl/packs/adapters/smt.py`: that module
is the only import site of `z3` in the SRL tree (asserted by an architecture
test in `tests/packs/test_smt_adapter.py`). Removing z3 is:

1. a `pyproject.toml` change (drop `z3-solver>=4.13.0` from
   `[project].dependencies`);
2. a `uv lock` to drop `z3-solver`;
3. replacing the body of `smt.py` with an alternative solver (or a
   hand-rolled procedure) behind the same typed surface (`check`,
   `SmtOutcome`, `SmtResult`, `SolverChoice`, `SmtError`).

Because the public surface is stable and is the only consumer, callers
(`wp41-gate.py`, future routers) would not need to change. The shipped corpus
and the restricted S-expression grammar are independent of the implementation.

## Evidence

- `pyproject.toml` declares `z3-solver>=4.13.0` in `[project].dependencies`;
  cvc5 is absent.
- `uv.lock` pins `z3-solver==5.0.0.0`; cvc5 is absent.
- `src/srl/packs/adapters/smt.py` is the sole `z3` import site; the
  architecture test `tests/packs/test_smt_adapter.py::TestZ3Isolation` asserts
  no other module imports it.
- `scripts/checks/wp41-gate.py` reports the resolved z3 version in its
  `GateReceipt/v1` evidence block and asserts (E41-05) the license inventory
  is clean (z3 MIT/allowed, cvc5 absent).
- `scripts/checks/license_inventory.py` classifies `z3-solver` as `MIT` /
  `allowed`; cvc5 is not in the locked closure.
- `docs/architecture/smt-pack.md` documents the operator grammar, the resource
  caps, the disagreement-preservation contract, and the honest ceiling.
- `packs/smt-z3-cvc5/manifest.json` declares the pack license as `MIT` with
  the z3 LICENSE text sha256; `packs/smt-z3-cvc5/LICENSE.txt` carries the z3
  MIT text.
