# P2 discovery registry (WP-H73)

WP-H73 defines the **P2** layer of capability discovery: a catalog of external
scientific capabilities that SRL has noticed and might one day wrap with an
actual-compute adapter. It sits two layers *below* admission: a discovery card
records **that a capability exists and what gap it would fill**, nothing more.
Every card carries the constant `admission_status` of `"catalog_only"`.

The framework is implemented in three places:

- `src/srl/knowledge/registry.py` — the `DiscoveryCard/v1` contract, the 13
  catalog-only cards, and the deterministic query API (`search`, `inspect`).
- `fixtures/conformance/registry/cards.v1.json` — the canonical serialization
  of the 13 cards, plus `cards.malformed.v1.json` (one malformed card for the
  H73-02 rejection check).
- `scripts/checks/wp73-gate.py` — the `GateReceipt/v1` acceptance gate.

## The catalog-only invariant

A card in this registry is **not** an admitted capability, **not** a cleared
license, **not** a built adapter, and **not** a promise to build one. It is a
catalog entry: a name, a kind, the domains it touches, the gap it would fill,
and (where known) the upstream license *as declared by the project*.
`admission_status` is pinned to `"catalog_only"` by construction:

- The programmatic builder `build_card(...)` does not accept `admission_status`
  as a parameter; it always sets the constant.
- The raw-JSON builder (`load_cards_from_doc` → `_build_card_from_raw`) rejects
  any value other than `"catalog_only"` with a typed `DiscoveryRegistryError`.

There is no code path that produces a `DiscoveryCard` with a different status.
The H73 gate (H73-03) and the hermetic test suite assert the invariant on every
card.

## The `DiscoveryCard/v1` shape

A discovery card is a plain immutable (`frozen=True`, `slots=True`) dataclass:

| Field | Type | Meaning |
| --- | --- | --- |
| `card_id` | str | Stable card identifier (e.g. `discovery.grobid`). |
| `name` | str | Human-readable capability name (e.g. `GROBID`). |
| `kind` | enum | One of `library`, `application`, `service`. |
| `domains` | tuple[str, ...] | Non-empty tuple of unique domain tags. |
| `license_declared` | str \| None | Upstream SPDX *as declared*, or `None`. Never a clearance. |
| `platforms` | tuple[str, ...] | Upstream-targeted platform families (may be empty). |
| `capability_gap_it_would_fill` | str | One sentence on the gap this capability would fill. |
| `admission_status` | const | Always `"catalog_only"`. |
| `notes` | str | Free-form caveats (declared-vs-cleared status, etc.). |

Validation mirrors the `srl.catalog.registry` pattern: a plain dataclass plus a
builder that routes every field through a validator, so raw-JSON construction
and programmatic construction share one validation path. A malformed card
(field of the wrong type, a `kind` outside the enum, a non-catalog_only
`admission_status`, a missing or extra key) is rejected wholesale with a typed
`DiscoveryRegistryError` carrying `fail_reason="CONTRACT_INVALID"`. No partial
card is ever emitted.

## `license_declared` is a declaration, never a clearance

The `license_declared` field is the SPDX expression the upstream project asserts
about itself. It is **not** a license clearance. A declared SPDX does not
satisfy P1's `license_closure` requirement; only the receipt issued by the P0
`LICENSE_CLEARED` stage does. This mirrors the P1 first-wave candidate cards,
which record `cleared_against_policy: false` against a declared upstream SPDX.

Three cards carry `license_declared: null`:

- `physics-domain-pack`, `economics-domain-pack`, `game-theory-domain-pack` —
  domain-pack placeholders that reserve discovery slots for future
  domain-scoped work. No upstream capability has been chosen yet, so no license
  is declared and no platform is targeted. They exist so the discovery surface
  is explicit about what is *not yet* chosen, rather than silently absent.
- `OpenModelica` — the OpenModelica distribution is under the OSMC Public
  License 1.2 (BSD-style), but the SPDX identifier is not confirmed, so no SPDX
  is declared. License identification is a P1 prerequisite.

## The query API

The registry exposes two deterministic query functions:

- `search(query, cards=None) -> tuple[DiscoveryCard, ...]` — case-insensitive
  substring search over a card's searchable fields (`card_id`, `name`, `kind`,
  `domains`, `platforms`, `capability_gap_it_would_fill`). An empty or
  whitespace-only query lists every card. The result is always sorted by
  `card_id`, independent of the input order of `cards`.
- `inspect(name, cards=None) -> DiscoveryCard | NotFound` — exact, case-sensitive
  match on the `name` field. A miss returns a typed `NotFound` (not `None`, not
  an exception) so a caller distinguishes "no such card" by type.

Both functions accept an optional explicit card tuple, defaulting to the 13
in-code `DEFAULT_CARDS`, so the query surface is hermetic and testable in
isolation.

## The 13 cards

Ten name real external capabilities; three reserve domain-pack placeholder
slots.

| card_id | name | kind | license_declared |
| --- | --- | --- | --- |
| `discovery.casadi` | CasADi | library | LGPL-3.0-only |
| `discovery.catlab` | Catlab | library | MIT |
| `discovery.clingo` | clingo | library | MIT |
| `discovery.domain.economics` | economics-domain-pack | library | null |
| `discovery.domain.game` | game-theory-domain-pack | library | null |
| `discovery.domain.physics` | physics-domain-pack | library | null |
| `discovery.fenicsx-petsc` | FEniCSx/PETSc | library | LGPL-3.0-or-later AND BSD-2-Clause |
| `discovery.grobid` | GROBID | service | Apache-2.0 |
| `discovery.openmodelica` | OpenModelica | application | null |
| `discovery.openturns` | OpenTURNS | library | LGPL-3.0-only |
| `discovery.problog` | ProbLog | library | Apache-2.0 |
| `discovery.souffle` | Souffle | application | UPL-1.0 |
| `discovery.vampire` | Vampire | application | BSD-3-Clause |

## Path to candidacy via P1 admission (WP-H70)

A discovery card is the *top* of the admission funnel, not a part of it. The
path from a catalog card to a real admitted capability runs through the P1
admission framework (WP-H70, `docs/architecture/p1-admission.md`):

1. **Catalog (P2, this layer).** A `DiscoveryCard` records that a capability
   exists and what gap it would fill. `admission_status` is `catalog_only`.
   No evidence is claimed.
2. **Candidacy (P1, WP-H70).** The capability becomes a P1 candidate card and
   `evaluate_p1_candidate` checks eight machine-checkable requirements. The
   card is `ADMIT_TO_PIPELINE` only when **all eight** carry honest evidence;
   otherwise the verdict is a typed `WAIT_*` / `REJECT_CONTRACT` naming the
   missing evidence. Critically, a declared `license_declared` SPDX does **not**
   satisfy P1 `license_closure` — that requires the P0 `LICENSE_CLEARED`
   receipt.
3. **Pack admission (P0, WP-C23).** An admitted P1 candidate is cleared to
   enter the P0 pipeline, where a *built pack* moves through nine stages from
   `DISCOVERED` to `EXPERIMENTAL_ACCEPTED`.

The catalog-only invariant exists precisely so that P2 discovery cannot be
confused with P1 candidacy or P0 admission. A card in this registry says "we
have noticed this capability and it would fill this gap"; it says nothing about
whether the capability is unique, buildable, licensed-clearable, or removable.
Those are P1 questions, and P1 demands evidence for each before any adapter
work begins.

## Acceptance gate

`scripts/checks/wp73-gate.py` runs four checks and emits a `GateReceipt/v1`:

- **H73-01** the canonical fixture loads through `load_cards_from_doc` and
  yields exactly 13 validated cards, identical to the in-code `DEFAULT_CARDS`,
  sorted by `card_id`.
- **H73-02** the malformed fixture is rejected with `DiscoveryRegistryError`
  (a `ContractError` with `fail_reason="CONTRACT_INVALID"`); no partial card
  set is emitted.
- **H73-03** every default and fixture card carries
  `admission_status == "catalog_only"`.
- **H73-04** `search` is deterministic, stable across repeated calls,
  independent of the input order of the card tuple, and always `card_id`-sorted.

The gate exits non-zero on any failure.

## Relationship to the capability catalog (WP-C24)

The P2 discovery registry (`srl.knowledge.registry`) and the capability catalog
(`srl.catalog.registry`) are distinct objects with distinct contracts:

- The **capability catalog** (`CapabilityRegistryEntry`) is the identity of a
  capability *inside* the SRL fabric: its profile, its adapter, its admitted
  pack digest, its measured resources, its admission stage in the P0 pipeline.
  Every seed entry is `admission_stage="not_admitted"`.
- The **discovery registry** (`DiscoveryCard`) is a capability *outside* the
  fabric that SRL has noticed: its name, its kind, the gap it would fill, and
  its declared upstream license. Every card is `admission_status="catalog_only"`.

A discovery card has no profile, no adapter, and no pack: it predates the
fabric. The two share the design pattern (immutable dataclass + builder +
canonical fixture) but not a schema.
