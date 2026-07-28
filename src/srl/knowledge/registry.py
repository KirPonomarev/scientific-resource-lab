"""P2 discovery registry: catalog-only discovery cards (WP-H73).

The P2 layer is the *catalog* of external scientific capabilities that SRL has
noticed and might one day wrap with an actual-compute adapter. It sits two
layers below admission: a :class:`DiscoveryCard` records *that a capability
exists and what gap it would fill*, nothing more. Every card carries the
constant ``admission_status`` of ``"catalog_only"``.

Honesty model
-------------
Registry presence never implies readiness. A card in this registry is **not** an
admitted capability, **not** a cleared license, **not** a built adapter, and
**not** a promise to build one. It is a catalog entry: a name, a kind, the
domains it touches, the gap it would fill, and (where known) the upstream
license *as declared by the project*. The path from a catalog card to a real
admitted capability runs through the P1 admission framework (WP-H70), which
demands eight machine-checkable pieces of evidence before any adapter work
begins. See :mod:`srl.packs.p1` and ``docs/architecture/p1-admission.md``.

The ``license_declared`` field is a *declaration*, never a clearance: it is the
SPDX expression the upstream project asserts about itself. A declared SPDX does
not satisfy P1's ``license_closure`` requirement; only the receipt issued by the
P0 ``LICENSE_CLEARED`` stage does. This mirrors the P1 first-wave cards, which
record ``cleared_against_policy: false`` against a declared upstream SPDX.

The catalog-only invariant
--------------------------
``admission_status`` is pinned to ``"catalog_only"`` by construction. The
programmatic builder :func:`build_card` does not accept ``admission_status`` as
a parameter and always sets the constant; the raw-JSON builder
:func:`_build_card_from_raw` rejects any value other than ``"catalog_only"``.
There is no code path that produces a :class:`DiscoveryCard` with a different
status. The H73 gate (``scripts/checks/wp73-gate.py``) and the hermetic test
suite assert the invariant on every card.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Schema identity for a discovery card collection. A ``DiscoveryCard/v1``
# document is an object with ``schema_version`` and a ``cards`` array of card
# records. Bumped only on a contract change to the card shape.
DISCOVERY_CARD_SCHEMA_VERSION: Final[str] = "DiscoveryCard/v1"

# The single permitted admission status for a discovery card. A card in this
# registry is catalog-only by definition; there is no second status value.
ADMISSION_STATUS_CATALOG_ONLY: Final[str] = "catalog_only"
DISCOVERY_CARD_ADMISSION_STATUSES: Final[tuple[str, ...]] = (ADMISSION_STATUS_CATALOG_ONLY,)

# The kind enum: what kind of external capability the card describes. A
# ``library`` is a programmable package; an ``application`` is a standalone
# tool with its own CLI/GUI; a ``service`` is a long-running process offering
# an API over the network or a local socket.
DISCOVERY_CARD_KINDS: Final[tuple[str, ...]] = ("library", "application", "service")


class DiscoveryRegistryError(ContractError):
    """Raised when a discovery card or card document violates its contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class NotFound:
    """Typed ``inspect`` miss: no card matches the queried name.

    Returned by :func:`inspect` so a caller distinguishes "no such card" from
    a found card via the type, rather than via ``None`` or an exception.

    Attributes
    ----------
    name:
        The name that was queried.
    detail:
        Human-readable summary of the miss.
    """

    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class DiscoveryCard:
    """One catalog-only discovery card (``DiscoveryCard/v1``).

    A plain immutable container. Structural validation is performed by the
    builders (:func:`_build_card_from_raw` over JSON; :func:`build_card` for
    programmatic construction), mirroring the :mod:`srl.catalog.registry`
    pattern (plain dataclass + builder). The dataclass field annotations are
    the type contract; direct construction with well-typed values is permitted,
    but ``admission_status`` is always the constant
    :data:`ADMISSION_STATUS_CATALOG_ONLY`.

    Attributes
    ----------
    card_id:
        Stable card identifier (e.g. ``discovery.grobid``).
    name:
        Human-readable capability name (e.g. ``GROBID``).
    kind:
        One of :data:`DISCOVERY_CARD_KINDS` (``library``, ``application``,
        ``service``).
    domains:
        Tuple of domain tags the capability touches (e.g. ``("nlp",)``).
    license_declared:
        Upstream SPDX expression *as declared by the project*, or ``None`` when
        the declared license is not known. A declaration is never a clearance.
    platforms:
        Tuple of platform family descriptors the upstream targets (e.g.
        ``("linux", "macos")``). Free-form strings, not SRL PlatformSpecs.
    capability_gap_it_would_fill:
        One sentence on the capability gap this capability would fill in SRL.
    admission_status:
        Always :data:`ADMISSION_STATUS_CATALOG_ONLY`. A card existing never
        implies the capability is ready, licensed, or built.
    notes:
        Free-form caveats (declared-vs-cleared license status, dependencies,
        placeholder provenance, etc.).
    """

    card_id: str
    name: str
    kind: str
    domains: tuple[str, ...]
    license_declared: str | None
    platforms: tuple[str, ...]
    capability_gap_it_would_fill: str
    admission_status: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        """Return the card as a plain JSON-serializable dict.

        Key order is not significant (canonical JSON sorts keys); the field set
        is the ``DiscoveryCard/v1`` contract.
        """
        return {
            "card_id": self.card_id,
            "name": self.name,
            "kind": self.kind,
            "domains": list(self.domains),
            "license_declared": self.license_declared,
            "platforms": list(self.platforms),
            "capability_gap_it_would_fill": self.capability_gap_it_would_fill,
            "admission_status": self.admission_status,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Field validators (mirror the srl.catalog.registry validator style).
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, field: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise."""
    if not isinstance(value, str) or value == "":
        msg = f"{field} must be a non-empty string, got {value!r}"
        raise DiscoveryRegistryError(msg)
    return value


def _validate_card_id(value: Any) -> str:
    """Validate the card_id field (non-empty string)."""
    return _require_non_empty_str(value, "card_id")


def _validate_name(value: Any) -> str:
    """Validate the name field (non-empty string)."""
    return _require_non_empty_str(value, "name")


def _validate_kind(value: Any) -> str:
    """Validate the kind field (one of the three kind values)."""
    kind = _require_non_empty_str(value, "kind")
    if kind not in DISCOVERY_CARD_KINDS:
        msg = f"kind {kind!r} must be one of {list(DISCOVERY_CARD_KINDS)}"
        raise DiscoveryRegistryError(msg)
    return kind


def _validate_string_tuple(value: Any, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    """Validate a tuple-of-strings field.

    Each element must be a non-empty string; duplicates are rejected so the
    field is a set-like tag list. When ``allow_empty`` is false the tuple must
    be non-empty.
    """
    if not isinstance(value, tuple):
        msg = f"{field} must be a tuple, got {type(value).__name__}"
        raise DiscoveryRegistryError(msg)
    if not allow_empty and len(value) == 0:
        msg = f"{field} must be a non-empty tuple"
        raise DiscoveryRegistryError(msg)
    seen: set[str] = set()
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or item == "":
            msg = f"{field}[{i}] must be a non-empty string, got {item!r}"
            raise DiscoveryRegistryError(msg)
        if item in seen:
            msg = f"{field} has duplicate entry {item!r}"
            raise DiscoveryRegistryError(msg)
        seen.add(item)
        out.append(item)
    return tuple(out)


def _validate_domains(value: Any) -> tuple[str, ...]:
    """Validate the domains field (non-empty tuple of unique non-empty strings)."""
    return _validate_string_tuple(value, "domains", allow_empty=False)


def _validate_platforms(value: Any) -> tuple[str, ...]:
    """Validate the platforms field (tuple of unique non-empty strings; may be empty)."""
    return _validate_string_tuple(value, "platforms", allow_empty=True)


def _validate_license_declared(value: Any) -> str | None:
    """Validate the license_declared field (None or non-empty string)."""
    if value is None:
        return None
    return _require_non_empty_str(value, "license_declared")


def _validate_gap(value: Any) -> str:
    """Validate the capability_gap_it_would_fill field (non-empty string)."""
    return _require_non_empty_str(value, "capability_gap_it_would_fill")


def _validate_notes(value: Any) -> str:
    """Validate the notes field (string; may be empty)."""
    if not isinstance(value, str):
        msg = f"notes must be a string, got {type(value).__name__}"
        raise DiscoveryRegistryError(msg)
    return value


# ---------------------------------------------------------------------------
# Builders.
# ---------------------------------------------------------------------------


def build_card(  # noqa: PLR0913 - mirrors the 9-field DiscoveryCard dataclass
    *,
    card_id: Any,
    name: Any,
    kind: Any,
    domains: Any,
    license_declared: Any,
    platforms: Any,
    capability_gap_it_would_fill: Any,
    notes: Any,
) -> DiscoveryCard:
    """Build and validate a :class:`DiscoveryCard`.

    Use this for programmatic construction (gate fixtures, tests). It validates
    every caller-supplied field and forces ``admission_status`` to
    :data:`ADMISSION_STATUS_CATALOG_ONLY`. There is no parameter for
    ``admission_status``: the catalog-only invariant is structural on this path.

    Raises
    ------
    DiscoveryRegistryError
        With fail reason ``CONTRACT_INVALID`` if any field is malformed.
    """
    return DiscoveryCard(
        card_id=_validate_card_id(card_id),
        name=_validate_name(name),
        kind=_validate_kind(kind),
        domains=_validate_domains(domains),
        license_declared=_validate_license_declared(license_declared),
        platforms=_validate_platforms(platforms),
        capability_gap_it_would_fill=_validate_gap(capability_gap_it_would_fill),
        admission_status=ADMISSION_STATUS_CATALOG_ONLY,
        notes=_validate_notes(notes),
    )


# The required card keys (the ``DiscoveryCard/v1`` field set) and the single
# allowed admission status, as frozensets for key-set validation.
_CARD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "card_id",
        "name",
        "kind",
        "domains",
        "license_declared",
        "platforms",
        "capability_gap_it_would_fill",
        "admission_status",
        "notes",
    }
)
_ADMISSION_STATUSES: Final[frozenset[str]] = frozenset(DISCOVERY_CARD_ADMISSION_STATUSES)


def _build_card_from_raw(raw: Any) -> DiscoveryCard:
    """Build a validated :class:`DiscoveryCard` from a raw dict.

    Routes every field through :func:`build_card` so raw-JSON construction and
    programmatic construction share one validation path. The
    ``admission_status`` field is validated against the catalog-only invariant:
    any value other than :data:`ADMISSION_STATUS_CATALOG_ONLY` is rejected.
    """
    if not isinstance(raw, dict):
        msg = f"discovery card must be an object, got {type(raw).__name__}"
        raise DiscoveryRegistryError(msg)

    actual = set(raw.keys())
    missing = _CARD_KEYS - actual
    if missing:
        msg = f"discovery card missing required key(s): {sorted(missing)}"
        raise DiscoveryRegistryError(msg)
    extra = actual - _CARD_KEYS
    if extra:
        msg = f"discovery card has unexpected key(s): {sorted(extra)}"
        raise DiscoveryRegistryError(msg)

    # Enforce the catalog-only invariant on the JSON path.
    admission_status = raw["admission_status"]
    if admission_status not in _ADMISSION_STATUSES:
        msg = (
            f"admission_status {admission_status!r} must be one of "
            f"{list(DISCOVERY_CARD_ADMISSION_STATUSES)}; a discovery card is "
            "catalog-only by definition"
        )
        raise DiscoveryRegistryError(msg)

    # ``domains`` and ``platforms`` arrive as JSON arrays (``list``). The
    # in-code literals in :data:`_RAW_CARDS` use Python tuples; both are valid
    # sequences, so accept either and route through :func:`_validate_*`, which
    # checks the elements. A ``str`` or other scalar is rejected.
    domains_raw = raw["domains"]
    if not isinstance(domains_raw, (list, tuple)):
        msg = f"domains must be an array, got {type(domains_raw).__name__}"
        raise DiscoveryRegistryError(msg)
    domains = _validate_domains(tuple(domains_raw))

    platforms_raw = raw["platforms"]
    if not isinstance(platforms_raw, (list, tuple)):
        msg = f"platforms must be an array, got {type(platforms_raw).__name__}"
        raise DiscoveryRegistryError(msg)
    platforms = _validate_platforms(tuple(platforms_raw))

    return build_card(
        card_id=raw["card_id"],
        name=raw["name"],
        kind=raw["kind"],
        domains=domains,
        license_declared=raw["license_declared"],
        platforms=platforms,
        capability_gap_it_would_fill=raw["capability_gap_it_would_fill"],
        notes=raw["notes"],
    )


def _validate_card_doc(doc: Any) -> dict[str, Any]:
    """Validate the raw card-document shape and return it."""
    if not isinstance(doc, dict):
        msg = f"discovery card document must be an object, got {type(doc).__name__}"
        raise DiscoveryRegistryError(msg)
    if doc.get("schema_version") != DISCOVERY_CARD_SCHEMA_VERSION:
        msg = (
            f"discovery card schema_version must be {DISCOVERY_CARD_SCHEMA_VERSION!r}, "
            f"got {doc.get('schema_version')!r}"
        )
        raise DiscoveryRegistryError(msg)
    cards = doc.get("cards")
    if not isinstance(cards, list):
        msg = f"discovery card document 'cards' must be an array, got {type(cards).__name__}"
        raise DiscoveryRegistryError(msg)
    return doc


def load_cards_from_doc(doc: Any) -> tuple[DiscoveryCard, ...]:
    """Load and validate a ``DiscoveryCard/v1`` document into a sorted card tuple.

    Parameters
    ----------
    doc:
        Raw JSON-decoded dict claiming to be a ``DiscoveryCard/v1`` collection
        (``{"schema_version": "DiscoveryCard/v1", "cards": [...]}``).

    Returns
    -------
    tuple[DiscoveryCard, ...]
        The validated cards, sorted by ``card_id`` for deterministic ordering.

    Raises
    ------
    DiscoveryRegistryError
        With ``CONTRACT_INVALID`` if the document shape, schema version, or any
        card is malformed (including a non-catalog_only ``admission_status``).
    """
    validated = _validate_card_doc(doc)
    cards = tuple(_build_card_from_raw(c) for c in validated["cards"])
    return tuple(sorted(cards, key=lambda c: c.card_id))


# ---------------------------------------------------------------------------
# Query API.
# ---------------------------------------------------------------------------


def _matches(card: DiscoveryCard, query: str) -> bool:
    """Return True if ``query`` (lowercased) appears in the card's searchable fields."""
    haystack = " ".join(
        (
            card.card_id,
            card.name,
            card.kind,
            " ".join(card.domains),
            " ".join(card.platforms),
            card.capability_gap_it_would_fill,
        )
    ).lower()
    return query in haystack


def search(
    query: str,
    cards: tuple[DiscoveryCard, ...] | None = None,
) -> tuple[DiscoveryCard, ...]:
    """Return the cards matching ``query``, deterministically sorted by ``card_id``.

    Matching is case-insensitive substring search over the card's searchable
    fields (``card_id``, ``name``, ``kind``, ``domains``, ``platforms``, and
    ``capability_gap_it_would_fill``). An empty or whitespace-only ``query``
    returns every card (it acts as a deterministic listing). The result is
    always sorted by ``card_id``, independent of the input order of ``cards``.

    Parameters
    ----------
    query:
        The search string.
    cards:
        The card tuple to search. Defaults to :data:`DEFAULT_CARDS`.

    Returns
    -------
    tuple[DiscoveryCard, ...]
        Matching cards sorted by ``card_id``. Empty if nothing matches.
    """
    pool = DEFAULT_CARDS if cards is None else cards
    needle = query.strip().lower()
    if needle == "":
        return tuple(sorted(pool, key=lambda c: c.card_id))
    matched = (c for c in pool if _matches(c, needle))
    return tuple(sorted(matched, key=lambda c: c.card_id))


def inspect(
    name: str,
    cards: tuple[DiscoveryCard, ...] | None = None,
) -> DiscoveryCard | NotFound:
    """Return the card whose ``name`` equals ``name``, or a typed :class:`NotFound`.

    The match is exact and case-sensitive on the ``name`` field. When no card
    matches, a :class:`NotFound` is returned (not ``None`` and not an exception)
    so callers distinguish a miss by type.

    Parameters
    ----------
    name:
        The exact capability name to look up (e.g. ``"GROBID"``).
    cards:
        The card tuple to search. Defaults to :data:`DEFAULT_CARDS`.

    Returns
    -------
    DiscoveryCard | NotFound
        The matching card, or a :class:`NotFound` carrying the queried name.
    """
    pool = DEFAULT_CARDS if cards is None else cards
    for card in pool:
        if card.name == name:
            return card
    return NotFound(
        name=name,
        detail=f"no discovery card with name {name!r} in the registry",
    )


# ---------------------------------------------------------------------------
# The 13 catalog-only discovery cards.
#
# These are honest catalog entries: each records that an external capability
# exists, the gap it would fill, and (where known) the upstream license *as
# declared by the project*. ``license_declared`` is never a clearance; the notes
# say so explicitly. The three domain-pack placeholders reserve slots for
# future domain-scoped discovery (physics, economics, game theory) and carry
# ``license_declared: null`` because no upstream has been chosen yet.
# ---------------------------------------------------------------------------


#: The raw card literals. Authored in ``card_id`` sorted order so the canonical
#: fixtures snapshot is stable.
_RAW_CARDS: Final[tuple[dict[str, Any], ...]] = (
    {
        "card_id": "discovery.casadi",
        "name": "CasADi",
        "kind": "library",
        "domains": ("optimization", "optimal-control", "symbolic-computation"),
        "license_declared": "LGPL-3.0-only",
        "platforms": ("linux", "macos", "windows"),
        "capability_gap_it_would_fill": (
            "Symbolic, derivative-aware numerical optimization and optimal-control "
            "problem formulation for SRL experiments."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Declared upstream SPDX LGPL-3.0-only. A declaration is not a P1 "
            "license_closure receipt; clearance against the SRL pack policy is "
            "required before any adapter work begins."
        ),
    },
    {
        "card_id": "discovery.catlab",
        "name": "Catlab",
        "kind": "library",
        "domains": ("category-theory", "algebra", "symbolic-computation"),
        "license_declared": "MIT",
        "platforms": ("linux", "macos", "windows"),
        "capability_gap_it_would_fill": (
            "Categorical-algebra and wiring-diagram structures for composing "
            "scientific models as typed morphisms."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Julia package; declared upstream SPDX MIT. Declaration is not a "
            "clearance. A Julia toolchain adapter would be a new platform surface."
        ),
    },
    {
        "card_id": "discovery.clingo",
        "name": "clingo",
        "kind": "library",
        "domains": ("answer-set-programming", "knowledge-representation", "reasoning"),
        "license_declared": "MIT",
        "platforms": ("linux", "macos", "windows"),
        "capability_gap_it_would_fill": (
            "Answer-set programming for declarative combinatorial reasoning and "
            "constraint satisfaction in SRL workflows."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Declared upstream SPDX MIT. Declaration is not a clearance; the "
            "P1 license_closure receipt is outstanding."
        ),
    },
    {
        "card_id": "discovery.domain.economics",
        "name": "economics-domain-pack",
        "kind": "library",
        "domains": ("economics", "decision-theory", "placeholder"),
        "license_declared": None,
        "platforms": (),
        "capability_gap_it_would_fill": (
            "Placeholder slot for a future economics domain pack (market, utility, "
            "and equilibrium models); reserves the discovery surface."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Domain-pack placeholder. No upstream capability has been chosen yet, "
            "so no license is declared and no platform is targeted. Catalog-only."
        ),
    },
    {
        "card_id": "discovery.domain.game",
        "name": "game-theory-domain-pack",
        "kind": "library",
        "domains": ("game-theory", "decision-theory", "placeholder"),
        "license_declared": None,
        "platforms": (),
        "capability_gap_it_would_fill": (
            "Placeholder slot for a future game-theory domain pack (strategic and "
            "extensive-form games); reserves the discovery surface."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Domain-pack placeholder. No upstream capability has been chosen yet, "
            "so no license is declared and no platform is targeted. Catalog-only."
        ),
    },
    {
        "card_id": "discovery.domain.physics",
        "name": "physics-domain-pack",
        "kind": "library",
        "domains": ("physics", "simulation", "placeholder"),
        "license_declared": None,
        "platforms": (),
        "capability_gap_it_would_fill": (
            "Placeholder slot for a future physics domain pack (classical and "
            "continuum simulation); reserves the discovery surface."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Domain-pack placeholder. No upstream capability has been chosen yet, "
            "so no license is declared and no platform is targeted. Catalog-only."
        ),
    },
    {
        "card_id": "discovery.fenicsx-petsc",
        "name": "FEniCSx/PETSc",
        "kind": "library",
        "domains": ("finite-elements", "pde", "numerical-analysis"),
        "license_declared": "LGPL-3.0-or-later AND BSD-2-Clause",
        "platforms": ("linux", "macos"),
        "capability_gap_it_would_fill": (
            "Finite-element discretization and scalable linear/nonlinear solvers "
            "for PDE-based scientific simulation."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Composite card: FEniCSx (dolfinx) declares LGPL-3.0-or-later and the "
            "PETSc solver dependency declares BSD-2-Clause; the declared SPDX "
            "expression combines both. Declaration is not a clearance. Heavy native "
            "build; platform_build evidence would be a P1 prerequisite."
        ),
    },
    {
        "card_id": "discovery.grobid",
        "name": "GROBID",
        "kind": "service",
        "domains": ("nlp", "information-extraction", "document-processing"),
        "license_declared": "Apache-2.0",
        "platforms": ("linux", "macos"),
        "capability_gap_it_would_fill": (
            "Structured parsing of scientific PDFs (headers, references, "
            "affiliations) into machine-checked metadata for the SRL corpus."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Long-running JVM service exposing an HTTP API. Declared upstream SPDX "
            "Apache-2.0. Declaration is not a clearance; a service adapter would "
            "add a new runtime dependency class (network/local-socket service)."
        ),
    },
    {
        "card_id": "discovery.openmodelica",
        "name": "OpenModelica",
        "kind": "application",
        "domains": ("modelica", "simulation", "dynamical-systems"),
        "license_declared": None,
        "platforms": ("linux", "macos", "windows"),
        "capability_gap_it_would_fill": (
            "Acausal, equation-based modeling and simulation of multi-domain "
            "physical systems via the Modelica Standard Library."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "OpenModelica is distributed under the OSMC Public License 1.2 "
            "(BSD-style); the SPDX identifier is not confirmed, so no SPDX is "
            "declared here. License identification is a P1 prerequisite."
        ),
    },
    {
        "card_id": "discovery.openturns",
        "name": "OpenTURNS",
        "kind": "library",
        "domains": ("uncertainty-quantification", "statistics", "simulation"),
        "license_declared": "LGPL-3.0-only",
        "platforms": ("linux", "macos", "windows"),
        "capability_gap_it_would_fill": (
            "Uncertainty quantification, sensitivity analysis, and probabilistic "
            "meta-modeling for SRL experiments."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Declared upstream SPDX LGPL-3.0-only. Declaration is not a clearance; "
            "the P1 license_closure receipt is outstanding."
        ),
    },
    {
        "card_id": "discovery.problog",
        "name": "ProbLog",
        "kind": "library",
        "domains": ("probabilistic-logic", "knowledge-representation", "reasoning"),
        "license_declared": "Apache-2.0",
        "platforms": ("linux", "macos", "windows"),
        "capability_gap_it_would_fill": (
            "Probabilistic logic programming combining logical inference with "
            "probability for uncertain-knowledge reasoning."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Declared upstream SPDX Apache-2.0. Declaration is not a clearance; "
            "the P1 license_closure receipt is outstanding."
        ),
    },
    {
        "card_id": "discovery.souffle",
        "name": "Souffle",
        "kind": "application",
        "domains": ("datalog", "program-analysis", "reasoning"),
        "license_declared": "UPL-1.0",
        "platforms": ("linux", "macos"),
        "capability_gap_it_would_fill": (
            "Datalog-based deductive database and program-analysis engine for "
            "rule-based static analysis over SRL artifacts."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Declared upstream SPDX UPL-1.0 (Universal Permissive License). "
            "Declaration is not a clearance; the P1 license_closure receipt is "
            "outstanding."
        ),
    },
    {
        "card_id": "discovery.vampire",
        "name": "Vampire",
        "kind": "application",
        "domains": ("theorem-proving", "first-order-logic", "reasoning"),
        "license_declared": "BSD-3-Clause",
        "platforms": ("linux", "macos"),
        "capability_gap_it_would_fill": (
            "First-order theorem proving for automated, machine-checked proof of "
            "logical properties arising in SRL contracts and models."
        ),
        "admission_status": "catalog_only",
        "notes": (
            "Declared upstream SPDX BSD-3-Clause. Declaration is not a clearance; "
            "the P1 license_closure receipt is outstanding."
        ),
    },
)

#: The 13 catalog-only discovery cards, validated through
#: :func:`_build_card_from_raw` at import and sorted by ``card_id``. This is the
#: authoritative in-code registry; the canonical fixtures snapshot at
#: ``fixtures/conformance/registry/cards.v1.json`` is its serialization.
DEFAULT_CARDS: Final[tuple[DiscoveryCard, ...]] = tuple(
    _build_card_from_raw(raw) for raw in _RAW_CARDS
)


def default_cards() -> tuple[DiscoveryCard, ...]:
    """Return the default 13 catalog-only discovery cards, sorted by ``card_id``."""
    return DEFAULT_CARDS


__all__ = [
    "ADMISSION_STATUS_CATALOG_ONLY",
    "DEFAULT_CARDS",
    "DISCOVERY_CARD_ADMISSION_STATUSES",
    "DISCOVERY_CARD_KINDS",
    "DISCOVERY_CARD_SCHEMA_VERSION",
    "DiscoveryCard",
    "DiscoveryRegistryError",
    "NotFound",
    "build_card",
    "default_cards",
    "inspect",
    "load_cards_from_doc",
    "search",
]
