# Router + planner conformance vectors (WP-B14)

This directory holds the conformance vectors for the SRL deterministic claim
router and plan builder (`srl.planning`). Each positive vector is a **scenario**:
a `request` + `claim` + `expected` block of routing/plan invariants that the
WP-B14 gate (`scripts/checks/wp14-gate.py`) replays through `srl.planning` and
asserts. Each negative vector names a `validator` and the
`exception`/`fail_reason`/`invariant` its scenario must produce.

> Everything here is an **admission** contract. A green routing/plan result
> means the inputs satisfied the structural contract; it never means a claim is
> *supported*. A `SELECTED` step means "will run", not "ran" or "succeeded".
> See `docs/architecture/router-planner.md` and `GOVERNANCE.md`.

## Positive scenarios (`p01`..`p03`)

- `p01-geometry-tda-wait-capability` — a geometry TDA claim (persistent
  homology + Betti numbers) auto-classifies to `geometry_tda`. With the shipped
  catalog (the `ripser` adapter is `availability=future`, so no local adapter is
  present), the router yields **`WAIT_CAPABILITY`** for `geometry_tda`
  (adapterless → honest wait, **never** a local fallback), `NOT_APPLICABLE` for
  the 14 unrelated profiles, and `EXCLUDED_TYPED` for none (auto-classify never
  excludes). The plan is a 15-step DAG with exactly one `WAIT_CAPABILITY` step
  and zero `SELECTED` steps.
- `p02-multi-profile-3step-dag` — a "composition of coupled ODE subsystems"
  claim auto-classifies to `dynamics`, `executable_ode_dae_sde_model`, and
  `model_composition`. The plan is a **3-step DAG**: `model_composition`
  depends on `dynamics` and `executable_ode_dae_sde_model` (its inputs come
  from their outputs), in topological order.
- `p03-explicit-exclusion-typed` — a request explicitly naming a single profile
  (`algebra_exact`) yields **`EXCLUDED_TYPED`** (reason `not_requested`) for the
  other 14 profiles, not `NOT_APPLICABLE`. The operator asked for exactly one
  profile, so the others are explicitly excluded with a reason — never silently
  dropped. The decision still covers all 15 profiles.

## Negative scenarios (`n01`..`n03`)

- `n01-cyclic-dependency` — a cyclic dependency graph (`a → b → a`) injected
  into the planner's topological sort raises `PlanError`
  (`fail_reason=CONTRACT_INVALID`, `invariant=cycle_detected`). The planner
  refuses to emit a plan with a back-edge.
- `n02-resource-overflow-remote-executor` — a plan whose summed `SELECTED`
  resource estimates exceed the admission caps for its `resource_class` raises
  `ResourceAdmissionError` (`fail_reason=WAIT_REMOTE_EXECUTOR`), **never**
  silently overflowing local. The honest behavior is to wait for a remote
  executor. The vector builds a request with `resource_class=exception` that
  engages enough heavy profiles (via a synthetic `available`-adapter catalog so
  the steps are `SELECTED`) to exceed the exception caps.
- `n03-remote-required-no-local-fallback` — a `remote_required` profile
  **never** falls back to a local adapter: absence of a local adapter yields
  `WAIT_CAPABILITY`, never a fake local substitute. The vector routes a claim
  engaging the `remote_required` profiles (`literature`,
  `executable_ode_dae_sde_model`, `literature_extraction`) and asserts the plan
  produces **no local step** (`adapter_id` is `null`) for any `remote_required`
  profile. Even a `remote_required` entry that names an `adapter_id` in the
  catalog still routes `WAIT_CAPABILITY`.

## Determinism (load-bearing)

The router and planner are pure functions: the same
`(request, claim, catalog, policy)` yields byte-identical output, even when the
input key order is shuffled (canonical JSON sorts keys; steps are emitted in a
stable canonical order). The WP-B14 determinism gate (`B14-01`) rebuilds the
plan three times — including a shuffled-input-key variant — and asserts
byte-identical bytes. The `router-determinism` CI job
(`scripts/checks/router-determinism.py`) rebuilds the golden plan fixture twice
and compares bytes.
