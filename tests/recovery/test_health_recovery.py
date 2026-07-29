from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from srl.cas import LocalArtifactStore
from srl.cas.store import StoreIntegrityError
from srl.contracts.schema import validate as schema_validate
from srl.health import (
    PulseStatus,
    RestoreDrillError,
    assess_pulse,
    bounded_restore_drill,
    build_federation_status,
    build_srf_pulse,
    project_cell,
)
from srl.observability import TraceLink, make_trace_id

_HEAD = "db871f25bff5008c6e2a2baa6ab7c4f180210f5b"
_NOW = "2026-07-29T12:00:00Z"


def test_srf_pulse_validates_and_is_authority_negative() -> None:
    pulse = build_srf_pulse(status=PulseStatus.GREEN, observed_utc=_NOW, head_sha=_HEAD)

    schema_validate(pulse, "SRFPulse")
    assert (
        pulse["pulse_id"]
        == build_srf_pulse(status=PulseStatus.GREEN, observed_utc=_NOW, head_sha=_HEAD)["pulse_id"]
    )
    assert pulse["canonical_writes"] == 0
    assert pulse["grants_authority"] is False


def test_stale_pulse_projects_wait_srf() -> None:
    pulse = build_srf_pulse(
        status=PulseStatus.GREEN,
        observed_utc="2026-07-29T11:00:00Z",
        head_sha=_HEAD,
    )

    assessment = assess_pulse(
        pulse,
        expected_head_sha=_HEAD,
        observed_utc=_NOW,
        max_age_seconds=60,
    )

    assert assessment.status is PulseStatus.WAIT
    assert assessment.wait_state == "WAIT_SRF"
    assert assessment.reason == "stale_pulse"


def test_cross_head_pulse_projects_wait_srf() -> None:
    pulse = build_srf_pulse(
        status=PulseStatus.GREEN,
        observed_utc=_NOW,
        head_sha="0" * 40,
    )

    assessment = assess_pulse(
        pulse,
        expected_head_sha=_HEAD,
        observed_utc=_NOW,
        max_age_seconds=60,
    )

    assert assessment.status is PulseStatus.WAIT
    assert assessment.reason == "cross_head_pulse"


def test_federation_status_is_read_only_cell_projection() -> None:
    market = project_cell(
        cell_id="market",
        native_status="RED",
        source="native_operator_bootstrap",
        detail="native RED remains native RED",
    )
    srf = project_cell(
        cell_id="srf",
        native_status="WAIT",
        source="SRFPulse/v1",
        detail="SRF local wait",
        is_srf=True,
    )

    status = build_federation_status(cells=(srf, market), observed_utc=_NOW)

    schema_validate(status, "FederationStatus")
    cell_items = cast(list[dict[str, object]], status["cells"])
    cells = {cell["cell_id"]: cell for cell in cell_items}
    assert cells["market"]["projection"] == "RED"
    assert cells["srf"]["projection"] == "WAIT_SRF"
    assert status["canonical_writes"] == 0
    assert status["grants_authority"] is False


def test_trace_id_is_deterministic_and_trace_link_is_plain_json() -> None:
    trace_a = make_trace_id({"stage": "S09"}, "receipt")
    trace_b = make_trace_id({"stage": "S09"}, "receipt")
    link = TraceLink(trace_id=trace_a, source_id="srf", target_id="restore", relation="proves")

    assert trace_a == trace_b
    assert trace_a.startswith("sha256:")
    assert link.to_dict()["relation"] == "proves"


def test_bounded_restore_drill_restores_unique_artifacts(tmp_path: Path) -> None:
    source = LocalArtifactStore(tmp_path / "source")
    first = source.put(b"alpha").digest
    second = source.put(json.dumps({"beta": 1}, sort_keys=True).encode()).digest

    receipt = bounded_restore_drill(
        source_store=source,
        restore_root=tmp_path / "restore",
        artifact_ids=(first, second, first),
        created_utc=_NOW,
    )

    schema_validate(receipt, "RestoreDrillReceipt")
    assert receipt["result"] == "PASS"
    assert receipt["restored_artifacts"] == sorted([first, second])
    restored = LocalArtifactStore(tmp_path / "restore")
    assert restored.has(first)
    assert restored.has(second)


def test_restore_drill_refuses_non_empty_target(tmp_path: Path) -> None:
    source = LocalArtifactStore(tmp_path / "source")
    artifact = source.put(b"alpha").digest
    target = tmp_path / "restore"
    target.mkdir()
    (target / "keep.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(RestoreDrillError):
        bounded_restore_drill(
            source_store=source,
            restore_root=target,
            artifact_ids=(artifact,),
            created_utc=_NOW,
        )


def test_restore_drill_surfaces_corrupt_source_cas(tmp_path: Path) -> None:
    source = LocalArtifactStore(tmp_path / "source")
    artifact = source.put(b"alpha").digest
    object_path = tmp_path / "source" / "objects" / artifact.removeprefix("sha256:")[:2] / artifact
    object_path.write_bytes(b"corrupt")

    with pytest.raises(StoreIntegrityError):
        bounded_restore_drill(
            source_store=source,
            restore_root=tmp_path / "restore",
            artifact_ids=(artifact,),
            created_utc=_NOW,
        )


def test_restore_drill_rejects_empty_manifest(tmp_path: Path) -> None:
    with pytest.raises(RestoreDrillError):
        bounded_restore_drill(
            source_store=LocalArtifactStore(tmp_path / "source"),
            restore_root=tmp_path / "restore",
            artifact_ids=(),
            created_utc=_NOW,
        )
