# Changelog

All notable changes to Scientific Resource Lab are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Commit subjects on `main` follow [Conventional Commits](https://www.conventionalcommits.org/).

A green entry means a change was admitted; it never means a scientific claim
is supported. See `README.md` and `GOVERNANCE.md` for the evidence rules.

## [Unreleased]

## [1.0.0] - 2026-07-28

Standalone Scientific Resource Lab with stable LabExportPacket/v1:
refuse-not-strip exporter (structural path detection, case-insensitive
credential patterns, recursive payload sanitization), export adversarial
corpus (12 valid + 44 malformed), read-only stdio MCP, static portal with
synthetic demo, P1 admission framework, bounded PyMC+ArviZ and CVXPY P1
candidates, P2 discovery registry, semantic future profiles, machine-
enforced lane ledger, and a sealed private retrospective pilot executed
through the SRL fabric (99 null/surrogate runs; null/inconclusive honored).


## [0.4.0] - 2026-07-28

P0 capability packs and knowledge adapters: units core (Pint, CODATA),
SMT (z3; cvc5 excluded on GPL grounds), ripser TDA (topology goldens,
surrogate controls), pyRiemann SPD geometry (train-only discipline),
OpenAlex/Crossref/arXiv/OEIS source adapters, and the P0 integration
release with a measured actual-compute corpus (20 runs) and sealed catalog.

## [0.3.0] - 2026-07-28

Bounded runner and security suite: fixed-entrypoint runner with sandbox
(rlimits, process groups, receipt-last), materializer and sealer, M1
resource policy, adversarial suite (14 case kinds, 50-run orphan-free
gate), secret scan / license inventory / public boundary / docs workflows.


### Added

- **P0 integration release (WP-E45)** — the Phase E capstone that proves the
  four P0 packs (units, smt, ripser, pyriemann) integrate as a coherent,
  measured, honestly-claimed release. `scripts/checks/wp45-gate.py` emits an
  `IntegrationReceipt/v1` with six checks: E45-01 runtime probes (each P0 pack
  adapter imports and its typed surface resolves), E45-02 actual-compute probes
  (each pack runs ONE real bounded compute matching its golden — a coherent SI
  identity, a SAT+UNSAT pair, the circle's single long-lived H1, the
  closed-form log-Euclidean mean), E45-03 ≥5 DISTINCT measured real-compute
  runs per pack with a REAL wall/rss/expanded-bytes triple read off the process
  (never fabricated), E45-04 catalog seal determinism (rebuild → identical
  `snapshot_id`/`merkle_root`/canonical bytes), E45-05 the synthetic
  end-to-end slice (claim → classify/plan → real units conversion → engine +
  validation receipts → demo portal page) with `exercise_level=actual_compute`
  and `integration_authority=none`, and E45-06 an overclaim scan (no
  `formal_check=proven` without a certificate; pack ceilings ≤ `checked`). The
  gate enforces a hard 300s wall guard; the measured corpus runs in
  single-digit seconds. `tests/integration/test_p0_end_to_end.py` — ten
  integration tests pinning the per-stage invariants and the full slice;
  `make gate-wp45` target; `p0-integration-gate (WP-E45)` job in
  `.github/workflows/integration.yml` (ubuntu-24.04, 30-minute timeout
  justified by the measured corpus, actions pinned from `ci.yml`);
  `docs/architecture/p0-integration.md` and `docs/adr/0007-p0-integration.md`.
- **P1 admission framework with typed candidate verdicts** under
  `srl.packs.admission` — an eight-stage candidate pipeline
  (`Candidate`, `CandidateBuilder`, `evaluate_candidate`) producing one of five
  typed verdicts (`EXPERIMENTAL_ACCEPTED` / `STABLE_ACCEPTED` /
  `REJECTED_LICENSE` / `REJECTED_CONTRACT` / `REJECTED_RESOURCE`) with a
  content-addressed `AdmissionVerdict/v1`, the public `admit(pack_dir)` entry
  point, and the train-only / license / resource gates a candidate must pass.
- **Static evidence portal with synthetic demo mode** under `srl.portal.build`
  (`PortalMode.private_local` / `PortalMode.public_demo`,
  `build_portal(objects_dir, out_dir, mode) -> PortalBuildReport`) — a
  stdlib-only static site generator emitting an index, per-object detail,
  transformation lineage, evidence matrix, run resources, and model interfaces
  pages from `string.Template` templates; the `public_demo` mode drops
  non-synthetic objects and refuses any input carrying an absolute local path
  or credential pattern with a typed `PUBLIC_LEAK_DETECTED` refusal
  (fail-closed on any leak).
- **pyRiemann SPD geometry pack (WP-E43)** under
  `srl.packs.adapters.pyriemann_adapter` — Riemannian and log-Euclidean means,
  distances, and a train-only shrinkage API (`fit_transform` / `transform`)
  whose state carries only training-derived statistics; non-SPD and trivial
  1×1 inputs raise `SpdError` (`CONTRACT_INVALID`) before any compute.
- **PilotSpec schema and private overlay machinery** under `srl.pilot` — a
  `PilotSpec/v1` schema for scoped pilot studies with a private overlay layer
  that keeps operator-local configuration out of the public fabric.
- **ripser TDA pack (WP-E42)** under `srl.packs.adapters.ripser_adapter` —
  persistent homology of a point cloud under hard resource limits (points,
  ambient dimension, homology degree) with decimal-string birth/death pairs, a
  deterministic preprocessing receipt, and a phase-randomized surrogate helper
  for null-hypothesis controls; `long_lived_classes` / `max_finite_persistence`
  analysis helpers.
- **Read-only stdio MCP server (F51)** under `srl.mcp` — a hand-rolled stdio
  MCP server exposing seven read-only P0 methods (catalog snapshot, capability
  lookup, plan inspection, evidence assessment, receipt fetch, corpus
  enumeration, portal manifest) with no write surface and no network egress.
- **AutonomyPolicy/v3 (governance)** — raises the implementation lane ceiling
  from 6 to 8 concurrent lanes, widening the governed multi-lane capacity
  without changing the lane path-ownership or lease disciplines.
- **Z3+cvc5 SMT pack (WP-E41)** under `srl.packs.adapters.smt` — a
  satisfiability adapter over a restricted S-expression grammar (no raw
  SMT-LIB text eval) with z3 as the cleared solver (cvc5 is `WAIT_LICENSE`),
  disagreement preservation (a dual-solver disagreement is recorded, never
  silently resolved), and an honest `FORMAL_CHECK_CEILING=checked` (a SAT/UNSAT
  answer is never promoted to `proven` without a verified certificate).
- **OpenAlex/Crossref/arXiv/OEIS knowledge source adapters (WP-E44)** under
  `srl.knowledge.sources` — four source parsers producing `SourceRecord/v1`
  entries with attribution, an `EndpointPolicy` with byte/cost budgets, and a
  `search_*` retriever that enforces the budget with a typed `RESOURCE_LIMIT`
  refusal; no FRED/ALFRED/Wolfram credential-requiring adapter ships.

### Changed

- The `integration_authority` axis is pinned `none` across every P0 integration
  receipt and assessment: an actual-compute run never grants integration
  authority, and the reserved `admitted_a1_sandbox` / `admitted_a2` tiers
  remain unreachable (there is no admission route in this codebase).

## [0.2.0] - 2026-07-28

Release contents: transactional CAS ingest engine with dedup, fsck and
receipt-last crash matrix (C21); T7 volume identity guard and storage
abstraction (C20); pack manifest, safe extraction and materialization (C22);
eight-stage pack builder and admission pipeline with machine-enforced stage
adjacency (C23); deterministic capability catalog snapshot with merkle root
(C24); M1 resource policy (D30); API retriever with budgets and query
receipts (D33); JSON-first CLI surface (F50); units semantic core with Pint
adapter and CODATA fixtures (E40); security/public-boundary/docs workflows
(A04); weekly-deep scheduled verification (A06); machine-enforced lane
ledger with leases and path ownership (governance).



### Added

- Thirty-task public conformance corpus under `srl.planning` (WP-B15):
  `srl.planning.corpus` — a pure, no-I/O corpus runner (`load_corpus`,
  `run_task`, `verdict`, `run_corpus`) that executes each `TaskSpec/v1`
  against the real science-lab pipeline (classifier → router → planner) and
  the real contract validators (the MathIR allowlist, the artifact-ref
  contract, the schema consts), resolving each task to one of seven typed
  outcomes (`PASS` / `WAIT_CAPABILITY` / `REJECT_CONTRACT` / `REJECT_IR` /
  `REJECT_RESOURCE` / `REJECT_LICENSE` / `REJECT_AUTHORITY`; `MISMATCH` is
  the internal verdict sentinel). The runner NEVER writes outside memory and
  maps every pipeline exception to the matching typed rejection outcome. The
  honesty model is load-bearing: because no scientific backend ships in this
  codebase, the dominant outcome is `WAIT_CAPABILITY` (an applicable profile
  with no available adapter waits honestly rather than fabricating one); the
  two exact-arithmetic tasks are the only `PASS` outcomes (clean IR constants
  with no capability engaged); `REJECT_IR` is a real `UnsupportedOperatorError`
  from the closed allowlist (`arith1.sqrt` / `arith1.log` for the domain
  violations); `REJECT_RESOURCE` is a real `ResourceAdmissionError`
  (`WAIT_REMOTE_EXECUTOR`); `REJECT_CONTRACT` is a real artifact-ref /
  structural rejection (incl. the public-boundary refusal of a packet
  smuggling a local path); `REJECT_AUTHORITY` is the real `grants_authority=
  false` schema const; `REJECT_LICENSE` is the documented corpus copyleft-
  refusal policy (GPL/AGPL/LGPL/SSPL/BUSL). `fixtures/conformance/corpus/`
  — exactly 30 public synthetic tasks (`task-NN-<slug>/task.json` +
  `README.md`) across 18 declared categories (algebraic identities, units
  and dimensions, domain violations, exact arithmetic, SAT/UNSAT/UNKNOWN,
  symbolic-law false positives, topology, SPD geometry, causal assumptions,
  uncertainty, ODE/PDE interface, model composition, literature extraction,
  proof obligations, resource/license/path/authority rejection), each with a
  category-coverage map (`manifest.json`); `scripts/checks/wp15-corpus.py`
  — the `CorpusReceipt/v1` check (30 outcomes, zero mismatches, category
  coverage vs manifest, byte-identical across runs); `make corpus` target;
  `public_conformance_corpus` CI job in `contracts.yml`;
  `tests/planning/test_corpus.py`; `docs/contracts/conformance-corpus.md`.
- Evidence assessment and science-lab run receipt model under `srl.semantic`
  (WP-B13): `EvidenceAssessment/v1` (`evidence-assessment.json`) — a typed
  assessment of the evidence behind a `ScientificClaim` on **11 orthogonal**
  evidence axes (capability_state / exercise_level / engine_execution /
  scientific_check / formal_check / formal_scope / statistical_support /
  causal_identification / algorithmic_cross_engine_reproduction /
  independent_empirical_replication / integration_authority), encoding the
  orthogonality invariants that a movement on one axis never grants a movement
  on another via `allOf`/`if-then` and re-enforced in Python by
  `srl.semantic.evidence.validate` / `build_assessment` (raising
  `EvidenceAxisError`, fail reason `CONTRACT_INVALID`, defense in depth):
  probe is not compute (`exercise_level=import_probe` forbids
  `engine_execution=completed`, invariant `probe_not_compute`), failed is not
  checked (`engine_execution=failed` forbids `scientific_check=checked`,
  invariant `failed_not_checked`), and the authority path is none (the reserved
  `admitted_a1_sandbox` / `admitted_a2` tiers are rejected, invariant
  `authority_path_none`); `ScienceLabEngineReceipt/v1`
  (`science-lab-engine-receipt.json`) — a receipt proving a backend engine ran
  (or failed) for a run request, with the honest `exercise_level` and
  `engine_execution`, encoding that an `import_probe` receipt CANNOT yield
  completed-and-computed semantics (a probe with non-empty
  `output_object_ids` is rejected); `ScienceLabValidationReceipt/v1`
  (`science-lab-validation-receipt.json`) — a receipt proving an independent
  validator checked an engine run's output, encoding that `formal_check=proven`
  REQUIRES a non-null `formal_certificate_ref` (invariant
  `proven_requires_certificate`; a SMT-style answer without a verified
  certificate yields at most `checked`); `ScienceLabRunReceipt/v1`
  (`science-lab-run-receipt.json`) — a receipt tying an engine run and its
  optional validation into a single terminal outcome with aggregate resource
  usage; all four schemas registered in the loader (`srl.contracts.schema`) and
  the four object types (`evidence_assessment`, `engine_receipt`,
  `validation_receipt`, `run_receipt`) added to
  `SUPPORTED_OBJECT_TYPES` (the envelope `object_type` enum widens additively
  to include `engine_receipt` and `validation_receipt`).
- `srl.semantic.evidence`: a typed `EvidenceAssessment` builder
  (`build_assessment`) enforcing the orthogonality invariants; an
  `update_assessment(prior, delta, evidence_ref, regression_reason=…) -> new
  assessment` with a per-axis monotonic transition guard (up freely; down only
  with a `regression_reason` naming the contradicted/divergent evidence,
  invariant `monotonic_transition`) and delta-orthogonality enforcement
  (formal_not_empirical: a formal-axis update never modifies
  statistical_support/causal_identification in the same step;
  algorithmic_not_independent: setting algorithmic reproduction never sets
  independent replication), threading the full prior state into the new
  assessment's `parents`; receipt builders `build_engine_receipt` /
  `build_validation_receipt` / `build_run_receipt` enforcing the
  probe-is-not-compute and proven-requires-certificate invariants; and three
  executable honesty collapse assertions `assert_probe_not_compute` /
  `assert_formal_not_empirical` / `assert_algorithmic_not_independent`.
- Conformance vectors under `fixtures/conformance/evidence/`: 5 positive (a
  probe-only assessment, an actual-compute + checked + formal-checked
  assessment with a certificate, a completed engine receipt, a proven
  validation receipt with a certificate, a completed run receipt) and 5
  negative (an import probe with a completed engine, a formal proven without a
  certificate, a formal-axis update mutating a statistical axis, a reserved
  integration_authority tier, a probe receipt claiming output objects), with a
  `manifest.json` and `README.md`.
- `scripts/checks/wp13-gate.py` running the four WP-B13 checks (B13-01 an
  import probe cannot yield COMPUTED at receipt + assessment levels; B13-02 a
  SMT-style answer yields at most CHECKED without a verified certificate,
  proven rejected without one; B13-03 a formal axis cannot update an empirical
  axis; B13-04 algorithmic reproduction differs from independent replication,
  reserved authority rejected, and the positive/negative fixtures
  validate/reject) and emitting a `GateReceipt/v1`; an `evidence-model-gate
  (WP-B13)` job in `.github/workflows/ci.yml`; a `receipt-invariants` job in
  `.github/workflows/contracts.yml` (backed by
  `scripts/checks/receipt-invariants.py`) verifying every receipt schema pins
  `canonical_writes=0` and `grants_authority=false` as `const`; a `Makefile`
  `gate-wp13` target.
- Unit and property tests under `tests/contracts/` (`test_evidence.py`,
  `test_receipts.py`) pinning the orthogonality invariants at both layers, the
  monotonic-transition guard, lineage threading, identity idempotency, schema
  round-trips, the receipt safety consts, plus a Hypothesis property that
  random axis-update sequences never produce a forbidden combination.
- `docs/contracts/evidence-model.md` documenting the 11 orthogonal axes, the
  orthogonality rules, the prohibited collapses table (READY != COMPUTED,
  COMPUTED != VALIDATED, SAT/UNSAT != empirical truth, algorithm agreement !=
  independent replication, formal proof != market validation, exportable !=
  admitted), the monotonic-transition ladder, the run receipts, and the
  authority states.

- Transformation receipts and adapter semantic profiles under `srl.semantic`
  (WP-B12): `TransformationReceipt/v1` (`transformation-receipt.json`) — a
  receipt binding `source_object_id`→`target_object_id` by a named
  `transform_kind` (normalize/project/convert_units/restrict_domain/serialize/
  deserialize/approximate), carrying the honest cost as a `conversion_class`
  (`LOSSLESS`/`LOSSY_EXPLICIT`/`LOSSY_IMPLICIT_DETECTED`), the
  `introduced_assumptions` (each `{assumption, justification}`), and the
  `dropped_features`, encoding the critical invariant that `LOSSLESS` REQUIRES
  `introduced_assumptions=[]` AND `dropped_features=[]` via `allOf`/`if-then`
  and re-enforced in Python by `srl.semantic.transforms.validate` /
  `record_transformation` (raising `TransformationInvariantError`, fail reason
  `CONTRACT_INVALID`, invariant `lossless_requires_no_loss`, defense in depth);
  `LOSSY_IMPLICIT_DETECTED` is detector-only — the producer API
  (`record_transformation`) cannot set it, only the detector constructor
  (`record_detected_loss`) can, enforced by constructor separation;
  `AdapterSemanticProfile/v1` (`adapter-semantic-profile.json`) — a typed
  semantic profile for a backend adapter declaring its `supported_cds` subset of
  `MATH_IR_ALLOWLIST`, its per-operator `unsupported_features` behavior
  (reject/approximate/drop), its input/output schema contracts, its
  `deterministic`/`network_access` posture, and its `license_spdx`, with the
  invariant that `supported_cds` MUST be a subset of the (closed) MathIR
  allowlist (raising `ProfileInvariantError`, invariant
  `supported_op_outside_allowlist`, defense in depth); both schemas registered
  in the loader (`srl.contracts.schema`) and the two object types
  (`adapter_profile`, `transformation_receipt`) added to
  `SUPPORTED_OBJECT_TYPES`.
- `srl.semantic.transforms`: a typed `TransformationReceipt` builder
  (`record_transformation`) enforcing the LOSSLESS invariant; a projection
  lineage builder (`project_to_backend(ir_tree, profile) -> (restricted_tree,
  receipt)`) verifying every op is in `profile.supported_cds`, handling
  unsupported ops by the profile's declared behavior (`reject` ->
  `UnsupportedFeatureError`, fail reason `IR_UNSUPPORTED`; `approximate`/`drop`
  -> recorded as a `LOSSY_EXPLICIT` step with the dropped feature and matching
  assumption), binding `adapter_profile_ref` (the profile's `profile_id`) and
  `pack_hash` (the profile's `pack_ref` digest) so the projection is
  reproducible, with lineage chaining (a downstream receipt's
  `source_object_id` equals the upstream's `target_object_id`); a detector-only
  `record_detected_loss` constructor producing `LOSSY_IMPLICIT_DETECTED`; and a
  module-level raw-eval guard `assert_no_raw_eval_route()` introspecting
  `srl.semantic` and verifying no `sympify`/`sage_eval`/`eval`/`lambdify` input
  route is exposed (the restricted MathIR allowlist is the only evaluation
  route).
- `srl.semantic.adapter_profiles`: the typed `AdapterSemanticProfile` validator
  (`validate_profile`) re-checking the supported-cds-subset-of-allowlist and
  no-supported/unsupported-contradiction invariants in Python as defense in
  depth, plus full `ArtifactRef/v1` validation of the inline `pack_ref`
  (portable-path rejection etc.); a `profile_id`/`build_profile` pair computing
  the content-addressed identity.
- Conformance vectors under `fixtures/conformance/transformations/`: 3 positive
  (a LOSSLESS unit-annotate receipt, an AdapterSemanticProfile for a solver
  backend lacking `calculus1.diff`, and the LOSSY_EXPLICIT projection receipt
  produced by projecting `calculus1.diff(x)` onto that profile) and 3 negative
  (LOSSLESS claimed with a dropped feature, an unsupported op hitting
  `behavior=reject`, and a profile claiming an op outside the MathIR allowlist),
  with a `manifest.json` and `README.md`.
- `scripts/checks/wp12-gate.py` running the four WP-B12 checks (B12-01 a lossy
  step cannot claim LOSSLESS at schema + python layer; B12-02 an introduced
  assumption is carried explicitly; B12-03 a backend projection binds the
  adapter/pack hash with lineage chaining and `behavior=reject` halts with
  `IR_UNSUPPORTED`; B12-04 no raw-eval route and the positive/negative fixtures
  validate/reject) and emitting a `GateReceipt/v1`; a `transformations-gate
  (WP-B12)` job in `.github/workflows/ci.yml`; a `Makefile` `gate-wp12` target.
- Unit tests under `tests/contracts/` (`test_transforms.py`,
  `test_adapter_profiles.py`) pinning the LOSSLESS invariant at both layers, the
  detector/producer separation, identity idempotency, schema round-trips, the
  projection lineage chain (two sequential projections link source to prior
  target), the reject behavior, the allowlist-closure invariant, and the
  raw-eval guard.
- `docs/contracts/transformations.md` documenting the conversion classes, the
  honesty rules (a lossy step never upgrades evidence; introduced assumptions
  travel with the object forever via lineage; LOSSLESS is a claim the producer
  must honor; implicit loss is detector-only), the projection lineage, the
  raw-eval prohibition, and the worked examples.

- Scientific object fabric under the new `srl.semantic` package (WP-B11): six
  scientific object types with JSON Schema 2020-12 documents under
  `src/srl/contracts/schemas/v1/` and typed Python validators. `ScientificClaim/v1`
  (`scientific-claim.json`) — a typed statement under epistemic discipline with
  `claim_class`/`claim_status`/`epistemic_source`/`support_refs`, encoding the
  critical invariant that an `established_law_reference` REQUIRES
  `epistemic_source='literature'` and a non-empty `support_refs` (and that a
  `candidate_hypothesis` cannot carry `claim_status='supported'` without
  `support_refs`) via `allOf`/`if-then` and re-enforced in Python by
  `srl.semantic.claims.validate` (raising `ClaimInvariantError`, fail reason
  `CONTRACT_INVALID`, defense in depth); `MathIR/v1` (`math-ir.json`) — a
  mathematical IR expression tree over a restricted OpenMath-style allowlist
  (`srl.semantic.ir.MATH_IR_ALLOWLIST`, 39 operators across 9 content
  dictionaries arith1/relation1/logic1/set1/calculus1/linalg1/nums1/fns1/stats1)
  enumerated in the schema's `op.enum` and re-checked by
  `srl.semantic.ir.validate_expression`, with nullary nums1 symbols
  (`pi`/`e`/`i`/`infinity`) carried as applications and never as floats, plus
  resource guards (depth 64, node-count 10000) raising
  `IRResourceLimitError`, and an `UnsupportedOperatorError` (fail reason
  `IR_UNSUPPORTED`) distinguishing unknown-name-in-known-cd from unknown-cd;
  `SymbolTable/v1`, `ConditionSet/v1`, `ConstantRef/v1`, and
  `ModelInterface/v1` (`symbol-table.json`, `condition-set.json`,
  `constant-ref.json`, `model-interface.json`); all nine schemas registered in
  the loader (`srl.contracts.schema`) and documented in the schemas README.
- `srl.semantic.fabric.mint_object(object_type, payload, parents=…,
  created_utc=…)` wrapping a type-specific payload into a
  `ScientificObjectEnvelope/v1` with a computed `object_id` (sha256 over the
  canonical encoding of the envelope without the id), provenance, and the two
  safety consts, validated against the envelope schema.
- Conformance vectors under `fixtures/conformance/object_fabric/`: 7 positive
  (Newton's second law as MathIR and as an established-law claim, a candidate
  hypothesis, a symbol table with units, a ConstantRef, a ConditionSet, a
  harmonic-oscillator ModelInterface) and 7 negative (unknown operator, unknown
  content dictionary, bool-as-int in exponents, established-law without
  literature source, candidate-supported without support, IR depth bomb, IR
  node flood), with a `manifest.json` and `README.md`.
- `scripts/checks/wp11-gate.py` running the four WP-B11 checks (restricted
  allowlist enforced at schema + python layer; fixture-scoped dimensional
  consistency `kg.m.s-2`≡`N` accepted and `kg` vs `m` rejected; candidate
  claim cannot be typed as established law at both layers; all schemas
  meta-valid and positive fixtures validate) and emitting a `GateReceipt/v1`;
  a `schema-compat` job in `.github/workflows/contracts.yml` (backed by
  `scripts/checks/schema-compat.py`) verifying every `schemas/v1/*.json`
  meta-validates and the loader registry is complete (no on-disk orphans,
  registry count == disk count, unique `$id`s); an `object-fabric-gate
  (WP-B11)` job in `.github/workflows/ci.yml`; a `Makefile` `gate-wp11` target.
- Unit and property tests under `tests/semantic/` (`test_math_ir.py`,
  `test_claims.py`, `test_fabric.py`) pinning the allowlist, the two failure
  modes, the resource guards, identity determinism, the claim invariants, and
  fixture round-trips, plus Hypothesis properties that random allowlist-only
  trees always validate and random ops outside the allowlist always raise
  `IR_UNSUPPORTED`.
- `docs/contracts/object-fabric.md` documenting the six object types, the
  restricted MathIR allowlist, the invariants, the prohibited collapses
  (candidate claim != established law; SAT/UNSAT != empirical truth), and the
  worked examples.

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
- Deterministic claim router and plan builder under `srl.planning` (WP-B14):
  `ScienceLabRunRequest/v1` (`science-lab-run-request.json`) — a request to run
  the science lab against a `ScientificClaim`, carrying the requested capability
  profiles, the resource class, and the seed/threads policy, with the two
  request-specific safety consts pinned
  (`prospective_holdout_materialization_allowed=false`,
  `status_promotion_allowed=false`) — a request is an intent, never authority;
  `ScienceLabPlan/v1` (`science-lab-plan.json`) — a deterministic execution plan
  produced by the planner, a DAG of steps in topological order with typed
  selection states (`SELECTED` / `EXCLUDED_TYPED` / `NOT_APPLICABLE` /
  `WAIT_CAPABILITY`), resource estimates, dependency edges, and the
  `policy_hash` / `catalog_hash` it was built against; both schemas registered in
  the loader (`srl.contracts.schema`).
- The 15 capability profiles (`srl.planning.profiles.SCIENCE_LAB_PROFILES`):
  `algebra_exact`, `symbolic_law`, `dynamics`, `geometry_tda`,
  `causal_time_series`, `uncertainty`, `optimization`, `formal_protocol`,
  `literature`, `theorem_or_proof_obligation`,
  `nonlinear_continuous_or_hybrid_constraint`, `executable_ode_dae_sde_model`,
  `pde_variational_model`, `model_composition`, `literature_extraction`, each
  with typed `required_inputs` (MathIR cds / object types),
  `produced_evidence_axes`, and `default_resource_class`.
- A deterministic claim classifier (`srl.planning.classifier.classify`): a pure
  function with an explicit rule table; every decision backed by a `rule_trace`.
- An in-repo capability catalog (`srl.planning.catalog`, `catalog_data.json`):
  a content-addressed map from the 15 profiles to future adapters, marking every
  adapter `future` or `remote_required` (no scientific backend ships in this
  codebase); `catalog_digest` = sha256 over the canonical bytes.
- A deterministic router (`srl.planning.router.route`): produces a
  `RoutingDecision` over all 15 profiles; `remote_required` profiles never fall
  back to a local adapter (absence yields `WAIT_CAPABILITY`, never a silent
  substitute).
- A deterministic plan builder (`srl.planning.planner.build_plan`): dependency
  DAG with topological order and cycle detection (raising `PlanError`,
  `CONTRACT_INVALID`), resource admission against per-class caps (default wall
  300s / rss 1.5 GiB / scratch 4 GiB; exception wall 900s / rss 2 GiB) with
  overflow raising `ResourceAdmissionError` (`WAIT_REMOTE_EXECUTOR`), and
  `plan_digest` over canonical bytes; byte-identical for byte-identical inputs
  (determinism).
- Two new typed fail reasons in `automation/fail-reasons.json`: `WAIT_CAPABILITY`
  (a required capability has no available adapter) and `WAIT_REMOTE_EXECUTOR` (a
  plan's summed estimates exceed the admission caps).
- Conformance vectors under `fixtures/conformance/planning/`: 3 positive
  scenarios (geometry TDA `WAIT_CAPABILITY`, a 3-step composition DAG, explicit
  `EXCLUDED_TYPED`) and 3 negative scenarios (cyclic dependency, resource
  overflow, remote_required no-fallback), with a manifest and README.
- `scripts/checks/wp14-gate.py` running the four WP-B14 checks (B14-01
  determinism across 3 rebuilds incl. shuffled input keys, B14-02 decision
  coverage of all 15 profiles, B14-03 no silent fallback for remote_required,
  B14-04 unknown capability -> `WAIT_CAPABILITY` + cyclic-dependency and
  resource-overflow negatives) and printing a `GateReceipt/v1` receipt;
  `scripts/checks/router-determinism.py` rebuilding the golden plan twice and
  comparing bytes.
- `make gate-wp14` and `make router-determinism` targets; a
  `router-planner-gate (WP-B14)` job in `.github/workflows/ci.yml`; a
  `router_determinism` job in `.github/workflows/contracts.yml`.
- Unit tests under `tests/planning/` (`test_classifier.py`, `test_router.py`,
  `test_planner.py`) covering rule-trace determinism, all four selection states,
  no-fallback, DAG order, cycle detection, admission, digest stability, and a
  Hypothesis property test that random valid requests produce deterministic
  plans.
- `docs/architecture/router-planner.md` documenting the profiles, decision
  states, honesty rules (a plan is not evidence; `WAIT_CAPABILITY` is honest
  absence; no silent fallback), admission policy, and determinism.

### Fixed

- `srl.semantic.claims.claim_id` is now idempotent: it strips the claim's own
  `claim_id` field before hashing, so building the same claim twice (with or
  without a pre-populated id) yields the same id. Previously `claim_id` hashed
  the claim including its own `claim_id` field (the content-addressing helper
  only guards a field literally named `object_id`), producing a
  self-referential fixed point and breaking the property that two independent
  builders of the same claim compute the same id — the same class of bug fixed
  earlier in `transforms.receipt_id` and `adapter_profiles.profile_id`.
  `validate` now also rejects a present `claim_id` that was computed over the
  claim including itself (new `claim_id_consistent` invariant, fail reason
  `CONTRACT_INVALID`, defense in depth). Regression tests pin both directions.

### Changed

- `.github/workflows/ci.yml` adds the `evidence-model-gate` job (WP-B13),
  previously added the `transformations-gate` job (WP-B12), earlier added the
  `object-fabric-gate` job (WP-B11), the `canonical-json-gate` job (WP-B10),
  and the `autonomy-contracts-gate` job (WP-A03); the existing lint,
  typecheck, unit, and package jobs are unchanged.
  `.github/workflows/contracts.yml` adds the `receipt-invariants` job (WP-B13)
  verifying every receipt schema pins the safety consts, previously added the
  `schema-compat` job (WP-B11) verifying the loader registry is complete.
- The schema loader registry (`srl.contracts.schema._SCHEMA_NAME_TO_FILE`) and
  the schemas README table now carry the four new WP-B13 schemas
  (`EvidenceAssessment`, `ScienceLabEngineReceipt`,
  `ScienceLabValidationReceipt`, `ScienceLabRunReceipt`), previously the two
  WP-B12 schemas (`AdapterSemanticProfile`, `TransformationReceipt`), earlier
  the six WP-B11 schemas (`ScientificClaim`, `MathIR`, `SymbolTable`,
  `ConditionSet`, `ConstantRef`, `ModelInterface`); the existing `ArtifactRef`,
  `ScientificObjectEnvelope`, and `GateReceipt` schemas are unchanged
  (additive only). `srl.semantic.fabric.SUPPORTED_OBJECT_TYPES` widens from
  eight to twelve kinds, adding `evidence_assessment`, `engine_receipt`,
  `validation_receipt`, and `run_receipt`; the envelope's `object_type` enum
  widens additively to include `engine_receipt` and `validation_receipt`
  (the `evidence_assessment` and `run_receipt` kinds were already present).
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

## [0.1.0] - 2026-07-28


Release contents: public repository with protected main and 22 required
checks; canonical JSON and SHA-256 object identity; Scientific IR
(restricted OpenMath allowlist); object fabric; transformation receipts
with explicit lossiness; 11-axis orthogonal evidence model; deterministic
claim router and plan builder; thirty-task public conformance corpus
(30/30 expected outcomes matched); AutonomyPolicy/v2 governance; M1
resource policy; T7 storage identity guard; fixed-entrypoint bounded
runner with sandbox; weekly-deep scheduled verification.

The first milestone target (`v0.1.0`) covers the repository, contracts, the
Scientific IR, and conformance. It is tracked as a GitHub milestone and is
released from this `Unreleased` section once the acceptance checks pass.
