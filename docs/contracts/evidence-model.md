# Evidence assessment and run receipt model (WP-B13)

This document describes the four object types WP-B13 introduces — the
`EvidenceAssessment/v1` and the three `ScienceLab*Receipt/v1` documents — the
11 ORTHOGONAL evidence axes, the orthogonality rules that prevent an evidence
collapse (READY ≠ COMPUTED, COMPUTED ≠ VALIDATED, SAT/UNSAT ≠ empirical truth,
algorithm agreement ≠ independent replication, formal proof ≠ market
validation, exportable ≠ admitted), the monotonic-transition guard, and the
worked examples that ship as conformance vectors. It is the companion to the
JSON Schemas under `src/srl/contracts/schemas/v1/` and the Python model under
`srl/semantic/evidence.py`.

> Everything here is an **admission** contract. A green validation result means
> a value satisfied the structural contract; it never means a scientific claim
> is *supported*. See `GOVERNANCE.md` for the evidence rules.

## Scope

WP-B13 introduces four object types, each with a JSON Schema 2020-12 document
and a Python validator, placing a `ScientificClaim` on an honest evidence
ladder and recording the compute lineage that produced (or failed to produce)
its backing:

| Object type              | Schema                          | Python module            |
|--------------------------|---------------------------------|--------------------------|
| `evidence_assessment`    | `EvidenceAssessment/v1`         | `srl.semantic.evidence`  |
| `engine_receipt`         | `ScienceLabEngineReceipt/v1`    | `srl.semantic.evidence`  |
| `validation_receipt`     | `ScienceLabValidationReceipt/v1`| `srl.semantic.evidence`  |
| `run_receipt`            | `ScienceLabRunReceipt/v1`       | `srl.semantic.evidence`  |

All four are carried by the `ScientificObjectEnvelope/v1` from WP-B10.

## The 11 orthogonal evidence axes

An `EvidenceAssessment/v1` places a claim on **11 independent** evidence axes.
Each axis is a separate dimension of evidence; a movement on one axis **never
grants** a movement on another. This orthogonality is the load-bearing honesty
property of the evidence model. The axes, grouped by concern:

### The compute axis (did it run?)

| Axis                 | Members                                              | Honesty note                                                                    |
|----------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `capability_state`   | `unknown` `declared` `profiled` `ready`              | `ready` is NOT compute — it only means the capability is asserted.              |
| `exercise_level`     | `none` `import_probe` `runtime_probe` `actual_compute`| `import_probe` CANNOT yield `engine_execution=completed` (probe is not compute).|
| `engine_execution`   | `not_run` `failed` `completed`                       | `completed` is NOT validated — it only means the engine finished.               |

### The checking axis (was it checked?)

| Axis                 | Members                                              | Honesty note                                                                    |
|----------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `scientific_check`   | `not_applicable` `unchecked` `checked` `contradicted`| `failed` engine forbids `checked` (a failed run produced no output to check).   |
| `formal_check`       | `not_applicable` `unchecked` `checked` `proven`      | `proven` REQUIRES a verified certificate; `checked` is a SAT/UNSAT answer only. |
| `formal_scope`       | `none` `exact_statement` `restricted_model` `full_model`| A proven statement over a restricted model is honest about its scope.        |

### The empirical axis (stat + causal)

| Axis                   | Members                                              | Honesty note                                                                    |
|------------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `statistical_support`  | `not_applicable` `none` `weak` `moderate` `strong`   | INDEPENDENT of the formal axes: a formal proof never updates statistical support.|
| `causal_identification`| `not_applicable` `assumed` `partially_identified` `identified`| INDEPENDENT of the formal axes: a formal proof never updates causal identification.|

### The reproduction axis

| Axis                                    | Members                                              | Honesty note                                                                    |
|-----------------------------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `algorithmic_cross_engine_reproduction` | `not_applicable` `none` `reproduced` `divergent`     | Algorithm agreement is NOT independent replication; setting one never sets the other.|
| `independent_empirical_replication`     | `not_applicable` `none` `replicated` `contradicted`  | Set ONLY by its own evidence_refs (distinct assessor); algorithmic never sets it.|

### The authority axis

| Axis                    | Members                                              | Honesty note                                                                    |
|-------------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| `integration_authority` | `none` `proposal_only` `admitted_a1_sandbox` `admitted_a2`| `admitted_*` is RESERVED; SRL has no authority path. Defaults to `none`; only `proposal_only` is admissible.|

## Orthogonality rules

The orthogonality rules are enforced at BOTH the schema layer (`allOf` /
`if-then`) and the Python layer (`srl.semantic.evidence`, defense in depth).
Each violation raises `EvidenceAxisError` (fail reason `CONTRACT_INVALID`).

1. **probe is not compute** (`probe_not_compute`) —
   `exercise_level=import_probe` forbids `engine_execution=completed`. An
   import probe only checks the object imports/loads; it cannot have produced
   computed output. Enforced at the assessment level (schema + python) and the
   engine-receipt level (a probe receipt with non-empty `output_object_ids` is
   rejected).

2. **failed is not checked** (`failed_not_checked`) —
   `engine_execution=failed` forbids `scientific_check=checked`. A failed run
   produced no scientific output to check.

3. **formal is not empirical** (`formal_not_empirical`) — an `update_assessment`
   delta that moves a formal axis (`formal_check` / `formal_scope`) AND an
   empirical axis (`statistical_support` / `causal_identification`) in the SAME
   step is rejected. Each axis is set by its own evidence across separate
   updates; a formal proof never claims empirical support.

4. **algorithmic is not independent** (`algorithmic_not_independent`) — an
   `update_assessment` delta that moves both reproduction axes in the same step
   is rejected. A second engine agreeing is not an independent empirical study
   confirming the result; setting one never sets the other.

5. **authority path none** (`authority_path_none`) — the `admitted_a1_sandbox`
   and `admitted_a2` tiers are reserved; SRL has no authority path to set them.
   An operator cannot self-admit a claim beyond `proposal_only`.

## Prohibited collapses

The evidence model exists to prevent six honesty collapses the governance layer
cares about. Each is a forbidden equivalence between two evidence states:

| Collapse                                  | Why it is prohibited                                                                  |
|-------------------------------------------|---------------------------------------------------------------------------------------|
| `READY == COMPUTED`                       | `capability_state=ready` does not imply the engine ran (`engine_execution=completed`).|
| `COMPUTED == VALIDATED`                   | `engine_execution=completed` does not imply `scientific_check=checked`.               |
| `SAT/UNSAT == empirical truth`            | A SMT-style answer yields at most `formal_check=checked`; `proven` needs a certificate.|
| algorithm agreement == independent replication | A second engine agreeing is not an independent empirical study confirming the result.|
| formal proof == market validation         | A formal proof never updates `statistical_support` or `causal_identification`.        |
| exportable == admitted                    | `integration_authority=proposal_only` is an admission; `admitted_*` is reserved.      |

## The SMT is not proven rule

A `ScienceLabValidationReceipt/v1` with `formal_check=proven` REQUIRES a
non-null `formal_certificate_ref` — a verified, independently-checkable
certificate. The invariant (`proven_requires_certificate`) is encoded at both
layers:

- the schema's `allOf`/`if-then` requires `formal_certificate_ref` to be an
  object when `formal_check=proven`;
- `build_validation_receipt` rejects `proven` with a null certificate.

A SMT-style SAT/UNSAT answer without a verified certificate yields at most
`formal_check=checked`; `checked` is a valid, honest state. `proven` without a
certificate is a dishonest upgrade and is rejected.

## Monotonic transitions

`update_assessment(prior, delta, evidence_ref)` applies an axis-update delta to
a prior assessment, returning a new one whose `parents` carry the prior
`assessment_id`. Each moved axis transitions **monotonically**:

- an axis can move UP the ladder freely;
- an axis can move DOWN only with an explicit `regression_reason` (a non-empty
  string naming the contradicted/divergent evidence object). A downward move
  without a reason is a quiet loss of evidence the builder refuses (invariant
  `monotonic_transition`).

Off-ladder values (`not_applicable`, `contradicted`, `divergent`) are not on
the ladder, so a move to/from them is unconstrained. The ladder orderings are:

- `exercise_level`: `none` < `import_probe` < `runtime_probe` < `actual_compute`
- `engine_execution`: `not_run` < `failed` < `completed`
- `scientific_check`: `unchecked` < `checked`
- `formal_check`: `unchecked` < `checked` < `proven`
- `statistical_support`: `none` < `weak` < `moderate` < `strong`

## The run receipts

The three `ScienceLab*Receipt/v1` documents record the compute lineage:

- `ScienceLabEngineReceipt/v1` — a backend engine ran (or failed) for a run
  request. Carries the `exercise_level`, the `engine_execution` outcome, the
  resource cost, and any `output_object_ids`. The probe-is-not-compute rule
  forbids an `import_probe` receipt from carrying output objects.
- `ScienceLabValidationReceipt/v1` — an independent validator checked an engine
  run's output. Carries the `scientific_check` and `formal_check`, the
  `formal_certificate_ref` (required for `proven`), and the empirical axes
  re-asserted by the validator (independent of the formal check).
- `ScienceLabRunReceipt/v1` — ties an engine run and its optional validation
  into a single terminal outcome (`completed` / `failed` / `wait_capability` /
  `wait_resource` / `inconclusive`) with aggregate `resource_usage`.

## Authority states

`integration_authority` is the authority an assessment confers to integrate a
claim into downstream artifacts:

- `none` — no integration authority (the default).
- `proposal_only` — the claim may be cited as a proposal only. This is the
  highest tier admissible in this codebase.
- `admitted_a1_sandbox` — RESERVED. Admitted to a sandbox integration tier;
  SRL has no authority path to set it.
- `admitted_a2` — RESERVED. Admitted to a full integration tier; SRL has no
  authority path to set it.

There is no admission route in SRL. An operator cannot self-admit a claim
beyond `proposal_only`; the `admitted_*` tiers require an external authority
path this codebase does not provide. Setting them raises
`EvidenceAxisError` (`authority_path_none`).

## Honesty collapse assertions

`srl.semantic.evidence` exposes three executable honesty assertions a gate or
test can call on an already-built assessment:

- `assert_probe_not_compute(assessment)` — raises if a probe yielded computed.
- `assert_formal_not_empirical(assessment)` — verifies a formal raise did not
  cause an empirical raise (no-op pass for well-formed assessments; the builder
  blocked the combined update).
- `assert_algorithmic_not_independent(assessment)` — verifies algorithmic
  reproduction did not cause independent replication (no-op pass for
  well-formed assessments).

## Worked examples

The conformance vectors under `fixtures/conformance/evidence/` are worked
examples. The positive set (`p01`..`p05`) covers a probe-only assessment, an
actual-compute + checked + formal-checked assessment with a certificate, a
completed engine receipt, a proven validation receipt with a certificate, and a
completed run receipt. The negative set (`n01`..`n05`) covers the five
prohibited collapses: a probe with a completed engine, a formal proven without
a certificate, a reserved authority tier, a probe receipt claiming outputs, and
a formal update mutating a statistical axis. See
`fixtures/conformance/evidence/README.md` for the full catalogue.

## Acceptance gate

`scripts/checks/wp13-gate.py` runs four checks and emits a `GateReceipt/v1`:

- **B13-01** import probe cannot yield COMPUTED — rejected at the receipt
  (schema + python) and assessment (schema + python) levels (`probe_not_compute`);
- **B13-02** SMT-style answer yields at most CHECKED without verified certificate
  — `formal_check=proven` rejected without a certificate
  (`proven_requires_certificate`); `checked` allowed without one;
- **B13-03** formal axis cannot update empirical axis — a combined formal +
  empirical delta rejected (`formal_not_empirical`); each axis across separate
  updates is allowed;
- **B13-04** algorithmic reproduction differs from independent replication — a
  combined reproduction delta rejected (`algorithmic_not_independent`); reserved
  authority rejected (`authority_path_none`); positive/negative fixtures
  validate/reject as expected.

The gate runs under `make gate-wp13` and the `evidence-model-gate (WP-B13)` CI
job in `.github/workflows/ci.yml`. The `receipt-invariants` job in
`.github/workflows/contracts.yml` (backed by
`scripts/checks/receipt-invariants.py`) verifies every receipt schema pins
`canonical_writes=0` and `grants_authority=false` as `const`.
