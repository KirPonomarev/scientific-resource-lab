# ADR-0011: Federated research organism ownership

## Status

Proposed. Governance admission and independent review are pending. Runtime
activation remains unproven.

Work package: `GOV-FED-01`. Tracking issue: `#81`.

## Context

Scientific Resource Lab, Dual Contour, Crypto Market Lab and Security Research
OS already contain overlapping scientific, transport, health and integration
concepts. Historical plans describe SRL as a shared scientific brain, but the
root agent entrypoint does not make the cross-repository ownership split
unavoidable. A new agent can therefore make one of three dangerous mistakes:

- turn the “brain” metaphor into global authority;
- assign scientific meaning to the transport contour;
- duplicate the planner, ledger, scheduler, interface or native writers.

The current V3.7 closeout is `BLOCKED_EXTERNAL_AUTHORITY`; no documentation
decision may imply that federation is deployed or that a parked bridge is
active.

## Decision

Propose
[`Federated Research Organism Doctrine v1`](../architecture/federated-research-organism-doctrine-v1.md)
and its machine-readable
[`FederationOwnershipPolicy/v1`](../../policies/federation-ownership-policy-v1.json)
as the static target ownership allocation for the successor federation
mission. Adoption does not activate any target role.

The executable decomposition is intentionally separate in the
[`Federated Research Organism Successor Plan v1`](../plans/federated-research-organism-successor-plan-v1.md),
whose initial state is `DRAFT_PROPOSED`.

The human metaphor and the formal authority model are deliberately separate:

```text
PRIMARY_SCIENTIFIC_CORTEX = SCIENTIFIC_RESOURCE_LAB
GLOBAL_SOVEREIGN_CONTROLLER = NONE
GLOBAL_SOVEREIGN_WRITER = NONE
GLOBAL_A2 = FORBIDDEN
```

The target ownership split is:

- SRL owns SRL `Scientific*` semantics, planning, bounded computation,
  scientific receipts and the shared read-only scientific interface; native
  Market/Security schemas remain native;
- after admitted cutover, the target Dual role owns cross-domain wire order and
  transport mechanics, not scientific meaning or domain truth;
- Market owns Market truth, admission and effects;
- Security owns Security truth, safety, admission and effects;
- CrossLab remains pager-only for its registered V0 peers and is not an SRL
  endpoint;
- every native domain alone admits and records its effects.

Scientific payload identity and wire identity remain separate. After admitted
cutover, target Dual Wire wraps exact SRL payload bytes or an immutable
reference and must not reinterpret or reserialize scientific meaning. SRL's
internal spool remains internal and does not become a second global transport.

## Current-state boundary

This ADR allocates target responsibility only. It does not:

- activate Dual as the deployed federation transport;
- activate Market or Security bridges;
- grant any authority;
- replace native bootstrap or health evidence;
- modify V3.7 plans or receipts;
- publish `v2.0.0`.

Activation requires a successor mission with exact native child closeouts,
current health, contract conformance and operational receipts.

## Alternatives considered

### Security as the global brain

Rejected. Security owns safety and native Security truth. Making it the general
scientific planner duplicates SRL and conflates safety verdicts with scientific
reasoning.

### Dual as the shared semantic owner

Rejected. Dual may own wire mechanics, but scientific payload meaning and
domain truth must remain with SRL and the native domains respectively.

### SRL as global sovereign writer

Rejected. Scientific cognition does not confer Market, Security, deployment,
credential, storage or A2 authority.

### Direct Market-to-SRL and Security-to-SRL transports

Rejected as the target architecture because they would create competing
cross-domain transports. Existing inactive adapters may be reused behind the
governed wire boundary, but their transport assumptions are not authoritative.

### Documentation-only prose without machine checks

Rejected. The ownership policy and consistency gate must fail when a protected
role or authority invariant drifts.

## Consequences

- Agents get one mandatory orientation block before cross-repository work.
- Ownership and current health remain separate facts.
- Existing V3.7 release truth stays historically exact.
- A successor federation mission must reconcile existing SRL spool contracts
  with the target Dual wire rather than silently running both as global buses.
- Changes touching the ownership policy or agent gate remain governance
  changes requiring independent review.
