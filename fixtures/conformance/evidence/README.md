# Evidence assessment + science-lab run receipt conformance vectors (WP-B13)

This directory holds the conformance vectors for the SRL evidence assessment
and science-lab run receipts (`srl.semantic.evidence`). Each positive vector
is a JSON document that MUST validate against its named schema (and pass the
Python validator). Each negative vector is a document the evidence/receipt
machinery MUST reject, with the validator, exception, invariant, and fail
reason named in its `expected_error.json`.

Positive vectors (`p01`..`p05`) cover the four object types and the honest
growth of an assessment:

- `p01` `EvidenceAssessment` (probe-only) — `exercise_level=import_probe`,
  `engine_execution=not_run`. A probe only checks the object imports/loads; it
  cannot have produced computed output. This is the lowest-honesty starting
  point an assessment grows from.
- `p02` `EvidenceAssessment` (compute + checked + formal checked) —
  `exercise_level=actual_compute`, `engine_execution=completed`,
  `scientific_check=checked`, `formal_check=checked` (`exact_statement` scope),
  `integration_authority=proposal_only`. The axes are independent: the formal
  axis did not move the statistical/causal axes (each was set by its own
  evidence across separate updates).
- `p03` `ScienceLabEngineReceipt` (completed) — a completed `actual_compute`
  run that produced one output object, binding the `adapter_id` and `pack_ref`.
- `p04` `ScienceLabValidationReceipt` (proven + certificate) —
  `formal_check=proven` with a non-null `formal_certificate_ref` (a verified,
  independently-checkable certificate). `proven` REQUIRES the certificate;
  without it the receipt is rejected.
- `p05` `ScienceLabRunReceipt` (completed) — ties the completed engine run and
  its proven validation into a `terminal_status=completed` outcome with
  aggregate resource usage.

Negative vectors (`negative/n01`..`negative/n05`) cover the five prohibited
collapses the orthogonality rules prevent:

- `n01` probe with completed engine — an `EvidenceAssessment` with
  `exercise_level=import_probe` and `engine_execution=completed` ->
  `CONTRACT_INVALID` (invariant `probe_not_compute`, enforced at the schema
  `allOf`/`if-then` layer and the Python layer).
- `n02` formal proven without certificate — a `ScienceLabValidationReceipt`
  with `formal_check=proven` and a null `formal_certificate_ref` ->
  `CONTRACT_INVALID` (invariant `proven_requires_certificate`; a SMT-style
  answer without a verified certificate yields at most `checked`).
- `n03` reserved integration authority — an `EvidenceAssessment` with
  `integration_authority=admitted_a2` -> `CONTRACT_INVALID` (invariant
  `authority_path_none`; the `admitted_*` tiers are reserved and SRL has no
  authority path to set them).
- `n04` probe receipt claims outputs — a `ScienceLabEngineReceipt` with
  `exercise_level=import_probe` and a non-empty `output_object_ids` ->
  `CONTRACT_INVALID` (invariant `probe_not_compute`; an import probe produces
  no scientific output).
- `n05` formal update mutates statistical axis — an `update_assessment` delta
  moving a formal axis (`formal_check`) and an empirical axis
  (`statistical_support`) in the same step -> `CONTRACT_INVALID` (invariant
  `formal_not_empirical`; formal proof is not empirical truth).

The check script `scripts/checks/wp13-gate.py` validates every positive vector
against its schema (and round-trips it through the Python validator) and every
negative vector against the named validator, emitting a `GateReceipt/v1`
receipt. See `docs/contracts/evidence-model.md` for the 11 axes, the
prohibited collapses, and the authority states.
