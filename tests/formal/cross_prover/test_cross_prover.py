from __future__ import annotations

import pytest

from srl.packs.formal import (
    CrossProverError,
    FormalContourStatus,
    build_cross_prover_admission_bundle,
    build_translation_manifest,
    discover_cross_prover_contours,
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
