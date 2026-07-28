"""P0 integration end-to-end test (WP-E45).

This is the **synthetic end-to-end integration test** for the P0 release. It
exercises the full vertical slice the WP-E45 plan gate must prove works:

    synthetic claim
      -> classify + route + plan  (the planning stack, against a catalog)
      -> real bounded actual-compute run  (the units adapter: a coherent
         conversion ``1 kg*m/s^2 -> 1 N`` rendered as the exact decimal
         identity)
      -> engine receipt + validation receipt  (built against the typed evidence
         model, ``exercise_level=actual_compute``, ``engine_execution=
         completed``, ``integration_authority=none``)
      -> a demo-mode evidence-portal page rendered from the synthetic objects

The test is deliberately bounded: it runs ONE real compute (a units
conversion) so it is fast (<1s) and deterministic, while still threading the
output through the typed evidence and portal layers. The heavier
``>=5 distinct measured runs per pack`` requirement is the gate's job
(``scripts/checks/wp45-gate.py``); this test proves the *wiring* is correct.

Honesty (load-bearing)
----------------------
Nothing in this test claims a scientific result. The engine receipt records
``exercise_level=actual_compute`` (a real conversion ran) but the validation
receipt records ``formal_check=unchecked`` and the assessment pins
``integration_authority=none`` — the compute happened, the wiring is sound,
and the authority is honestly none. The claim is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.catalog.registry import build_default_registry
from srl.catalog.snapshot import build_snapshot
from srl.contracts.schema import validate as schema_validate
from srl.packs.adapters.units import convert, pint_version
from srl.planning.catalog import load_catalog, load_default_catalog
from srl.planning.planner import (
    build_plan,
    default_policy,
)
from srl.planning.profiles import SCIENCE_LAB_PROFILES
from srl.planning.request import build_request
from srl.planning.router import (
    SELECTION_SELECTED,
    route,
)
from srl.portal.build import PortalBuildReport, PortalMode, build_portal
from srl.semantic.evidence import (
    DEFAULT_AXES,
    build_assessment,
    build_engine_receipt,
    build_validation_receipt,
)
from srl.semantic.evidence import (
    validate as validate_assessment,
)

# A fixed UTC timestamp so the engine/validation receipts are deterministic.
_FIXTURE_UTC = "2026-07-28T00:00:00Z"

# A synthetic sha256 object id reused for the claim/request ids (NOT a real
# content hash — a stable fixture digest, matching the corpus runner pattern).
_FIXTURE_DIGEST = "sha256:" + "a" * 64


def _pack_ref(hex_byte: str = "b") -> dict[str, Any]:
    """Return a valid synthetic ArtifactRef/v1 for the units pack.

    The engine receipt carries an inline pack ref; this helper keeps every
    receipt's ref structurally valid (schema_version + a sha256 digest over a
    repo-relative path) so the typed builder and the JSON Schema both accept it.
    """
    return {
        "schema_version": "ArtifactRef/v1",
        "media_type": "application/vnd.srl.adapter-pack+json",
        "digest": "sha256:" + hex_byte * 64,
        "size_bytes": 1024,
        "path": "units/pack.json",
    }


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _synthetic_claim() -> dict[str, Any]:
    """Return a bare synthetic ScientificClaim/v1-like dict.

    The claim is deliberately minimal: the planning stack treats it opaquely
    (the classifier keys off structural fields; the router consults the
    catalog). The statement names a units identity so the
    ``symbolic_law``/``algebra_exact`` profiles are plausible, but the test
    does NOT assert which profiles fire — it asserts the stack ran and the
    plan is well-formed.
    """
    return {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _FIXTURE_DIGEST,
        "statement": "1 N equals 1 kg*m/s^2 (a coherent SI identity)",
        "claim_class": "algebraic_identity",
        "epistemic_source": "synthetic",
    }


def _run_request() -> dict[str, Any]:
    """Build a ScienceLabRunRequest/v1 for the synthetic claim."""
    return build_request(
        claim_id=_FIXTURE_DIGEST,
        requested_profiles=[],  # auto-classify
        resource_class="default",
        seed=0,
        threads=1,
        output_schemas=[],
    )


# ---------------------------------------------------------------------------
# The end-to-end slice.
# ---------------------------------------------------------------------------


def test_synthetic_claim_routes_and_plans_against_default_catalog() -> None:
    """A synthetic claim routes + plans cleanly against the shipped catalog.

    The shipped catalog marks every adapter ``future``/``remote_required`` (no
    scientific backend ships in this codebase), so every *applicable* profile
    routes ``WAIT_CAPABILITY`` and none routes ``SELECTED``. This is the honest
    dominant outcome; the plan is still well-formed (a ScienceLabPlan/v1 with
    a content-addressed plan_id, policy_hash, and catalog_hash).
    """
    request = _run_request()
    claim = _synthetic_claim()
    catalog = load_default_catalog()
    policy = default_policy()

    decision = route(request, claim, catalog, policy)

    # The decision covers all 15 profiles (no silent drops).
    assert len(decision.profiles) == 15
    # With the shipped catalog, nothing is SELECTED (no adapter ships).
    assert decision.selected_profiles() == frozenset()

    plan = build_plan(request, decision, catalog, policy, created_utc=_FIXTURE_UTC)
    assert plan["schema_version"] == "ScienceLabPlan/v1"
    assert plan["grants_authority"] is False
    assert plan["canonical_writes"] == 0
    assert plan["catalog_hash"].startswith("sha256:")
    assert plan["policy_hash"].startswith("sha256:")
    assert plan["plan_id"].startswith("sha256:")
    # 15 steps (one per profile) — the plan emits full decision coverage.
    assert len(plan["steps"]) == 15
    # No step routed SELECTED (no adapter ships locally).
    selected = [s for s in plan["steps"] if s["selection"] == SELECTION_SELECTED]
    assert selected == []


def test_all_available_catalog_can_route_selected(tmp_path: Path) -> None:
    """A synthetic all-available catalog lets an applicable profile go SELECTED.

    This is the SELECTED branch of the stack: when a catalog marks a profile
    ``available`` and the request names it, the router routes SELECTED and the
    planner admits the single step under the default caps. It proves the
    positive path of the planning integration (the corpus runner exercises the
    WAIT_CAPABILITY path against the shipped catalog; this covers the other).
    """
    # A synthetic catalog with one profile available (units) and the rest
    # future. Built inline so the test is self-contained (no fixture file
    # dependency). All 15 profiles are listed so the router's full-coverage
    # path is exercised; the catalog_digest is recomputed by load_catalog.
    capabilities = []
    for profile in SCIENCE_LAB_PROFILES:
        if profile == "algebra_exact":
            availability = "available"
            adapter_id = "units"
        else:
            availability = "future"
            adapter_id = "none"
        capabilities.append(
            {
                "capability_id": f"cap.{profile}",
                "profile": profile,
                "adapter_id": adapter_id,
                "availability": availability,
            }
        )
    catalog_doc = {
        "schema_version": "CapabilityCatalog/v1",
        "catalog_digest": None,
        "capabilities": capabilities,
    }
    catalog = load_catalog(catalog_doc)
    request = build_request(
        claim_id=_FIXTURE_DIGEST,
        requested_profiles=["algebra_exact"],
        resource_class="default",
        seed=0,
        threads=1,
        output_schemas=[],
    )
    claim = _synthetic_claim()
    policy = default_policy()
    decision = route(request, claim, catalog, policy)
    assert "algebra_exact" in decision.selected_profiles()

    plan = build_plan(request, decision, catalog, policy, created_utc=_FIXTURE_UTC)
    selected = [s for s in plan["steps"] if s["selection"] == SELECTION_SELECTED]
    assert len(selected) == 1
    assert selected[0]["profile"] == "algebra_exact"
    assert selected[0]["adapter_id"] == "units"


def test_real_units_conversion_runs_actual_compute() -> None:
    """The units adapter performs a real coherent conversion (actual compute).

    ``1 kg*m/s^2 -> 1 N`` must yield the exact decimal identity ``"1"`` (no
    float artefact). This is the real bounded compute the engine receipt will
    honestly record as ``exercise_level=actual_compute``.
    """
    result = convert("1", "kg*m/s^2", "N")
    assert result == "1", f"expected exact decimal identity '1', got {result!r}"
    # The reverse identity also holds (round trip is exact).
    assert convert("1", "N", "kg*m/s^2") == "1"
    # The adapter is real (Pint version is non-empty).
    assert pint_version()


def test_engine_and_validation_receipts_record_actual_compute() -> None:
    """Engine + validation receipts honestly record the actual-compute run.

    The engine receipt records ``exercise_level=actual_compute`` and
    ``engine_execution=completed`` (a real conversion ran). The validation
    receipt records ``scientific_check=checked`` (the identity was verified)
    but ``formal_check=unchecked`` (no verified certificate backs it — a units
    conversion is not a formal proof). Both carry ``grants_authority=false``.
    """
    request = _run_request()
    # Run the real compute so the receipt is honest about what happened.
    converted = convert("1", "kg*m/s^2", "N")
    assert converted == "1"

    # A synthetic ArtifactRef/v1 for the units pack the engine "used".
    pack_ref = _pack_ref("b")
    engine_receipt = build_engine_receipt(
        run_request_id=request["request_id"],
        adapter_id="units",
        pack_ref=pack_ref,
        engine_execution="completed",
        exercise_level="actual_compute",
        wall_seconds=0,
        rss_bytes=0,
        output_object_ids=[],  # the conversion result is inline, not an object
        created_utc=_FIXTURE_UTC,
    )
    assert engine_receipt["schema_version"] == "ScienceLabEngineReceipt/v1"
    assert engine_receipt["exercise_level"] == "actual_compute"
    assert engine_receipt["engine_execution"] == "completed"
    assert engine_receipt["grants_authority"] is False

    validation = build_validation_receipt(
        engine_receipt_id=engine_receipt["receipt_id"],
        validator_id="units-identity-checker",
        scientific_check="checked",
        formal_check="unchecked",  # a conversion is not a formal proof
        formal_certificate_ref=None,
        statistical_support="not_applicable",
        causal_identification="not_applicable",
        created_utc=_FIXTURE_UTC,
    )
    assert validation["schema_version"] == "ScienceLabValidationReceipt/v1"
    assert validation["scientific_check"] == "checked"
    assert validation["formal_check"] == "unchecked"
    assert validation["formal_certificate_ref"] is None
    assert validation["grants_authority"] is False


def test_assessment_pins_integration_authority_none() -> None:
    """The evidence assessment honestly pins integration_authority=none.

    An actual-compute run does NOT grant integration authority. The assessment
    starts from the all-lowest DEFAULT_AXES and is raised only on the compute
    axes (exercise_level, engine_execution, scientific_check); the authority
    axis stays at its floor ``none``.
    """
    axes = dict(DEFAULT_AXES)
    axes["capability_state"] = "ready"
    axes["exercise_level"] = "actual_compute"
    axes["engine_execution"] = "completed"
    axes["scientific_check"] = "checked"
    assessment = build_assessment(
        subject_claim_id=_FIXTURE_DIGEST,
        axes=axes,
        evidence_refs=[],
        assessor="adapter",
        created_utc=_FIXTURE_UTC,
    )
    validate_assessment(assessment)
    assert assessment["axes"]["integration_authority"] == "none"
    assert assessment["axes"]["exercise_level"] == "actual_compute"
    assert assessment["grants_authority"] is False


def test_demo_portal_renders_from_synthetic_objects(tmp_path: Path) -> None:
    """A public-demo portal renders from synthetic objects, no leaks.

    The portal's public_demo mode drops any non-synthetic object and refuses
    any object carrying a local path or credential pattern. We feed it a
    single synthetic object (the units conversion result) and assert the build
    succeeds, accepts the object, and emits the expected pages — wiring the
    actual-compute output through the static portal layer.
    """
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    # A synthetic object the public_demo mode will accept (synthetic=true).
    obj = {
        "schema_version": "ScientificObjectEnvelope/v1",
        "object_id": "sha256:" + "c" * 64,
        "object_type": "transformation_receipt",
        "synthetic": True,
        "license": "CC0-1.0",
        "created_utc": _FIXTURE_UTC,
        "parents": [],
        "payload": {
            "adapter_id": "units",
            "operation": "convert",
            "value": "1",
            "from_unit": "kg*m/s^2",
            "to_unit": "N",
            "result": convert("1", "kg*m/s^2", "N"),
        },
    }
    (objects_dir / "obj.json").write_text(json.dumps(obj), encoding="utf-8")

    out_dir = tmp_path / "portal"
    report = build_portal(objects_dir, out_dir, PortalMode.public_demo)

    assert isinstance(report, PortalBuildReport)
    assert report.success is True
    assert report.leak_detected is False
    assert report.objects_accepted == 1
    assert report.objects_refused == 0
    assert report.mode is PortalMode.public_demo
    # The portal emits the canonical page set.
    assert "index.html" in report.pages
    assert "lineage.html" in report.pages
    assert "evidence.html" in report.pages
    # The index page actually rendered to disk.
    assert (out_dir / "index.html").is_file()


def test_catalog_snapshot_seal_is_deterministic() -> None:
    """Building the catalog snapshot twice yields identical identity bytes.

    The snapshot's ``snapshot_id`` and ``canonical_dumps()`` are a pure
    function of the registry entries (independent of build time and dynamic
    location state). Two builds of the same seed produce the same id and the
    same canonical bytes. This is the seal-determinism property E45-04 asserts
    at the gate level; this test pins it for the integration suite.
    """
    entries = build_default_registry()
    snap_a = build_snapshot(entries, created_utc=_FIXTURE_UTC)
    snap_b = build_snapshot(entries, created_utc=_FIXTURE_UTC)
    assert snap_a.snapshot_id == snap_b.snapshot_id
    assert snap_a.merkle_root == snap_b.merkle_root
    assert snap_a.canonical_dumps() == snap_b.canonical_dumps()
    # The snapshot never grants authority.
    assert snap_a.grants_authority is False
    assert snap_a.canonical_writes == 0


def test_receipts_validate_against_their_json_schemas() -> None:
    """The engine and validation receipts validate against their schemas.

    Defense in depth: the Python builders enforce the invariants, but the JSON
    Schema layer is the wire contract. This asserts both layers agree for the
    actual-compute receipts the integration mints.
    """
    pack_ref = _pack_ref("d")
    engine = build_engine_receipt(
        run_request_id=_FIXTURE_DIGEST,
        adapter_id="units",
        pack_ref=pack_ref,
        engine_execution="completed",
        exercise_level="actual_compute",
        wall_seconds=0,
        rss_bytes=0,
        created_utc=_FIXTURE_UTC,
    )
    validation = build_validation_receipt(
        engine_receipt_id=engine["receipt_id"],
        validator_id="units-identity-checker",
        scientific_check="checked",
        formal_check="unchecked",
        created_utc=_FIXTURE_UTC,
    )
    schema_validate(engine, "ScienceLabEngineReceipt")
    schema_validate(validation, "ScienceLabValidationReceipt")


def test_no_overclaim_in_integration_objects() -> None:
    """No integration object claims formal_check=proven with authority=none.

    The overclaim scan (E45-06) forbids a proven formal check paired with
    integration_authority=none anywhere in the integration evidence. Here we
    assert the engine/validation receipts we mint never carry proven (the
    units conversion is recorded as checked, not proven), which is the
    integration-suite instance of that rule.
    """
    pack_ref = _pack_ref("e")
    engine = build_engine_receipt(
        run_request_id=_FIXTURE_DIGEST,
        adapter_id="units",
        pack_ref=pack_ref,
        engine_execution="completed",
        exercise_level="actual_compute",
        wall_seconds=0,
        rss_bytes=0,
        created_utc=_FIXTURE_UTC,
    )
    validation = build_validation_receipt(
        engine_receipt_id=engine["receipt_id"],
        validator_id="units-identity-checker",
        scientific_check="checked",
        formal_check="unchecked",
        created_utc=_FIXTURE_UTC,
    )
    # No proven claim anywhere in the receipts.
    assert validation["formal_check"] != "proven"
    # And no object grants authority.
    assert engine["grants_authority"] is False
    assert validation["grants_authority"] is False


# ---------------------------------------------------------------------------
# The full slice, threaded end-to-end (one test that wires every stage).
# ---------------------------------------------------------------------------


def test_full_synthetic_slice_claim_plan_run_validate_portal(tmp_path: Path) -> None:
    """The full synthetic slice: claim -> plan -> run -> validate -> portal.

    One test that threads every stage together so a regression in any link
    breaks the integration story. It does NOT re-assert the per-stage
    invariants (the tests above do that); it asserts the stages compose.
    """
    # 1. Claim + request + plan (WAIT_CAPABILITY path, shipped catalog).
    request = _run_request()
    claim = _synthetic_claim()
    catalog = load_default_catalog()
    policy = default_policy()
    decision = route(request, claim, catalog, policy)
    plan = build_plan(request, decision, catalog, policy, created_utc=_FIXTURE_UTC)
    assert plan["schema_version"] == "ScienceLabPlan/v1"

    # 2. Real bounded compute (units coherent conversion).
    converted = convert("1", "kg*m/s^2", "N")
    assert converted == "1"

    # 3. Engine receipt (actual_compute) + validation receipt (checked).
    pack_ref = _pack_ref("f")
    engine = build_engine_receipt(
        run_request_id=request["request_id"],
        adapter_id="units",
        pack_ref=pack_ref,
        engine_execution="completed",
        exercise_level="actual_compute",
        wall_seconds=0,
        rss_bytes=0,
        created_utc=_FIXTURE_UTC,
    )
    validation = build_validation_receipt(
        engine_receipt_id=engine["receipt_id"],
        validator_id="units-identity-checker",
        scientific_check="checked",
        formal_check="unchecked",
        created_utc=_FIXTURE_UTC,
    )
    schema_validate(engine, "ScienceLabEngineReceipt")
    schema_validate(validation, "ScienceLabValidationReceipt")

    # 4. Evidence assessment pins integration_authority=none.
    axes = dict(DEFAULT_AXES)
    axes["capability_state"] = "ready"
    axes["exercise_level"] = "actual_compute"
    axes["engine_execution"] = "completed"
    axes["scientific_check"] = "checked"
    assessment = build_assessment(
        subject_claim_id=_FIXTURE_DIGEST,
        axes=axes,
        evidence_refs=[engine["receipt_id"], validation["receipt_id"]],
        assessor="adapter",
        created_utc=_FIXTURE_UTC,
    )
    assert assessment["axes"]["integration_authority"] == "none"

    # 5. Demo portal renders from the synthetic objects.
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    obj = {
        "schema_version": "ScientificObjectEnvelope/v1",
        "object_id": "sha256:" + "10" * 32,
        "object_type": "transformation_receipt",
        "synthetic": True,
        "license": "CC0-1.0",
        "created_utc": _FIXTURE_UTC,
        "parents": [],
        "payload": {
            "adapter_id": "units",
            "operation": "convert",
            "result": converted,
        },
        "axes": assessment["axes"],
    }
    (objects_dir / "obj.json").write_text(json.dumps(obj), encoding="utf-8")
    report = build_portal(objects_dir, tmp_path / "portal", PortalMode.public_demo)
    assert report.success
    assert report.objects_accepted == 1
    assert "index.html" in report.pages


if __name__ == "__main__":  # pragma: no cover
    # Allow `python -m pytest tests/integration/test_p0_end_to_end.py` and a
    # direct `python tests/integration/test_p0_end_to_end.py` run.
    pytest.main([__file__, "-v"])
