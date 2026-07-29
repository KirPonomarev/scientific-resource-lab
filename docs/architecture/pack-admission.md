# Pack admission pipeline (WP-C23)

WP-C23 defines the linear admission pipeline that moves a scientific resource
pack from a freshly discovered upstream artifact to an admitted experimental
bundle. It is the control-plane layer above WP-C22 (manifest, extraction, and
materialization) and below execution: a pack is admitted only after provenance,
license, lock integrity, byte identity, and both runtime and actual-compute
probes have been recorded.

The pipeline is implemented in three modules:

- `srl.packs.receipts` — the `PackStageReceipt/v1` content-addressed receipt.
- `srl.packs.admission` — the linear nine-stage state machine and typed
  rejections.
- `srl.packs.builder` — deterministic construction of a
  `ResourcePackManifest/v1` from a declarative spec and a file tree.

## Admission stages

A pack moves through nine named stages in strict order. No stage is ever
inferred: a pack is at the stage of its most recent receipt, and the receipts
form an immutable append-only chain.

```text
DISCOVERED
  -> SOURCE_VERIFIED
    -> LICENSE_CLEARED
      -> LOCKED
        -> BUILT
          -> BYTE_VERIFIED
            -> RUNTIME_PROBED
              -> ACTUAL_COMPUTE_PROBED
                -> EXPERIMENTAL_ACCEPTED
```

Stage semantics:

- `DISCOVERED` — initial state; no receipt exists.
- `SOURCE_VERIFIED` — the upstream source archive / repository has been fetched
  and its declared `source_sha256` matches.
- `LICENSE_CLEARED` — the declared SPDX license is in the SRL allowlist and not
  in an incompatible prefix class.
- `LOCKED` — the dependency lock has been resolved and its `lock_sha256` has not
  drifted from the recorded manifest.
- `BUILT` — a `ResourcePackManifest/v1` has been generated from the spec and tree
  and passed structural validation.
- `BYTE_VERIFIED` — the tree hash of the extracted pack matches
  `manifest.tree_sha256`.
- `RUNTIME_PROBED` — the pack loads and runs the `runtime_probe` entrypoint
  without an error.
- `ACTUAL_COMPUTE_PROBED` — the pack runs the `actual_compute_probe` entrypoint
  and produces a deterministic, checkable result.
- `EXPERIMENTAL_ACCEPTED` — the pack is admitted to the experimental fabric. This
  is an *admission* decision, not a scientific validation of the pack's claims.

## `PackStageReceipt/v1`

Each transition emits a content-addressed receipt. The receipt identity is the
SHA-256 of the canonical JSON body with the `receipt_id` field omitted, so the
same transition evidence always yields the same receipt id.

```json
{
  "schema_version": "PackStageReceipt/v1",
  "receipt_id": "sha256:...",
  "pack_id": "example.pack",
  "stage": "BUILT",
  "from_stage": "LOCKED",
  "evidence": {"kind": "build_manifest", "valid": true},
  "created_utc": "2026-07-28T00:00:00Z",
  "canonical_writes": 0,
  "grants_authority": false
}
```

Field semantics:

- `schema_version` — always `PackStageReceipt/v1`.
- `receipt_id` — `sha256:<hex>` of the canonical receipt body without this field.
- `pack_id` — the pack identifier.
- `stage` / `from_stage` — the target and source stages of the transition.
- `evidence` — a JSON object with a `kind` string naming the gate evidence and
  any gate-specific pass/fail flags.
- `created_utc` — UTC timestamp of the transition.
- `canonical_writes` — always `0`; receipts are immutable records.
- `grants_authority` — always `false`; admission receipts do not grant authority.

## Typed terminal rejections

Every gate failure raises `AdmissionError` with a typed fail reason from the SRL
fail-reason registry (`automation/fail-reasons.json`):

- `UPSTREAM_SOURCE_UNVERIFIED` — source verification evidence did not pass.
- `LICENSE_UNKNOWN` — the license could not be identified against the allowlist.
- `LICENSE_INCOMPATIBLE` — the license is identified but barred by policy.
- `DEPENDENCY_LOCK_DRIFT` — the resolved dependency lock drifted from the
  recorded manifest.
- `PACK_INTEGRITY_FAILURE` — the manifest or byte tree failed structural or
  hash checks.
- `ACTUAL_COMPUTE_FAILED` — a runtime or actual-compute probe did not pass.
- `PACK_PROBE_ONLY` — a request reached `EXPERIMENTAL_ACCEPTED` from
  `RUNTIME_PROBED` without the actual-compute probe stage.
- `CONTRACT_INVALID` — structural or order violations, including stage skips,
  regressions, unknown stages, and malformed evidence.

## Idempotent resume

`advance(state, stage, evidence)` returns the existing receipt and the same state
object when `stage` is already the current stage. This lets a long-running
admission process resume safely after a restart or retry without creating
duplicate receipts. Re-advancing the terminal `EXPERIMENTAL_ACCEPTED` stage is
also idempotent.

## Deterministic pack builder

`build_pack(spec, workdir)` constructs a validated `ResourcePackManifest/v1` from
a declarative spec and the file tree in `workdir`. The manifest is deterministic:

- `tree_sha256` is computed by the canonical tree hash from WP-C22.
- `source_sha256` is the hash of the canonical encoding of `source.url` and
  `source.commit`.
- `lock_sha256` is the hash of `lock.json` if present, otherwise the SHA-256 of
  the empty byte string.
- `license.texts_sha256` uses `LICENSE.txt` / `LICENSE` if present; otherwise a
  deterministic default text for the declared SPDX.
- `created_utc` defaults to `1970-01-01T00:00:00Z`.
- `platforms` defaults to the four supported os/arch combinations in canonical
  order.
- `probes` default to the first entrypoint (`runtime_probe`) and the second
  entrypoint if available, otherwise the first entrypoint (`actual_compute_probe`).

The builder raises `LicenseError` for unknown or incompatible licenses and
`BuilderError` for malformed specs or trees, surfacing the typed fail reason
from the manifest validator.

## Acceptance gate

`scripts/checks/wp23-gate.py` runs six checks on the admission machine using
synthetic evidence dicts:

- C23-01: a pack advances through all eight transitions and produces a correct
  receipt chain ending at `EXPERIMENTAL_ACCEPTED`.
- C23-02: skipping a mandatory stage (e.g., `DISCOVERED` -> `BUILT`) raises
  `CONTRACT_INVALID`.
- C23-03: failed source verification raises `UPSTREAM_SOURCE_UNVERIFIED`.
- C23-04: an unknown license raises `LICENSE_UNKNOWN`; an incompatible license
  raises `LICENSE_INCOMPATIBLE`.
- C23-05: dependency lock drift raises `DEPENDENCY_LOCK_DRIFT`.
- C23-06: invalid manifest build and byte-tree mismatch raise
  `PACK_INTEGRITY_FAILURE`; failed runtime and actual-compute probes raise
  `ACTUAL_COMPUTE_FAILED`; accepting from `RUNTIME_PROBED` without
  `ACTUAL_COMPUTE_PROBED` raises `PACK_PROBE_ONLY`.

The gate emits a `GateReceipt/v1` and exits non-zero on any failure.

## Relationship to WP-C22 and execution

WP-C22 provides the immutable manifest, safe extraction, platform matching, and
materialization bridge. WP-C23 orchestrates the *decisions* that authorize a pack
to cross that bridge: a pack should be materialized and executed only after it
has reached `EXPERIMENTAL_ACCEPTED` with a complete chain of receipts. The
probes referenced by the manifest (`runtime_probe` and `actual_compute_probe`)
are the hooks that WP-C23 uses to prove the pack before admission.

## S07 governance layer

S07 adds `srl.packs.governance` above the WP-C23 state machine. The governance
layer projects a validated `ResourcePackManifest/v1` into
`SciencePackManifest/v2` and then decides whether the pack can be `ACTIVE`.

`ACTIVE` requires all of the following evidence:

- schema-valid `SciencePackManifest/v2`;
- allowed license and content-addressed license text;
- SBOM digest;
- dependency lock digest;
- every dependency in the SBOM has an artifact hash;
- vulnerability scan summary within policy thresholds;
- full admission receipt chain through all WP-C23 transitions;
- no direct pack revocation and no revoked dependency.

Missing evidence parks the pack in a precise WAIT state (`WAIT_SBOM`,
`WAIT_LOCK`, `WAIT_VULNERABILITY_SCAN`, `WAIT_ADMISSION_RECEIPT` or
`WAIT_LICENSE`). Direct or transitive revocation returns `REVOKED`. There is no
path that marks a pack `ACTIVE` merely because it installed, imported, or passed
a runtime probe.

The current committed pack inventory is treated conservatively: licenses are
known and allowed, but missing production SBOM/vulnerability/admission evidence
keeps packs out of `ACTIVE` until their full evidence is present. This is a
capability truth claim, not a feature removal.
