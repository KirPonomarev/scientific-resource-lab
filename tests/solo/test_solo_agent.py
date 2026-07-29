"""A17 solo-agent entry acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.cli import EXIT_ERROR, EXIT_OK, main
from srl.contracts import schema_validate
from srl.interfaces import InterfaceService
from srl.labctl import enter_report
from srl.solo_agent import (
    SOLO_SESSION_SCHEMA,
    SoloAgentError,
    checkout_report,
    session_status,
)


def _stdout_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    line = capsys.readouterr().out.splitlines()[0]
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


def _stderr_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    line = capsys.readouterr().err.splitlines()[0]
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


def _read(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_fresh_agent_cli_lifecycle_completes_real_task(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_dir = tmp_path / "solo"

    assert main(["labctl", "doctor"]) == EXIT_OK
    doctor = _stdout_json(capsys)
    assert doctor["schema_version"] == "SoloAgentDoctorReport/v1"
    assert doctor["status"] == "OK"
    assert doctor["active_capability_count"] > 0
    assert doctor["truth_ledger_digest"].startswith("sha256:")

    assert main(["labctl", "submit", str(session_dir)]) == EXIT_OK
    submit = _stdout_json(capsys)
    assert submit["status"] == "COMPLETED"

    assert main(["labctl", "status", str(session_dir)]) == EXIT_OK
    status = _stdout_json(capsys)
    assert status["status"] == "COMPLETED"

    assert main(["labctl", "result", str(session_dir)]) == EXIT_OK
    result = _stdout_json(capsys)
    assert result["schema_version"] == "SoloAgentTaskResult/v1"
    assert result["compute"]["result"] == "1"
    assert result["engine_receipt"]["exercise_level"] == "actual_compute"
    assert result["validation_receipt"]["scientific_check"] == "checked"
    assert result["assessment"]["axes"]["integration_authority"] == "none"
    assert result["canonical_writes"] == 0
    assert result["grants_authority"] is False

    assert main(["labctl", "export", str(session_dir)]) == EXIT_OK
    exported = _stdout_json(capsys)
    assert exported["status"] == "EXPORTED"
    assert (session_dir / "export-packet.json").is_file()

    assert main(["labctl", "replay", str(session_dir)]) == EXIT_OK
    replay = _stdout_json(capsys)
    assert replay["status"] == "REPLAY_MATCH"

    assert main(["labctl", "portal", str(session_dir)]) == EXIT_OK
    portal = _stdout_json(capsys)
    assert portal["status"] == "RENDERED"
    assert "index.html" in portal["pages"]


def test_session_and_capability_files_keep_nested_contracts_valid(tmp_path: Path) -> None:
    session_dir = tmp_path / "solo"
    service = InterfaceService()
    submit = service.solo_submit(str(session_dir))
    assert submit["status"] == "COMPLETED"

    session = _read(session_dir / "session.json")
    assert session["schema_version"] == SOLO_SESSION_SCHEMA
    assert session["canonical_writes"] == 0
    assert session["grants_authority"] is False
    schema_validate(session["lab_session_envelope"], "LabSessionEnvelope")
    schema_validate(session["access_receipt"], "LabAccessReceipt")

    capability_manifest = _read(session_dir / "capability-manifest.json")
    schema_validate(capability_manifest, "CapabilityManifest")
    assert "truth_ledger_digest" not in capability_manifest
    assert session["truth_ledger_digest"].startswith("sha256:")


def test_cross_lab_enter_is_native_bootstrap_wait() -> None:
    for cell_id in ("market", "security"):
        report = enter_report(cell_id)
        assert report["status"] == "WAIT_NATIVE_BOOTSTRAP"
        assert report["receipt"]["scope"]["proposal_only"] is True


def test_market_submit_requires_native_bootstrap(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["labctl", "submit", str(tmp_path / "market"), "market"])
    assert code == EXIT_ERROR
    err = _stderr_json(capsys)
    assert "requires native bootstrap" in err["error"]


def test_stale_session_head_fails_closed(tmp_path: Path) -> None:
    session_dir = tmp_path / "solo"
    service = InterfaceService()
    service.solo_submit(str(session_dir))
    session_path = session_dir / "session.json"
    session = _read(session_path)
    session["git_head"] = "0" * 40
    session_path.write_text(json.dumps(session), encoding="utf-8")

    with pytest.raises(SoloAgentError) as exc_info:
        session_status(session_dir)
    assert exc_info.value.status == "STALE_OR_CROSS_HEAD"


def test_wrong_checkout_redirect_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("srl.solo_agent._git", lambda _args: None)
    report = checkout_report()
    assert report.status == "WRONG_CHECKOUT"
    assert report.project_root_ok is False
    assert "scientific-resource-lab checkout" in report.detail
