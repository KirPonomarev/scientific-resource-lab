# Transformation receipt + adapter profile conformance vectors (WP-B12)

This directory holds the conformance vectors for the SRL transformation receipts
and adapter semantic profiles (`srl.semantic.transforms`,
`srl.semantic.adapter_profiles`). Each positive vector is a JSON document that
MUST validate against its named schema (and pass the Python validator). Each
negative vector is a document the transform/profile machinery MUST reject, with
the validator, exception, and fail reason named in its `expected_error.json`.

Positive vectors (`p01`..`p03`) cover the two conversion classes and the
profile that drives a lossy projection:

- `p01` `TransformationReceipt` (LOSSLESS) — a normalize step binding Newton's
  second law `F = m*a` to itself. `source_object_id == target_object_id`
  because a lossless step yields a byte-equal tree; `introduced_assumptions`
  and `dropped_features` are both empty (the LOSSLESS invariant).
- `p02` `AdapterSemanticProfile` — a deterministic, offline, Apache-2.0 solver
  backend that supports `arith1.plus/minus/times` and `relation1.eq` and
  declares `behavior=drop` for `calculus1.diff` (no symbolic differentiation).
  `supported_cds` is a subset of `MATH_IR_ALLOWLIST`.
- `p03` `TransformationReceipt` (LOSSY_EXPLICIT) — the receipt produced by
  projecting `calculus1.diff(x)` onto the `p02` profile (which drops
  `calculus1.diff`). The receipt binds `adapter_profile_ref` (the `p02`
  `profile_id`) and `pack_hash` (the `p02` `pack_ref` digest), drops
  `calculus1.diff`, and introduces the matching assumption.

Negative vectors (`negative/n01`..`negative/n03`) cover the three prohibited
collapses the honesty rules prevent:

- `n01` LOSSLESS claims a dropped feature — a receipt with
  `conversion_class=LOSSLESS` and `dropped_features=['calculus1.diff']` ->
  `CONTRACT_INVALID` (invariant `lossless_requires_no_loss`, enforced at the
  schema `allOf`/`if-then` layer and the Python layer).
- `n02` projection reject — projecting a tree carrying `calculus1.diff` onto a
  profile declaring `behavior=reject` for it -> `IR_UNSUPPORTED`
  (`UnsupportedFeatureError`); the op and its cd are named on the error.
- `n03` profile op outside the allowlist — a profile claiming support for
  `transc1.exp` (outside `MATH_IR_ALLOWLIST`) -> `CONTRACT_INVALID` (invariant
  `supported_op_outside_allowlist`; the allowlist is closed).

The check script `scripts/checks/wp12-gate.py` validates every positive vector
against its schema (and round-trips it through the Python validator) and every
negative vector against the named validator, emitting a `GateReceipt/v1`
receipt. See `docs/contracts/transformations.md` for the conversion classes and
the honesty rules.
