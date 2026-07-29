# Reliable Spool Transport

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

Success writes the message to `inbox/imported/` and returns `SpoolAck/v1` with
`ACKNOWLEDGED`. Duplicate delivery returns `DUPLICATE` without another import.
Malformed messages, missing signatures, signature failures, corrupt partial
files, and rejected hash-chain transitions go to `quarantine/`. Expired or
terminal delivery failures go to `dlq/` with `DeadLetterRecord/v1`.

## Signatures

The transport module exposes a verifier interface for native Ed25519 keyrings.
No repository secret or production key is stored here. Local conformance tests
use a deliberately labelled `test-hmac-sha256` fixture signer to prove the core
property: unsigned or tampered messages are never accepted. A deployment without
a native verifier uses a null verifier and quarantines messages.

Each detached signature records:

- signer cell;
- message identity;
- monotonic sequence;
- previous signature file hash;
- signature value.

This provides deterministic key-rotation and replay fixtures without creating
authority. A signature proves transport authenticity only; it never grants
canonical write permission.

## Replay and Retry

Replay is deterministic: files are parsed and returned sorted by exact message
identity. Retry is a pure bounded exponential schedule with deterministic jitter
derived from the message id. The function produces retry delays; it does not
start a timer, daemon, service, or background loop.

## State Model

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

All imports remain C3 proposal evidence. SRF transport receipts do not perform
protected actions, execute child missions, mutate Market/Security authority, or
dispatch paid/live workloads.
