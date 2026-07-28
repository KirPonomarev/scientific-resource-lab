# ADR 0002: JSON Schema library for contract validation

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-B10 (Canonical JSON and identifiers)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

The scientific contracts layer (WP-B10) ships JSON Schema 2020-12 documents
for `ArtifactRef/v1`, `ScientificObjectEnvelope/v1`, and `GateReceipt/v1`
(under `src/srl/contracts/schemas/v1/`). The runtime must:

1. **Meta-validate** every shipped schema against the 2020-12 meta-schema, so
   a malformed or dialect-drifted schema cannot silently accept bad data.
2. **Validate** JSON instances against a named schema, reporting the failing
   JSON path so a caller can point at the exact field that failed.

Through Phase A the `srl` package was standard-library only. Adding schema
validation introduces the project's first runtime third-party dependency. The
choice affects:

1. Whether the 2020-12 keyword set, subschema composition, and error-path
   accumulation are handled correctly (they are intricate and easy to get
   wrong by hand).
2. The supply-chain surface (a runtime dependency is imported by every
   consumer of `srl.contracts`).
3. How easily new schemas and keywords can be adopted as the scientific IR
   grows.
4. Lockfile and reproducibility posture (`uv.lock` must pin the library and
   its transitive dependencies).

## Alternatives considered

### 1. `jsonschema` (chosen)

- The reference Python implementation of JSON Schema; maintained under
  `python-jsonschema/jsonschema` and the PyPA umbrella.
- Full JSON Schema 2020-12 support via `Draft202012Validator`, including the
  bundled meta-schema (fetched from the `jsonschema-specifications`
  distribution, so meta-validation works offline).
- Reports errors with a JSON path (`json_path`) and the failing keyword
  (`validator`), which the SRL `ContractValidationError` surfaces directly.
- Actively maintained, MIT-licensed, widely deployed, and depended on by a
  large part of the Python packaging and data ecosystem.
- Adds a small set of transitive dependencies (`attrs`, `referencing`,
  `rpds-py`, `jsonschema-specifications`), all pinned in `uv.lock`.

### 2. No validator (manual structural checks only)

- Keep the package stdlib-only and hand-roll the per-field checks (as the
  autonomy primitives in `src/srl/autonomy/` do).
- Acceptable for the narrow Phase-A policy/envelope shapes, but does not
  scale to the scientific IR: the 2020-12 keyword set (`allOf`, `oneOf`,
  `$ref`, `pattern`, `unevaluatedProperties`, conditional schemas) and the
  meta-schema conformance check would have to be reimplemented and kept in
  sync with the specification by hand.
- Rejects the ability to ship authoritative schema documents and validate
  against them; the schemas would become documentation rather than the
  executable contract.

### 3. Hand-rolled minimal validator

- Implement a small validator covering only the keywords SRL uses today
  (`type`, `const`, `enum`, `pattern`, `required`, `additionalProperties`,
  `properties`, `items`, `minimum`).
- Avoids the runtime dependency, but (a) must track specification drift
  manually, (b) cannot meta-validate shipped schemas against the 2020-12
  meta-schema (the whole point of meta-validation is to use the reference
  meta-schema), and (c) accumulates error paths incorrectly in edge cases
  unless reimplemented carefully.
- Trading ~one well-tested dependency for a permanent in-house maintenance
  burden with no feature headroom.

### 4. `fastjsonschema`

- Compiles schemas to Python source for speed; good for hot-path validation.
- Generates code rather than interpreting the schema, which complicates
  meta-validation and dynamic loading from `importlib.resources`, and produces
  less structured error objects than `jsonschema`.
- Speed is not a constraint for SRL contract validation (it runs at admission
  time, not in a tight loop), so the complexity is not justified.

## Decision

Adopt **`jsonschema`** as the runtime schema-validation library for
`srl.contracts`.

Configuration (see `pyproject.toml`):

```toml
[project]
dependencies = ["jsonschema>=4.23"]
```

The dev group adds `types-jsonschema` so `mypy --strict` has stubs (the
`jsonschema` distribution does not ship a `py.typed` marker):

```toml
[dependency-groups]
dev = [
    # ...
    "types-jsonschema>=4.23",
]
```

The schema loader (`src/srl/contracts/schema.py`) uses
`Draft202012Validator` both for meta-validation (every shipped schema is
checked against the 2020-12 meta-schema on first load) and for instance
validation. The 2020-12 meta-schema is fetched from `jsonschema`'s bundled
registry and memoized, so meta-validation works offline and pays its cost
once per process.

## Consequences

### Positive

- Shipped schema documents are the executable contract: a consumer can load
  and validate against exactly the schema that shipped with the installed
  wheel (via `importlib.resources`), with no loose-file drift.
- Meta-validation catches a malformed or dialect-drifted schema before it
  silently accepts bad data; the `contracts` CI workflow enforces this on
  every pull request.
- Structured errors: `ContractValidationError` carries the JSON path and the
  failing keyword, giving actionable diagnostics.
- Head room for the scientific IR: `allOf`/`oneOf`/`$ref`/conditional schemas
  are available as the object-type-specific sub-schemas are authored in later
  work packages.

### Negative

- Adds `jsonschema` as the project's first runtime third-party dependency,
  with four transitive packages (`attrs`, `referencing`, `rpds-py`,
  `jsonschema-specifications`). All are pinned in `uv.lock`.
- The `srl.contracts` package is no longer stdlib-only, so gate scripts that
  import it must run under `uv run python` (the WP-A03 autonomy gate remains
  stdlib-only and runs under bare `python3`).

### Security impact

`jsonschema` is imported only at validation time and does not touch the SRL
runner boundary, the content-addressed store, pack materialization, or the
disclosure sanitizer. It performs no I/O of its own in SRL's usage (schemas
are loaded from packaged resources). Pinning a lower bound (`>=4.23`) and
recording the resolved version in `uv.lock` bounds the supply-chain surface.
Reversibility is covered below.

### Resource impact

Negligible. Schema loading and meta-validation run once per process (memoized
via `lru_cache`); instance validation runs at admission time. All well within
the 15-minute CI budget.

### License impact

`jsonschema` is distributed under the MIT license, compatible with this
project's Apache-2.0 license. The transitive dependencies (`attrs`,
`referencing`, `rpds-py`, `jsonschema-specifications`) are likewise
MIT-licensed. No third-party attribution is required in `NOTICE` for a
runtime tool dependency beyond the existing baseline, but the licenses are
captured in `uv.lock` for audit.

## Reversibility

Reversible. Removing `jsonschema` is a `pyproject.toml` change (drop the
dependency and the `types-jsonschema` dev stub), followed by replacing
`src/srl/contracts/schema.py` with a hand-rolled or alternative validator.
Because the public surface (`load_schema`, `validate`, `meta_validate_all`,
`ContractValidationError`) is stable, callers would not need to change. The
shipped schema documents are independent of the validator implementation.

## Evidence

- `pyproject.toml` declares `jsonschema>=4.23` in `[project].dependencies`
  and `types-jsonschema>=4.23` in the `dev` group.
- `uv.lock` pins `jsonschema` and its transitive dependencies.
- `src/srl/contracts/schema.py` meta-validates every shipped schema against
  the 2020-12 meta-schema on first load, and validates instances with
  `Draft202012Validator`.
- `scripts/checks/schema-meta-validate.py` and the `contracts` CI workflow
  enforce meta-validation on every pull request.
- The WP-B10 gate (`scripts/checks/wp10-gate.py`) reports the loaded schema
  set as evidence.
