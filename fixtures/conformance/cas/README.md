# CAS transaction engine conformance vectors (WP-C21)

This directory holds the conformance documentation for the SRL CAS transaction
engine (`srl.cas.engine`, `srl.cas.fsck`, `srl.cas.descriptors`). **There are no
binary fixture files in this directory by design.**

## No binary fixtures — deterministic blobs are generated inline

The WP-C21 acceptance gate (`scripts/checks/wp21-gate.py`) and the unit tests
(`tests/cas/test_engine*.py`, `tests/cas/test_fsck.py`) generate every test blob
inline as a deterministic Python byte string. This keeps the conformance
directory free of opaque binary artifacts:

- the test payloads are short, human-readable ASCII (`b"cas-engine-..."`) so a
  reviewer can see exactly what bytes are being ingested;
- the corruption and crash injection cases mutate these inline bytes (flip one
  byte, patch `os.replace`) rather than shipping pre-corrupted binaries;
- the 1,000-ingest stress test uses a 256-byte inline payload (`b"k" * 256`)
  generated at run time.

This mirrors the WP-C20 storage directory's approach for the tiny fixture, but
goes further: WP-C21 ships **zero** blob files because the engine's invariants
(transaction order, receipt-last, dedup, crash safety) are exercised over
synthetic content, not over curated vectors.

## What lives here

This README and the manifest (`manifest.json`) are the only files. They document
the six acceptance checks the gate runs (C21-01 through C21-06) and the inline
payloads each uses, so a reviewer can reproduce a check without running it.

## The six WP-C21 checks

| Check  | What it asserts                                                                 | Inline payload                          |
|--------|---------------------------------------------------------------------------------|-----------------------------------------|
| C21-01 | No overwrite: two ingests of the same bytes produce a single object and a dedup receipt. | `b"c21-01-no-overwrite"`               |
| C21-02 | Typed corruption: flipping one byte in a published object is detected by fsck as `CAS_INTEGRITY_FAILURE`. | `b"c21-02-typed-corruption"`           |
| C21-03 | Interrupted ingest publishes no final receipt (patch `os.replace` to raise); the partial is reported by `recover_partials`. | `b"c21-03-interrupted"`                |
| C21-04 | 1,000 repeated deduplicating ingests produce exactly one object file and zero overwrites. | `b"k" * 256`                           |
| C21-05 | Crash at every publish boundary (after tmp write, after fsync, after replace, after descriptor) leaves old-or-new valid state, never a partial visible object. | `b"c21-05-crash-boundary"`             |
| C21-06 | Read-back corruption injection (patch first read-back to return wrong hash) -> ingest fails, no publish. | `b"c21-06-readback-injection"`         |

See `docs/architecture/cas-engine.md` for the transaction order, the
receipt-last invariant, the crash matrix, and the path-safety defense.
