# SRL Agent Operating Agreement

Scientific Resource Lab agents work from repository evidence, not chat memory.
Before non-trivial mutation, read
`docs/architecture/federated-research-organism-doctrine-v1.md`,
`START-HERE.md`, `SYSTEM-ATLAS.md`, `docs/architecture/README.md`,
`GOVERNANCE.md`, `CONTRIBUTING.md` and
`docs/plans/scientific-reasoning-fabric-activation-master-plan-v3.7.md`.

## Mandatory Static Target Doctrine Comprehension Gate

Before describing the federation or starting any cross-repository contract,
bridge, transport, shared-interface or authority work:

1. Read
   `docs/architecture/federated-research-organism-doctrine-v1.md` and
   `policies/federation-ownership-policy-v1.json`.
2. Run `make gate-federation-doctrine`.
3. Run `srlab labctl federation-orient [write-scope]` and report its exact
   orientation block. The command is allowed to characterize SRL release truth
   only; without exact current native receipts every runtime field remains
   `NOT_CHARACTERIZED`:

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

Scientific Resource Lab is the primary scientific cortex: it owns shared
scientific semantics, planning, bounded computation, proof, knowledge and SRL
receipts. The word “cortex” describes cognition, not authority. SRL does not
own Market or Security truth, native admission, native writers or A2.

Dual Contour owns the declared target wire-order role after admitted cutover,
not scientific meaning or domain truth; current deployment remains unproven
until exact native receipts say otherwise. Market and Security retain native
truth, gates, permits and effects. CrossLab is pager-only and has no SRL
endpoint. There is no global sovereign controller, global writer or global A2
authority. A caller-declared write scope is context only and grants no
authority.

`SYSTEM-ATLAS.md` is a generated SRL-local entry model, not current federation
runtime evidence. Its `D0_D1_spool_packet` labels describe inactive legacy SRL
adapter transport and must not be interpreted as the target Dual wire.

If the doctrine gate fails, the ownership policy is stale, or exact current
native receipts are unavailable, do not characterize current federation health
and do not mutate cross-repository state. Static role allocation never proves
runtime activation.

## Current V3.7 Mission State

V3.7 A00-A22 software lanes are completed in the public repository evidence,
but the mission is not `DONE` and `v2.0.0` is not released. The current V3.7
terminal receipt is
`docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json`, which is
`BLOCKED_EXTERNAL_AUTHORITY`.

The historical `docs/verification/mission-closeout-receipt.json` belongs to
the V3.6/v1.0.1 foundation release. Do not use it as the active V3.7 closeout.

## Allowed Local Actions

- Use separate `codex/*` branches or worktrees for code, test and
  documentation changes.
- Run bounded local tests, gates, receipt validation, documentation checks and
  reproducible build checks.
- Regenerate committed public receipts only through the repository gate scripts
  that bind them to current public evidence.
- Park protected external work as exact WAIT states and operator action packets.

## Forbidden Without Native Authority

- Do not claim `DONE`, publish or retag `v2.0.0`, or convert
  `BLOCKED_EXTERNAL_AUTHORITY` into success.
- Do not install secrets, bind production signing keys, mutate T7 protected
  state, deploy, restart services, start live trading actions, or run
  target-specific security actions.
- Do not treat fixture-only, adapter-only or cached evidence as a real ACTIVE
  capability.
- Do not run unbounded research jobs on macOS as a substitute for the declared
  durable execution target.

## Bootstrap

For V3.7 work, verify:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
make gate-v37-plan
```

Then run the narrow gate for the affected lane before broader verification.
