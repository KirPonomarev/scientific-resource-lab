"""Tests for :mod:`srl.knowledge.registry` (P2 discovery registry, WP-H73).

All tests are hermetic: they build cards in-process and assert the
catalog-only invariant, the query API, and the builder validators. The
canonical fixture at ``fixtures/conformance/registry/cards.v1.json`` is also
asserted to round-trip through :func:`load_cards_from_doc` and to equal the
in-code :data:`DEFAULT_CARDS`, so the fixture is a faithful serialization of
the authoritative registry. No network, no clock, no pack store.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.knowledge.registry import (
    ADMISSION_STATUS_CATALOG_ONLY,
    DEFAULT_CARDS,
    DISCOVERY_CARD_ADMISSION_STATUSES,
    DISCOVERY_CARD_KINDS,
    DISCOVERY_CARD_SCHEMA_VERSION,
    DiscoveryCard,
    DiscoveryRegistryError,
    NotFound,
    build_card,
    default_cards,
    inspect,
    load_cards_from_doc,
    search,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOOD_FIXTURE = _REPO_ROOT / "fixtures" / "conformance" / "registry" / "cards.v1.json"
_BAD_FIXTURE = _REPO_ROOT / "fixtures" / "conformance" / "registry" / "cards.malformed.v1.json"

# The exact card count the registry must carry.
_CARD_COUNT = 13

# The 10 named external capabilities + 3 domain-pack placeholders.
_EXPECTED_NAMES = {
    "GROBID",
    "Catlab",
    "FEniCSx/PETSc",
    "OpenModelica",
    "OpenTURNS",
    "clingo",
    "Souffle",
    "ProbLog",
    "Vampire",
    "CasADi",
    "physics-domain-pack",
    "economics-domain-pack",
    "game-theory-domain-pack",
}


def _good_card_dict(card_id: str = "discovery.test.good") -> dict[str, Any]:
    """Return a minimal valid card dict for builder/rejection tests."""
    return {
        "card_id": card_id,
        "name": "Test",
        "kind": "library",
        "domains": ["test"],
        "license_declared": "MIT",
        "platforms": ["linux"],
        "capability_gap_it_would_fill": "a test gap",
        "admission_status": "catalog_only",
        "notes": "test notes",
    }


# ---------------------------------------------------------------------------
# DEFAULT_CARDS shape and the catalog-only invariant.
# ---------------------------------------------------------------------------


class TestDefaultCards:
    """The in-code authoritative registry is well-formed and catalog-only."""

    def test_exactly_thirteen_cards(self) -> None:
        assert len(DEFAULT_CARDS) == _CARD_COUNT

    def test_all_expected_names_present(self) -> None:
        names = {c.name for c in DEFAULT_CARDS}
        assert names == _EXPECTED_NAMES

    def test_sorted_by_card_id(self) -> None:
        ids = [c.card_id for c in DEFAULT_CARDS]
        assert ids == sorted(ids)

    def test_unique_card_ids(self) -> None:
        ids = [c.card_id for c in DEFAULT_CARDS]
        assert len(set(ids)) == len(ids)

    def test_every_card_is_catalog_only(self) -> None:
        for card in DEFAULT_CARDS:
            assert card.admission_status == ADMISSION_STATUS_CATALOG_ONLY

    def test_every_kind_in_enum(self) -> None:
        for card in DEFAULT_CARDS:
            assert card.kind in DISCOVERY_CARD_KINDS

    def test_every_card_has_non_empty_domains(self) -> None:
        for card in DEFAULT_CARDS:
            assert len(card.domains) > 0, f"{card.card_id} has empty domains"

    def test_placeholders_declare_no_license(self) -> None:
        placeholders = {c for c in DEFAULT_CARDS if "placeholder" in c.domains}
        assert len(placeholders) == 3
        for card in placeholders:
            assert card.license_declared is None
            assert card.platforms == ()

    def test_default_cards_matches_helper(self) -> None:
        assert default_cards() == DEFAULT_CARDS


# ---------------------------------------------------------------------------
# build_card: programmatic construction forces the catalog-only invariant.
# ---------------------------------------------------------------------------


class TestBuildCard:
    """The programmatic builder validates fields and forces catalog-only."""

    def test_builds_a_valid_card_forcing_catalog_only(self) -> None:
        card = build_card(
            card_id="discovery.build.ok",
            name="Build",
            kind="library",
            domains=("math",),
            license_declared="MIT",
            platforms=("linux",),
            capability_gap_it_would_fill="a gap",
            notes="notes",
        )
        assert card.admission_status == ADMISSION_STATUS_CATALOG_ONLY
        assert isinstance(card, DiscoveryCard)
        assert card.to_dict()["admission_status"] == ADMISSION_STATUS_CATALOG_ONLY

    def test_license_declared_may_be_none(self) -> None:
        card = build_card(
            card_id="discovery.build.nolic",
            name="NoLic",
            kind="application",
            domains=("d",),
            license_declared=None,
            platforms=(),
            capability_gap_it_would_fill="gap",
            notes="",
        )
        assert card.license_declared is None
        assert card.platforms == ()
        assert card.notes == ""

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("card_id", ""),
            ("name", ""),
            ("kind", "framework"),
            ("capability_gap_it_would_fill", ""),
        ],
    )
    def test_rejects_bad_scalar(self, field: str, bad_value: Any) -> None:
        kwargs: dict[str, Any] = dict(
            card_id="discovery.bad",
            name="Bad",
            kind="library",
            domains=("d",),
            license_declared=None,
            platforms=(),
            capability_gap_it_would_fill="gap",
            notes="",
        )
        kwargs[field] = bad_value
        with pytest.raises(DiscoveryRegistryError):
            build_card(**kwargs)

    def test_rejects_empty_domains(self) -> None:
        with pytest.raises(DiscoveryRegistryError):
            build_card(
                card_id="discovery.bad",
                name="Bad",
                kind="library",
                domains=(),
                license_declared=None,
                platforms=(),
                capability_gap_it_would_fill="gap",
                notes="",
            )

    def test_rejects_duplicate_domain_tags(self) -> None:
        with pytest.raises(DiscoveryRegistryError):
            build_card(
                card_id="discovery.bad",
                name="Bad",
                kind="library",
                domains=("math", "math"),
                license_declared=None,
                platforms=(),
                capability_gap_it_would_fill="gap",
                notes="",
            )

    def test_rejects_non_string_domain_element(self) -> None:
        with pytest.raises(DiscoveryRegistryError):
            build_card(
                card_id="discovery.bad",
                name="Bad",
                kind="library",
                domains=("math", 5),  # type: ignore[arg-type]
                license_declared=None,
                platforms=(),
                capability_gap_it_would_fill="gap",
                notes="",
            )

    def test_rejects_empty_string_license_declared(self) -> None:
        with pytest.raises(DiscoveryRegistryError):
            build_card(
                card_id="discovery.bad",
                name="Bad",
                kind="library",
                domains=("d",),
                license_declared="",
                platforms=(),
                capability_gap_it_would_fill="gap",
                notes="",
            )


# ---------------------------------------------------------------------------
# load_cards_from_doc: JSON-path validation and the catalog-only invariant.
# ---------------------------------------------------------------------------


class TestLoadCardsFromDoc:
    """The raw-JSON builder validates shape, schema, and the invariant."""

    def test_loads_valid_document(self) -> None:
        cards = load_cards_from_doc(
            {
                "schema_version": DISCOVERY_CARD_SCHEMA_VERSION,
                "cards": [_good_card_dict()],
            }
        )
        assert len(cards) == 1
        assert cards[0].admission_status == ADMISSION_STATUS_CATALOG_ONLY

    def test_round_trips_canonical_fixture_to_default_cards(self) -> None:
        doc = json.loads(_GOOD_FIXTURE.read_text(encoding="utf-8"))
        assert load_cards_from_doc(doc) == DEFAULT_CARDS

    def test_fixture_schema_version_is_current(self) -> None:
        doc = json.loads(_GOOD_FIXTURE.read_text(encoding="utf-8"))
        assert doc["schema_version"] == DISCOVERY_CARD_SCHEMA_VERSION

    def test_fixture_card_count_is_thirteen(self) -> None:
        doc = json.loads(_GOOD_FIXTURE.read_text(encoding="utf-8"))
        assert len(doc["cards"]) == _CARD_COUNT

    def test_rejects_wrong_schema_version(self) -> None:
        bad = {
            "schema_version": "DiscoveryCard/v0",
            "cards": [_good_card_dict()],
        }
        with pytest.raises(DiscoveryRegistryError):
            load_cards_from_doc(bad)

    def test_rejects_non_object_document(self) -> None:
        with pytest.raises(DiscoveryRegistryError):
            load_cards_from_doc([])  # type: ignore[arg-type]

    def test_rejects_missing_cards_key(self) -> None:
        with pytest.raises(DiscoveryRegistryError):
            load_cards_from_doc({"schema_version": DISCOVERY_CARD_SCHEMA_VERSION})

    def test_rejects_card_missing_key(self) -> None:
        card = _good_card_dict()
        del card["kind"]
        with pytest.raises(DiscoveryRegistryError):
            load_cards_from_doc({"schema_version": DISCOVERY_CARD_SCHEMA_VERSION, "cards": [card]})

    def test_rejects_card_with_extra_key(self) -> None:
        card = _good_card_dict()
        card["surprise"] = "no"
        with pytest.raises(DiscoveryRegistryError):
            load_cards_from_doc({"schema_version": DISCOVERY_CARD_SCHEMA_VERSION, "cards": [card]})

    @pytest.mark.parametrize("status", ["admitted", "ready", "built", "candidate", "", None])
    def test_rejects_non_catalog_only_status(self, status: Any) -> None:
        card = _good_card_dict()
        card["admission_status"] = status
        with pytest.raises(DiscoveryRegistryError):
            load_cards_from_doc({"schema_version": DISCOVERY_CARD_SCHEMA_VERSION, "cards": [card]})

    def test_rejects_non_array_domains(self) -> None:
        card = _good_card_dict()
        card["domains"] = "nlp"
        with pytest.raises(DiscoveryRegistryError):
            load_cards_from_doc({"schema_version": DISCOVERY_CARD_SCHEMA_VERSION, "cards": [card]})

    def test_result_is_sorted_by_card_id(self) -> None:
        doc = {
            "schema_version": DISCOVERY_CARD_SCHEMA_VERSION,
            "cards": [
                _good_card_dict("discovery.z"),
                _good_card_dict("discovery.a"),
                _good_card_dict("discovery.m"),
            ],
        }
        cards = load_cards_from_doc(doc)
        assert [c.card_id for c in cards] == ["discovery.a", "discovery.m", "discovery.z"]

    def test_malformed_fixture_is_rejected_typed(self) -> None:
        doc = json.loads(_BAD_FIXTURE.read_text(encoding="utf-8"))
        with pytest.raises(DiscoveryRegistryError) as excinfo:
            load_cards_from_doc(doc)
        assert excinfo.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


# ---------------------------------------------------------------------------
# Query API: search and inspect.
# ---------------------------------------------------------------------------


class TestSearch:
    """``search`` is substring-based, case-insensitive, and deterministic."""

    def test_empty_query_lists_all_sorted(self) -> None:
        result = search("")
        assert [c.card_id for c in result] == sorted(c.card_id for c in DEFAULT_CARDS)
        assert len(result) == _CARD_COUNT

    def test_whitespace_query_lists_all(self) -> None:
        assert search("   ") == search("")

    def test_case_insensitive_substring_match(self) -> None:
        lower = {c.card_id for c in search("grobid")}
        upper = {c.card_id for c in search("GROBID")}
        assert lower == upper == {"discovery.grobid"}

    def test_matches_name_substring(self) -> None:
        result = {c.card_id for c in search("vamp")}
        assert result == {"discovery.vampire"}

    def test_matches_domain_substring(self) -> None:
        # "logic" appears in ProbLog and Vampire domains.
        result = {c.card_id for c in search("logic")}
        assert result == {"discovery.problog", "discovery.vampire"}

    def test_matches_card_id_substring(self) -> None:
        result = {c.card_id for c in search("domain.")}
        assert result == {
            "discovery.domain.economics",
            "discovery.domain.game",
            "discovery.domain.physics",
        }

    def test_no_match_returns_empty(self) -> None:
        assert search("zzz-no-such-thing-zzz") == ()

    def test_deterministic_across_calls(self) -> None:
        assert search("a") == search("a")

    def test_independent_of_input_order(self) -> None:
        forward = search("opt", tuple(DEFAULT_CARDS))
        reversed_ = search("opt", tuple(reversed(DEFAULT_CARDS)))
        assert forward == reversed_

    def test_uses_explicit_pool_when_given(self) -> None:
        custom = (
            build_card(
                card_id="discovery.custom.alpha",
                name="AlphaCustom",
                kind="library",
                domains=("customtag",),
                license_declared=None,
                platforms=(),
                capability_gap_it_would_fill="a custom gap",
                notes="",
            ),
        )
        assert {c.card_id for c in search("customtag", custom)} == {"discovery.custom.alpha"}
        # Without an explicit pool, the default registry is searched.
        assert search("customtag") == ()


class TestInspect:
    """``inspect`` is exact-match on name and returns a typed NotFound on miss."""

    def test_finds_card_by_exact_name(self) -> None:
        result = inspect("GROBID")
        assert isinstance(result, DiscoveryCard)
        assert result.card_id == "discovery.grobid"

    def test_miss_returns_typed_not_found(self) -> None:
        result = inspect("DoesNotExist")
        assert isinstance(result, NotFound)
        assert result.name == "DoesNotExist"
        assert "DoesNotExist" in result.detail

    def test_is_case_sensitive(self) -> None:
        # Names like 'clingo' are lowercase; 'CLINGO' must miss.
        assert isinstance(inspect("CLINGO"), NotFound)

    def test_finds_each_expected_name(self) -> None:
        for name in _EXPECTED_NAMES:
            result = inspect(name)
            assert isinstance(result, DiscoveryCard), f"miss for {name!r}"
            assert result.name == name

    def test_uses_explicit_pool_when_given(self) -> None:
        custom = (
            build_card(
                card_id="discovery.custom.beta",
                name="BetaCustom",
                kind="library",
                domains=("customtag",),
                license_declared=None,
                platforms=(),
                capability_gap_it_would_fill="a custom gap",
                notes="",
            ),
        )
        assert isinstance(inspect("BetaCustom", custom), DiscoveryCard)
        assert isinstance(inspect("BetaCustom"), NotFound)


# ---------------------------------------------------------------------------
# Error typing and frozen-dataclass behavior.
# ---------------------------------------------------------------------------


class TestErrorAndImmutability:
    """The error is a typed ContractError; cards are immutable."""

    def test_error_is_contract_error_with_contract_invalid_reason(self) -> None:
        with pytest.raises(DiscoveryRegistryError) as excinfo:
            build_card(
                card_id="",  # invalid
                name="Bad",
                kind="library",
                domains=("d",),
                license_declared=None,
                platforms=(),
                capability_gap_it_would_fill="gap",
                notes="",
            )
        assert isinstance(excinfo.value, ContractError)
        assert isinstance(excinfo.value, ValueError)
        assert excinfo.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_card_is_frozen(self) -> None:
        card = next(c for c in DEFAULT_CARDS if "placeholder" in c.domains)
        with pytest.raises((AttributeError, TypeError)):
            card.name = "Mutated"  # type: ignore[misc]

    def test_admission_statuses_constant_is_singleton(self) -> None:
        assert DISCOVERY_CARD_ADMISSION_STATUSES == (ADMISSION_STATUS_CATALOG_ONLY,)

    def test_to_dict_round_trips_through_load(self) -> None:
        # Serialize the defaults to the doc shape and reload them.
        doc = {
            "schema_version": DISCOVERY_CARD_SCHEMA_VERSION,
            "cards": [c.to_dict() for c in DEFAULT_CARDS],
        }
        reloaded = load_cards_from_doc(copy.deepcopy(doc))
        assert reloaded == DEFAULT_CARDS
