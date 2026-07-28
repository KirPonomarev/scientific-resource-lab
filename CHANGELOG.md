# Changelog

All notable changes to Scientific Resource Lab are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Commit subjects on `main` follow [Conventional Commits](https://www.conventionalcommits.org/).

A green entry means a change was admitted; it never means a scientific claim
is supported. See `README.md` and `GOVERNANCE.md` for the evidence rules.

## [Unreleased]

### Added

- Canonical JSON and identifiers foundation under the `srl.contracts` package
  (WP-B10): `canonical.py` providing `dumps(obj)->bytes` enforcing sorted keys,
  compact separators, UTF-8 (`ensure_ascii=False`), `allow_nan=False`, and a
  final newline, with `loads`/`validate` round-trip helpers and
  `decimal_to_str` rendering precision-sensitive values to the
  `^-?[0-9]+(\.[0-9]+)?$` policy string (no exponent); `ids.py` providing
  `object_id(obj)->str` computing `sha256:` + 64 lowercase hex over the
  canonical bytes, with `SelfHashError` (fail reason `CONTRACT_INVALID`)
  rejecting an object that already carries its own `object_id` field;
  `numbers.py` providing strict numeric validation (reject NaN/Infinity,
  reject bool-as-int, enforce decimal strings, non-negative integer byte
  counts); `timestamps.py` enforcing RFC 3339 UTC at seconds precision
  (`YYYY-MM-DDTHH:MM:SSZ`) with `validate`/`normalize`; `artifact_refs.py`
  validating `ArtifactRef/v1` including portable-path rejection (relative,
  no `..`, no drive letter, no leading `/`, no backslash); and `errors.py`
  with the `ContractError` base carrying a typed `fail_reason`.
- JSON Schema 2020-12 documents under `src/srl/contracts/schemas/v1/`:
  `ArtifactRef/v1`, `ScientificObjectEnvelope/v1` (the base envelope with
  `object_id`, `object_type` enum of 17 kinds, `created_utc`, `parents`,
  `payload`, and the safety consts `canonical_writes=0` /
  `grants_authority=false`), and `GateReceipt/v1`, each with a canonical
  `https://schemas.srlab.dev/v1/<Name>.json` `$id`, `additionalProperties:
  false`, and explicit `required`; plus a `README.md` documenting the
  naming/compatibility policy (additive optional -> minor; breaking -> major
  with the old `vN` retained).
- `src/srl/contracts/schema.py` schema loader: `load_schema(name)->dict` via
  `importlib.resources` (schemas ship in the wheel), meta-validating every
  schema against the 2020-12 meta-schema on first load (memoized), and
  `validate(instance, schema_name)->None` raising
  `ContractValidationError` (fail reason `CONTRACT_INVALID`) carrying the
  failing JSON path and keyword; `meta_validate_all()` returns the
  name->`$id` map and asserts `$id` uniqueness.
- `jsonschema>=4.23` as the project's first runtime third-party dependency
  (see `docs/adr/0002-jsonschema-library.md`), with `types-jsonschema>=4.23`
  added to the `dev` group for `mypy --strict` stubs; resolved to
  `jsonschema==4.26.0` in `uv.lock`.
- Conformance vectors under `fixtures/conformance/canonical_json/`: 12
  positive vector pairs (input variant + expected canonical bytes) covering
  key-order normalization, unicode NFC/supplementary passthrough, nested
  empty containers, decimal-string preservation, integer byte counts, deep
  sorted nesting, array-order preservation, null/bool/int distinctness, and
  safe-range large integers; plus 8 negative vectors (NaN, Infinity,
  bool-as-int, self-hash, absolute path, traversal path, fractional
  timestamp, offset timestamp) each naming the typed rejection it must
  trigger.
- `scripts/checks/wp10-gate.py` (executable; in-repo `srl` package) running
  the four WP-B10 acceptance checks (B10-01..B10-04: key-order determinism;
  NaN/Infinity/bool-as-int rejection; self-hash rejection; portable-path
  rejection) and emitting a canonical `GateReceipt/v1` receipt with a
  non-zero exit on any FAIL.
- `scripts/checks/schema-meta-validate.py` and
  `scripts/checks/canonical-vectors.py` (executable) printing JSON receipts:
  the former meta-validates every shipped schema against the 2020-12
  meta-schema and cross-checks the on-disk file set; the latter verifies
  every positive vector canonicalizes to its expected bytes and every
  negative vector is rejected with the named typed error.
- `Makefile` `gate-wp10` target and a `canonical-json-gate` job in
  `.github/workflows/ci.yml` (ubuntu-24.04, 15-minute timeout, same pinned uv
  setup); a new `.github/workflows/contracts.yml` workflow with
  `schema_meta_validate` and `canonical_json_vectors` jobs (SHA-pinned
  actions, `contents: read`, 15-minute timeout).
- Unit and property tests under `tests/contracts/`:
  `test_canonical_roundtrip.py` (Hypothesis: byte-stable round trip,
  key-order independence, no non-finite floats; decimal policy helpers),
  `test_ids.py` (determinism, self-hash rejection, shape),
  `test_numbers.py`, `test_timestamps.py`, `test_artifact_refs.py`, and
  `test_schema_loader.py` (meta-validation passes for all shipped schemas;
  envelope accepts valid, rejects `grants_authority=true`, rejects unknown
  additional property).
- `docs/adr/0002-jsonschema-library.md` recording the `jsonschema` decision
  (alternatives: none/hand-rolled/`fastjsonschema`; justification: mature,
  MIT-licensed, full 2020-12 support, structured errors).
- Autonomous workflow contracts under `AutonomyPolicy/v1` (WP-A03):
  `automation/policy.json` (`AutonomyPolicy/v1`, canonical JSON, 19 keys)
  encoding the active governance policy; `automation/fail-reasons.json`
  (`FailReasonRegistry/v1`) registering the 40 typed fail reasons with their
  class, hard-stop, and retriable flags; `automation/state.schema.json`
  (`AutomationStateSchema/v1`, JSON Schema 2020-12) for the persisted runtime
  state including the 17-value `terminal_status` enum and the max-4 lanes /
  max-1 scientific WIP bounds; and `automation/checks.json`
  (`GateCheckRegistry/v1`) mapping the five WP-A03 gate checks to script
  invocations.
- `src/srl/autonomy/` package (mypy strict, ruff clean, stdlib only):
  `policy.load_policy` validates the on-disk policy against an embedded
  expectation (19 keys, types, enum values, schema version) and raises
  `PolicyError` on drift; `scopes.check_write` enforces the declared write
  scope pre-write, rejecting out-of-scope, `..` traversal, and absolute paths
  with `ScopeViolation` (fail reason `CONTRACT_INVALID`); `leakguard.scan_diff`
  is a pure pre-commit public-leak guard flagging absolute POSIX home paths,
  `/Volumes/` paths, GitHub PAT shapes, `sk-`, AWS access key IDs, PEM private
  keys, and long hex secrets (fail reason `PUBLIC_LEAK_DETECTED`), with a
  false-positive guard so the word "secret" in prose is not flagged; and
  `resume.reconcile` implements the deterministic resume table (10 rows)
  with the SHA-256 idempotency key over `(repository_id, mission_digest,
  wp_id, base_sha, policy_sha)`, where only `RECONCILE_MERGED` permits merge.
- `scripts/checks/wp03-gate.py` (executable; stdlib + in-repo `srl` package)
  running the five WP-A03 acceptance checks (A03-01..A03-05) and emitting a
  canonical `GateReceipt/v1` JSON receipt with a non-zero exit on any FAIL,
  including a pre-write proof that no file is created for refused writes and
  an inline synthetic secret fixture (obviously fake `ghp_EXAMPLE...` token).
- `Makefile` `gate-wp03` target and an `autonomy-contracts-gate` job in
  `.github/workflows/ci.yml` (ubuntu-24.04, 15-minute timeout, same pinned uv
  setup) running the WP-A03 gate; the existing jobs are unchanged.
- `docs/architecture/autonomous-workflow.md` documenting the Git lifecycle
  state machine (mermaid + prose), work-package identity fields, commit
  policy, the ten auto-merge conditions, post-merge steps, the idempotency
  key formula, and the retry policy (max 2 retries with backoff only for
  explicit 429/5xx/network-reset; never for permission/privacy/license/
  policy/hash/injection/resource/scientific/conflict failures; product CI
  failures max 3 bounded fix cycles then park).
- Unit tests for the autonomy package: `test_autonomy_policy.py` (valid
  policy loads; each missing/extra/wrong-type/bad-value/wrong-schema
  deviation rejected), `test_scopes.py` (in-scope accept; out-of-scope,
  `..`, absolute, backslash, partial-name all raise), `test_leakguard.py`
  (each pattern class detected; clean diff passes; "secret" in prose is not
  flagged; bytes entry point reports scan failure), and `test_resume.py`
  (every resume-table row; only `RECONCILE_MERGED` permits merge; failing
  checks never merge; idempotency key stability and field sensitivity;
  byte-identical deterministic JSON).
- Committed the WP-A02 closeout receipt
  (`automation/receipts/wp-closeout-a02.json`).
- Repository governance baseline under `AutonomyPolicy/v1`: policy immutability
  for an active mission, protected governance paths, and a dedicated
  governance-change workflow requiring the old verifier on the new diff, a new
  verifier, and an independent review receipt, with no self-validation.
- `SECURITY.md` with private vulnerability reporting, a supported versions
  policy, scoped reporting guidance, and an explicit prohibition on secrets or
  private data in issues and pull requests.
- `CONTRIBUTING.md` establishing the pull-request-only workflow, the
  conventional commit type set (`feat`, `fix`, `refactor`, `test`, `docs`,
  `build`, `ci`, `chore`, `perf`, `security`), and the required pull request
  body sections.
- `CODE_OF_CONDUCT.md` based on the Contributor Covenant v2.1.
- `CITATION.cff` (CFF 1.2.0) for software citation.
- `NOTICE` for the Apache-2.0 attribution.
- `.github/pull_request_template.md` embedding the required pull request body
  sections.
- `.github/ISSUE_TEMPLATE/work-package.md` and
  `.github/ISSUE_TEMPLATE/governance-change.md` for structured issue intake.
- `.editorconfig`, `.gitattributes`, and `.pre-commit-config.yaml` for shared
  formatting and hygiene hooks (trailing whitespace, end-of-file fixer, JSON
  and YAML validation, large-file and private-key detection, `ruff`).
- Repository labels and milestones aligned to the implementation plan
  (`v0.1.0` through `v1.0.0`).
- Python package skeleton `srlab` (v0.1.0) with a `src/srl` layout, a typed
  surface (`py.typed`), a canonical-JSON helper (`srl.canonical`), and a
  JSON-first CLI dispatcher (`srl.cli`) implementing `srlab doctor`,
  `srlab version`, and a canonical `ErrorReport/v1` for unknown commands.
- `pyproject.toml` selecting `hatchling` as the build backend (see
  `docs/adr/0001-build-backend.md`), with `ruff`, `mypy` (strict for `srl`),
  and `pytest` configured, and a uv-native `dev` dependency group.
- `Makefile` with `bootstrap`, `lint`, `format`, `typecheck`, `test`, `build`,
  `verify`, and `repro-check` targets (portable; no absolute paths).
- `scripts/build/reproducible-check.py` (standard library only) that builds the
  wheel twice under a fixed `SOURCE_DATE_EPOCH`, normalizes both archives, and
  emits a `ReproducibleWheelManifest/v1` with a `content_manifest_sha256`.
- `.github/workflows/ci.yml` (`name: ci`) running lint, typecheck, a
  3.11/3.12/3.13 unit matrix, and a `ubuntu-24.04`/`macos-15` package job that
  runs the reproducible-wheel check; actions pinned to full commit SHAs.
- Unit tests for the CLI dispatcher and version identity, and Hypothesis
  property tests for canonical-JSON stability and round-tripping.
- `docs/adr/0001-build-backend.md` recording the `hatchling` decision.
- `.python-version` pinning the project baseline to `3.12`.
- Committed `uv.lock` and tracked the WP-A01 closeout receipt
  (`automation/receipts/wp-closeout-a01.json`).

### Changed

- `.github/workflows/ci.yml` adds the `canonical-json-gate` job (WP-B10) and
  previously added the `autonomy-contracts-gate` job (WP-A03); the existing
  lint, typecheck, unit, and package jobs are unchanged.
- `pyproject.toml` declares `jsonschema>=4.23` as the first runtime
  dependency and adds `types-jsonschema>=4.23` to the `dev` group; the sdist
  include list now carries `src/srl/contracts/schemas/v1` so schema documents
  ship in the wheel for `importlib.resources`.
- `src/srl/canonical.py` is now a compatibility re-export shim (ASCII-only,
  `str` return) preserving the Phase-A behavior for the autonomy receipts and
  CLI dispatcher; the scientific contracts layer uses the stricter
  `srl.contracts.canonical` (UTF-8 bytes, `allow_nan=False`).
- README now references `CHANGELOG.md`, `GOVERNANCE.md`, and `NOTICE`.

### Security

- Documented the public repository boundary and the prohibition on committing
  secrets, real datasets, operator identity, and absolute local paths.

## [0.1.0] - Unreleased

The first milestone target (`v0.1.0`) covers the repository, contracts, the
Scientific IR, and conformance. It is tracked as a GitHub milestone and is
released from this `Unreleased` section once the acceptance checks pass.
