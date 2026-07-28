# SRL schema documents (v1)

This directory ships the JSON Schema 2020-12 documents for SRL contracts.
Every schema here is a **packaged** artifact: it is loaded at runtime by
`srl.contracts.schema.load_schema` via `importlib.resources`, so the schema a
running program validates against is the schema that shipped with the
installed package — never a loose file a contributor may have edited locally.

## Schema dialect

All documents declare:

```json
{ "$schema": "https://json-schema.org/draft/2020-12/schema" }
```

JSON Schema 2020-12 is the current specification as of WP-B10. It is the only
dialect the loader meta-validates against (see
`src/srl/contracts/schema.py` and `docs/adr/0002-jsonschema-library.md`).

## Canonical $id

Every schema carries a canonical `$id` of the form:

```
https://schemas.srlab.dev/v1/<Name>.json
```

`<Name>` is the PascalCase schema title with the `/vN` suffix stripped
(`ArtifactRef`, `ScientificObjectEnvelope`, `GateReceipt`). The `$id` is the
stable public address of the schema; it does not need to be resolvable over
HTTP today, but it must be unique and must not change for a given shape.

## Files present (v1)

| File                              | Title                         | Purpose                                            |
|-----------------------------------|-------------------------------|----------------------------------------------------|
| `artifact-ref.json`               | `ArtifactRef/v1`              | Portable, content-addressed reference to bytes.    |
| `scientific-object-envelope.json` | `ScientificObjectEnvelope/v1` | Base envelope for every scientific object.         |
| `gate-receipt.json`               | `GateReceipt/v1`              | Receipt emitted by an acceptance gate.             |
| `scientific-claim.json`           | `ScientificClaim/v1`          | A typed scientific statement under epistemic discipline. |
| `math-ir.json`                    | `MathIR/v1`                   | A mathematical IR expression tree over a restricted OpenMath allowlist. |
| `symbol-table.json`               | `SymbolTable/v1`              | A table of symbols (id/name/role/domain/unit).     |
| `condition-set.json`              | `ConditionSet/v1`             | A set of assumptions (domain/positivity/...) attached to a model. |
| `constant-ref.json`               | `ConstantRef/v1`              | A reference to a physical/mathematical constant from a named source. |
| `model-interface.json`            | `ModelInterface/v1`           | A typed interface to a scientific model (ode/dae/...). |
| `adapter-semantic-profile.json`   | `AdapterSemanticProfile/v1`   | A typed semantic profile for a backend adapter (supported_cds subset of MATH_IR_ALLOWLIST, unsupported-feature behavior, determinism, network posture, SPDX license). |
| `transformation-receipt.json`     | `TransformationReceipt/v1`    | A receipt binding source->target by a named transform, carrying the honest cost (LOSSLESS / LOSSY_EXPLICIT / LOSSY_IMPLICIT_DETECTED) and lineage. |
| `evidence-assessment.json`        | `EvidenceAssessment/v1`       | A typed assessment of the evidence behind a ScientificClaim on 11 ORTHOGONAL axes (capability / exercise / engine / scientific / formal / statistical / causal / algorithmic / empirical / authority), enforcing orthogonality (probe is not compute; formal is not empirical; algorithmic is not independent; exportable is not admitted). |
| `science-lab-engine-receipt.json` | `ScienceLabEngineReceipt/v1`  | A receipt proving a backend engine ran (or failed) for a run request, carrying the honest exercise_level and engine_execution (an import_probe cannot yield completed-and-computed semantics). |
| `science-lab-validation-receipt.json` | `ScienceLabValidationReceipt/v1` | A receipt proving an independent validator checked an engine run's output, carrying the scientific_check and formal_check (formal_check=proven REQUIRES a non-null formal_certificate_ref). |
| `science-lab-run-receipt.json`    | `ScienceLabRunReceipt/v1`     | A receipt tying an engine run and its optional validation into a single terminal run outcome with aggregate resource usage. |
| `science-lab-run-request.json`    | `ScienceLabRunRequest/v1`     | A request to run the science lab against a ScientificClaim: the router/planner input (claim, requested profiles, resource class, seed/threads policy). A request is an intent, never authority (prospective_holdout_materialization_allowed and status_promotion_allowed pinned false). |
| `science-lab-plan.json`           | `ScienceLabPlan/v1`           | A deterministic execution plan produced by the planner: a DAG of capability-profile steps with typed selection states (SELECTED / EXCLUDED_TYPED / NOT_APPLICABLE / WAIT_CAPABILITY), resource estimates, and dependency edges. A plan is not evidence (grants_authority pinned false). |
| `pilot-spec.json`                 | `PilotSpec/v1`                | A retrospective pilot specification: the public, content-addressed description of a retrospective analysis over ALREADY-EXTANT artifacts (sha256 digests only, never paths), with null generators, seed policy, and the two safety consts pinned false (a pilot cannot promote status, materialize a prospective holdout, or grant authority). |

## Naming and compatibility policy

SRL schemas evolve under a **compat-first** policy modeled on Semantic
Versioning, applied per-schema via the `vN` suffix in the title and `$id`.

### Additive optional changes -> minor (keep `vN`)

Adding a new **optional** property (not in `required`), widening an `enum`
with a new member, relaxing a `pattern`/`minimum`, or adding a new
`$id`-addressable sub-schema is **backward-compatible**. Existing valid
instances remain valid. These changes stay under the same `vN` (e.g.
`ArtifactRef/v1` stays `ArtifactRef/v1`).

Document every additive change in `CHANGELOG.md` under the schema's title.

### Breaking changes -> major (bump `vN`)

Any of the following is a **breaking** change and requires a new major schema
document (e.g. `ArtifactRef/v2`), keeping the old one in place for legacy
consumers:

- adding a property to `required`;
- removing or renaming a property;
- narrowing an `enum` (removing members) or a `pattern`/`minimum`/`maximum`;
- changing `additionalProperties` from `true`/absent to `false`;
- changing a `const` value;
- changing the `$id` of an existing shape.

The old `vN` document must remain loadable so historical artifacts keep
validating against the schema they were authored under. Do not edit a shipped
`vN` document in a breaking way in place — add a new file and bump the suffix.

### The two safety consts are never relaxed

`ScientificObjectEnvelope/v1` pins `canonical_writes` to `0` and
`grants_authority` to `false`. These are governance invariants (see
`GOVERNANCE.md`): an SRL scientific object is immutable once authored and
never grants authority on its own. Any schema change that would admit a
non-zero `canonical_writes` or a `true` `grants_authority` is a governance
change, not a schema-compatibility change, and follows the governance-change
workflow.

## Meta-validation

`scripts/checks/schema-meta-validate.py` loads every `schemas/v1/*.json` and
meta-validates it against the 2020-12 meta-schema. The `.github/workflows/contracts.yml`
workflow runs this check on every pull request. A schema that fails
meta-validation cannot land.
