"""Semantic future profile cards (WP-H72).

A *future profile card* names a scientific capability the SRL planning layer has
noticed but has not admitted, built, or installed. Cards are deliberately
registry-only: they record that the capability exists and what gap it would fill,
but they never claim the capability is ready, licensed, or available locally.

A plan request that explicitly names a future profile is routed to
``WAIT_CAPABILITY`` through the router's existing unknown/future capability path.
The router does not fabricate a local adapter, silently substitute a different
profile, or mark the profile SELECTED. This is the honesty property that keeps a
plan from claiming it can run something it cannot.

Admission path
--------------
A future profile card is a catalog entry, not an admitted capability. Moving it
toward a real adapter requires the P1 admission framework (WP-H70), which
demands eight machine-checkable pieces of evidence before any adapter work
begins. See :mod:`srl.packs.p1` and ``docs/architecture/p1-admission.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Schema identity for a future profile card collection. A ``FutureProfileCard/v1``
# document is an object with ``schema_version`` and a ``cards`` array of card
# records. Bumped only on a contract change to the card shape.
FUTURE_PROFILE_CARD_SCHEMA_VERSION: Final[str] = "FutureProfileCard/v1"

# The two permitted status values for a future profile card. A card is either
# purely catalog-only or has one bounded experimental case; neither implies
# general installation or readiness.
FUTURE_PROFILE_STATUS_REGISTRY_ONLY: Final[str] = "registry_only"
FUTURE_PROFILE_STATUS_BOUNDED_EXPERIMENTAL: Final[str] = "bounded_experimental"
FUTURE_PROFILE_STATUSES: Final[tuple[str, ...]] = (
    FUTURE_PROFILE_STATUS_REGISTRY_ONLY,
    FUTURE_PROFILE_STATUS_BOUNDED_EXPERIMENTAL,
)


class FutureProfileRegistryError(ContractError):
    """Raised when a future profile card or card document violates its contract.

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
class FutureProfileCard:
    """One future profile card (``FutureProfileCard/v1``).

    A plain immutable container. Structural validation is performed by the
    builders (:func:`build_card` for programmatic construction and
    :func:`_build_card_from_raw` over JSON). The ``status`` field is restricted to
    :data:`FUTURE_PROFILE_STATUSES` and never carries an installed/ready value.

    Attributes
    ----------
    profile_id:
        Stable profile identifier (e.g. ``content_mathml``).
    name:
        Human-readable capability name (e.g. ``Content MathML``).
    status:
        One of :data:`FUTURE_PROFILE_STATUSES`.
    required_capability:
        The capability identifier the profile would need (e.g. ``cap.content_mathml``).
    platform_note:
        Platform or execution context note (e.g. ``remote/WAIT_PLATFORM``).
    honesty_note:
        Free-form caveat that restates the registry-only / bounded-experimental
        semantics and disclaims readiness.
    """

    profile_id: str
    name: str
    status: str
    required_capability: str
    platform_note: str
    honesty_note: str

    def to_dict(self) -> dict[str, Any]:
        """Return the card as a plain JSON-serializable dict."""
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "status": self.status,
            "required_capability": self.required_capability,
            "platform_note": self.platform_note,
            "honesty_note": self.honesty_note,
        }


# ---------------------------------------------------------------------------
# Field validators.
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, field: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise."""
    if not isinstance(value, str) or value == "":
        msg = f"{field} must be a non-empty string, got {value!r}"
        raise FutureProfileRegistryError(msg)
    return value


def _validate_profile_id(value: Any) -> str:
    """Validate the profile_id field (non-empty string)."""
    return _require_non_empty_str(value, "profile_id")


def _validate_name(value: Any) -> str:
    """Validate the name field (non-empty string)."""
    return _require_non_empty_str(value, "name")


def _validate_status(value: Any) -> str:
    """Validate the status field (one of the two permitted values)."""
    status = _require_non_empty_str(value, "status")
    if status not in FUTURE_PROFILE_STATUSES:
        msg = f"status {status!r} must be one of {list(FUTURE_PROFILE_STATUSES)}"
        raise FutureProfileRegistryError(msg)
    return status


def _validate_required_capability(value: Any) -> str:
    """Validate the required_capability field (non-empty string)."""
    return _require_non_empty_str(value, "required_capability")


def _validate_platform_note(value: Any) -> str:
    """Validate the platform_note field (non-empty string)."""
    return _require_non_empty_str(value, "platform_note")


def _validate_honesty_note(value: Any) -> str:
    """Validate the honesty_note field (string; may be empty)."""
    if not isinstance(value, str):
        msg = f"honesty_note must be a string, got {type(value).__name__}"
        raise FutureProfileRegistryError(msg)
    return value


# ---------------------------------------------------------------------------
# Builders.
# ---------------------------------------------------------------------------


def build_card(  # noqa: PLR0913 - mirrors the 6-field FutureProfileCard dataclass
    *,
    profile_id: Any,
    name: Any,
    status: Any,
    required_capability: Any,
    platform_note: Any,
    honesty_note: Any,
) -> FutureProfileCard:
    """Build and validate a :class:`FutureProfileCard`.

    Raises
    ------
    FutureProfileRegistryError
        With fail reason ``CONTRACT_INVALID`` if any field is malformed.
    """
    return FutureProfileCard(
        profile_id=_validate_profile_id(profile_id),
        name=_validate_name(name),
        status=_validate_status(status),
        required_capability=_validate_required_capability(required_capability),
        platform_note=_validate_platform_note(platform_note),
        honesty_note=_validate_honesty_note(honesty_note),
    )


# The required card keys (the ``FutureProfileCard/v1`` field set) and the allowed
# status values, as frozensets for key-set validation.
_CARD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "profile_id",
        "name",
        "status",
        "required_capability",
        "platform_note",
        "honesty_note",
    }
)
_STATUSES: Final[frozenset[str]] = frozenset(FUTURE_PROFILE_STATUSES)


def _build_card_from_raw(raw: Any) -> FutureProfileCard:
    """Build a validated :class:`FutureProfileCard` from a raw dict.

    Routes every field through :func:`build_card` so raw-JSON construction and
    programmatic construction share one validation path.
    """
    if not isinstance(raw, dict):
        msg = f"future profile card must be an object, got {type(raw).__name__}"
        raise FutureProfileRegistryError(msg)

    actual = set(raw.keys())
    missing = _CARD_KEYS - actual
    if missing:
        msg = f"future profile card missing required key(s): {sorted(missing)}"
        raise FutureProfileRegistryError(msg)
    extra = actual - _CARD_KEYS
    if extra:
        msg = f"future profile card has unexpected key(s): {sorted(extra)}"
        raise FutureProfileRegistryError(msg)

    status = raw["status"]
    if status not in _STATUSES:
        msg = (
            f"status {status!r} must be one of {list(FUTURE_PROFILE_STATUSES)}; "
            "a future profile card never claims installation or readiness"
        )
        raise FutureProfileRegistryError(msg)

    return build_card(
        profile_id=raw["profile_id"],
        name=raw["name"],
        status=status,
        required_capability=raw["required_capability"],
        platform_note=raw["platform_note"],
        honesty_note=raw["honesty_note"],
    )


def _validate_card_doc(doc: Any) -> dict[str, Any]:
    """Validate the raw card-document shape and return it."""
    if not isinstance(doc, dict):
        msg = f"future profile card document must be an object, got {type(doc).__name__}"
        raise FutureProfileRegistryError(msg)
    if doc.get("schema_version") != FUTURE_PROFILE_CARD_SCHEMA_VERSION:
        msg = (
            f"future profile card schema_version must be {FUTURE_PROFILE_CARD_SCHEMA_VERSION!r}, "
            f"got {doc.get('schema_version')!r}"
        )
        raise FutureProfileRegistryError(msg)
    cards = doc.get("cards")
    if not isinstance(cards, list):
        msg = f"future profile card document 'cards' must be an array, got {type(cards).__name__}"
        raise FutureProfileRegistryError(msg)
    return doc


def load_cards_from_doc(doc: Any) -> tuple[FutureProfileCard, ...]:
    """Load and validate a ``FutureProfileCard/v1`` document into a sorted card tuple.

    Returns
    -------
    tuple[FutureProfileCard, ...]
        The validated cards, sorted by ``profile_id`` for deterministic ordering.

    Raises
    ------
    FutureProfileRegistryError
        With ``CONTRACT_INVALID`` if the document shape, schema version, or any
        card is malformed.
    """
    validated = _validate_card_doc(doc)
    cards = tuple(_build_card_from_raw(c) for c in validated["cards"])
    return tuple(sorted(cards, key=lambda c: c.profile_id))


# ---------------------------------------------------------------------------
# Query API.
# ---------------------------------------------------------------------------


def _matches(card: FutureProfileCard, query: str) -> bool:
    """Return True if ``query`` (lowercased) appears in the card's searchable fields."""
    haystack = " ".join(
        (
            card.profile_id,
            card.name,
            card.status,
            card.required_capability,
            card.platform_note,
            card.honesty_note,
        )
    ).lower()
    return query in haystack


def search(
    query: str,
    cards: tuple[FutureProfileCard, ...] | None = None,
) -> tuple[FutureProfileCard, ...]:
    """Return the cards matching ``query``, deterministically sorted by ``profile_id``.

    Matching is case-insensitive substring search over all card fields. An empty
    or whitespace-only ``query`` returns every card (deterministic listing).
    """
    pool = DEFAULT_CARDS if cards is None else cards
    needle = query.strip().lower()
    if needle == "":
        return tuple(sorted(pool, key=lambda c: c.profile_id))
    matched = (c for c in pool if _matches(c, needle))
    return tuple(sorted(matched, key=lambda c: c.profile_id))


def inspect(
    profile_id: str,
    cards: tuple[FutureProfileCard, ...] | None = None,
) -> FutureProfileCard | None:
    """Return the card whose ``profile_id`` equals ``profile_id``, or ``None``.

    The match is exact and case-sensitive on the ``profile_id`` field.
    """
    pool = DEFAULT_CARDS if cards is None else cards
    for card in pool:
        if card.profile_id == profile_id:
            return card
    return None


# ---------------------------------------------------------------------------
# The six semantic future profile cards.
#
# These are honest registry entries: each records that a capability exists, the
# gap it would fill, and the platform/honesty notes that disclaim readiness. They
# are sorted by ``profile_id`` so canonical fixture output is stable.
# ---------------------------------------------------------------------------


#: The raw card literals. Authored in ``profile_id`` sorted order so the
#: canonical fixture snapshot is stable.
_RAW_CARDS: Final[tuple[dict[str, Any], ...]] = (
    {
        "profile_id": "content_mathml",
        "name": "Content MathML",
        "status": "registry_only",
        "required_capability": "cap.content_mathml",
        "platform_note": ("Import/export format surface; no executable platform target."),
        "honesty_note": (
            "Registry-only: no Content MathML parser or serializer is installed, "
            "and no claim of import/export readiness is implied."
        ),
    },
    {
        "profile_id": "dreal",
        "name": "dReal",
        "status": "registry_only",
        "required_capability": "cap.dreal",
        "platform_note": (
            "Remote/WAIT_PLATFORM: delta-satisfiability solving requires a remote "
            "executor or a dedicated platform build; not available locally."
        ),
        "honesty_note": (
            "Registry-only: no dReal binary is installed and no solver invocation "
            "path is implied. A request routes to WAIT_CAPABILITY."
        ),
    },
    {
        "profile_id": "latexml",
        "name": "LaTeXML",
        "status": "registry_only",
        "required_capability": "cap.latexml",
        "platform_note": (
            "Quarantined source ingestion: TeX-to-MathML conversion runs in an "
            "isolated sandbox with no write access to the corpus."
        ),
        "honesty_note": (
            "Registry-only: no LaTeXML installation or quarantine pipeline is implied."
        ),
    },
    {
        "profile_id": "lean_mathlib",
        "name": "Lean/mathlib",
        "status": "registry_only",
        "required_capability": "cap.lean_mathlib",
        "platform_note": (
            "Formal proof-engine capability; requires a Lean toolchain and a remote "
            "or sandboxed executor."
        ),
        "honesty_note": (
            "Registry-only: no Lean kernel, no mathlib checkout, and no proof "
            "certificate path is implied."
        ),
    },
    {
        "profile_id": "orkg_opencitations",
        "name": "ORKG / OpenCitations",
        "status": "registry_only",
        "required_capability": "cap.orkg_opencitations",
        "platform_note": (
            "Query-only: external knowledge-graph access over the network; no local "
            "mirror or write path."
        ),
        "honesty_note": (
            "Registry-only: no API credential, no local cache, and no federation "
            "guarantee is implied."
        ),
    },
    {
        "profile_id": "sciml_bounded",
        "name": "Bounded SciML executable model",
        "status": "bounded_experimental",
        "required_capability": "cap.sciml_bounded",
        "platform_note": (
            "One bounded SciML executable-model case: a single, resource-capped, "
            "deterministic simulation trace."
        ),
        "honesty_note": (
            "Bounded-experimental, not admitted: one toy case exists but does not "
            "satisfy the P1 admission framework and is not a general SciML capability."
        ),
    },
)

#: The six semantic future profile cards, validated at import and sorted by
#: ``profile_id``. This is the authoritative in-code registry; the canonical
#: fixture at ``fixtures/conformance/future_profiles/cards.v1.json`` is its
#: serialization.
DEFAULT_CARDS: Final[tuple[FutureProfileCard, ...]] = tuple(
    _build_card_from_raw(raw) for raw in _RAW_CARDS
)

#: The six future profile identifiers in canonical sorted order.
FUTURE_PROFILE_NAMES: Final[tuple[str, ...]] = tuple(c.profile_id for c in DEFAULT_CARDS)

#: O(1) membership test for the six future profile identifiers.
FUTURE_PROFILE_IDS: Final[frozenset[str]] = frozenset(FUTURE_PROFILE_NAMES)


def default_cards() -> tuple[FutureProfileCard, ...]:
    """Return the default six future profile cards, sorted by ``profile_id``."""
    return DEFAULT_CARDS


__all__ = [
    "DEFAULT_CARDS",
    "FUTURE_PROFILE_CARD_SCHEMA_VERSION",
    "FUTURE_PROFILE_IDS",
    "FUTURE_PROFILE_NAMES",
    "FUTURE_PROFILE_STATUSES",
    "FUTURE_PROFILE_STATUS_BOUNDED_EXPERIMENTAL",
    "FUTURE_PROFILE_STATUS_REGISTRY_ONLY",
    "FutureProfileCard",
    "FutureProfileRegistryError",
    "build_card",
    "default_cards",
    "inspect",
    "load_cards_from_doc",
    "search",
]
