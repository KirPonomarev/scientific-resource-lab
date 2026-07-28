# Run materializer and sealer (WP-D32, M1)

This document describes the run materializer and sealer introduced in WP-D32:
how a content-addressed run specification is staged into a private execution tree,
how the runner's output is sealed into the content-addressed store, and how the
final run receipt is written **last** with all digests bound and no host-local
paths.

> The engine receipt is **execution evidence**, not scientific validation. It
> records that the bounded runner reported `completed` or `failed`, how much wall
> time and RSS it consumed, and the content-addressed ids of the output objects.
> It does not claim that a scientific assertion is *supported* (see
> `GOVERNANCE.md` for the evidence rules).

## Scope

WP-D32 layers the materializer and sealer on top of the WP-D31 bounded runner and
the WP-C20/C21 content-addressed store. The flow is intentionally three distinct
steps so that each step has a single, checkable failure mode:

| Concern | Artifact | Python module |
|---------|----------|---------------|
| Resolve and stage exact refs | `StagedRun` | `srl.execution.materialize` |
| Bounded execution | `RunOutcome` | `srl.execution.runner` |
| Validate, ingest, receipt | `SealedRun` | `srl.execution.sealer` |
| Acceptance gate | `GateReceipt/v1` (WP-D32) | `scripts/checks/wp32-gate.py` |

## Flow

A run specification is a plain dict with three keys:

```python
{
    "adapter_id": "echo.v1",
    "input_payloads": {"input.json": "sha256:<64 hex>"},
    "pack_ref": "sha256:<64 hex>" | None,
}
```

`input_payloads` maps a **name** to a `sha256:<64 hex>` digest. The digest is an
exact, pinned reference to a content-addressed object in the store. The
materializer (`srl.execution.materialize.materialize_run`):

1. Resolves every input digest from the store (`store.has` then `store.get`).
   A digest that is malformed or not present in the store is an **unpinned
   reference** and aborts with `CONTRACT_INVALID`.
2. Creates a fresh staging directory under `staging_root` (`tempfile.mkdtemp`).
3. Copies the resolved bytes into the staging tree under the given name.
4. Re-hashes the staged bytes and compares them to the declared digest. A
   mismatch is a `CAS_INTEGRITY_FAILURE` and aborts; the fresh staging tree is
   removed so no half-staged run is left behind.
5. Makes every input file read-only (`chmod 0o400`).
6. Returns a `StagedRun` carrying the adapter id, the staging path, the bound
   input digests, and the optional pack digest.

A pack reference is resolved and staged the same way, but it is written as a
single blob (`pack.blob`) in the staging tree and is not made read-only (the
pack is the execution environment, not an input to the adapter).

After the run is staged, the bounded runner (`srl.execution.runner.run_adapter`)
executes the adapter. The sealer (`srl.execution.sealer.seal_run`) then:

1. Validates the runner's output with an **injected** output-schema validator.
   A validation failure produces **no** run receipt and **no** ingest; the
   caller's failure is `CONTRACT_INVALID`.
2. Canonicalizes the output and ingests it into the store (if the output is
   not `None`).
3. Builds a `ScienceLabEngineReceipt/v1` dict recording the adapter id, the
   `actual_compute` exercise level, whether the engine reported `completed` or
   `failed`, the wall seconds and RSS bytes, and the ids of the output objects.
4. Ingests the engine receipt into the store.
5. Builds a `ScienceLabRunReceipt/v1` dict that **binds** the input digests,
   the output digests, the engine receipt id, and the ids of the store
   descriptors published by this seal.
6. Writes the run receipt to `receipt_dir/<receipt_id>.json`.

## Receipt-last

The run receipt is the **last** artifact. Any failure before the receipt file is
written leaves no run receipt:

- malformed run specification → no receipt
- unpinned input/pack reference → no receipt
- hash mismatch on staging → no receipt
- output schema validation failure → no receipt and no ingest
- store ingest failure → no receipt (partial CAS objects may remain as evidence)
- run receipt write failure → no receipt

This is a hard invariant for both the materializer and the sealer. The materializer
cleans up the fresh staging tree on any failure; the sealer does not roll back CAS
objects because the store's receipt-last transaction already makes every
successful ingest durable and independently checkable.

## Redaction

The run receipt never contains an absolute host-local path. The store root is
recorded as a `redacted:<16 hex>` digest-prefix token via
`srl.cas.privacy.redact_store_path`. The staging path and the receipt directory
are not written into the receipt. The receipt only binds content-addressed ids:

- `input_digests`: name → `sha256:<64 hex>`
- `output_digests`: name → `sha256:<64 hex>`
- `engine_receipt_id`: `sha256:<64 hex>`
- `store_descriptor_ids`: list of `sha256:<64 hex>` ids published by this seal
- `store_root_redacted`: `redacted:<16 hex>`

A receipt containing a raw `/Users/`, `/Volumes/`, `/home/`, or Windows-style path
is a leak and a hard failure in the gate (`D32-05`).

## Honesty: engine receipt = execution evidence, not validation

The `ScienceLabEngineReceipt/v1` records what the bounded runner *reported*:

```json
{
    "schema_version": "ScienceLabEngineReceipt/v1",
    "receipt_id": "sha256:<64 hex>",
    "adapter_id": "echo.v1",
    "exercise_level": "actual_compute",
    "engine_execution": "completed",
    "wall_seconds": 0.123,
    "rss_bytes": 4096,
    "output_object_ids": ["sha256:<64 hex>"],
    "created_utc": "2026-07-28T12:00:00Z"
}
```

`engine_execution` is `completed` only when the runner's status is
`RunStatus.COMPLETED`. Every other status (`failed`, `timeout`, `resource_limit`,
`policy_violation`) is recorded as `failed`. The engine receipt does not try to
prove that the output is scientifically correct; it only proves that the
engine consumed the resources it claims and produced the outputs it claims. The
output schema validator is injected by the caller, so the sealer stays honest:
it records *that* the output validated, not *why* the validation is true.

The run receipt then binds the execution evidence to the staged inputs, the
published outputs, and the store descriptor ids, making the whole chain
content-addressed and auditable.

## Running the gate

```bash
python3 scripts/checks/wp32-gate.py          # bare (adds src/ to sys.path)
# or
uv run python scripts/checks/wp32-gate.py     # under the locked env
```

The gate prints one canonical `GateReceipt/v1` JSON line and exits 0 only if all
five checks PASS. The check IDs are D32-01 through D32-05 (see the gate's module
docstring). The gate uses the shipped `echo.v1` adapter and temporary stores; it
touches no real T7 volume or operator path.
