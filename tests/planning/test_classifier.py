"""Unit tests for the deterministic claim classifier (``srl.planning.classifier``).

Pins the load-bearing properties:

1. **determinism**: the same inputs always yield the same profiles and the
   same rule trace (pure function).
2. **traceability**: every decision is backed by a non-empty rule trace when
   profiles are selected (the classifier never silently selects a profile).
3. **keyword + cd coverage**: the rule table maps the documented scientific
   vocabulary and MathIR cds to the right profiles.
4. **empty result**: a claim matching no rule yields an empty frozenset and an
   empty trace (the router then routes every profile NOT_APPLICABLE).
5. **profile completeness**: the rule table only ever selects known profiles.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from srl.contracts.errors import ContractError
from srl.planning.classifier import classify
from srl.planning.profiles import PROFILE_NAMES, SCIENCE_LAB_PROFILES

_DIGEST = "sha256:" + "a" * 64


def _claim(statement: str = "", **overrides: Any) -> dict[str, Any]:
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


class TestClassifierDeterminism:
    """The classifier is a pure, deterministic function of its inputs."""

    def test_same_inputs_yield_same_profiles_and_trace(self) -> None:
        claim = _claim("We compute persistent homology and Betti numbers.")
        p1, t1 = classify(claim, {}, {})
        p2, t2 = classify(claim, {}, {})
        assert p1 == p2
        assert t1 == t2

    def test_input_key_order_does_not_affect_result(self) -> None:
        # A claim with shuffled top-level keys must classify identically.
        claim_a = _claim("persistent homology betti numbers")
        claim_b = {k: claim_a[k] for k in reversed(list(claim_a))}
        assert classify(claim_a, {}, {}) == classify(claim_b, {}, {})

    def test_empty_claim_yields_empty_result(self) -> None:
        profiles, trace = classify(_claim("a claim with no matching keywords"), {}, {})
        assert profiles == frozenset()
        assert trace == []

    def test_selected_profiles_are_known(self) -> None:
        # Every rule selects only known profile names (validated at import, but
        # assert at runtime too across a range of claims).
        statements = [
            "persistent homology betti numbers",
            "ordinary differential equation initial value problem",
            "partial differential equation variational weak form",
            "nonlinear constraint smt satisfiability",
            "causal granger intervention time series",
            "uncertainty bayesian posterior",
            "optimization optimal control minimize",
            "theorem proof lemma",
            "linear system eigenvalue exact arithmetic",
            "composition coupled subsystem hierarchical",
            "protocol specification refinement",
        ]
        for statement in statements:
            profiles, _ = classify(_claim(statement), {}, {})
            assert profiles <= frozenset(SCIENCE_LAB_PROFILES), statement


class TestClassifierRules:
    """The rule table maps vocabulary + cds to the documented profiles."""

    @pytest.mark.parametrize(
        ("statement", "expected"),
        [
            ("persistent homology betti numbers", {"geometry_tda"}),
            ("topological data analysis filtration", {"geometry_tda"}),
            (
                "ordinary differential equation initial value problem",
                {"executable_ode_dae_sde_model", "dynamics"},
            ),
            ("stochastic differential sde", {"executable_ode_dae_sde_model", "dynamics"}),
            (
                "partial differential equation variational weak form",
                {"pde_variational_model", "dynamics"},
            ),
            (
                "nonlinear constraint smt satisfiability",
                {"nonlinear_continuous_or_hybrid_constraint"},
            ),
            ("causal granger intervention time series", {"causal_time_series"}),
            ("uncertainty bayesian posterior confidence interval", {"uncertainty"}),
            ("optimization optimal control minimize", {"optimization"}),
            ("theorem proof lemma corollary", {"theorem_or_proof_obligation"}),
            ("linear system eigenvalue exact arithmetic", {"algebra_exact"}),
            ("composition coupled subsystem hierarchical", {"model_composition"}),
            ("protocol specification refinement", {"formal_protocol"}),
        ],
    )
    def test_statement_rule_selects_expected_profiles(
        self, statement: str, expected: set[str]
    ) -> None:
        profiles, trace = classify(_claim(statement), {}, {})
        assert set(profiles) == expected
        # Every selected profile must be backed by a fired rule.
        assert len(trace) >= 1

    def test_literature_source_selects_literature_profiles(self) -> None:
        claim = _claim(
            "an established law",
            epistemic_source="literature",
            claim_class="established_law_reference",
        )
        profiles, trace = classify(claim, {}, {})
        assert {"literature", "literature_extraction"} <= set(profiles)
        assert "R-LITERATURE" in trace

    def test_established_law_class_selects_symbolic_law(self) -> None:
        claim = _claim(
            "an established law",
            epistemic_source="literature",
            claim_class="established_law_reference",
        )
        profiles, trace = classify(claim, {}, {})
        assert {"symbolic_law", "theorem_or_proof_obligation"} <= set(profiles)
        assert "R-ESTABLISHED-LAW" in trace

    def test_cd_rules_select_profiles_from_inputs(self) -> None:
        # A symbol_table with a calculus1 cd selects dynamics via R-CD-CALCULUS.
        claim = _claim("a bare claim with no keywords")
        st_table = {"symbols": [{"cd": "calculus1", "name": "diff"}]}
        profiles, trace = classify(claim, st_table, {})
        assert "dynamics" in profiles
        assert "R-CD-CALCULUS" in trace

    def test_condition_set_op_cd_is_extracted(self) -> None:
        # A condition_set entry whose op is 'linalg1.determinant' selects algebra_exact.
        claim = _claim("a bare claim")
        cond_set = {"conditions": [{"op": "linalg1.determinant"}]}
        profiles, trace = classify(claim, {}, cond_set)
        assert "algebra_exact" in profiles
        assert "R-CD-LINALG" in trace

    def test_multiple_rules_combine(self) -> None:
        # A claim matching several rules selects the union.
        claim = _claim(
            "persistent homology of a point cloud; ordinary differential equation; "
            "causal time series; optimization"
        )
        profiles, _ = classify(claim, {}, {})
        assert {
            "geometry_tda",
            "executable_ode_dae_sde_model",
            "dynamics",
            "causal_time_series",
            "optimization",
        } <= set(profiles)


class TestClassifierValidation:
    """The classifier rejects malformed inputs."""

    def test_non_object_claim_rejected(self) -> None:
        with pytest.raises(ContractError):
            classify("not a dict", {}, {})

    def test_non_object_symbol_table_rejected(self) -> None:
        with pytest.raises(ContractError):
            classify(_claim(), "not a dict", {})

    def test_non_object_condition_set_rejected(self) -> None:
        with pytest.raises(ContractError):
            classify(_claim(), {}, "not a dict")


class TestClassifierHypothesis:
    """Hypothesis: random statements never select an unknown profile."""

    @given(statement=st.text(min_size=0, max_size=200))
    def test_random_statement_never_selects_unknown_profile(self, statement: str) -> None:
        profiles, _ = classify(_claim(statement), {}, {})
        assert profiles <= frozenset(PROFILE_NAMES)
