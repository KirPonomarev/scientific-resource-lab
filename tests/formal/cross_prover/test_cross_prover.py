from __future__ import annotations

import pytest

from srl.packs.formal import (
    CrossProverError,
    FormalContour,
    FormalContourStatus,
    build_a10_translation_manifests,
    build_cross_prover_admission_bundle,
    build_translation_manifest,
    discover_cross_prover_contours,
    independent_prover_pin_manifest_hash,
    load_independent_prover_pins,
)


def test_default_contours_preserve_waits_without_external_tools() -> None:
    contours = discover_cross_prover_contours(executable_resolver=lambda _name: None)
    by_id = {contour.contour_id: contour for contour in contours}

    assert by_id["lean.primary"].status is FormalContourStatus.ACTIVE
    assert by_id["rocq.primary"].status is FormalContourStatus.WAIT_TOOLCHAIN
    assert by_id["isabelle.hol"].status is FormalContourStatus.WAIT_TOOLCHAIN
    assert by_id["hol4.primary"].status is FormalContourStatus.WAIT_TOOLCHAIN


def test_external_contour_can_become_active_with_resolved_executable() -> None:
    contours = discover_cross_prover_contours(
        executable_resolver=lambda name: "/bin/echo" if name == "coqc" else None
    )
    by_id = {contour.contour_id: contour for contour in contours}

    assert by_id["rocq.primary"].status is FormalContourStatus.ACTIVE
    assert by_id["rocq.primary"].reason == "coqc_available"


def test_translation_manifest_records_semantic_gap_without_equivalence() -> None:
    manifest = build_translation_manifest(
        theorem_label="zero_add",
        source_contour_id="lean.primary",
        target_contour_id="isabelle.hol",
        source_logic="dependent_type_theory",
        target_logic="classical_higher_order_logic",
        source_assumptions=("nat",),
        target_assumptions=("nat", "classical_choice"),
        translation_notes=("operator manually translated statement shape",),
    )

    assert manifest["equivalence_claimed"] is False
    assert manifest["requires_independent_review"] is True
    assert manifest["canonical_writes"] == 0
    assert manifest["grants_authority"] is False
    assert manifest["semantic_gap"] == {
        "logic_delta": True,
        "assumption_delta": ["classical_choice"],
    }


def test_translation_manifest_refuses_automatic_equivalence_claim() -> None:
    with pytest.raises(CrossProverError, match="equivalence"):
        build_translation_manifest(
            theorem_label="bad",
            source_contour_id="lean.primary",
            target_contour_id="hol4.primary",
            source_logic="dependent_type_theory",
            target_logic="classical_higher_order_logic",
            source_assumptions=(),
            target_assumptions=(),
            translation_notes=("bad equivalence claim",),
            equivalence_claimed=True,
        )


def test_admission_bundle_is_authority_negative_and_counts_waits() -> None:
    contours = discover_cross_prover_contours(executable_resolver=lambda _name: None)
    manifest = build_translation_manifest(
        theorem_label="zero_add",
        source_contour_id="lean.primary",
        target_contour_id="rocq.primary",
        source_logic="dependent_type_theory",
        target_logic="calculus_of_inductive_constructions",
        source_assumptions=("formalization_correctness_not_implied",),
        target_assumptions=("kernel_acceptance_is_per_statement",),
        translation_notes=("test-only shape comparison",),
    )

    bundle = build_cross_prover_admission_bundle(
        contours=contours,
        translation_manifests=(manifest,),
    )

    assert bundle["active_contour_ids"] == ["lean.primary"]
    assert bundle["wait_contour_ids"] == [
        "rocq.primary",
        "isabelle.hol",
        "hol4.primary",
    ]
    assert bundle["automatic_equivalence_claims"] == 0
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


def test_admission_bundle_refuses_manifest_equivalence_claim() -> None:
    manifest = build_translation_manifest(
        theorem_label="zero_add",
        source_contour_id="lean.primary",
        target_contour_id="rocq.primary",
        source_logic="dependent_type_theory",
        target_logic="calculus_of_inductive_constructions",
        source_assumptions=(),
        target_assumptions=(),
        translation_notes=("shape only",),
    )
    bad_manifest = {**manifest, "equivalence_claimed": True}

    with pytest.raises(CrossProverError, match="equivalence"):
        build_cross_prover_admission_bundle(translation_manifests=(bad_manifest,))


def test_independent_prover_pin_manifest_is_authority_negative() -> None:
    pins = load_independent_prover_pins()

    assert pins["schema_version"] == "IndependentProverPins/v1"
    assert pins["automatic_equivalence_claims"] == 0
    assert pins["canonical_writes"] == 0
    assert pins["grants_authority"] is False
    assert len(independent_prover_pin_manifest_hash()) == 64


def test_a10_translation_manifests_cover_all_independent_contours() -> None:
    contours = (*discover_cross_prover_contours(executable_resolver=lambda _name: None),)
    manifests = build_a10_translation_manifests(contours=contours)

    assert [manifest["target_contour_id"] for manifest in manifests] == [
        "rocq.primary",
        "isabelle.hol",
        "hol4.primary",
    ]
    assert {manifest["theorem_label"] for manifest in manifests} == {"srl_a10_zero_add"}
    assert all(manifest["equivalence_claimed"] is False for manifest in manifests)
    assert all(manifest["requires_independent_review"] is True for manifest in manifests)


def test_a10_translation_manifests_require_all_contours() -> None:
    contours = tuple(
        contour
        for contour in discover_cross_prover_contours(executable_resolver=lambda _name: None)
        if contour.contour_id != "hol4.primary"
    )

    with pytest.raises(CrossProverError, match=r"hol4\.primary"):
        build_a10_translation_manifests(contours=contours)


def test_a10_admission_bundle_can_count_all_active_contours() -> None:
    contours = (
        FormalContour(
            contour_id="lean.primary",
            prover_name="Lean/mathlib",
            logic="dependent_type_theory_calculus_of_inductive_constructions_family",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("lean", "lake"),
            version_output="A09 receipt",
            semantic_scope="declared_statement_only",
            assumptions=("formalization_correctness_not_implied",),
            reason="A09_lean_primary_proven",
        ),
        FormalContour(
            contour_id="rocq.primary",
            prover_name="Rocq/Coq",
            logic="calculus_of_inductive_constructions",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("rocq", "coqc"),
            version_output="Rocq Prover 9.2.0",
            semantic_scope="constructive_type_theory_with_universe_constraints",
            assumptions=("kernel_acceptance_is_per_statement",),
            reason="a10_stage_receipt",
        ),
        FormalContour(
            contour_id="isabelle.hol",
            prover_name="Isabelle/HOL",
            logic="classical_higher_order_logic",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("isabelle",),
            version_output="Isabelle2025-2",
            semantic_scope="object_logic_hol_inside_isabelle_framework",
            assumptions=("session_image_and_theory_imports_are_part_of_the_statement",),
            reason="a10_stage_receipt",
        ),
        FormalContour(
            contour_id="hol4.primary",
            prover_name="HOL4",
            logic="classical_higher_order_logic",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("hol", "Holmake"),
            version_output="HOL4 trindemossen-2",
            semantic_scope="hol4_kernel_theory_graph",
            assumptions=("theory_load_order_is_part_of_the_statement",),
            reason="a10_stage_receipt",
        ),
    )

    bundle = build_cross_prover_admission_bundle(
        contours=contours,
        translation_manifests=build_a10_translation_manifests(contours=contours),
    )

    assert bundle["active_contour_ids"] == [
        "lean.primary",
        "rocq.primary",
        "isabelle.hol",
        "hol4.primary",
    ]
    assert bundle["wait_contour_ids"] == []
