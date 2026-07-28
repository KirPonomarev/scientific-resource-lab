"""Unit tests for the deterministic plan builder (``srl.planning.planner``).

Pins the load-bearing properties:

1. **DAG order**: steps are emitted in topological order; a step appears after
   every step it depends_on.
2. **cycle detection**: a cyclic dependency graph raises ``PlanError``
   (``CONTRACT_INVALID``, ``invariant=cycle_detected``).
3. **resource admission**: summed SELECTED estimates exceeding the class caps
   raise ``ResourceAdmissionError`` (``WAIT_REMOTE_EXECUTOR``); under-cap plans
   admit.
4. **digest stability**: ``plan_id`` and ``plan_digest`` are idempotent
   (recomputing yields the same value).
5. **determinism (Hypothesis)**: random valid requests produce deterministic
   plans (byte-identical across rebuilds, including a shuffled-key variant).
6. **safety consts**: a plan pins ``canonical_writes=0`` and
   ``grants_authority=false``.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.contracts.schema import validate as schema_validate
from srl.planning import (
    SCIENCE_LAB_PROFILES,
    AdmissionPolicy,
    PlanError,
    ResourceAdmissionError,
    build_plan,
    build_request,
    default_policy,
    load_catalog,
    load_default_catalog,
    plan_digest,
    plan_id,
    route,
    topological_order,
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


def _available_catalog() -> Any:
    """A synthetic catalog where every profile has an available adapter."""
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
                for p in SCIENCE_LAB_PROFILES
            ],
        }
    )


class TestPlannerDagOrder:
    """Steps are emitted in topological order; depends_on edges respected."""

    def test_steps_in_topological_order(self) -> None:
        cat = load_default_catalog()
        claim = _claim("composition of coupled ode subsystems forming a hierarchical model")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())
        # Every step appears after every step it depends_on.
        seen: set[str] = set()
        for step in plan["steps"]:
            for dep in step["depends_on"]:
                assert dep in seen, f"{step['step_id']} depends on {dep} before it appeared"
            seen.add(step["step_id"])

    def test_model_composition_depends_on_components(self) -> None:
        cat = load_default_catalog()
        claim = _claim("composition of coupled ode subsystems forming a hierarchical model")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())
        comp = next(s for s in plan["steps"] if s["profile"] == "model_composition")
        assert "dynamics" in comp["depends_on"]
        assert "executable_ode_dae_sde_model" in comp["depends_on"]

    def test_plan_step_count_is_15(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())
        assert len(plan["steps"]) == 15


class TestPlannerCycleDetection:
    """A cyclic dependency graph raises PlanError (cycle_detected)."""

    def test_cycle_raises_plan_error(self) -> None:
        with pytest.raises(PlanError) as exc_info:
            topological_order(
                ["dynamics", "executable_ode_dae_sde_model"],
                {
                    "dynamics": {"executable_ode_dae_sde_model"},
                    "executable_ode_dae_sde_model": {"dynamics"},
                },
            )
        assert exc_info.value.fail_reason == "CONTRACT_INVALID"
        assert exc_info.value.invariant == "cycle_detected"

    def test_self_cycle_raises_plan_error(self) -> None:
        with pytest.raises(PlanError):
            topological_order(["dynamics"], {"dynamics": {"dynamics"}})

    def test_acyclic_graph_orders_stably(self) -> None:
        order = topological_order(
            ["a", "b", "c"],
            {"a": set(), "b": {"a"}, "c": {"b"}},
        )
        assert order == ["a", "b", "c"]


class TestPlannerResourceAdmission:
    """Summed SELECTED estimates exceeding caps raise WAIT_REMOTE_EXECUTOR."""

    def test_overflow_raises_resource_admission_error(self) -> None:
        cat = _available_catalog()
        # Engage enough heavy profiles under exception caps to overflow rss_bytes.
        claim = _claim("a bare claim")
        req = build_request(
            claim_id=_DIGEST,
            requested_profiles=[
                "pde_variational_model",
                "geometry_tda",
                "nonlinear_continuous_or_hybrid_constraint",
                "executable_ode_dae_sde_model",
            ],
            resource_class="exception",
        )
        dec = route(req, claim, cat, default_policy())
        with pytest.raises(ResourceAdmissionError) as exc_info:
            build_plan(req, dec, cat, default_policy())
        assert exc_info.value.fail_reason == "WAIT_REMOTE_EXECUTOR"
        assert exc_info.value.over  # at least one dimension overflowed

    def test_single_profile_admits(self) -> None:
        cat = _available_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=["geometry_tda"])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())  # must not raise
        assert plan["schema_version"] == "ScienceLabPlan/v1"

    def test_tight_caps_force_overflow(self) -> None:
        # A custom policy with tiny caps forces overflow even for one profile.
        cat = _available_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=["geometry_tda"])
        dec = route(req, claim, cat, default_policy())
        tight = AdmissionPolicy(
            {
                "schema_version": "AdmissionPolicy/v1",
                "default_caps": {
                    "wall_seconds": 1,
                    "rss_bytes": 1,
                    "scratch_bytes": 1,
                },
                "exception_caps": {
                    "wall_seconds": 1,
                    "rss_bytes": 1,
                    "scratch_bytes": 1,
                },
            }
        )
        with pytest.raises(ResourceAdmissionError) as exc_info:
            build_plan(req, dec, cat, tight)
        assert exc_info.value.fail_reason == "WAIT_REMOTE_EXECUTOR"


class TestPlannerDigestStability:
    """plan_id and plan_digest are idempotent."""

    def test_plan_id_idempotent(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())
        assert plan["plan_id"] == plan_id(plan)

    def test_plan_digest_idempotent(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())
        assert plan["plan_digest"] == plan_digest(plan)

    def test_plan_validates_against_schema(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())
        schema_validate(plan, "ScienceLabPlan")
        schema_validate(req, "ScienceLabRunRequest")

    def test_safety_consts_pinned(self) -> None:
        cat = load_default_catalog()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[])
        dec = route(req, claim, cat, default_policy())
        plan = build_plan(req, dec, cat, default_policy())
        assert plan["canonical_writes"] == 0
        assert plan["grants_authority"] is False
        # Request-specific safety consts.
        assert req["prospective_holdout_materialization_allowed"] is False
        assert req["status_promotion_allowed"] is False


class TestPlannerDeterminismHypothesis:
    """Hypothesis: random valid requests produce deterministic plans."""

    @given(
        seed=st.integers(min_value=0, max_value=1000),
        threads=st.integers(min_value=1, max_value=8),
        resource_class=st.sampled_from(["default", "exception"]),
    )
    def test_random_request_yields_deterministic_plan(
        self, seed: int, threads: int, resource_class: str
    ) -> None:
        cat = load_default_catalog()
        pol = default_policy()
        claim = _claim("persistent homology betti numbers")
        req = build_request(
            claim_id=_DIGEST,
            requested_profiles=[],
            resource_class=resource_class,
            seed=seed,
            threads=threads,
        )
        dec1 = route(req, claim, cat, pol)
        plan1 = build_plan(req, dec1, cat, pol)
        dec2 = route(req, claim, cat, pol)
        plan2 = build_plan(req, dec2, cat, pol)
        # Byte-identical canonical encoding.
        assert dumps(plan1) == dumps(plan2)
        assert plan1["plan_id"] == plan2["plan_id"]

    @given(
        seed=st.integers(min_value=0, max_value=100),
    )
    def test_shuffled_input_keys_yield_identical_plan(self, seed: int) -> None:
        cat = load_default_catalog()
        pol = default_policy()
        claim = _claim("persistent homology betti numbers")
        req = build_request(claim_id=_DIGEST, requested_profiles=[], seed=seed)
        plan1 = build_plan(req, route(req, claim, cat, pol), cat, pol)
        # Shuffle the request's top-level key order; canonical JSON must sort.
        shuffled_req = {k: req[k] for k in reversed(list(req))}
        plan2 = build_plan(shuffled_req, route(shuffled_req, claim, cat, pol), cat, pol)
        assert dumps(plan1) == dumps(plan2)


class TestPlannerValidation:
    """The planner rejects malformed requests."""

    def test_non_object_request_rejected(self) -> None:
        cat = load_default_catalog()
        with pytest.raises(ContractError):
            build_plan(
                "not a dict",
                route(build_request(claim_id=_DIGEST), _claim(), cat, default_policy()),
                cat,
                default_policy(),
            )

    def test_wrong_schema_version_rejected(self) -> None:
        cat = load_default_catalog()
        bad_req = {"schema_version": "Wrong/v1", "request_id": _DIGEST}
        with pytest.raises(ContractError):
            build_plan(
                bad_req,
                route(build_request(claim_id=_DIGEST), _claim(), cat, default_policy()),
                cat,
                default_policy(),
            )
