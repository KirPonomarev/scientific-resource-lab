# Transformation receipts and adapter semantic profiles (WP-B12)

This document describes the two object types WP-B12 introduces — the
`TransformationReceipt/v1` and the `AdapterSemanticProfile/v1` — the conversion
classes that carry the honest cost of a transformation step, the honesty rules
that prevent a lossy step from upgrading evidence, and the worked examples that
ship as conformance vectors. It is the companion to the JSON Schemas under
`src/srl/contracts/schemas/v1/` and the Python model under
`srl/semantic/transforms.py` and `srl/semantic/adapter_profiles.py`.

> Everything here is an **admission** contract. A green validation result means
> a value satisfied the structural contract; it never means a scientific claim
> is *supported*. See `GOVERNANCE.md` for the evidence rules.

## Scope

WP-B12 introduces two object types, each with a JSON Schema 2020-12 document
and a Python validator, carrying the lineage and the cost of deriving one
scientific object from another:

| Object type              | Schema                       | Python module                  |
|--------------------------|------------------------------|--------------------------------|
| `adapter_profile`        | `AdapterSemanticProfile/v1`  | `srl.semantic.adapter_profiles`|
| `transformation_receipt` | `TransformationReceipt/v1`   | `srl.semantic.transforms`      |

Both are carried by the `ScientificObjectEnvelope/v1` from WP-B10
(`object_type` `adapter_profile`, `transformation_receipt`).

## The two object types

### 1. AdapterSemanticProfile/v1 — a backend adapter's contract

An `AdapterSemanticProfile/v1` is the contract between a `MathIR/v1` expression
and a concrete computational backend (a solver, a CAS shim, a numeric kernel).
It declares:

- `adapter_id` — a stable logical identifier for the backend.
- `pack_ref` — an `ArtifactRef/v1` pointing at the versioned, content-addressed
  adapter pack (the executable bytes this profile governs). The `digest` is
  authoritative; the path is a portable hint.
- `supported_cds` — the subset of `MATH_IR_ALLOWLIST` the adapter accepts, each
  a `<cd>.<name>` pair. **MUST be a subset of the allowlist** (the allowlist is
  closed); an entry outside it is rejected at profile-validation time
  (`CONTRACT_INVALID`, invariant `supported_op_outside_allowlist`). A subset
  (not the whole allowlist) is normal and expected: a solver need not support
  `calculus1`, for example.
- `unsupported_features` — per-operator behavior declarations for operators the
  profile does NOT support. Each entry names a `feature` (an exact `<cd>.<name>`
  or a cd-level wildcard `<cd>.*`) and a `behavior`: `reject` (hard stop,
  `IR_UNSUPPORTED`), `approximate` (recorded as a lossy assumption), or `drop`
  (silently elided, recorded as a dropped feature).
- `input_contract` / `output_contract` — schema references governing the
  adapter's input/output shapes.
- `deterministic` — whether the adapter's output is a pure function of its
  input. A lossy projection through a non-deterministic adapter is a stronger
  claim of evidence.
- `network_access` — `none` / `allowlisted` / `required`. A projection through a
  network-required adapter cannot be claimed as a closed-form derivation.
- `license_spdx` — the SPDX license of the adapter pack.

The profile carries the two safety consts (`canonical_writes=0`,
`grants_authority=false`). A profile never grants authority to run its adapter;
that is a governance decision.

### 2. TransformationReceipt/v1 — honest lineage between two objects

A `TransformationReceipt/v1` proves one scientific object was derived from
another by a named transformation. It binds:

- `source_object_id` → `target_object_id` — the input and output object ids.
  For a lineage chain, a downstream receipt's `source_object_id` equals the
  upstream receipt's `target_object_id`.
- `transform_kind` — `normalize`, `project`, `convert_units`, `restrict_domain`,
  `serialize`, `deserialize`, `approximate`.
- `conversion_class` — the **honest cost** of the step (see below).
- `introduced_assumptions` — assumptions the step introduced (each
  `{assumption, justification}`).
- `dropped_features` — features (operators) the step dropped or replaced with an
  approximation.
- `adapter_profile_ref` / `pack_hash` — for a backend projection, the profile's
  `profile_id` and the pack content hash binding the projection to a specific,
  reproducible adapter; `null` for a transformation not bound to a backend
  adapter.

## Conversion classes — the honest cost

Every transformation step carries a `conversion_class` placing it on the honesty
ladder:

| Class                    | Meaning                                                                 | Who may set it                 |
|--------------------------|-------------------------------------------------------------------------|--------------------------------|
| `LOSSLESS`               | No information lost. Target is a faithful re-expression of the source.  | Producer (requires empty assumptions + dropped features) |
| `LOSSY_EXPLICIT`         | The producer declares a loss (an assumption or a dropped feature).      | Producer                       |
| `LOSSY_IMPLICIT_DETECTED`| A detector found a loss the producer did not declare.                   | **Detector only**              |

### The critical invariant

**`LOSSLESS` requires `introduced_assumptions=[]` AND `dropped_features=[]`.**
A lossy transformation that claims `LOSSLESS` is a dishonest upgrade of
evidence and is rejected at both layers:

- the schema encodes it via `allOf`/`if-then` (`maxItems: 0`);
- `srl.semantic.transforms.record_transformation` and
  `srl.semantic.transforms.validate` re-enforce it in Python as defense in depth
  (`TransformationInvariantError`, fail reason `CONTRACT_INVALID`, invariant
  `lossless_requires_no_loss`).

### Implicit loss is detector-only

`LOSSY_IMPLICIT_DETECTED` may **only** be produced by a detector — an
independent lineage auditor comparing two trees and finding a loss the producer
did not declare. The producer API (`record_transformation`) deliberately does
not expose this class; only the detector constructor
(`record_detected_loss`) produces it. A producer cannot bury an undetected loss.

## Honesty rules

1. **A lossy step never upgrades evidence.** A `LOSSY_*` receipt in an object's
   lineage means the object carries less evidence than its source. A later
   `LOSSLESS` step on the same object cannot wash the loss away: the lossy
   receipt stays in the chain. The conversion class of a step is a permanent
   property of the lineage, not a transient note.

2. **Introduced assumptions travel forever.** An `introduced_assumption` is part
   of the object's permanent provenance. It is carried in the receipt body and
   travels with the object down the lineage chain; a downstream agent that
   reads the object's lineage sees every assumption every step introduced.

3. **LOSSLESS is a claim the producer must be able to honor.** The producer API
   enforces the invariant: a `LOSSLESS` step with a non-empty assumption or
   dropped feature is rejected. If a step introduces an assumption or drops a
   feature, the producer must declare the step `LOSSY_EXPLICIT`.

4. **Implicit loss is detector-only.** A producer cannot set
   `LOSSY_IMPLICIT_DETECTED`; only an independent detector can. This makes the
   detector/producer separation load-bearing: a dishonest producer has no API
   to hide a loss as "detected".

## Projection lineage

`srl.semantic.transforms.project_to_backend(ir_tree, profile)` projects a
`MathIR/v1` tree onto an `AdapterSemanticProfile/v1`:

1. it validates the profile (an out-of-allowlist `supported_cds` raises at
   projection time);
2. it validates the input expression (allowlist + resource guards);
3. for every operator in the tree not in `supported_cds`, it consults the
   profile's declared `behavior`:
   - `reject` (or undeclared) → `UnsupportedFeatureError` (fail reason
     `IR_UNSUPPORTED`); the projection halts, no receipt is produced;
   - `approximate` / `drop` → the op is recorded as a dropped feature and the
     step is stamped `LOSSY_EXPLICIT`;
4. it binds `adapter_profile_ref` (the profile's `profile_id`) and `pack_hash`
   (the profile's `pack_ref` digest) so the projection is reproducible and
   auditable;
5. the receipt's `source_object_id` is the input tree's `ir_id` and its
   `target_object_id` is the projected tree's `ir_id` (identical for a lossless
   projection, since a lossless projection yields a byte-equal tree).

**Lineage chaining:** pass prior projection receipts via `parents` to chain
projections. A downstream projection's `source_object_id` equals the upstream
projection's `target_object_id`; the chain is linked by these ids, so an
object's lineage is recoverable by walking the receipts.

## Raw-eval prohibition

The MathIR is restricted precisely so that a scientific object is never
evaluated by feeding a string into a CAS/sympy/sage `eval` route.
`srl.semantic.transforms.assert_no_raw_eval_route()` introspects the
`srl.semantic` package and verifies no forbidden input route (`sympify`,
`sage_eval`, `eval`, `lambdify`, `sympy`, `sage`) is exposed on its public
surface. The restricted MathIR allowlist is the only evaluation route; a raw-eval
route would let a scientific object's content reach a CAS as a string, defeating
the allowlist. The WP-B12 gate (B12-04) and a unit test enforce this at every
change.

## Prohibited collapses

The contract exists to prevent two honesty collapses the governance layer cares
about:

- **A lossy step must not claim to be lossless.** The LOSSLESS invariant
  (`lossless_requires_no_loss`) makes the boundary load-bearing: a step that
  drops a feature or introduces an assumption cannot declare itself LOSSLESS,
  and a producer cannot bury an undetected loss (the implicit-loss class is
  detector-only). See the `n01` negative vector.
- **A backend projection must not pretend to be content-free.** A projection
  receipt binds the adapter profile and the pack hash, so a downstream agent
  can always see which backend produced a target and reproduce the step. An
  unsupported op hitting a `reject`-behavior profile halts the projection
  outright (`IR_UNSUPPORTED`); the source tree is never projected onto a
  rejecting backend. See the `n02` negative vector.

## Worked examples

The conformance vectors under `fixtures/conformance/transformations/` are
worked examples. The positive set (`p01`..`p03`) covers:

- `p01` a `LOSSLESS` `TransformationReceipt` binding Newton's second law
  `F = m*a` to itself under a normalize step (`source == target`, no
  assumptions, no dropped features);
- `p02` an `AdapterSemanticProfile` for a deterministic, offline, Apache-2.0
  solver backend that supports `arith1.plus/minus/times` and `relation1.eq`
  and declares `behavior=drop` for `calculus1.diff`;
- `p03` the `LOSSY_EXPLICIT` `TransformationReceipt` produced by projecting
  `calculus1.diff(x)` onto the `p02` profile (drops `calculus1.diff`, binds
  the adapter/pack hash).

The negative set (`n01`..`n03`) covers the three prohibited collapses: a lossy
step claiming LOSSLESS, a projection hitting `behavior=reject`, and a profile
claiming an op outside the MathIR allowlist. See
`fixtures/conformance/transformations/README.md` for the full catalogue.

## Acceptance gate

`scripts/checks/wp12-gate.py` runs four checks and emits a `GateReceipt/v1`:

- **B12-01** lossy conversion cannot claim LOSSLESS — rejected at the schema and
  Python layer (`lossless_requires_no_loss`);
- **B12-02** introduced assumption is explicit — a lossy step carries its
  introduced assumption in the receipt body; the producer API requires the
  declaration;
- **B12-03** backend projection binds adapter/pack hash — the projection binds
  `adapter_profile_ref` and `pack_hash`, lineage chains link source to prior
  target, and `behavior=reject` halts the projection with `IR_UNSUPPORTED`;
- **B12-04** raw sympify/sage_eval input route absent — the `srl.semantic`
  package exposes no raw-eval route, and the positive/negative fixtures
  validate/reject as expected.

The gate runs under `make gate-wp12` and the `transformations-gate (WP-B12)` CI
job in `.github/workflows/ci.yml`.
