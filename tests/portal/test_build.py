"""Tests for the static portal generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.portal import PortalMode, build_portal


def _write_object(objects_dir: Path, name: str, obj: dict[str, Any]) -> None:
    (objects_dir / name).write_text(json.dumps(obj) + "\n", encoding="utf-8")


def _synthetic_envelope(
    *,
    object_type: str = "claim",
    payload: dict[str, Any] | None = None,
    source_path: str = "fixtures/public/test.json",
) -> dict[str, Any]:
    return {
        "schema_version": "ScientificObjectEnvelope/v1",
        "object_type": object_type,
        "created_utc": "2026-07-28T00:00:00Z",
        "parents": [],
        "payload": payload or {"statement": "synthetic claim"},
        "provenance": {"source_path": source_path},
        "canonical_writes": 0,
        "grants_authority": False,
    }


def test_build_portal_report_shape(tmp_path: Path) -> None:
    """The build report carries the expected shape."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(objects_dir, "a.json", _synthetic_envelope())

    out_dir = tmp_path / "out"
    report = build_portal(objects_dir, out_dir, PortalMode.public_demo)

    assert report.mode is PortalMode.public_demo
    assert report.output_dir == out_dir
    assert report.success is True
    assert report.objects_scanned == 1
    assert report.objects_accepted == 1
    assert report.objects_refused == 0
    assert report.leak_detected is False
    assert report.refusals == []
    assert "index.html" in report.pages
    assert report.generator_version
    assert report.built_at


def test_public_demo_accepts_only_synthetic(tmp_path: Path) -> None:
    """Public demo accepts synthetic objects and refuses a non-synthetic one."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(objects_dir, "synthetic.json", _synthetic_envelope())
    _write_object(
        objects_dir,
        "private.json",
        {
            "schema_version": "ScientificObjectEnvelope/v1",
            "object_type": "claim",
            "created_utc": "2026-07-28T00:00:00Z",
            "parents": [],
            "payload": {"statement": "not synthetic"},
            "canonical_writes": 0,
            "grants_authority": False,
        },
    )

    out_dir = tmp_path / "out"
    report = build_portal(objects_dir, out_dir, PortalMode.public_demo)

    assert report.success is True
    assert report.objects_accepted == 1
    assert report.objects_refused == 1
    assert report.refusals[0]["reason"] == "PUBLIC_NON_SYNTHETIC"


def test_public_demo_refuses_leaked_paths(tmp_path: Path) -> None:
    """A public-demo build refuses any object that contains an absolute path."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(
        objects_dir,
        "leaked.json",
        {
            "schema_version": "ScientificObjectEnvelope/v1",
            "object_type": "artifact",
            "created_utc": "2026-07-28T00:00:00Z",
            "parents": [],
            "payload": {"source_path": "fixtures/public/leaked.json", "path": "/etc/passwd"},
            "canonical_writes": 0,
            "grants_authority": False,
        },
    )

    out_dir = tmp_path / "out"
    report = build_portal(objects_dir, out_dir, PortalMode.public_demo)

    assert report.success is False
    assert report.leak_detected is True
    assert report.objects_accepted == 0
    assert any(r["reason"] == "PUBLIC_LEAK_DETECTED" for r in report.refusals)
    assert not (out_dir / "index.html").exists()


def test_private_mode_accepts_non_synthetic(tmp_path: Path) -> None:
    """Private-local mode is not restricted to the public synthetic corpus."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(
        objects_dir,
        "local.json",
        {
            "schema_version": "ScientificObjectEnvelope/v1",
            "object_type": "claim",
            "created_utc": "2026-07-28T00:00:00Z",
            "parents": [],
            "payload": {"local_path": "/Users/alice/private.json"},
            "canonical_writes": 0,
            "grants_authority": False,
        },
    )

    out_dir = tmp_path / "out"
    report = build_portal(objects_dir, out_dir, PortalMode.private_local)

    assert report.success is True
    assert report.objects_accepted == 1
    assert report.objects_refused == 0
    assert (out_dir / "index.html").exists()


def test_html_escaping(tmp_path: Path) -> None:
    """A <script> payload is escaped in generated output."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(
        objects_dir,
        "xss.json",
        _synthetic_envelope(payload={"statement": "<script>alert(1)</script>"}),
    )

    out_dir = tmp_path / "out"
    build_portal(objects_dir, out_dir, PortalMode.public_demo)

    text = "\n".join(
        p.read_text(encoding="utf-8") for p in out_dir.iterdir() if p.suffix == ".html"
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_no_external_resources(tmp_path: Path) -> None:
    """Generated pages contain no external resource references."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(objects_dir, "clean.json", _synthetic_envelope())

    out_dir = tmp_path / "out"
    build_portal(objects_dir, out_dir, PortalMode.public_demo)

    forbidden = ["http://", "https://", "<script", "<link", "<img", "src="]
    for page in out_dir.iterdir():
        if page.suffix != ".html":
            continue
        text = page.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{marker!r} found in {page.name}"


def test_demo_watermark_on_every_page(tmp_path: Path) -> None:
    """Every public-demo page carries the demo watermark."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(objects_dir, "demo.json", _synthetic_envelope())

    out_dir = tmp_path / "out"
    build_portal(objects_dir, out_dir, PortalMode.public_demo)

    for page in out_dir.iterdir():
        if page.suffix != ".html":
            continue
        assert "DEMO" in page.read_text(encoding="utf-8")


def test_private_mode_has_no_watermark(tmp_path: Path) -> None:
    """Private-local pages do not carry the demo watermark."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(objects_dir, "private.json", _synthetic_envelope())

    out_dir = tmp_path / "out"
    build_portal(objects_dir, out_dir, PortalMode.private_local)

    for page in out_dir.iterdir():
        if page.suffix != ".html":
            continue
        assert "DEMO" not in page.read_text(encoding="utf-8")


def test_integration_authority_is_none(tmp_path: Path) -> None:
    """The interfaces page always reports integration authority as none."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(
        objects_dir,
        "iface.json",
        _synthetic_envelope(
            object_type="model_interface",
            payload={"adapter_id": "demo", "capabilities": ["compute"]},
        ),
    )

    out_dir = tmp_path / "out"
    build_portal(objects_dir, out_dir, PortalMode.public_demo)

    interfaces = (out_dir / "interfaces.html").read_text(encoding="utf-8")
    assert "Integration authority" in interfaces
    assert "none" in interfaces


def test_evidence_matrix_shows_all_axes(tmp_path: Path) -> None:
    """The evidence page renders the 11 axes for an assessment object."""
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    _write_object(
        objects_dir,
        "assessment.json",
        _synthetic_envelope(
            object_type="evidence_assessment",
            payload={
                "schema_version": "EvidenceAssessment/v1",
                "subject_claim_id": "sha256:" + "0" * 64,
                "axes": {
                    "capability_state": "ready",
                    "exercise_level": "actual_compute",
                    "engine_execution": "completed",
                    "scientific_check": "checked",
                    "formal_check": "checked",
                    "formal_scope": "exact_statement",
                    "statistical_support": "moderate",
                    "causal_identification": "partially_identified",
                    "algorithmic_cross_engine_reproduction": "reproduced",
                    "independent_empirical_replication": "none",
                    "integration_authority": "none",
                },
                "evidence_refs": [],
                "assessor": "operator",
                "created_utc": "2026-07-28T00:00:00Z",
                "canonical_writes": 0,
                "grants_authority": False,
            },
        ),
    )

    out_dir = tmp_path / "out"
    build_portal(objects_dir, out_dir, PortalMode.public_demo)

    evidence = (out_dir / "evidence.html").read_text(encoding="utf-8")
    assert "capability_state" in evidence
    assert "independent_empirical_replication" in evidence
    assert "completed" in evidence


def test_mode_must_be_portal_mode() -> None:
    """build_portal rejects a non-PortalMode value."""
    with pytest.raises(TypeError):
        build_portal("objects", "out", "public_demo")  # type: ignore[arg-type]
