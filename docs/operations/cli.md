# JSON-first CLI surface (WP-F50)

This document describes the `srlab` command-line interface introduced in WP-F50.
Every path emits **one canonical JSON record** on stdout; command errors emit a
record on stderr. The dispatcher is an explicit table (no `argparse`) so the
command contract is auditable and easy to keep deterministic.

> A green CLI result means the command **completed** and produced a typed
> receipt. It never means a scientific claim is *supported* or that an
> authority was granted. The CLI is a control surface, not an evidence surface.

## Scope

WP-F50 adds namespaced commands on top of the legacy Phase-A `doctor` and
`version` top-level commands. The legacy commands are kept unchanged so existing
A02 tests continue to pass.

| Concern            | Commands                                | Python module                |
|--------------------|-----------------------------------------|------------------------------|
| Contract schemas   | `schema validate`                       | `srl.contracts.schema`       |
| Claim admission    | `claim validate`                        | `srl.semantic.claims`        |
| Planning           | `plan build`, `plan inspect`            | `srl.planning`               |
| Artifact store     | `cas status`, `cas verify`, `cas fsck`  | `srl.cas.store`              |
| Bounded execution  | `run execute`, `run verify`             | `srl.execution.runner`       |
| Knowledge query    | `knowledge query`                       | `srl.knowledge.retriever`    |
| Capability catalog | `catalog list`, `catalog inspect`       | `srl.planning.catalog`       |
| Acceptance gate    | `GateReceipt/v1` (WP-F50)              | `scripts/checks/wp50-gate.py` |

The CLI module is `src/srl/cli.py`. It is the only owned path changed in WP-F50.

## JSON-first contract

- **One line per invocation.** Every successful command prints exactly one JSON
  line to stdout, terminated by a newline. Errors print one JSON line to stderr.
- **Canonical JSON.** Output is sorted by key, uses compact separators (`","` and
  `":"`), and is UTF-8. Re-parsing and re-serializing with the same canonical
  rules reproduces the same bytes.
- **Typed `fail_reason`.** Errors carry a `fail_reason` field (e.g.
  `CONTRACT_INVALID`, `ORPHAN_PROCESS_DETECTED`, `WAIT_ENVIRONMENT`). The top
  of `src/srl/cli.py` documents the exit-code semantics; the bottom of the file
  documents the `ErrorReport/v1` shape.

## Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Command completed and a receipt was emitted. |
| `1`  | A command-level failure (e.g. bad input, missing file, validation error). |
| `2`  | Unknown or missing command (legacy A02 behavior keeps the report on stdout). |
| `3`  | `cas fsck` found corruption (`failed_digests` non-empty). |
| `4`  | `run execute` hit a runner policy violation (e.g. orphan process). |

## Global options

Two options are parsed before any subcommand dispatch:

- `--cache-dir <path>` — required for `knowledge query`; used for the budgeted
  retriever's persistent cache and rate-limiter state.
- `--transport <path>` — optional for `knowledge query`; provides a fixture file
  that the command returns as the HTTPS response, so tests and gates can run
  with no network.

Both `--option value` and `--option=value` forms are accepted. These options may
appear anywhere on the command line.

## Commands

### Legacy top-level commands

```bash
srlab doctor      # DoctorReport/v1
srlab version     # VersionReport/v1
```

These remain unchanged from A02 and write to stdout.

### `schema validate <schema-name> <file>`

Validates a JSON file against a shipped contract schema. Known schema names are
managed by `srl.contracts.schema` (e.g. `ScientificClaim`,
`ScienceLabRunRequest`, `ScienceLabPlan`, `GateReceipt`).

```bash
srlab schema validate ScientificClaim claim.json
```

On success:

```json
{"file": "claim.json", "schema_name": "ScientificClaim", "schema_version": "SchemaValidationReport/v1", "valid": true}
```

On failure the error is written to stderr with `fail_reason: CONTRACT_INVALID`.

### `claim validate <file>`

Validates a `ScientificClaim/v1` JSON file against both the JSON Schema and the
Python invariant layer in `srl.semantic.claims`.

```bash
srlab claim validate claim.json
```

On success:

```json
{"claim_class": "candidate_hypothesis", "claim_status": "proposed", "file": "claim.json", "schema_version": "ClaimValidationReport/v1", "valid": true}
```

### `plan build <bundle-file>` and `plan inspect <file>`

`plan build` takes a bundle file containing a `ScienceLabRunRequest/v1` and a
`ScientificClaim/v1`:

```json
{
  "request": {"schema_version": "ScienceLabRunRequest/v1", ...},
  "claim": {"schema_version": "ScientificClaim/v1", ...}
}
```

It runs the classifier, router, and planner and emits a `PlanBuildReport/v1`
containing the full `ScienceLabPlan/v1`.

```bash
srlab plan build bundle.json
```

`plan inspect` reads a `ScienceLabPlan/v1` and reports step counts and selected
profiles.

```bash
srlab plan inspect plan.json
```

### `cas status|verify|fsck <root>`

Operate on a `LocalArtifactStore` rooted at `<root>`.

- `status` — counts objects and failed items.
- `verify` — returns `valid: true` only if every object passes integrity.
- `fsck` — returns `failed_digests`; exits `3` if any corruption is found.

```bash
srlab cas status /tmp/store
srlab cas verify /tmp/store
srlab cas fsck /tmp/store
```

### `run execute <run-spec-file>` and `run verify <receipt-file>`

`run execute` runs a bounded adapter via the WP-D31 runner using the shipped M1
resource policy. The run spec is:

```json
{"adapter_id": "echo.v1", "input": {"value": 42}}
```

```bash
srlab run execute run.json
```

The runner returns a `RunExecutionReport/v1` on stdout. A policy violation (e.g.
an orphan process) exits `4` with `fail_reason: ORPHAN_PROCESS_DETECTED`.

`run verify` checks a `RunReceipt/v1` against its recorded `output_path`:

```bash
srlab run verify receipt.json
```

### `knowledge query <endpoint-id> <path> [params-json]`

Runs a budgeted API query against a P0 endpoint. The command is **offline-safe**:
if no network is available and no `--transport` fixture is provided, it emits a
`WAIT_ENVIRONMENT` typed error on stderr rather than crashing.

```bash
srlab knowledge query openalex /works '{"q": "symplectic geometry"}' \
  --cache-dir /tmp/knowledge-cache
```

For hermetic testing or gate runs, pass a fixture file:

```bash
srlab knowledge query openalex /works '{}' \
  --cache-dir /tmp/knowledge-cache \
  --transport fixtures/conformance/knowledge/payloads/openalex_works.json
```

On success the stdout record is a `KnowledgeQueryReport/v1` containing the full
`QueryReceipt/v1`.

### `catalog list` and `catalog inspect`

View the shipped capability catalog.

```bash
srlab catalog list      # CapabilityCatalogList/v1
srlab catalog inspect   # CapabilityCatalogReport/v1
```

## Unknown and missing commands

An unknown top-level command or no command at all exits `2` and writes an
`ErrorReport/v1` to stdout (A02 compatibility). An unknown subcommand (e.g.
`schema nope`) also exits `2` but writes the error to stderr.

```bash
$ srlab nope
{"command": "nope", "error": "unknown command", "fail_reason": "CONTRACT_INVALID", "schema_version": "ErrorReport/v1"}
$ echo $?
2
```

## Acceptance gate

Run the WP-F50 gate with `uv` (recommended) or with a bare Python interpreter
after making dependencies available:

```bash
uv run python scripts/checks/wp50-gate.py
```

The gate prints one canonical `GateReceipt/v1` JSON line and exits `0` only if
every check (F50-01 through F50-09) PASSes. No check makes a live network call.
The CI workflow `.github/workflows/cli.yml` runs the gate on every PR and push
to `main`.

## CI

`.github/workflows/cli.yml` runs:

1. `uv sync --locked`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run mypy`
5. `uv run pytest tests/unit/test_cli.py -q`
6. `uv run pytest tests/cli/test_commands.py -q`
7. `uv run python scripts/checks/wp50-gate.py`

All steps must pass before a WP-F50 PR is merged.
