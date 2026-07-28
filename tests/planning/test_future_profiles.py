"""Hermetic tests for the semantic future profile registry (WP-H72).

Pins the load-bearing properties:

1. The six future profile cards exist and are structurally valid.
2. Every card is registry-only or bounded-experimental; no card claims readiness.
3. A request that explicitly names a future profile routes to
   ``WAIT_CAPABILITY`` via the router's unknown/future capability path, with no
   adapter and no fabricated success.
4. The in-code registry and the canonical fixture are identical.
5. Future-profile routing is deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.planning import SCIENCE_LAB_PROFILES, default_policy, load_default_catalog
from srl.planning.future_profiles import (
    DEFAULT_CARDS,
    FUTURE_PROFILE_NAMES,
    FUTURE_PROFILE_STATUSES,
    FutureProfileCard,
    FutureProfileRegistryError,
    build_card,
    inspect,
    load_cards_from_doc,
    search,
)
from srl.planning.router import (
    SELECTION_EXCLUDED_TYPED,
    SELECTION_NOT_APPLICABLE,
    SELECTION_WAIT_CAPABILITY,
    route,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FUTURE_FIXTURES = _REPO_ROOT / "fixtures" / "conformance" / "future_profiles"
_CARDS_FIXTURE = _FUTURE_FIXTURES / "cards.v1.json"
_DREAL_CLAIM_FIXTURE = _FUTURE_FIXTURES / "dreal-claim.json"


def _cards_fixture() -> dict[str, Any]:
    """Load the canonical future profile card fixture as a raw dict."""
    return json.loads(_CARDS_FIXTURE.read_text(encoding="utf-8"))


def _minimal_claim() -> dict[str, Any]:
    """Return a minimal ScientificClaim/v1 for routing tests."""
    return {
        "schema_version": "ScientificClaim/v1",
        "claim_id": "sha256:" + "a" * 64,
        "statement": "a claim that names a future profile",
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _route_future(profile_id: str) -> Any:
    """Route a request that explicitly names a single future profile."""
    request: dict[str, Any] = {"requested_profiles": [profile_id]}
    return route(request, _minimal_claim(), load_default_catalog(), default_policy())


class TestFutureProfileRegistry:
    """The six cards are present, valid, and never claim readiness."""

    def test_default_card_count(self) -> None:
        assert len(DEFAULT_CARDS) == 6

    def test_default_cards_sorted(self) -> None:
        ids = [c.profile_id for c in DEFAULT_CARDS]
        assert ids == sorted(ids)

    def test_all_statuses_allowed(self) -> None:
        for card in DEFAULT_CARDS:
            assert card.status in FUTURE_PROFILE_STATUSES

    def test_no_card_claims_readiness(self) -> None:
        for card in DEFAULT_CARDS:
            assert card.status not in {"installed", "ready"}

    def test_build_card_validates_status(self) -> None:
        with pytest.raises(FutureProfileRegistryError):
            build_card(
                profile_id="x",
                name="X",
                status="installed",
                required_capability="cap.x",
                platform_note="none",
                honesty_note="none",
            )

    def test_to_dict_round_trip(self) -> None:
        for card in DEFAULT_CARDS:
            raw = card.to_dict()
            rebuilt = build_card(**raw)
            assert rebuilt == card

    def test_load_cards_from_doc_matches_defaults(self) -> None:
        doc = _cards_fixture()
        loaded = load_cards_from_doc(doc)
        assert loaded == DEFAULT_CARDS
        assert [c.profile_id for c in loaded] == sorted([c.profile_id for c in loaded])

    def test_load_cards_from_doc_rejects_bad_schema_version(self) -> None:
        doc = _cards_fixture()
        doc["schema_version"] = "WrongSchema/v1"
        with pytest.raises(FutureProfileRegistryError):
            load_cards_from_doc(doc)

    def test_search_and_inspect(self) -> None:
        assert len(search("")) == 6
        assert len(search("dreal")) == 1
        assert inspect("dreal").profile_id == "dreal"
        assert inspect("not_a_profile") is None


class TestFutureProfileRouting:
    """A future profile request routes to WAIT_CAPABILITY honestly."""

    @pytest.mark.parametrize("profile_id", FUTURE_PROFILE_NAMES)
    def test_future_profile_routes_wait_capability(self, profile_id: str) -> None:
        decision = _route_future(profile_id)
        routing = decision.profiles[profile_id]
        assert routing.selection == SELECTION_WAIT_CAPABILITY
        assert routing.adapter_id is None
        assert routing.capability_id == f"cap.{profile_id}"
        assert routing.availability == "unknown"
        assert len(decision.selected_profiles()) == 0

    def test_dreal_claim_fixture_routes_wait_capability(self) -> None:
        claim = json.loads(_DREAL_CLAIM_FIXTURE.read_text(encoding="utf-8"))
        request: dict[str, Any] = {"requested_profiles": ["dreal"]}
        decision = route(request, claim, load_default_catalog(), default_policy())
        assert decision.profiles["dreal"].selection == SELECTION_WAIT_CAPABILITY

    def test_unrequested_profiles_are_excluded_typed(self) -> None:
        decision = _route_future("dreal")
        for profile in SCIENCE_LAB_PROFILES:
            assert profile in decision.profiles
            selection = decision.profiles[profile].selection
            assert selection in {SELECTION_EXCLUDED_TYPED, SELECTION_NOT_APPLICABLE}

    def test_routing_is_deterministic(self) -> None:
        request: dict[str, Any] = {"requested_profiles": list(FUTURE_PROFILE_NAMES)}
        catalog = load_default_catalog()
        policy = default_policy()
        claim = _minimal_claim()
        d1 = route(request, claim, catalog, policy)
        d2 = route(request, claim, catalog, policy)
        assert d1.to_dict() == d2.to_dict()
        assert d1.classifier_trace == d2.classifier_trace

    def test_future_profile_card_dataclass(self) -> None:
        card = FutureProfileCard(
            profile_id="test",
            name="Test",
            status="registry_only",
            required_capability="cap.test",
            platform_note="none",
            honesty_note="none",
        )
        assert card.status == "registry_only"
        assert card.to_dict()["status"] == "registry_only"
