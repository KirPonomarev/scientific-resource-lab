# Federated Research Organism Doctrine v1

```text
STATUS: DRAFT_PROPOSED
SCOPE: static architecture, ownership and authority boundaries
RUNTIME_TRUTH: false
RELEASE_TRUTH: false
ACTIVATES_FEDERATION: false
GRANTS_AUTHORITY: false
```

This doctrine defines how Scientific Resource Lab participates in the wider
research organism. It does not activate a bridge, prove a runtime healthy,
grant a permit, replace a native bootstrap, or change the current V3.7 release
state.

The machine-readable companion is
[`policies/federation-ownership-policy-v1.json`](../../policies/federation-ownership-policy-v1.json).
If this document and that policy disagree, the change is invalid until both
are reconciled through the governance-change workflow.

## Mandatory orientation

Every agent must preserve this block exactly when describing or changing the
federation:

```text
PRIMARY_SCIENTIFIC_CORTEX: SCIENTIFIC_RESOURCE_LAB
SRL_FORMAL_ROLE: SCIENTIFIC_REASONING_COMPUTE_FABRIC
TARGET_WIRE_ORDER_OWNER: DUAL_CONTOUR
TARGET_WIRE_ORDER_ROLE_STATE: TARGET_DECLARED_NOT_RUNTIME_PROVEN
SAFETY_CORTEX: SECURITY_RESEARCH_OS
MARKET_TRUTH_OWNER: CRYPTO_MARKET_LAB
SECURITY_TRUTH_OWNER: SECURITY_RESEARCH_OS
GLOBAL_SOVEREIGN_CONTROLLER: NONE
GLOBAL_SOVEREIGN_WRITER: NONE
GLOBAL_A2: FORBIDDEN
CROSS_DOMAIN_EFFECT_OWNER: TARGET_NATIVE_DOMAIN_ONLY
CROSSLAB_ROLE: PAGER_ONLY
CROSSLAB_SRL_ENDPOINT: NONE
CURRENT_SRL_RELEASE_TRUTH: BLOCKED_EXTERNAL_AUTHORITY
CURRENT_FEDERATION_RUNTIME: NOT_CHARACTERIZED
CURRENT_SRL_RUNTIME: NOT_CHARACTERIZED
CURRENT_MARKET_RUNTIME: NOT_CHARACTERIZED
CURRENT_SECURITY_RUNTIME: NOT_CHARACTERIZED
CURRENT_DUAL_RUNTIME: NOT_CHARACTERIZED
FEDERATION_RUNTIME_STATE_SOURCE: EXACT_CURRENT_NATIVE_RECEIPTS_ONLY
DECLARED_WRITE_SCOPE: <caller-declared scope or NONE>
DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY: FALSE
```

`TARGET_WIRE_ORDER_OWNER` is a proposed post-cutover allocation, not proof that
Dual Wire is active. `CURRENT_SRL_RELEASE_TRUTH` is bound to the exact SRL V3.7
closeout named by the ownership policy; it is not federation runtime truth.
Current SRL, Market, Security and Dual runtime health comes only from each
repository's exact native bootstrap, so this static orientation reports all of
them and the federation as `NOT_CHARACTERIZED`. `DECLARED_WRITE_SCOPE` is
caller-supplied context, not a receipt, permit or authority grant. `srlab labctl
federation-orient` must emit the same distinctions together with the exact
policy hash, current checkout HEAD and SRL receipt lineage.

The mandatory one-sentence description is: SRL reasons; only after admitted
cutover, target Dual transports; Security protects; Market owns market truth;
and each native domain alone admits and records its effects.

## What “scientific brain” means

Scientific Resource Lab is the organism's primary scientific cortex. In human
language it is the main scientific brain shared by standalone, Market and
Security research agents.

That metaphor means only:

- reusable scientific semantics;
- deterministic scientific planning and capability selection;
- reproducible bounded computation;
- formal and numerical reasoning;
- literature and knowledge retrieval;
- scientific provenance, receipts and proposal-safe export.

It never means:

- global authority or a global sovereign controller;
- ownership of Market or Security canonical truth;
- permission to trade or place an order;
- permission to execute a target-specific security action;
- permission to deploy, restart, install credentials or mutate protected
  storage;
- automatic validation, promotion or application of an SRL result.

The formal role code is
`SCIENTIFIC_REASONING_COMPUTE_FABRIC`. Formal contracts and receipts must use
that role code, not the ambiguous word “brain”.

## Reading precedence

When any source appears to disagree, use this order:

1. Current physical state and the repository-native read-only bootstrap.
2. Native governance, authority and policy receipts.
3. Exact runtime, source, artifact and release identities.
4. Current immutable closeout, execution and health receipts.
5. The machine-readable ownership policy and this doctrine for static roles.
6. Generated views such as `SYSTEM-ATLAS.md`, matrices and dashboards.
7. Plans, trackers, historical documentation and chat summaries.

This doctrine cannot make a stale receipt current. It cannot turn a proposed
target role into operational proof.

## Current release truth

This doctrine does not modify the admitted V3.7 mission or its receipts.
Until replaced by new exact evidence:

- V3.7 remains `BLOCKED_EXTERNAL_AUTHORITY`;
- `v2.0.0` remains unpublished;
- A18, A19 and A20 remain parked behind their native closeouts and health;
- software readiness is not operational activation;
- historical V3.6/v1.0.1 receipts are not current V3.7 release truth;
- every native WAIT state remains a WAIT state.

Implementation or activation of the target federation requires an admitted
successor mission. Existing V3.7 plans and receipts must not be rewritten
retroactively.

## Ownership map

| Component | Owns | Explicitly does not own |
|---|---|---|
| Scientific Resource Lab | SRL-owned `Scientific*` semantics, scientific object fabric, capability catalog, planner/router, bounded computation, formal proof, knowledge retrieval, scientific receipts and the shared read-only scientific interface | Native Market/Security schemas or truth, cross-domain delivery order, native admission, native writers or A2 authority |
| Dual Contour | Target cross-domain wire protocol, route epochs and sequences, durable delivery order, ACK, deduplication, backpressure and transport ledger watermarks after admitted cutover | Scientific meaning, domain truth, scientific validation, native effects or global authority |
| Crypto Market Lab | Market evidence, material-event projection, Market gates, Market experiments, Market admission and Market native writers | Security truth, global transport order or SRL capability truth |
| Security Research OS | Security evidence, safety attention, containment policy, safety verdicts, Security admission and the native executor boundary | General scientific planning, Market truth, global transport order or SRL scientific semantics |
| SRL InterfaceService | Read-only aggregation and proposal-only scientific request construction | Direct execution, native database writes, permits, deployment controls, trading controls or target actions |
| Native domain writers | Domain-specific canonical effects after native authority checks | Cross-domain authority inference |
| CrossLab | Wake notification carrying an immutable reference | Payload transport, evidence, queue truth, execution or permission |

No adapter, dashboard, model or temporary worker may silently assume one of
these ownership responsibilities.

## Contract ownership

### SRL scientific semantics

SRL owns the meaning and versioning of SRL-owned scientific contracts,
including:

- `ScientificObjectEnvelope`;
- `ScientificRequestEnvelope`;
- `ScientificResultEnvelope`;
- `ScientificRunReceipt` and `ScientificImportReceipt`;
- `EvidenceAssessment` and `TransformationReceipt`;
- scientific claims, conditions, symbols, IR and model interfaces;
- capability, pack and scientific validation contracts;
- `SRFPulse` and SRL's scientific federation projection.

Consumers may use exact schema bytes and published conformance vectors. They
must not fork the meaning under the same schema identifier.

Native Market and Security schemas remain native. Dual's historical shared
schema and conformance role remains historical evidence until a successor
mission admits an explicit migration; this doctrine does not relabel existing
Dual contracts as SRL contracts.

### Dual wire semantics

Dual owns the target cross-domain wire semantics:

- wire envelope and acknowledgement;
- route epoch, sequence and predecessor chain;
- delivery acceptance and transport ledger order;
- transport deduplication, backpressure and reservations;
- transport watermarks and recovery mechanics.

A wire signature or ACK proves sender identity, byte integrity or transport
acceptance only. It proves no scientific claim, native admission, permit or
execution authority.

Dual's wire role is a declared target allocation, not a claim that the target
transport is currently deployed or proven.

### Native domain semantics

Market and Security own:

- their native pulse and health semantics;
- their domain evidence and canonical truth;
- their gates and admission receipts;
- their native execution grants, leases and action receipts;
- their canonical writers and effects.

SRL and Dual may reference exact native objects. They may not redefine or mint
them.

## Exact reuse/delta matrix

This matrix is the required decision record before any successor contract is
proposed. “Reuse” means reuse the existing owner and exact schema bytes; it
does not authorize a bridge or change an admitted schema.

| Earlier proposed concept | Existing canonical owner/artifact | Decision | Exact delta, if any |
|---|---|---|---|
| `CellDescriptor` | SRL `LabCellManifest/v1` and `LabFederationManifest/v1` | Reuse | Add no duplicate global cell schema. A successor may add an authority-negative runtime binding that references the existing manifest identity. |
| `CellPulse` | Native Market/Security pulses; SRL `SRFPulse/v1` only for SRL | Keep native | No common replacement pulse. The read plane references exact native pulse identities and preserves native semantics. |
| `DomainPulse` | Native domain pulse/envelope contracts | Keep native | Dual transports exact bytes/ref/hash only; SRL does not reinterpret native health. |
| `FederatedSystemPulse` | SRL `FederationStatus/v1` read-only projection | Evolve, do not duplicate | A versioned successor may close cell items and add exact generation/currentness bindings; it remains advisory and can never overwrite native gates or claim global GREEN from stale input. |
| `ControlIntent` | SRL `ScientificRequestEnvelope/v1` plus native C3 proposal semantics | Reuse envelope with typed profile | A future typed semantic profile may constrain a C3 intent payload. It must contain no command, writer, permit or authority and is revalidated by the target domain. |
| `NativeActionReceipt` | Native Market/Security action and execution receipts | Keep native | SRL `ScientificResultEnvelope`, `ScientificRunReceipt` and `ScienceLabRunReceipt` may reference a native receipt but never substitute for it. |
| `GenerationVector` | No exact current contract; `FederationStatus/v1` is the nearest read-only projection | Versioned delta | Add exact HEAD/pulse/policy/currentness references only if required by the successor plan. It is a rebuildable read model, not a ledger or authority source. |
| Participant registry | `LabFederationManifest/v1` and `LabCellManifest/v1` | Reuse | Native runtime bindings remain separate and authority-negative. |
| Semantic import/projection receipt | `ScientificImportReceipt/v1` | Reuse only for proposal payloads | Its legacy `IMPORTED_AS_C3` outcome is proposal-only. It cannot represent evidence or receipt import. Evidence import remains `WAIT_UNSUPPORTED` until a versioned successor is admitted; native import/admission receipts remain native and are referenced, not replaced. |
| Export/DLP boundary | `LabExportPacket/v1` and SRL sanitizer; native Security DLP | Reuse both at their owners | SRL sanitizes scientific export; Security retains its native safety/DLP authority. Neither may relabel D2/D3 as D1. |
| Wire envelope/ACK | SRL `SpoolMessage/v1` and `SpoolAck/v1` are internal only | New Dual-only delta | Dual may define epoch/sequence/predecessor/dedupe/backpressure/commit-ACK around exact SRL payload bytes or an immutable ref. ACK never proves scientific or native acceptance. |

No new federation contract is admitted by this draft doctrine. Any genuine
delta requires its owner repository, a new version, frozen conformance vectors
and the successor mission's native closeout workflow.

## Canonical-byte boundary

SRL scientific objects and Dual wire documents are separate canonical layers.

The required target path is:

```text
native domain object
-> sanitized D0/D1 semantic projection
-> exact SRL canonical scientific payload bytes
-> scientific payload SHA-256
-> Dual canonical wire wrapper
-> wire document SHA-256 and signature
```

Dual transports the exact scientific payload bytes or an immutable reference.
It must not parse and reserialize a scientific payload to assign a new
scientific identity. SRL must not use a wire document identifier as a
scientific object identifier.

Every boundary crossing must retain both identity layers:

```text
scientific_object_id
scientific_payload_sha256
wire_envelope_id
wire_document_sha256
```

## Transport separation

SRL `SpoolMessage/SpoolAck` is an internal file-backed SRL transport. It is not
the target global wire, a second cross-domain ledger or a competing bus.

| State | Transport interpretation |
|---|---|
| Current repository evidence | SRL internal spool exists; Market and Security adapters remain inactive/proposal-only; no active cross-domain delivery-order owner is proven by this doctrine |
| Target doctrine | Dual Wire becomes the sole cross-domain delivery-order owner only after exact native closeout, conformance and cutover receipts |
| Cutover invariant | SRL spool and Dual Wire must never act simultaneously as cross-domain delivery-order authorities |

```text
ACTIVE_CROSS_DOMAIN_WIRE: NONE_PROVEN_BY_THIS_DOCTRINE
```

The target cross-domain path is:

```text
native adapter -> Dual Wire -> target adapter
```

CrossLab may wake an already governed registered V0 consumer after durable
publication. Its registered peers are Bridge, Market and Security; SRL is not a
CrossLab V0 endpoint. A CrossLab delivery receipt proves delivery only and must
never trigger a native action or become an alternative SRL bus.

## Target end-to-end scientific flow

This section describes the post-cutover target. It is not current deployment
evidence.

### Request path

1. A native domain detects a material scientific need.
2. The native domain creates a sanitized D0/D1 projection and binds the native
   source, schema, generation, adapter hash and dropped fields.
3. A producer constructs a schema-valid `ScientificRequestEnvelope`.
4. After admitted cutover, target Dual Wire wraps the exact request bytes or
   immutable reference.
5. Target Dual Wire validates transport identity, epoch, sequence, TTL,
   classification and idempotency before acknowledging transport acceptance.
6. SRL imports the request as a C3 proposal for scientific work.
7. SRL rechecks source binding, capability policy and resource limits.
8. SRL either emits a typed WAIT or runs one bounded allowlisted capability.

### Result path

1. SRL produces exact scientific output and execution receipts.
2. Computed, validated, formally checked and independently replicated remain
   separate evidence axes.
3. SRL constructs `ScientificResultEnvelope`.
4. After admitted cutover, target Dual Wire transports the exact result bytes
   or immutable reference.
5. The native domain imports the result as authority-negative evidence while
   preserving its exact semantic kind and receipt identities. The result is not
   reclassified as C3.
6. The native domain rechecks its current HEAD, generation, pulse and gate.
7. If an effect is requested, the native domain constructs a separate C3
   proposal from the result; the evidence remains evidence.
8. Only the native domain may admit an experiment or effect.
9. Any admitted state change appears in the next native generation.

Required causality:

```text
NativeGeneration_n
-> ScientificRequest_n
-> WireAdmission_n
-> SRLResult_n
-> NativeImport_n
-> SeparateC3Proposal_if_effect_requested
-> NativeAdmission
-> NativeGeneration_n+1
```

## Result semantics

Semantic kind and authority are independent axes:

| Object | Semantic kind | Authority effect |
|---|---|---|
| Scientific request, intent or proposal envelope | C3 proposal | None; target-native revalidation is mandatory |
| Scientific result, evidence or validation artifact | Evidence | None; crossing a boundary does not make it C3 |
| Run, import, transport or native receipt | Receipt | None unless an exact native authority contract explicitly says otherwise |

`authority-negative` does not mean `C3`. Evidence referenced by a C3 proposal
remains evidence; the containing envelope remains a proposal. A receiver must
never overwrite the semantic kind of either object merely because both grant
no authority.

These distinctions are permanent:

```text
READY != COMPUTED
COMPUTED != VALIDATED
VALIDATED != PROMOTED
SAT/UNSAT != empirical truth
formal proof != empirical validation
algorithm agreement != independent replication
exportable != admitted
transport ACK != application acceptance
application acceptance != native admission
native admission != execution
execution complete != scientific validation
```

Exit code zero means the command completed and its receipt exists. It does not
mean the underlying claim is true.

## Authority path

Cross-domain request, intent and proposal-envelope objects remain C3. Results,
receipts, evidence and validation artifacts remain authority-negative but are
not reclassified as proposals merely because they cross a boundary. Any effect
derived from evidence begins as a new C3 proposal with its own identity.

SRL may validate its own schemas, formal claims and declared scientific
evidence axes; plan; compute; compare; criticize; and produce scientific
receipts. SRL validation never substitutes for native empirical admission. SRL
may not issue a native permit, select a native writer, bypass Market or Security
admission, create an order, execute a target-specific security action or
convert computation directly into promotion.

A native A1 action requires the native domain's current generation,
deterministic admission, execution grant, lease, budget and revocation checks.
A2 always requires the native domain's human and kernel authority chain.

There is no global A2 authority.

## Health and failure isolation

Every component owns only its own health:

- Market Pulse describes Market;
- Security Pulse describes Security;
- SRFPulse describes SRL;
- Dual health describes transport and ledger integrity;
- federation status is a read-only vector of those native states.

Federation status must never overwrite native health. A stale or unknown peer
cannot be projected as global GREEN.

| Failure | Required effect |
|---|---|
| SRL unavailable | Scientific work becomes `WAIT_SRF`; independent native cores continue |
| Dual unavailable | Cross-domain work becomes `WAIT_TRANSPORT`; native cores continue |
| Security unavailable | Safety-dependent work parks; independent safe lanes remain separately reportable |
| Market unavailable | Market-dependent work parks; other contours remain separately reportable |
| Interface unavailable | No runtime or native writer stops |
| One stale member | That member is `STALE` or `UNKNOWN`; federation cannot claim global GREEN |
| D2/D3 or authority violation | The affected route is fenced and evidence is preserved |

## Unified interface

The common scientific interface belongs to the existing SRL
`InterfaceService`, CLI, read-only MCP and portal convergence path.

It may display native pulses and gates, Dual watermarks, SRL capabilities and
sessions, Security safety attention, scientific lineage, WAIT states and
authority queues. It may construct proposal-only scientific request previews.

It must not contain direct native writes, arbitrary shell commands, SSH
actions, deploy or restart controls, trading controls, target-specific security
controls, permit identifiers, writer identifiers or arbitrary executable
fields.

The interface is a disposable read model. Its failure must not stop the
organism.

## Forbidden interpretations

Each statement below is a contract violation:

1. “SRL is the brain, therefore SRL is the authority.”
2. “Dual accepted the bytes, therefore the native domain accepted the result.”
3. “Security approved safety, therefore execution is permitted.”
4. “The computation completed, therefore the hypothesis is validated.”
5. “Federation status is GREEN, therefore every native domain is GREEN.”
6. “The schemas share field names, therefore the objects are identical.”
7. “The scientific payload hash and wire hash identify the same object.”
8. “A newer timestamp supersedes an exact identity.”
9. “CrossLab delivered a message, therefore the recipient acted.”
10. “The interface emitted an intent, therefore a native action may start.”
11. “A stale bridge can be repaired by relaxing source binding.”
12. “A second transport, ledger, planner or scheduler is acceptable because it
    is temporary.”
13. “A direct Python import across repositories is a contract integration.”
14. “A model response may select a writer, command, target or A2 action.”
15. “A declared target role proves the target runtime is active.”

## Change-routing decision tree

Answer these questions in order before changing the federation.

### What meaning changes?

- Scientific request, result, object, capability or evidence meaning belongs
  to SRL.
- Wire delivery, order, ACK, epoch or backpressure meaning belongs to Dual.
- Market evidence, gate or action meaning belongs to Market.
- Security evidence, safety or executor meaning belongs to Security.
- Shared scientific rendering belongs to SRL InterfaceService.
- A native effect belongs to the target native domain.

If more than one answer applies, split the work into native child missions.

### Does data cross a repository boundary?

- No: use the native repository contract.
- D0/D1: use a sanitized semantic projection and the governed transport.
- D2: the native owner may derive a policy-allowed public digest or opaque
  reference as a new sanitized D1 metadata projection; raw D2 is never put in
  an SRL or wire envelope and is never relabelled D1; otherwise WAIT.
- D3: do not export, hash, reference, identify or log the payload across the
  boundary; keep it native or WAIT.
- Unknown classification: reject and preserve safe metadata only.

### Does the object request an effect?

- No: it may remain a read-only observation, evidence object, receipt or result.
- Yes: construct a separate C3 proposal and submit that new object to the native
  domain; do not relabel the source evidence.
- It contains a command, writer, permit, credential, order or target action:
  reject structurally.

### Is the source generation exact and current?

- Exact current binding: continue.
- Stale, missing, future, cross-HEAD or ambiguous: WAIT or reject.
- Never select “latest by timestamp” as a substitute for exact identity.

### Is a new state store or worker proposed?

- If an existing owner can express the state, extend that owner.
- If it creates a second ledger, bus, planner, scheduler, provider loop or
  daemon, reject it.
- If it is only a rebuildable projection, prove source ownership and deletion
  safety before admission.

## No-duplication rules

There is one declared owner for each concern:

```text
SRL-owned scientific semantics = SRL
target wire order after admitted cutover = Dual
market truth and effects = Market
security truth, safety and effects = Security
native effect = target native domain
common scientific interface = SRL InterfaceService
```

Adapters translate. They never become owners. Repositories consume exact
schemas or versioned adapters; they do not copy another repository's business
logic, selector, ledger or authority rules.

## Acceptance checklist

A federation change remains parked unless every answer is YES:

- Is the owner repository unambiguous?
- Is there exactly one schema owner?
- Are source and target identities exact?
- Are scientific and wire identities separate?
- Is the payload D0/D1, with any allowed D2-derived public reference already
  emitted by the native owner as a separate sanitized D1 projection, while D3
  stays native?
- Are authority fields structurally false?
- Is native generation current?
- Does transport ACK remain distinct from native outcome?
- Do proposal, evidence and receipt semantic kinds remain distinct from their
  independent authority-negative status?
- Is retry idempotent?
- Is failure scoped to the affected dependency?
- Can federation be disabled without stopping native domains?
- Does the change avoid a second ledger, selector, scheduler or daemon?
- Does the native domain still perform its own admission?
- Does every A2 path terminate at native `WAIT_AUTHORITY`?
- Are conformance vectors checked independently by producer and consumer?

Any NO answer parks the change.

<!-- FEDERATION-DOCTRINE-END -->
