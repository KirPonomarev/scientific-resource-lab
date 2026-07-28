# P0 integration release (WP-E45)

This document describes what the P0 integration release **proves** and,
explicitly, what it **does not prove**. It is the companion to the
`scripts/checks/wp45-gate.py` acceptance gate and the
`tests/integration/test_p0_end_to_end.py` integration suite.

## Scope

The P0 integration release is the **Phase E capstone**. It wires the four P0
packs — units (WP-E40), smt (WP-E41), ripser (WP-E42), pyriemann (WP-E43) —
into the fabric alongside the knowledge sources (WP-E44), the planning stack
(classifier → router → planner), the typed evidence model (WP-B13), the
catalog snapshot (C24), and the static evidence portal (WP-F52). The release
gate (`IntegrationReceipt/v1`) runs six checks (E45-01..E45-06) and the
integration suite pins the per-stage invariants.

The release does **not** ship a scientific backend for any of the 15 capability
profiles against real data. The shipped catalog still marks every adapter
`future` / `remote_required`; the integration runs are bounded synthetic
conformance cases, not empirical studies.

## What the integration proves

### 1. The P0 packs are real and importable (E45-01)

Each P0 pack adapter imports cleanly and its typed surface resolves:
`parse_unit` / `convert` / `Dimension` (units); `check` / `SmtOutcome` /
`SmtResult` / `SolverChoice` (smt); `compute_persistence` /
`PersistenceResult` / `long_lived_classes` (ripser); `riemannian_mean` /
`log_euclidean_mean` / `distance` / `Metric` (pyriemann). The pinned dependency
versions (pint, z3, ripser, pyriemann, numpy, scipy) are published in the
receipt. This is the `exercise_level=runtime_probe` rung.

### 2. Each pack runs a real bounded compute (E45-02)

Each executable P0 pack runs ONE real compute on synthetic input and the
observed output matches its golden:

- **units** — `convert("1", "kg*m/s^2", "N")` yields the exact decimal
  identity `"1"` (no float artefact; the conversion renders through
  `decimal.Decimal`).
- **smt** — a SAT formula (`x + 1 > 0`) decides `sat` with a witness; an UNSAT
  formula (`x > 5 ∧ x < 5`) decides `unsat`.
- **ripser** — a synthetic unit circle produces exactly one long-lived H1 class
  above threshold, with the dominant persistence matching the golden.
- **pyriemann** — the log-Euclidean mean of two commuting diagonal SPD matrices
  matches the closed-form element-wise geometric mean within `1e-9`.

This is the `exercise_level=actual_compute` rung: real compute happened, the
wiring is sound.

### 3. Each pack completes ≥5 distinct measured runs (E45-03)

Each executable P0 pack completes at least five DISTINCT real-compute runs
(different inputs). Each run publishes a REAL measurement triple:

- `wall_seconds` — the monotonic-clock elapsed time of the compute;
- `rss_bytes` — the process resident set size read from
  `resource.getrusage(RUSAGE_SELF).ru_maxrss` after the compute;
- `expanded_bytes` — the byte length of the canonical-JSON encoding of the
  result.

Every field is read off the running process; nothing is hardcoded. The runs are
distinct (different unit identities, different smt formulas, different point
clouds, different SPD matrices), so this is not five copies of one number. Wall
is non-negative and finite across the batch; rss and expanded_bytes are
non-negative.

### 4. The catalog seal is deterministic (E45-04)

Building the capability catalog snapshot from the registry seed twice yields an
identical `snapshot_id`, `merkle_root`, and canonical byte encoding. The seal
is a pure function of the entries (independent of build time and dynamic
location state), so two agents building over the same entries compute the same
identity. The snapshot never grants authority (`grants_authority=false`).

### 5. The end-to-end slice composes (E45-05)

The synthetic end-to-end slice — claim → classify/plan → real bounded run
(units conversion) → engine + validation receipts → demo portal page —
succeeds. The resulting receipts carry `exercise_level=actual_compute` and
`engine_execution=completed`, the validation receipt carries
`scientific_check=checked` but `formal_check=unchecked` (a units conversion is
not a formal proof), and the evidence assessment pins
`integration_authority=none`. The demo portal accepts the synthetic object and
renders the canonical page set.

### 6. No overclaim (E45-06)

No integration evidence object claims `formal_check=proven` without a verified
certificate. The smt pack publishes `FORMAL_CHECK_CEILING=checked` (a SAT/UNSAT
answer is never promoted to `proven`); the units/ripser/pyriemann packs have no
formal-verification surface. The overclaim scan asserts the receipts the gate
mints never carry `proven`, and that `integration_authority` is pinned `none`.

## What the integration does NOT prove

### 1. It does not prove any scientific claim

The integration runs are bounded synthetic conformance cases. A PASS on the
gate means the wiring is sound and the measurements are real; it does **not**
mean a scientific result is supported. The dominant outcome for any real claim
routed against the shipped catalog is `WAIT_CAPABILITY` (no adapter ships), and
the integration assessment pins `integration_authority=none`.

### 2. It does not ship a scientific backend

The shipped catalog marks every adapter `future` / `remote_required`. No
scientific backend runs against real data in this release. A future WP that
lands a real adapter flips the catalog entry to `available`; until then, every
applicable profile waits honestly.

### 3. It does not prove formal correctness

The smt pack's `FORMAL_CHECK_CEILING` is `checked`, not `proven`. A SAT/UNSAT
answer yields at most `checked`; `proven` requires an independently checked
certificate (an unsat core verified by replay, or a proof object checked by a
trusted checker), which this release does not implement. The overclaim scan
(E45-06) enforces this.

### 4. The measurements are not benchmarks

The `wall_seconds` / `rss_bytes` / `expanded_bytes` triple is a REAL
measurement of a single run on the host that executed the gate, not a
benchmark. The numbers vary across hosts and runs; they are published so a
reviewer can confirm the runs are distinct and the outputs are real, not to
compare performance. The gate enforces only that each measurement is
non-negative, finite, and read off the process.

### 5. It does not grant integration authority

`integration_authority` is pinned `none` across every P0 integration receipt
and assessment. An actual-compute run does not grant authority to integrate a
claim; the reserved `admitted_a1_sandbox` / `admitted_a2` tiers remain
unreachable (there is no admission route in this codebase).

## Gate runtime budget

The gate targets `< 300s` wall (enforced by a hard guard in
`scripts/checks/wp45-gate.py`). The measured corpus on commodity hardware
completes in single-digit seconds (the published `gate_wall_seconds` is
typically ~0.2s); the 300s budget absorbs CI runner variance and the
five-distinct-runs-per-pack measurement batch. The CI job
(`p0-integration-gate (WP-E45)`) has a 30-minute timeout, which is a generous
envelope over the measured corpus (the timeout comment in
`.github/workflows/integration.yml` documents the justification).

## Honesty model

The load-bearing property of the P0 integration release is that **every
measurement is real and every claim is honest**:

- the `exercise_level` axis records what actually happened (`runtime_probe` for
  the import check, `actual_compute` for the real runs);
- the `formal_check` axis never exceeds `checked` without a verified
  certificate;
- the `integration_authority` axis is pinned `none`;
- `grants_authority` is `false` on every receipt, assessment, plan, and
  snapshot the release mints.

A green gate never means a scientific claim is supported. See
`docs/contracts/evidence-model.md` for the evidence axes and
`GOVERNANCE.md` for the authority rules.
