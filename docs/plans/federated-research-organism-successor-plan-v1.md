# Federated Research Organism Successor Plan v1

```text
STATUS: DRAFT_PROPOSED
PLAN_ID: FRO-SUCCESSOR-PLAN-V1
SUPERSEDES: NONE
MUTATES_V3_7_PLAN_OR_RECEIPTS: false
RUNTIME_TRUTH: false
ACTIVATES_FEDERATION: false
GRANTS_AUTHORITY: false
CANONICAL_WRITES: 0
LIVE_ACTIONS: 0
GLOBAL_A2: FORBIDDEN
```

## Purpose

This is the proposed successor to the closed-but-blocked V3.7 activation
mission. It does not edit, relabel or supersede the admitted V3.7 plan or any
V3.7 receipt. It becomes executable only through a later governance admission
that names exact native child missions, source heads, policies and authority
gates.

The governing doctrine is
[`Federated Research Organism Doctrine v1`](../architecture/federated-research-organism-doctrine-v1.md).
Its required one-sentence model is: SRL reasons; only after admitted cutover,
target Dual transports; Security protects; Market owns market truth; and each
native domain alone admits and records its effects.

## Current state

The current state remains derived from existing immutable receipts:

- SRL V3.7 result is `BLOCKED_EXTERNAL_AUTHORITY`;
- target `v2.0.0` is not published;
- A18 Dual, A19 Market and A20 Security are
  `WAIT_NATIVE_CHILD_CLOSEOUT`;
- the Market and Security SRL adapters are inactive and proposal-only;
- no active target Dual cross-domain wire is proven by this plan;
- T7 binding, T2/T3 enforced compute and the second recovery target remain
  external WAIT conditions where recorded by V3.7;
- native runtime health must be re-read through each repository's native
  bootstrap and must not be copied from these historical receipts.

Run `srlab labctl federation-orient` for the exact SRL policy hash, current
checkout HEAD and SRL release-receipt lineage. The command is read-only and
cannot characterize current SRL, Market, Security, Dual or federation runtime;
without exact native receipts each runtime remains `NOT_CHARACTERIZED`.

## Target state

The proposed target has no global sovereign controller or writer.

| Concern | Accountable owner | Consulted consumers | Explicit non-owner |
|---|---|---|---|
| Shared scientific semantics, planner, bounded compute, proof and knowledge | Scientific Resource Lab | Market, Security | Dual |
| Cross-domain wire epoch, order, sequence, ACK, dedupe and backpressure | Dual Contour | SRL, Market, Security | SRL spool |
| Market truth, admission, permits, effects and writers | Crypto Market Lab | SRL, Security safety overlay | SRL and Dual |
| Security truth, safety attention, containment, admission and effects | Security Research OS | SRL, Market | SRL and Dual |
| Shared scientific read model | SRL InterfaceService / portal / labctl | All domains | Native writers |
| Wake notification | CrossLab registered peers only | Registered native peers | SRL and evidence stores |

Every cross-domain effect terminates at the target native domain. Scientific
or safety output remains evidence. A target domain may derive a separate C3
proposal from it, but neither the evidence nor that proposal becomes authority.

## Semantic and wire boundary

SRL owns exact scientific payload semantics and canonical bytes. Dual owns a
separate wire document around those bytes or an immutable reference.

```text
native sanitized D0/D1 projection
-> exact SRL scientific object bytes + scientific SHA-256
-> exact Dual wire wrapper + wire SHA-256/signature
-> target adapter import
-> target native revalidation/admission
```

Dual must not parse and reserialize an SRL payload to create a different
scientific identity. SRL `SpoolMessage/v1` and `SpoolAck/v1` remain internal
and are never promoted into a second global bus. A Dual ACK proves transport
commit only; it proves neither SRL application acceptance nor native
admission, execution or validation.

Semantic kind and authority are independent axes. Requests, intents and
proposal envelopes are C3 proposals. Results, evidence, validation artifacts
and receipts retain their own semantic kinds when transported. All are
authority-negative at the federation boundary; authority-negative does not
mean C3. Any requested effect derived from evidence is a new C3 proposal with a
new identity and target-native admission.

Legacy SRL `IMPORTED_AS_C3` is valid only for proposal payloads. V1 has no typed
evidence-import outcome, so evidence routing remains `WAIT_UNSUPPORTED` until a
versioned successor contract and producer/consumer conformance are admitted.

## Reuse-first contract decision

The exact reuse/delta matrix in the doctrine is a prerequisite for every
work package. The default is reuse:

- cell identity uses `LabCellManifest/v1` and `LabFederationManifest/v1`;
- scientific request/result/run contracts retain their existing scopes;
- `ScientificImportReceipt/v1` is reused only for proposal imports; evidence
  import requires a versioned successor and remains `WAIT_UNSUPPORTED` before
  that admission;
- export uses `LabExportPacket/v1` and the SRL sanitizer;
- native pulses, gates and action receipts stay native;
- federation read status evolves `FederationStatus/v1` only through a new
  version if strict currentness is required;
- only Dual wire mechanics are a genuine new cross-domain contract family.

No contract may be added merely because an earlier architecture brief named
a similar object.

## Proposed work packages

All packages below are parked until this plan is admitted. Each package uses a
separate branch, bounded owned paths, old/new verifiers where governance is
affected, and an independent review receipt.

### FRO-GOV-01 — doctrine admission

Inputs: issue `#81`, doctrine, ADR, ownership policy, machine orientation,
generated-document sources and consistency gate.

Gate: old verifier passes on the new diff; the new doctrine verifier passes;
independent review is content-addressed; V3.7 plan and receipts are byte-exact
unchanged.

Output: DRAFT_PROPOSED artifacts admitted or rejected. No runtime action.

### FRO-NATIVE-01 — fresh native truth and child closeouts

Each repository independently repairs its current truth and emits its native
closeout. Market, Security and Dual retain their own authority gates and
writers. SRL imports only sanitized authority-negative closeout projections.

Gate: exact source/current runtime identity, current native health, zero
forbidden writes, and explicit WAIT on any stale or missing generation.

### FRO-CONTRACT-01 — semantic reuse conformance

Freeze exact SRL schema bytes and conformance vectors for the already existing
scientific contracts. Native repositories vendor exact bytes or use a governed
adapter; they never import SRL Python business logic across repositories.

Gate: producer and every consumer independently accept positive fixtures and
reject authority smuggling, D2/D3, unknown fields, stale source bindings and
native-receipt substitution. They also prove that proposal, evidence and
receipt semantic kinds remain distinct from authority-negative status.

### FRO-WIRE-01 — Dual mechanical wire

Dual may propose the minimal additive envelope/ACK/route contracts for
epoch/sequence/predecessor/dedupe/backpressure and commit acknowledgement.
The envelope carries exact SRL bytes or an immutable ref/hash and never owns
payload semantics.

Gate: no second ledger, daemon, scheduler or provider route; ACK only after
durable commit; replay/equivocation/gap/restore/key-epoch faults fail closed;
transport ACK remains distinct from application/native outcome.

### FRO-ADAPTER-01 — inactive native adapters

Market and Security add export/import adapters behind feature-off or shadow
gates. Adapters emit no live action, no canonical scientific write and no
provider call. Security remains the safety/DLP owner for Security material;
Market remains the Market truth owner.

Gate: D0/D1 only, native source generation exact, receipt-last publication,
idempotent duplicate handling and federation-disable independence.

### FRO-READ-01 — unified read-only interface

Extend the existing SRL portal/labctl/InterfaceService read model. Overlay
Security safety attention without turning it into the scientific planner or
an execution permit. Show separate transport, application, native admission,
execution, validation and `WAIT_AUTHORITY` states.

Gate: no write controls, commands, credentials, writer identifiers, arbitrary
targets or hidden provider routes; stale members become `STALE`/`UNKNOWN`,
never global GREEN.

### FRO-C3-01 — typed intent profile

Only if reuse conformance proves it necessary, define a typed semantic profile
inside `ScientificRequestEnvelope/v1` or a versioned successor. The object is
C3, authority-negative and contains exact evidence/preconditions/generation,
TTL and idempotency identity but no command, permit or writer. Evidence named
by the proposal remains evidence and is not imported as C3.

Gate: the native target rebuilds current state and emits its own native receipt.

### FRO-A1-01 — bounded native handoff

Prove one fixture/shadow scientific request through SRL reasoning and native
deterministic A1 admission. Effective execution requires the native grant,
lease, budget, generation match and no revocation. Receipt saga only; no 2PC.

Gate: offline or fixture-first, no global A2, final state `WAIT_AUTHORITY`, and
no claim of operational proof without the exact observation window.

## Release order

```text
doctrine admission
-> native closeouts
-> semantic reuse conformance
-> Dual wire feature-off/credit-zero
-> inactive adapters
-> signed shadow pulses/results
-> read-only interface
-> C3 intent profile
-> bounded native A1 fixture
```

No later step may compensate for a failed earlier gate. A peer blocked by an
external authority request remains parked while independent safe lanes may
continue.

## Failure and rollback rules

- Federation disablement must leave every native core working.
- SRL outage parks scientific work as `WAIT_SRF`.
- Dual outage parks delivery as `WAIT_TRANSPORT`.
- Security outage parks safety-dependent work without rewriting Market truth.
- Market outage parks Market-dependent work without rewriting SRL or Security
  truth.
- Stale, future, mixed-generation or cross-HEAD input becomes `UNKNOWN` or
  `WAIT`, never GREEN.
- A failed contract or adapter release is rolled back inside its owner repo;
  no cross-repository database rollback exists.
- Existing V3.7 receipts remain immutable evidence during every rollback.

## Admission checklist

This proposed plan cannot move beyond DRAFT until all are true:

- governance-change issue and complete PR body exist;
- old verifier and new verifier pass on one exact candidate diff;
- independent reviewer receipt is valid and author-distinct;
- generated docs reproduce exactly from machine sources;
- ownership policy hash and current source HEAD are emitted by labctl;
- exact reuse/delta matrix has no unresolved duplicate;
- native Market, Security and Dual closeouts are current;
- no bridge, signer, scheduler, daemon or wire path was activated by the
  documentation package;
- global sovereign writer remains `NONE`;
- global A2 remains `FORBIDDEN`.

Until then the next state is `WAIT_GOVERNANCE_ADMISSION`.

<!-- FEDERATION-SUCCESSOR-PLAN-END -->
