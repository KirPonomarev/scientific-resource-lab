# Private overlay and retrospective pilot semantics (WP-G60)

This document describes the **private overlay** introduced in WP-G60: how a
public, hashes-only `PilotSpec/v1` connects to an operator's private artifact
store, what never enters the public repository, and the **honest pilot
semantics** the contract enforces. It is the companion to the JSON Schema at
`src/srl/contracts/schemas/v1/pilot-spec.json`, the Python model under
`src/srl/pilot/`, and the acceptance gate at `scripts/checks/wp60-gate.py`.

> A pilot spec carries **sha256 digests**, never paths. The public repository
> only ever sees the generic machinery and the digests; the private overlay
> config file is NEVER committed, NEVER logged, and NEVER serialized into a
> public artifact. A null or inconclusive outcome is a VALID pilot outcome;
> execution conformance is NOT statistical power (see `GOVERNANCE.md`).

## Scope

WP-G60 ships the *public parts* of the private overlay: the machine-checkable
contract for a retrospective pilot and the generic resolver that reads an
operator's private environment at runtime.

| Concern                       | Artifact                              | Python module / schema           |
|-------------------------------|---------------------------------------|----------------------------------|
| Pilot spec contract           | `PilotSpec/v1`                        | `schemas/v1/pilot-spec.json`     |
| Spec loader / freezer / guards| `load_pilot_spec`, `freeze_spec`      | `srl.pilot.spec`                 |
| Overlay resolver              | `resolve_overlay` -> `OverlayConfig`  | `srl.pilot.overlay`              |
| Conformance vectors           | `fixtures/conformance/pilot/`         | (positive + negative)            |
| Acceptance gate               | `GateReceipt/v1` (WP-G60)             | `scripts/checks/wp60-gate.py`    |

The `srl.pilot` package depends on the contracts layer (`srl.contracts`) for
canonical JSON, content addressing, and schema validation; it adds no new
runtime dependency.

## The overlay contract

A `PilotSpec/v1` is **hashes-only**: it carries `sha256:` digests of source
artifacts, adapter packs, the catalog, and the policy, but never the paths to
them. The public repository therefore contains everything needed to *describe*
and *verify* a pilot, but nothing that locates the operator's private data.

The private overlay is how a real operator resolves those digests to bytes at
runtime. `resolve_overlay(env)` reads two environment variables **from the
passed `env` dict only** (it never touches `os.environ` directly):

- `SRL_PRIVATE_CONFIG` — the path to the operator's private overlay config
  file. The file is operator-owned and NEVER committed to the public repo.
- `SRL_ARTIFACT_STORE` — the path to the operator's private content-addressed
  artifact store root, where the source-artifact digests resolve to bytes.

Both are required. Either missing raises `OverlayError` with fail reason
`WAIT_ENVIRONMENT` — an honest wait. The resolver **never fabricates a default
path**, **never falls back to `~/.srl`**, and **never guesses a location**.
Fabricating a path would hide a misconfigured environment behind a silent
default and risk pointing the analysis at the wrong data; a typed wait is the
honest failure (the environment is not yet ready, retry after setting the
variables).

Structural problems in an otherwise-present overlay (a config file that is not
valid JSON, a store path that is not a directory) raise `OverlayError` with
fail reason `CONTRACT_INVALID` — the environment was provided but the value is
malformed, which is a different failure from a wait.

The returned `OverlayConfig` exposes **only the two resolved paths**. The
private config's contents are parsed (to validate they are a JSON object) but
are intentionally NOT returned: a public artifact, a gate, or a test can
inspect an `OverlayConfig` without any operator-private content leaking into
its output.

## What never enters public git

The public/private boundary for the overlay is absolute and machine-checked:

- **The private overlay config file** (named by `SRL_PRIVATE_CONFIG`) is NEVER
  committed. It lives outside the repository, in operator-controlled storage.
- **No absolute local path** (`/Users/`, `/home/`, `/Volumes/`) may appear in
  any public pilot artifact. The `public_boundary` CI check
  (`scripts/checks/public_boundary.py`) scans every tracked file for these
  markers, and the WP-G60 gate's G60-04 re-scans the pilot fixtures and the
  schema specifically.
- **No private identifier** appears in the public repo. The conformance
  fixtures under `fixtures/conformance/pilot/` use fully synthetic digests:
  each is `sha256:` of a deterministic synthetic seed string (e.g.
  `srl-pilot-synthetic-source-cloud-circle`), never of a real artifact and
  never of a path.
- **The `OverlayConfig` object** never surfaces private config contents; its
  `repr` exposes only the two paths.

The overlay module (`src/srl/pilot/overlay.py`) itself contains no hardcoded
private path — it is the generic machinery only. The test
`test_overlay_module_has_no_hardcoded_private_path` pins this.

## Honest pilot semantics

A `PilotSpec/v1` describes a **retrospective** analysis over ALREADY-EXTANT
artifacts. Three safety consts are pinned `false` in the schema and re-checked
in Python (defense in depth):

| Const                                              | Meaning                                                                 |
|----------------------------------------------------|-------------------------------------------------------------------------|
| `status_promotion_allowed`                         | A pilot cannot promote a claim's status (e.g. under_investigation -> supported). Status promotion is a governance decision. |
| `prospective_holdout_materialization_allowed`      | A pilot cannot authorize materializing a prospective holdout (data held out for out-of-sample validation that does not yet exist at authoring time). |
| `grants_authority`                                 | A pilot is a description, not an authority.                             |

A fourth const, `canonical_writes = 0`, pins that a spec is immutable once
authored.

### Null / inconclusive is a valid outcome

A pilot that runs to completion and reports a **null** or **inconclusive**
result has not failed. The null generators (`phase_randomized`,
`block_bootstrap`, `permutation`) exist precisely to characterize the
reference distribution under the null hypothesis; a measured effect that does
not exceed the null distribution is an honest null result, not an error. An
`inconclusive` outcome (the analysis could not separate signal from null
within tolerance) is likewise valid. The contract does not prefer a "positive"
result and provides no path to inflate one.

### Execution conformance is not statistical power

A spec that **validates** (satisfies the schema, the const-false invariants,
and the holdout guard) has met the *admission* contract — it is structurally
well-formed. Validation never means the pilot's claim is *supported*, just as
a green run receipt elsewhere in SRL never means a scientific claim is
supported (see `docs/contracts/evidence-model.md`). Statistical power is a
property of the analysis against the data, established by the analysis itself,
not by the spec's structural conformance.

### The retrospective / prospective integrity boundary

The load-bearing integrity property is the boundary between **retrospective**
analysis (over already-extant data) and **prospective** data collection. A
pilot reads data that existed at authoring time; materializing a prospective
holdout (data held out for out-of-sample validation that does not yet exist)
would cross that boundary. The schema pins
`prospective_holdout_materialization_allowed` to `false`, and the Python
`validate_holdout_free` guard rejects any field name or value pattern that
indicates a holdout is being materialized (invariant
`prospective_holdout_materialization`). The legitimate
`prospective_holdout_materialization_allowed: false` const is NOT a marker;
an affirmative marker (`holdout_materialized: true`, or a value string naming
prospective holdout collection) is.

## Content addressing

A `PilotSpec/v1` is content-addressed: its `pilot_id` is `sha256:` over the
canonical encoding of the spec WITHOUT the `pilot_id` field (the self-hash-free
pattern, mirroring `request_id` and `plan_id`). Two independent agents that
author the same pilot compute the same `pilot_id`. `freeze_spec` returns the
canonical frozen bytes (sorted keys, compact separators, UTF-8, no
NaN/Infinity, trailing newline); the gate's G60-01 asserts that freezing is
deterministic and that the recomputed `pilot_id` matches the stored field.

## Acceptance gate

`scripts/checks/wp60-gate.py` runs four checks and emits a `GateReceipt/v1`:

- **G60-01** the synthetic analog spec validates (schema + const-false +
  holdout guards) and freezes deterministically, and its `pilot_id`
  recomputes to the stored id;
- **G60-02** `status_promotion_allowed=true` is rejected
  (`pilot_safety_const`) and a holdout materialization marker is rejected
  (`prospective_holdout_materialization`); both negative conformance vectors
  reject as their `expected_error.json` predicts;
- **G60-03** `resolve_overlay` with a missing/empty env raises `WAIT_ENVIRONMENT`
  and names the missing variables, never fabricating a default;
- **G60-04** no `/Users/`, `/home/`, or `/Volumes/` path marker appears in any
  public pilot artifact (the fixtures use digests only).

The gate runs under the `pilot-spec-gate (WP-G60)` CI job in
`.github/workflows/contracts.yml`. The `receipt-invariants` job verifies every
*receipt* schema pins the safety consts; `PilotSpec/v1` carries the consts too
(it is not a receipt by title, but it pins `canonical_writes=0` and
`grants_authority=false` as `const`).
