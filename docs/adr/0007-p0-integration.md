# ADR 0007: P0 integration release gate

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-E45 (P0 integration release — Phase E capstone)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

WP-E40 through WP-E44 landed four P0 packs (units, smt, ripser, pyriemann) and
the knowledge source adapters, each behind its own acceptance gate
(`wp40-gate.py` .. `wp44-gate.py`) that proves the pack in isolation. The
Phase E capstone (WP-E45) must prove these packs **integrate** into the fabric
as a coherent, measured, honestly-claimed release: the packs compose with the
planning stack, the typed evidence model, the catalog snapshot, and the static
portal; and the integration evidence is measured (real wall/rss/expanded-bytes)
and honest (no overclaim).

The integration gate must answer four questions the per-pack gates do not:

1. Do the four P0 packs run together in one process without import/version
   conflicts (each pins a heavy native dependency: pint, z3, ripser, pyriemann
   over numpy/scipy)?
2. Does each pack complete enough distinct real-compute runs to publish a
   measured corpus (the plan gate requires "at least 5 distinct real-compute
   conformance runs per pack with measured wall/rss/expanded-bytes")?
3. Is the catalog seal deterministic across rebuilds (the content-addressed
   identity must be a pure function of the entries)?
4. Does the synthetic end-to-end slice compose, and does the resulting evidence
   stay honest (`exercise_level=actual_compute`, `formal_check≤checked`,
   `integration_authority=none`)?

## Decision

Ship a single WP-E45 acceptance gate (`scripts/checks/wp45-gate.py`) that emits
an `IntegrationReceipt/v1` with six checks, plus a
`tests/integration/test_p0_end_to_end.py` suite that pins the per-stage
invariants. The gate is the only integration-level proof in the release; the
per-pack gates remain the authority for each pack's isolated behaviour.

### E45-01 runtime probes

Each P0 pack adapter is imported and its typed surface is resolved
(`parse_unit`/`convert`, `check`/`SmtOutcome`, `compute_persistence`,
`riemannian_mean`/`distance`, etc.). The pinned dependency versions are
published. This is the `exercise_level=runtime_probe` rung: it catches an
import or version-pinning regression across the four native dependencies in a
single process.

### E45-02 actual-compute probes

Each executable pack runs ONE real bounded compute on synthetic input and the
observed output is compared against a golden: the exact decimal identity for a
coherent SI conversion; a SAT and an UNSAT decision; the circle's single
long-lived H1; the closed-form log-Euclidean mean of two commuting diagonal
SPD matrices. This is the `exercise_level=actual_compute` rung.

### E45-03 ≥5 distinct measured runs per pack

Each pack completes at least five DISTINCT real-compute runs (different
inputs). Each run publishes a REAL measurement triple — `wall_seconds`
(monotonic clock), `rss_bytes` (`resource.getrusage`), `expanded_bytes`
(canonical-JSON byte length of the result) — read off the process after the
compute. **No measurement is ever fabricated.** The runs are distinct so the
corpus is not five copies of one number. This satisfies the plan gate's "at
least 5 distinct real-compute conformance runs per pack with measured
wall/rss/expanded-bytes" requirement.

### E45-04 catalog seal determinism

The catalog snapshot is built twice from the registry seed and the
`snapshot_id`, `merkle_root`, and canonical bytes are asserted identical. This
proves the seal is a pure function of the entries (the content-addressed
identity is stable across rebuilds and immune to build-time / location-state
changes).

### E45-05 end-to-end pass

The synthetic slice — claim → classify/plan → real units conversion → engine +
validation receipts → demo portal page — is run end-to-end. The receipts
carry `exercise_level=actual_compute` and `integration_authority=none`; the
portal accepts the synthetic object and renders. This wires every P0 subsystem
together.

### E45-06 overclaim scan

No integration evidence claims `formal_check=proven` without a verified
certificate. The smt pack's `FORMAL_CHECK_CEILING` is asserted `≤ checked`;
the gate's own receipts are asserted `≠ proven`. `integration_authority` is
pinned `none`.

### Runtime guard

The gate enforces a hard 300s wall guard (the gate fails closed if its own
wall exceeds 300s). The measured corpus runs in single-digit seconds; the
budget absorbs CI variance.

## Alternatives considered

### 1. Re-run the per-pack gates as the integration proof (rejected)

The per-pack gates prove each pack in isolation; they do not prove the packs
compose in one process, do not publish a cross-pack measured corpus, and do
not exercise the end-to-end slice. A capstone gate that runs all four packs
and the planning/portal stack is needed for the integration claim.

### 2. Fabricate or estimate the measurement triple (rejected)

The plan gate requires REAL measurements. Hardcoding `wall_seconds` / `rss` /
`expanded_bytes` would be an overclaim (the numbers would not reflect any
actual run). The gate reads every measurement off the running process; the
runs are distinct so the corpus is genuine.

### 3. Promote the smt ceiling to `proven` (rejected)

A SAT/UNSAT answer yields at most `checked`. `proven` requires an
independently checked certificate (unsat-core replay or a checked proof
object), which this release does not implement. The overclaim scan (E45-06)
enforces the honest ceiling.

### 4. Grant integration authority on a clean integration run (rejected)

An actual-compute run does not grant integration authority. The reserved
`admitted_a1_sandbox` / `admitted_a2` tiers are unreachable (there is no
admission route in this codebase). `integration_authority` is pinned `none`.

## Consequences

- The P0 integration release has a single capstone gate (`make gate-wp45`) and
  a CI job (`p0-integration-gate (WP-E45)`) that must pass on every PR.
- The `IntegrationReceipt/v1` is the published evidence for the release; its
  measured corpus (20 runs: 5 per pack × 4 packs) is real and reproducible.
- The release does NOT ship a scientific backend, does NOT prove formal
  correctness, and does NOT grant integration authority. These non-claims are
  documented in `docs/architecture/p0-integration.md` ("What the integration
  does NOT prove").
- A future WP that lands a real adapter or a verified certificate will extend
  this gate (e.g. raise the smt ceiling to `proven` only after a certificate
  path ships); until then the honest ceilings hold.
