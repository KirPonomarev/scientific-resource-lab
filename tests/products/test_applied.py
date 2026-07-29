from __future__ import annotations

from typing import cast

import pytest

from srl.products import (
    AppliedScienceError,
    build_applied_result_receipt,
    build_applied_science_admission_bundle,
)


def test_applied_bundle_activates_existing_bounded_adapters() -> None:
    bundle = build_applied_science_admission_bundle()

    active = cast(list[str], bundle["active_pack_ids"])
    waits = cast(list[str], bundle["wait_pack_ids"])
    assert {"ripser", "pyriemann", "cvxpy"} <= set(active)
    assert {"gudhi", "pymc", "dowhy", "botorch"} <= set(waits)
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


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
