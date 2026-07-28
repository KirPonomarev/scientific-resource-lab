# The scientific object fabric (WP-B11)

This document describes the six scientific object types the SRL fabric produces,
the invariants that govern them, the prohibited collapses the contract prevents,
and the worked examples that ship as conformance vectors. It is the companion
to the JSON Schemas under `src/srl/contracts/schemas/v1/` and the Python model
under `src/srl/semantic/`.

> Everything here is an **admission** contract. A green validation result means
> a value satisfied the structural contract; it never means a scientific claim
> is *supported*. See `GOVERNANCE.md` for the evidence rules.

## Scope

WP-B11 introduces six object types, each with a JSON Schema 2020-12 document
and (where it carries a non-trivial invariant) a Python validator. They are the
first payload-bearing objects; the `ScientificObjectEnvelope/v1` from WP-B10
carries them. The fabric (`srl.semantic.fabric.mint_object`) wraps a
type-specific payload into a content-addressed envelope.

| Object type        | Schema                  | Python module            | Epistemic load |
|--------------------|-------------------------|--------------------------|----------------|
| `claim`            | `ScientificClaim/v1`    | `srl.semantic.claims`    | high           |
| `math_ir`          | `MathIR/v1`             | `srl.semantic.ir`        | low            |
| `symbol_table`     | `SymbolTable/v1`        | (schema only)            | low            |
| `condition_set`    | `ConditionSet/v1`       | (schema only)            | low            |
| `constant_ref`     | `ConstantRef/v1`        | (schema only)            | low            |
| `model_interface`  | `ModelInterface/v1`     | (schema only)            | low            |

## The six object types

### 1. MathIR/v1 — the restricted mathematical IR

`MathIR/v1` is a typed expression tree over a **restricted** OpenMath-style
content-dictionary allowlist. A node is one of:

- an **application** `{op: "<cd>.<name>", args: [...]}`;
- a **constant** `{const: "<decimal-string>"}`;
- a **variable** `{var: "<symbol-id>"}`.

The allowlist (`srl.semantic.ir.MATH_IR_ALLOWLIST`, 39 operators across 9
content dictionaries) is the single introspectable source of truth. It is
enumerated verbatim in the schema's `op.enum` and re-checked in
`srl.semantic.ir.validate_expression`. The accepted content dictionaries:

- **arith1** — `plus, minus, times, divide, power, root, abs, unary_minus`
- **relation1** — `eq, neq, lt, leq, gt, geq`
- **logic1** — `and, or, not, implies, equivalent`
- **set1** — `in, subset, union, intersect`
- **calculus1** — `diff, partialdiff, int`
- **linalg1** — `determinant, transpose, inverse`
- **nums1** — `pi, e, i, infinity` (nullary **symbols**, never floats)
- **fns1** — `lambda, domain, range`
- **stats1** — `mean, variance, covariance`

An operator outside the allowlist raises `UnsupportedOperatorError` (fail
reason `IR_UNSUPPORTED`). The error distinguishes the two failure modes:
an unknown *name* in a known cd (`arith1.log`) and an entirely unknown *cd*
(`foo1.plus`). Non-finite values are never carried: `infinity` is the nullary
symbol `nums1.infinity`, not a float; the constant channel is a decimal-string
policy value (`^-?[0-9]+(\.[0-9]+)?$`).

Two **resource guards** the schema cannot express are enforced in Python:
a depth limit of 64 and a node-count limit of 10000. Exceeding either raises
`IRResourceLimitError` (fail reason `CONTRACT_INVALID`).

### 2. ScientificClaim/v1 — a statement under epistemic discipline

`ScientificClaim/v1` is a typed scientific statement carrying:

- a structured `statement` (a subject/predicate/object triple, or a MathIR
  reference via inline `math` or a `math_ref` object_id);
- a `claim_class` on the epistemic ladder: `candidate_hypothesis`,
  `derived_result`, `established_law_reference`, `empirical_observation`,
  `definition`;
- a `claim_status` tracking investigation: `proposed`,
  `under_investigation`, `supported`, `refuted`, `inconclusive`;
- an `epistemic_source`: `operator`, `literature`, `derivation`, `experiment`;
- `support_refs`: the object_ids of supporting objects.

See **Invariants** below for the two critical rules.

### 3. SymbolTable/v1 — symbols and their units

`SymbolTable/v1` declares the symbols a MathIR expression or a
`ModelInterface` uses. Each symbol has a stable logical `symbol_id`, a
human-readable `name`, a `role` (`variable`, `parameter`, `constant`,
`function`, `index`), an optional `domain` (an inline MathIR set expression or
`null`), and an optional `unit_ref` (a `ConstantRef` `constant_id` or `null`).
The inline domain tree uses a structural shape; the allowlist is enforced on it
by `validate_expression`.

### 4. ConditionSet/v1 — the assumptions of a model

`ConditionSet/v1` is a set of conditions (assumptions) attached to a
`ModelInterface`. Each condition carries a `kind` (`domain`, `positivity`,
`boundedness`, `smoothness`, `stationarity`, `independence`, `custom`) and a
mathematical `expression` given either as a `math_ref` (object_id) to a
`MathIR/v1` object or as an inline `math` tree.

### 5. ConstantRef/v1 — a physical or mathematical constant

`ConstantRef/v1` references a constant from a named `source` (`CODATA2018`,
`CODATA2022`, `QUDT`, `UCUM`, `pack_local`). The `value` and optional
`uncertainty` are decimal strings (no exponent, no float coercion); the `unit`
is a UCUM string or a QUDT IRI; the `vintage` names the edition.

**Design decision (no separate unit-ref schema):** there is no `UnitRef/v1`
object. A unit is a single string field carried inline in `ConstantRef/v1` and
`SymbolTable/v1`, because SRL does not yet carry a unit-algebra object. Full
dimensional analysis is deferred to WP-E40; WP-B11 ships only a fixture-scoped
dimensional-equivalence check (the Newton identity `kg.m.s-2` ≡ `N`).

### 6. ModelInterface/v1 — a typed interface to a model

`ModelInterface/v1` exposes a scientific model: the `kind` (`ode`, `dae`,
`sde`, `pde_variational`, `discrete_map`, `statistical_model`, `composition`),
the `symbol_id`s it exposes (`state_variables`, `parameters`, `inputs`,
`outputs`), the `governing` equations as `MathIR/v1` references, an optional
`assumptions` reference to a `ConditionSet/v1`, and a `composition` list of
sub-model `interface_id`s (empty when the model is atomic).

## Invariants

Two epistemic invariants are encoded in `ScientificClaim/v1` **at both layers**
(the schema via `allOf`/`if-then`, and `srl.semantic.claims.validate` in
Python as defense in depth):

1. **An established law requires the literature and support.** A claim with
   `claim_class='established_law_reference'` MUST have
   `epistemic_source='literature'` AND a non-empty `support_refs`. An
   established physical law cannot be asserted from an operator's own
   derivation or experiment — it must be cited from the literature and backed
   by at least one supporting object.

2. **A candidate hypothesis cannot graduate to supported unsupported.** A claim
   with `claim_class='candidate_hypothesis'` and `claim_status='supported'`
   MUST have non-empty `support_refs`. A bare proposal cannot declare itself
   supported.

Both violations raise `ClaimInvariantError` (fail reason `CONTRACT_INVALID`)
with a named `invariant` (`established_law_requires_literature`,
`established_law_requires_support`, `candidate_supported_requires_support`).

The MathIR carries a third structural invariant: **the allowlist is closed**.
Any operator outside it is rejected at both layers with `IR_UNSUPPORTED`.

## Prohibited collapses

The contract exists to prevent two epistemic collapses the governance layer
cares about:

- **A candidate claim must not become an established law.** A `candidate_hypothesis`
  is a proposal awaiting evidence; an `established_law_reference` cites prior
  work. The established-law invariant makes the boundary load-bearing: you
  cannot type a hypothesis as a law, and you cannot assert a law without a
  citation. See the `n04` and `n05` negative vectors.
- **SAT/UNSAT is not empirical truth, and admission is not authorization.** A
  `supported` claim is still an admission, not a license: `grants_authority`
  is pinned to `false` by the envelope and the claim payload. A solver's
  SAT/UNSAT answer about a model's satisfiability is a property of the model
  under its `ConditionSet`, not a measurement of the world. The fabric never
  conflates the two: it only admits well-formed objects.

## Worked examples

The conformance vectors under `fixtures/conformance/object_fabric/` are worked
examples. The positive set (`p01`..`p07`) covers:

- `p01` Newton's second law `F = m*a` as a `MathIR/v1` (`relation1.eq`,
  `arith1.times`);
- `p02` Newton's second law as an `established_law_reference` claim WITH a
  `support_ref` and `epistemic_source=literature` (satisfies invariant 1);
- `p03` a bare `candidate_hypothesis` (proposed, unsupported);
- `p04` a `SymbolTable/v1` for the harmonic oscillator with units and
  positivity domains;
- `p05` a `ConstantRef/v1` for the Newton (force) unit, value as a decimal
  string, unit `kg.m.s-2`;
- `p06` a `ConditionSet/v1` of positivity assumptions on `k` and `m`;
- `p07` a `ModelInterface/v1` for the harmonic oscillator (`kind=ode`).

The negative set (`n01`..`n07`) covers the allowlist rejection (unknown name
and unknown cd), bool-as-int rejection, both claim invariants, and both
resource guards (depth and node-count). See
`fixtures/conformance/object_fabric/README.md` for the full catalogue.

## Acceptance gate

`scripts/checks/wp11-gate.py` runs four checks and emits a `GateReceipt/v1`:

- **B11-01** restricted OpenMath allowlist — unknown op and unknown cd rejected
  at the schema and Python layer (`IR_UNSUPPORTED`);
- **B11-02** fixture-scoped dimensional consistency — `kg.m.s-2` ≡ `N`
  accepted, `kg` vs `m` rejected;
- **B11-03** candidate claim cannot be typed as established physical law — the
  invariants hold at the schema and Python layer;
- **B11-04** schemas meta-valid and positive fixtures validate.

The gate runs under `make gate-wp11` and the `object-fabric-gate (WP-B11)` CI
job in `.github/workflows/ci.yml`.
