from __future__ import annotations

from typing import Any, cast

import pytest

from srl.packs import (
    SciMLDomainError,
    SciMLDomainResultSpec,
    build_cross_language_fixture_receipt,
    build_sciml_domain_admission_bundle,
    build_sciml_domain_result_receipt,
)


def _profiles(bundle: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], bundle["profiles"])


def _fixture_spec(  # noqa: PLR0913
    *,
    result_id: str = "r1",
    profile_id: str = "python.diffrax",
    language: str = "python",
    solver_name: str = "tsit5",
    solver_family: str = "ode",
    trace_sha256: str = "0" * 64,
) -> SciMLDomainResultSpec:
    return SciMLDomainResultSpec(
        result_id=result_id,
        profile_id=profile_id,
        language=language,
        solver_name=solver_name,
        solver_family=solver_family,
        unit_bindings=("time:s", "position:m"),
        tolerance_abs=1e-9,
        tolerance_rel=1e-8,
        trace_sha256=trace_sha256,
        assumptions=("bounded fixture trace",),
    )


def test_sciml_domain_bundle_records_master_plan_profiles() -> None:
    bundle = build_sciml_domain_admission_bundle()
    ids = {profile["profile_id"] for profile in _profiles(bundle)}

    assert {
        "julia.sciml",
        "julia.modelingtoolkit",
        "julia.datadrivendiffeq",
        "python.diffrax",
        "python.qutip",
        "python.cadabra",
        "python.astropy",
        "python.cantera",
        "python.pybamm",
        "python.quimb",
        "python.cotengra",
    } <= ids


def test_absent_sciml_domain_runtimes_are_wait_capability() -> None:
    bundle = build_sciml_domain_admission_bundle()
    waits = set(cast(list[str], bundle["wait_profile_ids"]))

    assert {
        "julia.sciml",
        "python.diffrax",
        "python.qutip",
        "python.astropy",
        "python.cotengra",
    } <= waits
    assert bundle["shared_mutable_global_depots"] == 0
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


def test_result_receipt_carries_units_solver_and_tolerances() -> None:
    receipt = build_sciml_domain_result_receipt(_fixture_spec())

    assert receipt["unit_bindings"] == ["time:s", "position:m"]
    assert receipt["solver_name"] == "tsit5"
    assert receipt["tolerance_abs"] == 1e-9
    assert receipt["comparison_scope"] == "tolerance_provenance_only"
    assert receipt["bitwise_identity_claimed"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_result_receipt_rejects_unit_loss() -> None:
    with pytest.raises(SciMLDomainError, match="unit_bindings"):
        SciMLDomainResultSpec(
            result_id="r1",
            profile_id="python.diffrax",
            language="python",
            solver_name="tsit5",
            solver_family="ode",
            unit_bindings=(),
            tolerance_abs=1e-9,
            tolerance_rel=1e-8,
            trace_sha256="0" * 64,
            assumptions=("bounded fixture trace",),
        )


def test_result_receipt_requires_positive_tolerance() -> None:
    with pytest.raises(SciMLDomainError, match="tolerance"):
        SciMLDomainResultSpec(
            result_id="r1",
            profile_id="python.diffrax",
            language="python",
            solver_name="tsit5",
            solver_family="ode",
            unit_bindings=("time:s",),
            tolerance_abs=0.0,
            tolerance_rel=0.0,
            trace_sha256="0" * 64,
            assumptions=("bounded fixture trace",),
        )


def test_cross_language_fixture_rejects_bitwise_identity_claim() -> None:
    python_receipt = build_sciml_domain_result_receipt(_fixture_spec())
    julia_receipt = build_sciml_domain_result_receipt(
        _fixture_spec(
            result_id="r2",
            profile_id="julia.sciml",
            language="julia",
            trace_sha256="1" * 64,
        )
    )

    with pytest.raises(SciMLDomainError, match="bitwise identity"):
        build_cross_language_fixture_receipt(
            receipts=(python_receipt, julia_receipt),
            comparison_label="ode fixture",
            tolerance_abs=1e-8,
            tolerance_rel=1e-7,
            bitwise_identity_claimed=True,
        )


def test_cross_language_fixture_allows_tolerance_comparison() -> None:
    python_receipt = build_sciml_domain_result_receipt(_fixture_spec())
    julia_receipt = build_sciml_domain_result_receipt(
        _fixture_spec(
            result_id="r2",
            profile_id="julia.sciml",
            language="julia",
            trace_sha256="1" * 64,
        )
    )

    receipt = build_cross_language_fixture_receipt(
        receipts=(python_receipt, julia_receipt),
        comparison_label="ode fixture",
        tolerance_abs=1e-8,
        tolerance_rel=1e-7,
    )

    assert receipt["comparison_scope"] == "bounded_fixture_tolerance_only"
    assert receipt["bitwise_identity_claimed"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
