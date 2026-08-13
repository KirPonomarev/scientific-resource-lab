# Reliable Spool Transport

```text
SCOPE: SRL_INTERNAL_FILE_BACKED_SPOOL
NOT: TARGET_DUAL_WIRE
TARGET_DUAL_WIRE_RUNTIME_PROVEN: false
GRANTS_AUTHORITY: false
```

This document describes SRL's internal spool only. Existing Market and
Security adapter labels are inactive legacy transport assumptions. They do not
define the target cross-domain wire, prove Dual deployed, or authorize a
second global bus.

SRF transport V1 is a local, file-backed at-least-once spool. It does not add a
broker, daemon, shared database, SFTP channel, polling loop, or canonical writer.
Every state transition is a canonical JSON file written through `tmp`, flushed,
and committed with atomic rename.

## Layout

```text
spool/
  tmp/
  outbox/queued/
  inbox/imported/
  acks/
  signatures/
  quarantine/
  dlq/
```

Payload bytes are never embedded in a spool message. A `SpoolMessage/v1` carries
only immutable `sha256:` references, source/target cell names, D0/D1
classification, created time, an idempotency key, and the pinned invariants
`canonical_writes=0` and `grants_authority=false`.

## Acceptance

Receiver acceptance is fail-closed:

- schema validation must pass for `SpoolMessage/v1`;
- classification must be D0 or D1;
- detached signature verification must pass;
- the monotonic signature hash chain must match the latest accepted signature;
- TTL must not be expired;
- receiver-side dedup by message identity or idempotency key plus payload hash
  must not find a prior import.

Transport success writes the message to `inbox/imported/` and returns
`SpoolAck/v1` with `ACKNOWLEDGED`. That step proves transport acceptance only;
it does not determine whether the referenced payload is a proposal, evidence or
receipt. Duplicate delivery returns `DUPLICATE` without another import.
Malformed messages, missing signatures, signature failures, corrupt partial
files, and rejected hash-chain transitions go to `quarantine/`. Expired or
terminal delivery failures go to `dlq/` with `DeadLetterRecord/v1`.

## Signatures

The transport module exposes a native Ed25519 signer/verifier interface.
Production verification uses `Ed25519Verifier`, a public-key keyring and an
explicit revoked-key set. No repository secret or production private key is
stored here. Local conformance tests use ephemeral in-memory Ed25519 keys.

The legacy `test-hmac-sha256` fixture signer remains available only for
test/conformance namespaces. It is deliberately labelled and is rejected by the
production Ed25519 verifier.

Each detached signature records:

- signer cell;
- key id;
- message identity;
- monotonic sequence;
- previous signature file hash;
- signature value.

The receiver enforces the monotonic hash chain against the latest imported
signature. Replays, sequence rollback, stale predecessors and revoked keys are
quarantined. A signature proves transport authenticity only; it never grants
canonical write permission.

Native production key binding is recorded by
`docs/verification/srf-v3-7-a04-production-key-binding-receipt.json`. The
private Ed25519 key remains in the operator-controlled native secret store
outside git; the public receipt commits only the key id, public-key fingerprint,
secret-store reference hashes, receiver-keyring binding, and nonfixture
roundtrip evidence. Fixture HMAC and revoked-key signatures remain rejected in
production mode.

## Replay and Retry

Replay is deterministic: files are parsed and returned sorted by exact message
identity. Retry is a pure bounded exponential schedule with deterministic jitter
derived from the message id. The function produces retry delays; it does not
start a timer, daemon, service, or background loop.

If a process dies after importing a message but before writing its ACK,
`reconcile_acknowledgements()` rebuilds the missing `ACKNOWLEDGED` record from
the imported message on restart. Duplicate delivery returns `DUPLICATE` without
overwriting the original persisted `ACKNOWLEDGED` receipt.

## State Model

The following legacy terminal label is valid only for proposal payloads. This
V1 spool has no typed evidence-import state.

```text
CREATED
  -> SEALED
  -> QUEUED
  -> IN_FLIGHT
  -> ACKNOWLEDGED
  -> IMPORTED_AS_C3

Terminal alternatives:
REJECTED | EXPIRED | DUPLICATE | QUARANTINED | DEAD_LETTERED
```

For proposal payloads only, `IMPORTED_AS_C3` records a legacy proposal-import
disposition. It is neither an authority class nor a universal import-success
state and grants no authority. Receipts, results and evidence retain their
semantic kind and remain authority-negative; transport never reclassifies them
as proposals. Because V1 cannot represent a typed evidence import, an evidence
route remains `WAIT_UNSUPPORTED` until an admitted versioned successor exists.
SRF transport receipts do not perform protected actions, execute child
missions, mutate Market/Security authority, or dispatch paid/live workloads.
