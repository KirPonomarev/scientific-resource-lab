from __future__ import annotations

from typing import Any, cast

from srl.packs.p0 import P0Component, P0ComponentStatus, build_p0_admission_bundle
from srl.packs.p0.core import default_p0_components


def _components(bundle: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], bundle["components"])


def _component_ids(bundle: dict[str, object], key: str) -> set[str]:
    return set(cast(list[str], bundle[key]))


def test_p0_bundle_records_all_master_plan_components() -> None:
    bundle = build_p0_admission_bundle()
    ids = {component["component_id"] for component in _components(bundle)}

    assert {
        "numeric.numpy",
        "numeric.scipy",
        "units.pint",
        "smt.z3",
        "smt.cvc5",
        "symbolic.sympy",
        "numeric.mpmath",
        "exact.flint",
        "exact.pari",
        "cas.maxima",
        "cas.gap",
        "cas.singular",
    } <= ids


def test_current_importable_core_is_active_and_missing_engines_wait() -> None:
    bundle = build_p0_admission_bundle()

    assert {"numeric.numpy", "numeric.scipy", "units.pint", "smt.z3"} <= _component_ids(
        bundle, "active_component_ids"
    )
    assert "smt.cvc5" in _component_ids(bundle, "degraded_component_ids")
    assert {"symbolic.sympy", "numeric.mpmath"} <= _component_ids(bundle, "active_component_ids")
    assert "exact.flint" in _component_ids(bundle, "active_component_ids")
    assert {"exact.pari", "cas.maxima"} <= _component_ids(bundle, "wait_component_ids")


def test_cvc5_is_not_silently_replaced_by_z3() -> None:
    bundle = build_p0_admission_bundle()
    components = {component["component_id"]: component for component in _components(bundle)}

    assert components["smt.z3"]["status"] == "ACTIVE"
    assert components["smt.cvc5"]["status"] == "DEGRADED"
    assert "no_z3_substitution" in components["smt.cvc5"]["cross_checks"]
    assert bundle["solver_disagreement_policy"] == (
        "preserve_disagreement_never_substitute_z3_for_cvc5"
    )


def test_missing_required_import_downgrades_active_component() -> None:
    component = P0Component(
        "numeric.fake",
        "numeric",
        P0ComponentStatus.ACTIVE,
        ("definitely_missing_srl_p0_component",),
        ("fake",),
        ("MIT",),
        ("numeric_array",),
        "fake",
        ("import_probe",),
        "importable_and_license_allowed",
    )

    bundle = build_p0_admission_bundle(components=(component,))

    assert bundle["active_component_ids"] == []
    assert bundle["wait_component_ids"] == ["numeric.fake"]


def test_p0_bundle_digest_is_deterministic() -> None:
    assert build_p0_admission_bundle()["bundle_id"] == build_p0_admission_bundle()["bundle_id"]


def test_default_components_are_authority_negative() -> None:
    for component in default_p0_components():
        data = component.to_dict()
        assert data["canonical_writes"] == 0
        assert data["grants_authority"] is False
