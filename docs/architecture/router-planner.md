# Router and planner (WP-B14)

This document is the architecture reference for the science-lab **deterministic
claim router** and **plan builder** (`srl.planning`). It covers the 15 capability
profiles, the four typed selection states the router produces, the honesty
rules (a plan is not evidence; `WAIT_CAPABILITY` is honest absence; no silent
fallback), the resource admission policy, and the determinism property that
makes a plan content-addressed. The machine-checkable contracts live in
`src/srl/planning/` and the JSON Schemas under
`src/srl/contracts/schemas/v1/science-lab-run-request.json` and
`science-lab-plan.json`; this document is the prose that explains *why* they are
shaped the way they are.

> Everything here is an **admission** contract. A green routing/plan result
> means the inputs satisfied the structural contract; it never means a claim is
> *supported*. A `SELECTED` step means "will run", not "ran" or "succeeded". See
> `GOVERNANCE.md` and `docs/contracts/evidence-model.md` for the evidence rules.

## Pipeline

A `ScienceLabRunRequest/v1` (an intent — never authority) plus a
`ScientificClaim/v1` flow through three pure, deterministic stages:

```
ScienceLabRunRequest + ScientificClaim
        │
        ▼
 1. classifier.classify(claim, symbol_table, condition_set)
        │   -> (frozenset of profiles, rule_trace)
        ▼
 2. router.route(request, claim, catalog, policy)
        │   -> RoutingDecision (one of 4 states per profile, all 15 covered)
        ▼
 3. planner.build_plan(request, routing, catalog, policy)
        -> ScienceLabPlan/v1 (DAG, topological, resource-admitted)
```

Each stage is a pure function of its inputs. This is load-bearing: it is *why*
the plan is content-addressed (the `plan_id` is the SHA-256 of the canonical
bytes, and two independent agents that build the same plan compute the same id
with no coordination).

## The 15 capability profiles

The router routes over exactly 15 capability profiles
(`srl.planning.profiles.SCIENCE_LAB_PROFILES`), grouped into families the
classifier keys off:

| Family        | Profiles                                                                 |
|---------------|--------------------------------------------------------------------------|
| symbolic      | `algebra_exact`, `symbolic_law`, `theorem_or_proof_obligation`, `formal_protocol` |
| dynamical     | `dynamics`, `executable_ode_dae_sde_model`, `pde_variational_model`, `nonlinear_continuous_or_hybrid_constraint` |
| geometric     | `geometry_tda`                                                           |
| statistical   | `causal_time_series`, `uncertainty`, `optimization`                      |
| composition   | `model_composition`                                                      |
| literature    | `literature`, `literature_extraction`                                    |

Each profile carries typed metadata (`srl.planning.profiles.CapabilityProfile`):

- **`required_inputs`** — which MathIR content-dictionaries (cds) / object types
  the profile consumes (e.g. `geometry_tda` consumes `set1`, `relation1`,
  `model_interface`). The classifier uses these to decide applicability.
- **`produced_evidence_axes`** — which `srl.semantic.evidence` axes a `SELECTED`
  run *could* move (informational — the planner never asserts a movement).
- **`default_resource_class`** — `default` or `exception` (the request's class
  overrides this for admission).

The 15 names mirror the `requested_profiles` enum in
`science-lab-run-request.json` / `science-lab-plan.json` exactly.

## The classifier

`srl.planning.classifier.classify(claim, symbol_table, condition_set)` is a
**pure, deterministic** function: the same inputs always yield the same set of
profiles and the same `rule_trace`. There is no randomness, no I/O, and no clock
dependence.

The rule table is explicit in code (`_RULES`). Each rule has a stable `id`, the
`profiles` it selects, and a predicate (`applies`). Rules are evaluated in
declaration order; a profile selected by any firing rule is in the result. The
trace is the list of rule ids that fired, in order — so **every decision is
traceable** (the classifier never silently selects a profile).

The classifier reads only the claim's structural fields (`claim_class`,
`epistemic_source`, `statement` substrings) and the cds present in the
symbol_table / condition_set. It does NOT inspect evidence and does NOT consult
the catalog — so classification is stable across catalog changes.

## The four typed selection states

The router (`srl.planning.router.route`) produces, for **each** of the 15
profiles, exactly one of four typed states (`ProfileRouting.selection`):

| State            | Meaning                                                                              |
|------------------|--------------------------------------------------------------------------------------|
| `SELECTED`       | The profile applies to the claim AND a local adapter is available (`availability=available`). The step **will run**. |
| `EXCLUDED_TYPED` | The request or classifier explicitly excluded it, with a typed reason (`not_requested`). |
| `NOT_APPLICABLE` | The profile does not apply to this claim (auto-classify did not select it).          |
| `WAIT_CAPABILITY`| The profile applies but no adapter is available yet (unknown / future / remote_required). An **honest wait**, never a silent fallback. |

**Decision coverage (no silent drops):** the decision covers ALL 15 profiles.
The `B14-02` gate asserts this: every profile has a routing entry. No profile
is silently dropped.

## Honesty rules (load-bearing)

### A plan is not evidence

`grants_authority` is pinned to `false` on both the request and the plan. A
`SELECTED` step means "the capability applies and an adapter is available, so
the step will run" — NOT "the claim is supported". The evidence model
(`docs/contracts/evidence-model.md`) is a separate, orthogonal layer; the plan
does not touch it.

### `WAIT_CAPABILITY` is honest absence

A profile with no available adapter routes `WAIT_CAPABILITY`. This is an honest
acknowledgment that the capability is not present — the router **never
fabricates** a local adapter for a capability that does not exist. The shipped
catalog (`catalog_data.json`) marks every adapter `future` or `remote_required`
because **no scientific backend ships in this codebase**, so every applicable
profile currently routes `WAIT_CAPABILITY`. A future WP that lands a real adapter
flips the catalog entry to `available`; until then, the router waits honestly.

### No silent fallback (remote_required never runs local)

A `remote_required` profile **never** falls back to a local adapter. Even if a
`remote_required` catalog entry names an `adapter_id`, the router does NOT engage
it locally — absence yields `WAIT_CAPABILITY`. The `B14-03` gate asserts that no
plan step for a `remote_required` profile carries a non-null `adapter_id`.

## Resource admission policy

`srl.planning.planner.AdmissionPolicy` carries per-class resource caps. The
planner sums the `SELECTED` steps' estimates and admits them against the
request's `resource_class` caps:

| Class       | wall_seconds | rss_bytes            | scratch_bytes        |
|-------------|--------------|----------------------|----------------------|
| `default`   | 300          | 1.5 GiB (1610612736) | 4 GiB (4294967296)   |
| `exception` | 900          | 2 GiB (2147483648)   | 4 GiB (4294967296)   |

**Admission, not authorization.** Exceeding the caps raises
`ResourceAdmissionError` (fail reason `WAIT_REMOTE_EXECUTOR`) — an honest wait
for a remote executor — rather than silently overflowing local. The planner
refuses to admit an oversized local plan. Only `SELECTED` steps are summed (a
`WAIT_CAPABILITY` step is not running locally, so it does not consume local
budget).

## Determinism (the load-bearing property)

The router and planner are pure functions: the same
`(request, claim, catalog, policy)` yields **byte-identical** output. This holds
even when the input key order is shuffled, because:

- the canonical JSON encoder (`srl.contracts.canonical.dumps`) sorts keys;
- the steps are emitted in a **stable** order (canonical profile order, then
  dependency-respecting topological order within that);
- the resource estimates are deterministic functions of the profile + class;
- the `plan_digest` and `plan_id` are computed over canonical bytes.

The `B14-01` gate rebuilds the plan **three times** — plain rebuild, re-route
rebuild, and a shuffled-input-key variant — and asserts byte-identical output
with a single `plan_id`. The `router_determinism` CI job
(`scripts/checks/router-determinism.py`) rebuilds the golden plan fixture twice
and compares bytes, failing closed the moment the planner's output becomes
input-order-dependent (a regression that would break content-addressed
identity).

## The plan DAG

Each applicable profile becomes a step. Inter-profile dependency edges:

- `model_composition` (when applicable) depends on every OTHER applicable
  component profile (its inputs come from their outputs).

The planner performs a topological sort (stable, canonical tie-break) and raises
`PlanError` (`CONTRACT_INVALID`, `invariant=cycle_detected`) on a cycle. The
`B14-04` gate asserts a cyclic dependency graph is rejected.

## Acceptance gates

WP-B14 is gated by `scripts/checks/wp14-gate.py` (four checks) and
`scripts/checks/router-determinism.py` (the determinism CI job):

- **B14-01** — determinism: 3 rebuilds (incl. shuffled input keys) yield
  byte-identical plans; positive fixtures replay with expected invariants.
- **B14-02** — decision coverage: the decision covers all 15 profiles; all four
  selection states are reachable; `EXCLUDED_TYPED` always carries a reason.
- **B14-03** — no silent fallback: `remote_required` profiles never produce a
  local step; even a named adapter is not engaged locally.
- **B14-04** — unknown capability → `WAIT_CAPABILITY`; cyclic dependency raises
  `PlanError`; resource overflow raises `ResourceAdmissionError`
  (`WAIT_REMOTE_EXECUTOR`).

Run them with `make gate-wp14` and `make router-determinism`.
