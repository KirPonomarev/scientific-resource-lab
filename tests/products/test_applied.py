from __future__ import annotations

from typing import cast

import pytest

from srl.products import (
    A13_APPLIED_RECEIPT_SCHEMA_VERSION,
    AppliedScienceError,
    build_applied_result_receipt,
    build_applied_science_admission_bundle,
    run_a13_applied_science_smoke,
)


def test_applied_bundle_activates_existing_bounded_adapters() -> None:
    bundle = build_applied_science_admission_bundle()

    active = cast(list[str], bundle["active_pack_ids"])
    waits = cast(list[str], bundle["wait_pack_ids"])
    replaced = cast(list[str], bundle["formally_replaced_pack_ids"])
    assert active == [
        "ripser",
        "pyriemann",
        "cvxpy",
        "native_bayesian_conjugate",
        "native_causal_backdoor",
    ]
    assert waits == []
    assert {"gudhi", "pymc", "dowhy", "botorch"} <= set(replaced)
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


def test_a13_smoke_runs_real_workloads_and_remains_authority_negative() -> None:
    receipt = run_a13_applied_science_smoke()

    assert receipt["schema_version"] == A13_APPLIED_RECEIPT_SCHEMA_VERSION
    assert receipt["active_pack_ids"] == [
        "ripser",
        "pyriemann",
        "cvxpy",
        "native_bayesian_conjugate",
        "native_causal_backdoor",
    ]
    assert receipt["promotion_allowed"] is False
    assert receipt["automatic_scientific_promotion"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
    workloads = cast(list[dict[str, object]], receipt["workload_receipts"])
    assert [item["pack_id"] for item in workloads] == receipt["active_pack_ids"]
    by_id = {str(item["pack_id"]): item for item in workloads}
    topology = cast(dict[str, object], by_id["ripser"]["diagnostics"])
    assert topology["circle_long_lived_h1"] == 1
    assert topology["control_long_lived_h1"] == 0
    bayesian = cast(dict[str, object], by_id["native_bayesian_conjugate"]["diagnostics"])
    assert bayesian["convergence_claim"] is False
    assert bayesian["rhat"] is None
    assert bayesian["ess"] is None
    causal = cast(dict[str, object], by_id["native_causal_backdoor"]["diagnostics"])
    assert by_id["native_causal_backdoor"]["causal_identification"] == "identified"
    assert abs(cast(float, causal["adjusted_treatment_effect"]) - 2.0) <= 0.08
    optimization = cast(dict[str, object], by_id["cvxpy"]["diagnostics"])
    assert optimization["license_verified"] is True
    assert optimization["denied_solvers"] == ["cbc", "glpk"]


def test_applied_result_requires_diagnostics_and_is_authority_negative() -> None:
    receipt = build_applied_result_receipt(
        product="cvxpy_fixture",
        assumptions=("convex objective",),
        diagnostics=("solver_status_checked",),
        solver_status="optimal",
    )

    assert receipt["status"] == "checked"
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_unidentified_causal_effect_cannot_carry_estimate() -> None:
    with pytest.raises(AppliedScienceError, match="unidentified"):
        build_applied_result_receipt(
            product="causal_fixture",
            assumptions=("backdoor not established",),
            diagnostics=("falsification_missing",),
            solver_status="inconclusive",
            causal_identification="assumed",
            effect_estimate=1.0,
        )


def test_inconclusive_solver_status_does_not_become_checked() -> None:
    receipt = build_applied_result_receipt(
        product="topology_fixture",
        assumptions=("synthetic null control",),
        diagnostics=("null_distribution_overlap",),
        solver_status="inconclusive",
    )

    assert receipt["status"] == "inconclusive"
