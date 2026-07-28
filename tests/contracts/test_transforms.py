"""Unit tests for the TransformationReceipt/v1 lineage machinery (srl.semantic.transforms).

Pins:

1. **LOSSLESS invariant**: a LOSSLESS receipt with a non-empty
   ``introduced_assumptions`` or ``dropped_features`` is rejected at the schema
   layer (``allOf``/``if-then``) and the Python layer
   (:func:`record_transformation` / :func:`validate`) with fail reason
   ``CONTRACT_INVALID`` and invariant ``lossless_requires_no_loss``.
2. **Conversion classes**: a producer may set ``LOSSLESS`` or ``LOSSY_EXPLICIT``;
   ``LOSSY_IMPLICIT_DETECTED`` is detector-only (:func:`record_detected_loss`),
   and the producer API rejects it.
3. **Schema round-trips**: the positive fixtures validate against the
   ``TransformationReceipt`` schema and round-trip through the Python validator;
   ``receipt_id`` is idempotent (computed without the id field).
4. **Projection lineage**: :func:`project_to_backend` binds the adapter/pack
   hash; a lossless projection yields ``source == target``; two sequential
   projections produce receipts where the second's ``source_object_id`` equals
   the first's ``target_object_id``.
5. **Reject behavior**: an unsupported op with ``behavior=reject`` halts the
   projection with :class:`UnsupportedFeatureError` (``IR_UNSUPPORTED``).
6. **Raw-eval prohibition**: :func:`assert_no_raw_eval_route` verifies the
   ``srl.semantic`` package exposes no ``sympify``/``sage_eval``/``eval`` route.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.contracts.schema import ContractValidationError
from srl.contracts.schema import validate as schema_validate
from srl.semantic.adapter_profiles import build_profile
from srl.semantic.ir import Application, Var, build, ir_id
from srl.semantic.transforms import (
    LOSSLESS,
    LOSSY_EXPLICIT,
    LOSSY_IMPLICIT_DETECTED,
    TRANSFORMATION_INVARIANT_FAIL_REASON,
    TransformationInvariantError,
    UnsupportedFeatureError,
    assert_no_raw_eval_route,
    project_to_backend,
    receipt_id,
    record_detected_loss,
    record_transformation,
    validate,
)

# Fixtures directory (repo-relative for the round-trip tests).
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "conformance" / "transformations"

# A canonical sha256 digest used across fixture receipts / object ids.
_DIGEST = "sha256:" + "a" * 64


# ---------------------------------------------------------------------------
# Pins: LOSSLESS invariant.
# ---------------------------------------------------------------------------


def test_lossless_with_dropped_feature_rejected_python() -> None:
    """A LOSSLESS receipt with a dropped feature is rejected (python layer)."""
    with pytest.raises(TransformationInvariantError) as exc_info:
        record_transformation(
            source_object_id=_DIGEST,
            target_object_id=_DIGEST,
            transform_kind="project",
            conversion_class=LOSSLESS,
            dropped_features=["calculus1.diff"],
        )
    assert exc_info.value.fail_reason == TRANSFORMATION_INVARIANT_FAIL_REASON
    assert exc_info.value.invariant == "lossless_requires_no_loss"


def test_lossless_with_assumption_rejected_python() -> None:
    """A LOSSLESS receipt with an introduced assumption is rejected (python layer)."""
    with pytest.raises(TransformationInvariantError) as exc_info:
        record_transformation(
            source_object_id=_DIGEST,
            target_object_id=_DIGEST,
            transform_kind="normalize",
            conversion_class=LOSSLESS,
            introduced_assumptions=[{"assumption": "x >= 0", "justification": "convenience"}],
        )
    assert exc_info.value.invariant == "lossless_requires_no_loss"


def test_lossless_with_dropped_feature_rejected_schema() -> None:
    """A LOSSLESS receipt with a dropped feature is rejected (schema layer)."""
    bad = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="project",
        conversion_class=LOSSY_EXPLICIT,
        dropped_features=["calculus1.diff"],
    )
    # Tamper to claim LOSSLESS while keeping the dropped feature; the id is now
    # stale but the schema check fires on conversion_class + dropped_features.
    tampered = dict(bad)
    tampered["conversion_class"] = LOSSLESS
    with pytest.raises(ContractValidationError) as exc_info:
        schema_validate(tampered, "TransformationReceipt")
    assert exc_info.value.validator == "maxItems"


def test_lossless_zero_loss_validates() -> None:
    """A LOSSLESS receipt with no assumptions and no dropped features validates."""
    receipt = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="normalize",
        conversion_class=LOSSLESS,
    )
    validate(receipt)
    schema_validate(receipt, "TransformationReceipt")
    assert receipt["conversion_class"] == LOSSLESS
    assert receipt["introduced_assumptions"] == []
    assert receipt["dropped_features"] == []


# ---------------------------------------------------------------------------
# Pins: conversion classes + detector separation.
# ---------------------------------------------------------------------------


def test_producer_cannot_claim_implicit_loss() -> None:
    """record_transformation rejects LOSSY_IMPLICIT_DETECTED (detector-only)."""
    with pytest.raises(ContractError):
        record_transformation(
            source_object_id=_DIGEST,
            target_object_id=_DIGEST,
            transform_kind="normalize",
            conversion_class=LOSSY_IMPLICIT_DETECTED,
            dropped_features=["calculus1.diff"],
        )


def test_detector_can_produce_implicit_loss() -> None:
    """record_detected_loss produces a LOSSY_IMPLICIT_DETECTED receipt."""
    receipt = record_detected_loss(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="normalize",
        dropped_features=["calculus1.diff"],
    )
    assert receipt["conversion_class"] == LOSSY_IMPLICIT_DETECTED
    assert receipt["dropped_features"] == ["calculus1.diff"]
    schema_validate(receipt, "TransformationReceipt")


def test_detector_requires_a_loss() -> None:
    """A detector-only receipt with no detected loss is vacuous and rejected."""
    with pytest.raises(ContractError):
        record_detected_loss(
            source_object_id=_DIGEST,
            target_object_id=_DIGEST,
            transform_kind="normalize",
        )


def test_lossy_explicit_carries_assumption() -> None:
    """A LOSSY_EXPLICIT receipt carries its introduced assumption."""
    receipt = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="approximate",
        conversion_class=LOSSY_EXPLICIT,
        introduced_assumptions=[
            {
                "assumption": "calculus1.diff approximated by finite differences",
                "justification": "the solver backend lacks symbolic differentiation",
            }
        ],
        dropped_features=["calculus1.diff"],
    )
    assert len(receipt["introduced_assumptions"]) == 1
    assert receipt["introduced_assumptions"][0]["assumption"].startswith("calculus1.diff")


# ---------------------------------------------------------------------------
# Pins: identity + schema round-trips.
# ---------------------------------------------------------------------------


def test_receipt_id_is_sha256_without_id_field() -> None:
    """receipt_id is sha256 over the canonical bytes of the receipt without receipt_id."""
    receipt = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="normalize",
        conversion_class=LOSSLESS,
    )
    without_id = {k: v for k, v in receipt.items() if k != "receipt_id"}
    expected = "sha256:" + hashlib.sha256(dumps(without_id)).hexdigest()
    assert receipt["receipt_id"] == expected


def test_receipt_id_is_idempotent() -> None:
    """receipt_id computed on a receipt with or without its id field is equal."""
    receipt = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="normalize",
        conversion_class=LOSSLESS,
    )
    assert receipt_id(receipt) == receipt["receipt_id"]
    without_id = {k: v for k, v in receipt.items() if k != "receipt_id"}
    assert receipt_id(without_id) == receipt["receipt_id"]


def test_receipt_is_deterministic() -> None:
    """The same inputs yield the same receipt on every build."""
    a = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="normalize",
        conversion_class=LOSSLESS,
    )
    b = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="normalize",
        conversion_class=LOSSLESS,
    )
    assert a == b


@pytest.mark.parametrize("name", ["p01-receipt-lossless", "p03-receipt-lossy-projection"])
def test_positive_fixture_validates_and_round_trips(name: str) -> None:
    """Every positive TransformationReceipt fixture validates + round-trips."""
    path = _FIXTURES / f"{name}.input.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    schema_validate(doc, "TransformationReceipt")
    validate(doc)
    assert receipt_id(doc) == doc["receipt_id"]


# ---------------------------------------------------------------------------
# Pins: projection lineage.
# ---------------------------------------------------------------------------


def _solver_profile() -> dict[str, object]:
    """A solver profile supporting plus/eq and dropping calculus1.diff."""
    return build_profile(
        {
            "schema_version": "AdapterSemanticProfile/v1",
            "adapter_id": "solver-no-calculus",
            "pack_ref": {
                "schema_version": "ArtifactRef/v1",
                "media_type": "application/vnd.srlab.adapter-pack+json",
                "digest": _DIGEST,
                "size_bytes": 4096,
            },
            "supported_cds": ["arith1.plus", "arith1.minus", "relation1.eq"],
            "unsupported_features": [
                {"feature": "calculus1.diff", "behavior": "drop", "note": "no diff"}
            ],
            "input_contract": "MathIR",
            "output_contract": "MathIR",
            "deterministic": True,
            "network_access": "none",
            "license_spdx": "Apache-2.0",
            "canonical_writes": 0,
            "grants_authority": False,
        }
    )


def test_lossless_projection_source_equals_target() -> None:
    """A lossless projection binds adapter/pack hash and yields source==target."""
    profile = _solver_profile()
    tree = build(Application("arith1.plus", [Var("a"), Var("b")]))
    restricted, receipt = project_to_backend(tree, profile)
    assert receipt["conversion_class"] == LOSSLESS
    assert receipt["source_object_id"] == receipt["target_object_id"]
    assert receipt["adapter_profile_ref"] == profile["profile_id"]
    assert receipt["pack_hash"] == profile["pack_ref"]["digest"]
    # The restricted tree is the same content-addressed object (lossless).
    assert restricted["ir_id"] == receipt["target_object_id"]


def test_lineage_chain_links_source_to_prior_target() -> None:
    """Two sequential projections: the second's source equals the first's target."""
    profile = _solver_profile()
    tree = build(Application("arith1.plus", [Var("a"), Var("b")]))
    restricted1, receipt1 = project_to_backend(tree, profile)
    _restricted2, receipt2 = project_to_backend(restricted1, profile, parents=[receipt1])
    assert receipt2["source_object_id"] == receipt1["target_object_id"]


def test_lossy_projection_drops_unsupported_op() -> None:
    """A projection dropping calculus1.diff is LOSSY_EXPLICIT and binds the adapter."""
    profile = _solver_profile()
    diff_tree = build(Application("calculus1.diff", [Var("x")]))
    _restricted, receipt = project_to_backend(diff_tree, profile)
    assert receipt["conversion_class"] == LOSSY_EXPLICIT
    assert receipt["dropped_features"] == ["calculus1.diff"]
    assert receipt["adapter_profile_ref"] == profile["profile_id"]
    assert len(receipt["introduced_assumptions"]) == 1


def test_reject_behavior_halts_projection() -> None:
    """behavior=reject for an unsupported op halts the projection (IR_UNSUPPORTED)."""
    profile = _solver_profile()
    reject_profile = build_profile(
        {
            **{k: v for k, v in profile.items() if k not in ("profile_id", "unsupported_features")},
            "unsupported_features": [{"feature": "calculus1.diff", "behavior": "reject"}],
        }
    )
    diff_tree = build(Application("calculus1.diff", [Var("x")]))
    with pytest.raises(UnsupportedFeatureError) as exc_info:
        project_to_backend(diff_tree, reject_profile)
    assert exc_info.value.fail_reason == "IR_UNSUPPORTED"
    assert exc_info.value.op == "calculus1.diff"
    assert exc_info.value.cd == "calculus1"


def test_projection_target_is_input_ir_id() -> None:
    """The projection source_object_id is the input tree's ir_id."""
    profile = _solver_profile()
    tree = build(Application("arith1.plus", [Var("a"), Var("b")]))
    expected_source = ir_id(tree.expression)
    _restricted, receipt = project_to_backend(tree, profile)
    assert receipt["source_object_id"] == expected_source


# ---------------------------------------------------------------------------
# Pins: raw-eval prohibition.
# ---------------------------------------------------------------------------


def test_assert_no_raw_eval_route_passes() -> None:
    """The srl.semantic package exposes no raw-eval input route."""
    names = assert_no_raw_eval_route()
    assert isinstance(names, list)
    assert len(names) > 0
    # The forbidden names are absent from the introspected surface.
    forbidden = {"sympify", "sage_eval", "eval", "lambdify", "sympy", "sage"}
    assert not (forbidden & set(names))


def test_validate_rejects_wrong_schema_version() -> None:
    """A wrong schema_version is rejected."""
    with pytest.raises(ContractError):
        validate({"schema_version": "TransformationReceipt/v2"})
