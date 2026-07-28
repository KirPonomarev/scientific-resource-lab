# Public conformance corpus (WP-B15)

This document describes the **thirty-task public conformance corpus**: a set of
synthetic, fully-public semantic tasks that pin the science-lab pipeline's
*admission* behavior. The corpus lives under `fixtures/conformance/corpus/`
(each task a `task-NN-<slug>/` directory with a `task.json` `TaskSpec/v1` and a
one-paragraph `README.md`); it is loaded by `srl.planning.corpus.load_corpus`
and executed by `scripts/checks/wp15-corpus.py` (the `public_conformance_corpus`
CI job in `contracts.yml`, also `make corpus`).

> Everything here is an **admission** contract. A corpus PASS never means a
> scientific claim is *supported*. The honest outcome for the overwhelming
> majority of tasks is `WAIT_CAPABILITY`: the capability applies to the claim
> but no adapter ships in this codebase, so the router waits rather than
> fabricating one. See `GOVERNANCE.md` and `docs/architecture/router-planner.md`.

## What the corpus is for

The corpus is a **public, deterministic regression net** for the routing and
admission layer. Each task is a tiny, self-contained scientific intent (an
algebraic identity, a domain violation, a resource-bound overflow, …) with a
declared `expected.outcome`. The runner executes the task against the *real*
pipeline (classifier → router → planner) and the *real* validators (the MathIR
allowlist, the artifact-ref contract, the schema consts) and records the typed
outcome the pipeline genuinely produces. A task PASSES when the pipeline's
actual outcome equals the task's expected outcome.

Because the runner is a pure evaluation with no I/O, the corpus is byte-stable:
two runs produce identical outcomes and an identical `CorpusReceipt/v1`. This
makes a corpus regression (a routing change that flips an outcome) immediately
visible in CI.

## The eight typed outcomes

Each task's `expected.outcome` is one of seven task outcomes (the eighth,
`MISMATCH`, is an internal runner sentinel for a failed comparison, never a
task's expected outcome):

| Outcome | Meaning | How it is produced |
|---|---|---|
| `PASS` | The pipeline completed with no violation and no applicable profile waiting. | A clean IR constant (decimal / big-int), or a fully-admitted plan under a synthetic available catalog. |
| `WAIT_CAPABILITY` | The capability applies but no adapter is available yet. | An applicable profile routes `WAIT_CAPABILITY` against the shipped (adapterless) catalog. **The dominant, honest outcome.** |
| `REJECT_CONTRACT` | The request / claim / packet violated a structural contract. | A bad `resource_class`, a non-portable path, or a packet smuggling a local path. |
| `REJECT_IR` | A MathIR operator is outside the closed allowlist. | `validate_expression` raises `UnsupportedOperatorError` (e.g. `arith1.sqrt`, `arith1.log`). |
| `REJECT_RESOURCE` | The summed SELECTED resource estimates exceed the caps. | `build_plan` raises `ResourceAdmissionError` (`WAIT_REMOTE_EXECUTOR`). |
| `REJECT_LICENSE` | A copyleft-licensed adapter pack is refused. | The corpus copyleft-refusal policy (GPL/AGPL/LGPL/SSPL/BUSL). |
| `REJECT_AUTHORITY` | A packet whose `grants_authority` is `true` is refused. | The authority invariant (`grants_authority` is pinned `false`). |

## Honesty statement (load-bearing)

**`WAIT_CAPABILITY` is the correct, honest outcome for an unbuilt capability.**
No scientific backend (CAS, TDA, SMT, ODE, PDE, causal, uncertainty, literature,
composition) ships in this codebase — the shipped catalog
(`src/srl/planning/catalog_data.json`) marks every adapter `future` or
`remote_required`. So every task that engages a scientific capability routes
`WAIT_CAPABILITY`: the router refuses to fabricate a local adapter for a
capability that does not exist. A future WP that lands a real adapter flips the
catalog entry to `available`; until then, the router waits honestly.

**A corpus PASS never means scientific validation.** `PASS` appears only on the
two exact-arithmetic tasks (a decimal constant and a big-integer constant that
validate cleanly against the IR's decimal-string policy, with no capability
engaged) — it means *the structural contract admitted and nothing waited*, not
that a scientific claim was verified. The corpus pins admission behavior, not
scientific truth.

**The typed rejections are genuinely raised by the contract layer**, not
simulated: `REJECT_IR` is a real `UnsupportedOperatorError` from the closed
allowlist; `REJECT_RESOURCE` is a real `ResourceAdmissionError`; `REJECT_CONTRACT`
is a real `ArtifactRefError` / `ContractError`; `REJECT_AUTHORITY` is the real
`grants_authority=false` schema const. `REJECT_LICENSE` is the one corpus-level
policy (the codebase does not yet ship a standalone license validator); it is
documented in `srl/planning/corpus.py` as the single source of truth and will
migrate to a dedicated validator in a future WP.

## The thirty tasks

| # | Task | Category | Expected | What it pins |
|---|---|---|---|---|
| 01 | algebraic-distributivity | algebraic-identities | `WAIT_CAPABILITY` | distributivity engages `algebra_exact`; no CAS adapter → honest wait |
| 02 | algebraic-power-rule | algebraic-identities | `WAIT_CAPABILITY` | power rule engages `algebra_exact`; no adapter → wait, no fabricated proof |
| 03 | algebraic-exact-rational | algebraic-identities | `WAIT_CAPABILITY` | exact rational engages `algebra_exact`; no adapter → wait, no float approx |
| 04 | units-si-coherence | units-and-dimensions | `WAIT_CAPABILITY` | SI coherence engages symbolic+uncertainty; no unit adapter → wait |
| 05 | units-dimension-mismatch | units-and-dimensions | `WAIT_CAPABILITY` | dimension mismatch engages `algebra_exact`; no unit algebra → wait |
| 06 | domain-sqrt-negative | domain-violations | `REJECT_IR` | `arith1.sqrt` outside the allowlist → refused structurally |
| 07 | domain-log-nonpositive | domain-violations | `REJECT_IR` | `arith1.log` outside the allowlist → refused structurally |
| 08 | exact-decimal-preservation | exact-arithmetic | `PASS` | `0.1` preserved as a decimal string; IR validates cleanly |
| 09 | exact-integer-overflow-free | exact-arithmetic | `PASS` | `100!` carried overflow-free as a decimal string |
| 10 | sat-linear-integer | sat-unsat-unknown | `WAIT_CAPABILITY` | linear SAT engages nonlinear-constraint; z3 `future` → wait |
| 11 | sat-unsat-contradiction | sat-unsat-unknown | `WAIT_CAPABILITY` | UNSAT engages nonlinear-constraint; z3 `future` → wait |
| 12 | sat-unknown-undecidable | sat-unsat-unknown | `WAIT_CAPABILITY` | UNKNOWN engages nonlinear-constraint; z3 `future` → wait |
| 13 | law-fma-misbound-variable | symbolic-law-false-positives | `WAIT_CAPABILITY` | F=ma misbind engages symbolic-law; no adapter → never ratified |
| 14 | law-conservation-overreach | symbolic-law-false-positives | `WAIT_CAPABILITY` | overreach engages symbolic-law; no adapter → never ratified |
| 15 | topology-circle-h1-golden | topology | `WAIT_CAPABILITY` | circle H1 engages `geometry_tda`; ripser `future` → wait |
| 16 | topology-two-component-h0 | topology | `WAIT_CAPABILITY` | two-component H0 engages `geometry_tda`; ripser `future` → wait |
| 17 | spd-valid-distance | spd-geometry | `WAIT_CAPABILITY` | SPD distance engages geometry+optimization; no adapter → wait |
| 18 | spd-non-spd-rejection | spd-geometry | `WAIT_CAPABILITY` | non-SPD engages geometry+algebra; no adapter → never silently accepted |
| 19 | causal-confounded-naive | causal-assumptions | `WAIT_CAPABILITY` | confounded estimate engages `causal_time_series`; no adapter → wait |
| 20 | causal-identified-backdoor | causal-assumptions | `WAIT_CAPABILITY` | backdoor engages `causal_time_series`; no adapter → wait |
| 21 | uncertainty-posterior-interval | uncertainty | `WAIT_CAPABILITY` | posterior engages `uncertainty`; no adapter → wait |
| 22 | ode-harmonic-oscillator | ode-pde-interface | `WAIT_CAPABILITY` | oscillator engages ODE+dynamics; ODE `remote_required` → wait |
| 23 | pde-variational-stub | ode-pde-interface | `WAIT_CAPABILITY` | PDE weak form engages PDE+dynamics; no adapter → wait |
| 24 | composition-two-component-dag | model-composition | `WAIT_CAPABILITY` | composition engages `model_composition`+components; no adapter → wait |
| 25 | literature-citation-metadata | literature-extraction | `WAIT_CAPABILITY` | citation engages literature+extraction; both `remote_required` → wait |
| 26 | proof-unproven-stays-checked | proof-obligations | `WAIT_CAPABILITY` | unproven obligation engages proof profile; no adapter → never promoted |
| 27 | resource-over-exception-caps | resource-rejection | `REJECT_RESOURCE` | heavy SELECTED plan exceeds exception caps → `WAIT_REMOTE_EXECUTOR` |
| 28 | license-gpl-pack-refused | license-rejection | `REJECT_LICENSE` | GPL-licensed pack refused at admission (copyleft policy) |
| 29 | redaction-local-path-refused | public-redaction | `REJECT_CONTRACT` | packet smuggling `/Users/` path refused (public boundary) |
| 30 | authority-grants-authority-refused | bridge-authority | `REJECT_AUTHORITY` | packet with `grants_authority=true` refused (authority invariant) |

## Outcome distribution

The corpus resolves to the following outcome distribution (asserted by
`tests/planning/test_corpus.py`):

- `WAIT_CAPABILITY` — 22 tasks (every unbuilt scientific capability)
- `REJECT_IR` — 2 tasks (the two domain violations)
- `PASS` — 2 tasks (the two exact-arithmetic constants)
- `REJECT_RESOURCE` / `REJECT_LICENSE` / `REJECT_CONTRACT` / `REJECT_AUTHORITY` — 1 each

This is exactly what the plan means by "P0 executes 10–12 tasks; future-only
profiles produce exact `WAIT_CAPABILITY`": the executable outcomes against the
current code are routing decisions and validation rejections, and the corpus
makes each one precise and pinned.

## The runner

`srl.planning.corpus` provides:

- `load_corpus(dir) -> list[TaskSpec]` — load every `task.json` under a directory;
- `run_task(task, catalog=None, policy=None) -> TaskOutcome` — run one task
  through the pipeline (pure, no I/O; maps every pipeline exception to the
  matching typed rejection outcome);
- `verdict(task, outcome) -> Verdict` — compare expected vs actual, with a
  typed `MISMATCH` reason on a divergence;
- `run_corpus(tasks) -> (outcomes, verdicts)` — convenience wrapper.

The runner's resolution order matches the pipeline's own: license / packet /
IR admission checks fire before routing, then routing decides `WAIT_CAPABILITY`
vs `PASS`. This keeps the outcomes deterministic and independent of catalog
state for the rejection families.

## Acceptance

WP-B15 is gated by `scripts/checks/wp15-corpus.py` (the `public_conformance_corpus`
CI job, `make corpus`) and `tests/planning/test_corpus.py`:

- **30/30 matches** — every task's expected outcome is reproduced exactly;
- **category coverage** — the observed category counts match the manifest;
- **outcome enum** — every expected outcome is a member of the seven-value enum;
- **determinism** — two runs produce byte-identical outcomes and receipt.
