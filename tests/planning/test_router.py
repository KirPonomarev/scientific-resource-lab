"""Unit tests for the deterministic claim router (``srl.planning.router``).

Pins the load-bearing properties:

1. **four selection states**: SELECTED, EXCLUDED_TYPED, NOT_APPLICABLE,
   WAIT_CAPABILITY are all reachable and typed correctly.
2. **decision coverage**: the decision covers ALL 15 profiles (no silent drops).
3. **no silent fallback**: a remote_required profile never falls back to a local
   adapter; absence yields WAIT_CAPABILITY, never a fabricated adapter.
4. **adapterless waits**: a profile with no available adapter (future /
   remote_required / unknown) routes WAIT_CAPABILITY.
5. **explicit exclusion**: a request naming a subset yields EXCLUDED_TYPED for
   the rest, with the typed reason.
6. **determinism**: the same inputs yield the same decision.
"""

from __future__ import annotations

from typing import Any

import pytest

from srl.contracts.errors import ContractError
from srl.planning import (
    SCIENCE_LAB_PROFILES,
    build_request,
    default_policy,
    load_catalog,
    load_default_catalog,
    route,
)
from srl.planning.router import (
    EXCLUSION_NOT_REQUESTED,
    SELECTION_EXCLUDED_TYPED,
    SELECTION_NOT_APPLICABLE,
    SELECTION_SELECTED,
    SELECTION_WAIT_CAPABILITY,
)

_DIGEST = "sha256:" + "a" * 64


def _claim(statement: str = "a bare claim", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": statement,
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    base.update(overrides)
    return base


def _available_catalog(profiles: list[str] | None = None) -> Any:
    """A synthetic catalog where every (named) profile has an available adapter."""
    caps = SCIENCE_LAB_PROFILES if profiles is None else profiles
    return load_catalog(
        {
            "schema_version": "CapabilityCatalog/v1",
            "capabilities": [
                {
                    "capability_id": f"cap.{p}",
                    "profile": p,
                    "adapter_id": f"adapter-{p}",
                    "availability": "available",
                }
                for p in caps
            ],
        }
    )


class TestRouterSelectionStates:
    """All four selection states are reachable and typed correctly."""

    def test_wait_capability_reachable_for_adapterless_profile(self) -> None:
        # geometry_tda in the shipped catalog is availability=future -> WAIT_CAPABILITY.
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        assert dec.selection_for("geometry_tda") == SELECTION_WAIT_CAPABILITY
        assert dec.profiles["geometry_tda"].adapter_id is None

    def test_selected_reachable_with_available_adapter(self) -> None:
        cat = _available_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=["geometry_tda"])
        dec = route(req, claim, cat, default_policy())
        assert dec.selection_for("geometry_tda") == SELECTION_SELECTED
        assert dec.profiles["geometry_tda"].adapter_id == "adapter-geometry_tda"

    def test_not_applicable_reachable_for_unrelated_profile(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        # A profile the classifier did not select (auto-classify) is NOT_APPLICABLE.
        assert dec.selection_for("optimization") == SELECTION_NOT_APPLICABLE
        assert dec.profiles["optimization"].exclusion_reason is None

    def test_excluded_typed_reachable_for_not_requested_profile(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=["geometry_tda"])
        dec = route(req, claim, cat, default_policy())
        # A profile outside the requested set is EXCLUDED_TYPED with reason.
        assert dec.selection_for("optimization") == SELECTION_EXCLUDED_TYPED
        assert dec.profiles["optimization"].exclusion_reason == EXCLUSION_NOT_REQUESTED


class TestRouterCoverage:
    """The decision covers ALL 15 profiles (no silent drops)."""

    def test_decision_covers_all_profiles(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        assert set(dec.profiles) == set(SCIENCE_LAB_PROFILES)

    def test_applicable_union_of_selected_and_waiting(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        applicable = dec.applicable_profiles()
        assert applicable == dec.selected_profiles() | dec.waiting_profiles()


class TestRouterNoSilentFallback:
    """A remote_required profile never falls back to a local adapter."""

    def test_remote_required_profile_has_no_local_adapter(self) -> None:
        cat = load_default_catalog()
        claim = _claim(
            "an established law reference",
            epistemic_source="literature",
            claim_class="established_law_reference",
        )
        claim["support_refs"] = [_DIGEST]
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        # literature is remote_required in the shipped catalog.
        assert cat.is_remote_required("literature")
        assert dec.selection_for("literature") == SELECTION_WAIT_CAPABILITY
        assert dec.profiles["literature"].adapter_id is None

    def test_remote_required_with_named_adapter_still_waits(self) -> None:
        # A remote_required entry that NAMES an adapter_id still routes WAIT_CAPABILITY.
        cat = load_catalog(
            {
                "schema_version": "CapabilityCatalog/v1",
                "capabilities": [
                    {
                        "capability_id": "cap.literature",
                        "profile": "literature",
                        "adapter_id": "some-remote-adapter",
                        "availability": "remote_required",
                    }
                ],
            }
        )
        claim = _claim(
            "an established law reference",
            epistemic_source="literature",
            claim_class="established_law_reference",
        )
        claim["support_refs"] = [_DIGEST]
        req = build_request(claim_id=_DIGEST, requested_profiles=["literature"])
        dec = route(req, claim, cat, default_policy())
        assert dec.selection_for("literature") == SELECTION_WAIT_CAPABILITY
        assert dec.profiles["literature"].adapter_id is None

    def test_unknown_capability_routes_wait_capability(self) -> None:
        # A profile absent from the catalog routes WAIT_CAPABILITY (no fabricated adapter).
        cat = load_catalog(
            {
                "schema_version": "CapabilityCatalog/v1",
                "capabilities": [
                    {
                        "capability_id": "cap.algebra_exact",
                        "profile": "algebra_exact",
                        "adapter_id": None,
                        "availability": "future",
                    }
                ],
            }
        )
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=["geometry_tda"])
        dec = route(req, claim, cat, default_policy())
        assert dec.selection_for("geometry_tda") == SELECTION_WAIT_CAPABILITY
        assert dec.profiles["geometry_tda"].adapter_id is None
        assert dec.profiles["geometry_tda"].availability == "unknown"


class TestRouterDeterminism:
    """The router is deterministic: same inputs -> same decision."""

    def test_same_inputs_yield_same_decision(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        d1 = route(req, claim, cat, default_policy())
        d2 = route(req, claim, cat, default_policy())
        assert d1.to_dict() == d2.to_dict()
        assert d1.classifier_trace == d2.classifier_trace


class TestRouterValidation:
    """The router rejects malformed inputs."""

    def test_non_object_request_rejected(self) -> None:
        with pytest.raises(ContractError):
            route("not a dict", _claim(), load_default_catalog(), default_policy())

    def test_non_object_claim_rejected(self) -> None:
        req = build_request(claim_id=_DIGEST)
        with pytest.raises(ContractError):
            route(req, "not a dict", load_default_catalog(), default_policy())

    def test_unknown_requested_profile_rejected(self) -> None:
        req = build_request(claim_id=_DIGEST)
        # Mutate to carry an unknown profile (build_request would reject it).
        bad_req = dict(req)
        bad_req["requested_profiles"] = ["not_a_profile"]
        with pytest.raises(ContractError):
            route(bad_req, _claim(), load_default_catalog(), default_policy())
