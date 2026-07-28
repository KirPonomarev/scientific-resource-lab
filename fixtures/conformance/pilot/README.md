# PilotSpec conformance vectors (WP-G60)

This directory holds the conformance vectors for the SRL retrospective pilot
specification (`srl.pilot.spec`, schema `PilotSpec/v1`). Each positive vector
is a JSON document that MUST validate against the schema (and pass the Python
const-false / holdout guards). Each negative vector is a document the pilot
machinery MUST reject, with the validator, exception, invariant, and fail
reason named in its `expected_error.json`.

## Provenance

Every digest in these vectors is **fully synthetic**: it is `sha256:` of a
deterministic synthetic seed string (e.g. `srl-pilot-synthetic-source-cloud-circle`),
not of any real artifact, and never of a path. No real data, no real
identifier, and no local or remote path appears anywhere in these fixtures.
The `pilot_id` of the positive vector is the real content-addressed id
(`sha256:` over the canonical encoding of the body without `pilot_id`), so the
fixture doubles as a determinism oracle: two independent agents that author
the same pilot compute the same `pilot_id`.

## Positive vectors

- `p01` `analog-retrospective` — a synthetic retrospective pilot over two
  synthetic source-artifact digests, a chronological 80/20 window, two metrics
  with decimal tolerances, two null generators (phase-randomized + block
  bootstrap), a seed policy, and the three safety consts pinned false. This is
  the shape a real operator's pilot takes after private paths are stripped to
  digests; it validates against the schema and freezes deterministically.

## Negative vectors (`negative/`)

- `n01` `status-promotion-allowed-true` — a `PilotSpec` with
  `status_promotion_allowed=true` -> `CONTRACT_INVALID` (invariant
  `pilot_safety_const`, enforced at the schema `const:false` layer and the
  Python `_validate_const_false` layer). A pilot cannot authorize promoting a
  claim's status.
- `n02` `holdout-materialization-marker` — a `PilotSpec` whose
  `preprocessing_scope` encodes a prospective-holdout materialization intent
  -> `CONTRACT_INVALID` (invariant `prospective_holdout_materialization`,
  enforced by `validate_holdout_free` in Python). A retrospective pilot reads
  already-extant data; materializing a prospective holdout crosses the
  integrity boundary. The marker is encoded as a value (not an extra field) so
  the spec is schema-valid and the holdout guard is the layer that rejects.

## Acceptance

`scripts/checks/wp60-gate.py` runs the four WP-G60 checks (G60-01..G60-04) and
emits a `GateReceipt/v1`. The positive vector validates and freezes
deterministically (G60-01); the two negative vectors are rejected with the
typed `CONTRACT_INVALID` fail reason and the named invariant (G60-02).
