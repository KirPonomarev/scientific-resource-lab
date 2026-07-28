# Scientific object fabric conformance vectors (WP-B11)

This directory holds the conformance vectors for the SRL scientific object
fabric (`srl.semantic`). Each positive vector is a JSON document that MUST
validate against its named schema (and pass the Python validator where one
exists). Each negative vector is a document the fabric MUST reject, with the
contract reason named in its `expected_error.json`.

Positive vectors (`p01`..`p07`) cover the six object types introduced in
WP-B11 plus a representative well-formed instance of each:

- `p01` `MathIR` — Newton's second law `F = m*a` as an allowlisted expression
  tree (`relation1.eq`, `arith1.times`).
- `p02` `ScientificClaim` — Newton's second law as an `established_law_reference`
  claim WITH a `support_ref` and `epistemic_source=literature` (satisfies the
  established-law invariant).
- `p03` `ScientificClaim` — a bare `candidate_hypothesis` (proposed,
  unsupported) — a hypothesis that has not graduated to supported.
- `p04` `SymbolTable` — the harmonic-oscillator symbols with units and
  positivity domains.
- `p05` `ConstantRef` — the Newton unit (force), value as a decimal string,
  unit in UCUM form (`kg.m.s-2`).
- `p06` `ConditionSet` — positivity assumptions on `k` and `m` (inline
  allowlist-compliant MathIR).
- `p07` `ModelInterface` — the harmonic oscillator (`kind=ode`) with state
  variables, parameters, a governing MathIR ref, and an empty composition list.

Negative vectors (`negative/n01`..`negative/n07`) cover the prohibited
collapses and resource guards:

- `n01` unknown operator — `arith1.log` (known cd, unknown name) -> `IR_UNSUPPORTED`.
- `n02` unknown content dictionary — `foo1.plus` (unknown cd) -> `IR_UNSUPPORTED`.
- `n03` bool-as-int in exponents — a `const: true` node -> `CONTRACT_INVALID`.
- `n04` established-law without literature source -> `CONTRACT_INVALID`.
- `n05` candidate-hypothesis with status `supported` and no `support_refs` ->
  `CONTRACT_INVALID`.
- `n06` IR depth bomb (depth > 64) -> `CONTRACT_INVALID`.
- `n07` IR node flood (> 10000 nodes, breadth-heavy, depth 2) ->
  `CONTRACT_INVALID`.

The check script `scripts/checks/wp11-gate.py` validates every positive
vector against its schema and every negative vector against the named
validator, emitting a `GateReceipt/v1` receipt. See
`docs/contracts/object-fabric.md` for the object-type and invariant catalogue.
