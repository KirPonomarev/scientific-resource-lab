# Semantic future profiles (WP-H72)

WP-H72 defines the **semantic future profile** layer of the SRL planning router.
A future profile card names a scientific capability that the router has noticed
but has not admitted, built, or installed. The layer is deliberately thin: it
records *that the capability exists and what gap it would fill*, nothing more.

## Cards

A future profile card is a `FutureProfileCard/v1` record with exactly these
fields:

- `profile_id` — stable identifier used in `requested_profiles` (e.g. `dreal`).
- `name` — human-readable name (e.g. `dReal`).
- `status` — one of `{registry_only, bounded_experimental}`.
- `required_capability` — the capability identifier the profile would need
  (e.g. `cap.dreal`).
- `platform_note` — execution-context note (e.g. `remote/WAIT_PLATFORM`,
  `quarantined source ingestion`).
- `honesty_note` — caveat that restates the registry-only semantics and
  disclaims readiness.

The in-code registry is `src/srl/planning/future_profiles.py` and contains six
semantic cards:

| `profile_id` | `name` | `status` | `platform_note` |
| --- | --- | --- | --- |
| `content_mathml` | Content MathML | `registry_only` | Import/export format surface; no executable platform target. |
| `dreal` | dReal | `registry_only` | Remote/WAIT_PLATFORM: delta-satisfiability solving requires a remote executor or a dedicated platform build. |
| `latexml` | LaTeXML | `registry_only` | Quarantined source ingestion: TeX-to-MathML conversion runs in an isolated sandbox. |
| `lean_mathlib` | Lean/mathlib | `registry_only` | Formal proof-engine capability; requires a Lean toolchain and a remote or sandboxed executor. |
| `orkg_opencitations` | ORKG / OpenCitations | `registry_only` | Query-only: external knowledge-graph access over the network; no local mirror or write path. |
| `sciml_bounded` | Bounded SciML executable model | `bounded_experimental` | One bounded SciML executable-model case: a single, resource-capped, deterministic simulation trace. |

The canonical fixture serialization lives at
`fixtures/conformance/future_profiles/cards.v1.json`.

## Registry-only semantics

A future profile card is **not** an admitted capability, **not** a cleared
license, **not** a built adapter, and **not** a promise to build one. The card
carries only one of two honest statuses:

- `registry_only` — the capability has been cataloged, no implementation exists
  in SRL, and no readiness is claimed.
- `bounded_experimental` — one deliberately bounded, non-general case exists,
  but it does not satisfy the P1 admission framework and is not a shipped
  capability.

In particular, no card may carry `installed` or `ready`. The WP-H72 gate
(`scripts/checks/wp72-gate.py`) asserts this invariant on both the in-code
cards and the canonical fixture.

## Router integration

The router (`src/srl/planning/router.py`) knows the union of the 15 shipped
capability profiles and the six future profile identifiers. When a request
explicitly names a future profile, the router routes it through its existing
unknown/future capability path:

- `selection` = `WAIT_CAPABILITY`
- `capability_id` = `cap.<profile_id>`
- `availability` = `unknown`
- `adapter_id` = `None`
- no local adapter is fabricated, no silent fallback occurs, and no profile is
  marked `SELECTED`.

The router does **not** weaken its coverage of the 15 shipped profiles: a
`RoutingDecision` still contains a decision for every shipped profile, and the
future profile is added only when explicitly requested. This preserves the
existing determinism and no-silent-fallback properties of WP-B14.

## What admission requires

A future profile card is a catalog entry, not an admitted capability. Moving it
toward a real actual-compute adapter requires the P1 admission framework
(WP-H70), implemented in `src/srl/packs/p1.py` and documented in
`docs/architecture/p1-admission.md`. The framework demands eight
machine-checkable pieces of evidence before any adapter work begins:

1. `unique_capability` — the capability fills a distinct slot in the SRL
   capability registry and is not a duplicate of an admitted capability.
2. `concrete_hypothesis` — a concrete, falsifiable scientific hypothesis names
   the capability and the experiment that would test it.
3. `license_closure` — the upstream SPDX has been identified and cleared against
   the SRL pack license policy (a receipt from P0 `LICENSE_CLEARED`).
4. `platform_build` — the candidate builds and runs on at least one declared SRL
   platform (`linux`/`macos`, `x86_64`/`arm64`).
5. `resource_measurement` — an honest measured resource footprint (expanded
   bytes, RSS, wall seconds) exists for the candidate.
6. `actual_compute_adapter` — a real actual-compute adapter exists for the
   capability (not a stub).
7. `independent_scientific_role` — the capability plays a role that is not
   already covered by another admitted capability.
8. `removal_rollback_path` — a documented, tested path to cleanly remove the
   capability (uninstall the adapter and drop it from the registry).

Evidence is never inferred. A future profile card carries none of this evidence,
so it remains registry-only until a WP explicitly satisfies P1 and updates the
catalog, the adapter registry, and the profile set accordingly.

## Acceptance gate

`scripts/checks/wp72-gate.py` emits a `GateReceipt/v1` with four checks:

- **H72-01** — all six cards validate against the canonical fixture and match the
  in-code `DEFAULT_CARDS`.
- **H72-02** — a request for any future profile (including `dreal`) routes to
  exact `WAIT_CAPABILITY` with no adapter and `unknown` availability.
- **H72-03** — no card claims readiness; every status is `registry_only` or
  `bounded_experimental`.
- **H72-04** — future-profile routing is deterministic across repeated calls.

The gate exits non-zero on any failure and is run in CI by the
`future-profiles-gate (WP-H72)` job in `.github/workflows/contracts.yml`.
