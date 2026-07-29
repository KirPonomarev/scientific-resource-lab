"""Tests for the S02 solo-agent labctl entry semantics."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from srl.cli import EXIT_ERROR, EXIT_OK, main
from srl.labctl import enter_report, lab_access_receipt, labctl_manifest


def _stdout_json(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert isinstance(parsed, dict)
    return parsed


def _stderr_json(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert isinstance(parsed, dict)
    return parsed


def test_labctl_manifest_authority_negative() -> None:
    """The shared manifest pins the authority-negative SRF boundary."""
    manifest = labctl_manifest()
    invariants = manifest["authority_invariants"]
    assert invariants == {
        "grants_authority": False,
        "canonical_writes": 0,
        "live_actions": 0,
        "orders_allowed": False,
        "security_actions_allowed": False,
    }


def test_labctl_enter_report_contains_scope_receipt() -> None:
    """Standalone entry returns a scope projection, not a permission grant."""
    report = enter_report()
    receipt = report["receipt"]
    assert report["schema_version"] == "LabCtlEnterReport/v1"
    assert receipt["schema_version"] == "LabAccessReceipt/v1"
    assert receipt["cell"]["cell_id"] == "standalone"
    assert receipt["grants_authority"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["live_actions"] == 0


def test_cross_lab_cells_are_proposal_only_waits() -> None:
    """Market and Security entries require native bootstrap and stay proposal-only."""
    for cell_id in ("market", "security"):
        receipt = lab_access_receipt(cell_id)
        assert receipt["cell"]["status"] == "WAIT_NATIVE_BOOTSTRAP"
        assert receipt["scope"]["proposal_only"] is True
        assert receipt["orders_allowed"] is False
        assert receipt["security_actions_allowed"] is False


def test_cli_labctl_enter(capsys: pytest.CaptureFixture[str]) -> None:
    """``srlab labctl enter`` emits one canonical JSON report."""
    code = main(["labctl", "enter"])
    assert code == EXIT_OK
    report = _stdout_json(capsys)
    assert report["schema_version"] == "LabCtlEnterReport/v1"
    receipt = report["receipt"]
    assert receipt["cell"]["cell_id"] == "standalone"
    assert receipt["grants_authority"] is False


def test_cli_labctl_enter_unknown_cell(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown cell IDs fail closed with a typed error."""
    code = main(["labctl", "enter", "unknown"])
    assert code == EXIT_ERROR
    report = _stderr_json(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"
    assert "unknown lab cell" in str(report["error"])


def test_solo_agent_docs_are_generated() -> None:
    """Generated S02 docs stay synchronized with ``srl.labctl``."""
    result = subprocess.run(
        [sys.executable, "scripts/docs/generate_solo_agent_docs.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
