# Public conformance corpus (WP-B15)

This directory holds the **thirty-task public conformance corpus**: a set of
synthetic, fully-public semantic tasks that pin the science-lab pipeline's
*admission* behavior. Each task is a directory `task-NN-<slug>/` containing a
`task.json` (`TaskSpec/v1`) and a `README.md` (one paragraph: what semantic
property it pins). The corpus is loaded by `srl.planning.corpus.load_corpus`
and executed by `scripts/checks/wp15-corpus.py` (the `public_conformance_corpus`
CI job).

> Everything here is an **admission** contract. A corpus PASS never means a
> scientific claim is supported. The honest outcome for the overwhelming
> majority of tasks is `WAIT_CAPABILITY`: the capability applies to the claim
> but no adapter ships in this codebase, so the router waits rather than
> fabricating one. See `docs/contracts/conformance-corpus.md` for the honesty
> statement and the full task table.

## The eight typed outcomes

Each task's `expected.outcome` is one of eight typed outcomes, each *executable*
against the current code (the runner in `srl.planning.corpus` reproduces it
exactly):

- `PASS` — the pipeline completed with no violation and no applicable profile
  waiting (e.g. a decimal/big-int IR constant that validates cleanly, or a
  fully-satisfied plan under a synthetic available catalog).
- `WAIT_CAPABILITY` — the capability applies but no adapter is available yet
  (the dominant, honest outcome for every unbuilt capability).
- `REJECT_CONTRACT` — the request/claim/path violated a structural contract
  (e.g. a bad `resource_class`, or a packet smuggling a local path).
- `REJECT_IR` — a MathIR operator is outside the closed allowlist
  (e.g. `arith1.sqrt` / `arith1.log` for domain violations).
- `REJECT_RESOURCE` — the summed SELECTED resource estimates exceed the caps
  (`WAIT_REMOTE_EXECUTOR`, never a silent local overflow).
- `REJECT_LICENSE` — a copyleft-licensed (GPL/AGPL/LGPL/SSPL/BUSL) adapter
  pack is refused at admission.
- `REJECT_AUTHORITY` — a packet whose `grants_authority` field is `true` is
  refused (the safety const is pinned `false` across every schema).

## Category coverage

The 30 tasks cover 18 declared categories (the counts are asserted by the
`public_conformance_corpus` check):

| Category | Count | Expected outcome |
|---|---|---|
| algebraic-identities | 3 | WAIT_CAPABILITY |
| units-and-dimensions | 2 | WAIT_CAPABILITY |
| domain-violations | 2 | REJECT_IR |
| exact-arithmetic | 2 | PASS |
| sat-unsat-unknown | 3 | WAIT_CAPABILITY |
| symbolic-law-false-positives | 2 | WAIT_CAPABILITY |
| topology | 2 | WAIT_CAPABILITY |
| spd-geometry | 2 | WAIT_CAPABILITY |
| causal-assumptions | 2 | WAIT_CAPABILITY |
| uncertainty | 1 | WAIT_CAPABILITY |
| ode-pde-interface | 2 | WAIT_CAPABILITY |
| model-composition | 1 | WAIT_CAPABILITY |
| literature-extraction | 1 | WAIT_CAPABILITY |
| proof-obligations | 1 | WAIT_CAPABILITY |
| resource-rejection | 1 | REJECT_RESOURCE |
| license-rejection | 1 | REJECT_LICENSE |
| public-redaction | 1 | REJECT_CONTRACT |
| bridge-authority | 1 | REJECT_AUTHORITY |

## Determinism

The corpus runner is a pure function of the task set: the same corpus yields
byte-identical outcomes and a byte-identical `CorpusReceipt/v1` across runs
(the receipt excludes the non-deterministic `duration_ms` from the digest). The
`tests/planning/test_corpus.py` suite asserts this two-run determinism.
