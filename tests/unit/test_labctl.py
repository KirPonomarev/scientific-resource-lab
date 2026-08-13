"""Tests for the S02 solo-agent labctl entry semantics."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest

import srl.cli as cli_module
import srl.labctl as labctl_module
from srl.cli import EXIT_ERROR, EXIT_OK, main
from srl.contracts.schema import validate
from srl.labctl import (
    FEDERATION_DOCTRINE_GATE_PATH,
    FEDERATION_ORIENTATION_SCHEMA_PATH,
    FEDERATION_POLICY_PATH,
    FEDERATION_RELEASE_RECEIPT_PATH,
    FEDERATION_STAGE_RECEIPTS,
    FEDERATION_SUCCESSOR_PLAN_PATH,
    FederationOrientationError,
    enter_report,
    federation_orientation_report,
    lab_access_receipt,
    labctl_manifest,
)


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


def _git(root: Path, *args: str) -> str:
    process = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        text=True,
    )
    return process.stdout.strip()


@pytest.fixture
def orientation_repo(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    paths = (
        FEDERATION_POLICY_PATH,
        FEDERATION_SUCCESSOR_PLAN_PATH,
        FEDERATION_RELEASE_RECEIPT_PATH,
        *FEDERATION_STAGE_RECEIPTS.values(),
        "src/srl/labctl.py",
        "src/srl/cli.py",
        "src/srl/contracts/schema.py",
        FEDERATION_ORIENTATION_SCHEMA_PATH,
    )
    for relative_path in paths:
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative_path, target)
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "orientation@example.invalid")
    _git(root, "config", "user.name", "Orientation Fixture")
    _git(root, "add", "--all")
    _git(root, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
    return root


def _raw_digest(root: Path, relative_path: str) -> str:
    return labctl_module._sha256_bytes((root / relative_path).read_bytes())


def _passing_gate_report(root: Path) -> dict[str, object]:
    head = _git(root, "rev-parse", "HEAD")
    input_manifest: dict[str, object] = {
        "checked_document_sha256": {
            FEDERATION_SUCCESSOR_PLAN_PATH: _raw_digest(
                root,
                FEDERATION_SUCCESSOR_PLAN_PATH,
            ),
        },
        "checked_source_sha256": {
            relative_path: _raw_digest(root, relative_path)
            for relative_path in (
                "src/srl/labctl.py",
                "src/srl/cli.py",
                "src/srl/contracts/schema.py",
                FEDERATION_ORIENTATION_SCHEMA_PATH,
            )
        },
        "candidate_base_head": head,
        "current_head": head,
        "candidate_diff_sha256": labctl_module._sha256_bytes(b""),
        "policy_sha256": _raw_digest(root, FEDERATION_POLICY_PATH),
        "release_receipt_sha256": _raw_digest(root, FEDERATION_RELEASE_RECEIPT_PATH),
        "verifier_sha256": labctl_module._sha256_bytes(b"fixture verifier"),
        "worktree_matches_index": True,
    }
    report: dict[str, object] = {
        "schema_version": "FederationDoctrineConsistencyReceipt/v1",
        "policy_id": "FEDERATION_OWNERSHIP_POLICY_V1",
        "result": "PASS",
        "input_manifest": input_manifest,
        "input_manifest_sha256": labctl_module._canonical_sha256(input_manifest),
        "checks": [
            {"check_id": check_id, "detail": "fixture PASS", "status": "PASS"}
            for check_id in sorted(labctl_module._EXPECTED_GATE_CHECK_IDS)
        ],
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }
    report["receipt_id"] = labctl_module._canonical_receipt_id(report)
    return report


def _install_passing_gate(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> Callable[[], None]:
    gate_holder = [_passing_gate_report(root)]

    def run_gate(_root: Path, environment: dict[str, str]) -> dict[str, object]:
        assert _root == root.resolve()
        assert {key for key in environment if key.startswith("GIT_")} == {
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_OPTIONAL_LOCKS",
            "GIT_TERMINAL_PROMPT",
        }
        return labctl_module._validate_gate_report(deepcopy(gate_holder[0]))

    def refresh() -> None:
        gate_holder[0] = _passing_gate_report(root)

    monkeypatch.setattr(labctl_module, "_run_doctrine_gate", run_gate)
    monkeypatch.setattr(
        labctl_module,
        "_assert_loaded_checkout_sources",
        lambda _root, _manifest: None,
    )
    return refresh


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    assert isinstance(receipt, dict)
    cell = receipt["cell"]
    assert isinstance(cell, dict)
    assert cell["cell_id"] == "standalone"
    assert receipt["grants_authority"] is False


def test_cli_labctl_enter_unknown_cell(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown cell IDs fail closed with a typed error."""
    code = main(["labctl", "enter", "unknown"])
    assert code == EXIT_ERROR
    report = _stderr_json(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["fail_reason"] == "CONTRACT_INVALID"
    assert "unknown lab cell" in str(report["error"])


def test_federation_orientation_is_exact_checkout_bound_and_stable(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_passing_gate(monkeypatch, orientation_repo)

    report = federation_orientation_report(
        repo_root=orientation_repo,
        write_scope="docs/governance-only",
    )
    second = federation_orientation_report(
        repo_root=orientation_repo,
        write_scope="docs/governance-only",
    )

    assert report == second
    assert report["schema_version"] == "FederationOrientationReport/v1"
    assert report["orientation"] == {
        "PRIMARY_SCIENTIFIC_CORTEX": "SCIENTIFIC_RESOURCE_LAB",
        "SRL_FORMAL_ROLE": "SCIENTIFIC_REASONING_COMPUTE_FABRIC",
        "TARGET_WIRE_ORDER_OWNER": "DUAL_CONTOUR",
        "TARGET_WIRE_ORDER_ROLE_STATE": "TARGET_DECLARED_NOT_RUNTIME_PROVEN",
        "SAFETY_CORTEX": "SECURITY_RESEARCH_OS",
        "MARKET_TRUTH_OWNER": "CRYPTO_MARKET_LAB",
        "SECURITY_TRUTH_OWNER": "SECURITY_RESEARCH_OS",
        "GLOBAL_SOVEREIGN_CONTROLLER": "NONE",
        "GLOBAL_SOVEREIGN_WRITER": "NONE",
        "GLOBAL_A2": "FORBIDDEN",
        "CROSS_DOMAIN_EFFECT_OWNER": "TARGET_NATIVE_DOMAIN_ONLY",
        "CROSSLAB_ROLE": "PAGER_ONLY",
        "CROSSLAB_SRL_ENDPOINT": "NONE",
        "CURRENT_SRL_RELEASE_TRUTH": "BLOCKED_EXTERNAL_AUTHORITY",
        "CURRENT_FEDERATION_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_SRL_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_MARKET_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_SECURITY_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_DUAL_RUNTIME": "NOT_CHARACTERIZED",
        "FEDERATION_RUNTIME_STATE_SOURCE": "EXACT_CURRENT_NATIVE_RECEIPTS_ONLY",
        "DECLARED_WRITE_SCOPE": "docs/governance-only",
        "DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY": False,
    }
    assert report["orientation_block"].splitlines()[-1] == (
        "DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY: FALSE"
    )
    assert report["target_role_activation"] == {
        "dual_wire_order": "TARGET_DECLARED_NOT_RUNTIME_PROVEN"
    }
    evidence = report["recorded_v37_evidence"]
    assert evidence["evidence_role"] == "RECORDED_V3_7_NOT_CURRENT_RUNTIME_HEALTH"
    assert evidence["release"]["result"] == "BLOCKED_EXTERNAL_AUTHORITY"
    assert evidence["release"]["target_release_published"] is False
    assert {
        participant: (item["stage_id"], item["terminal_state"], item["evidence_role"])
        for participant, item in evidence["stages"].items()
    } == {
        "dual": ("A18", "WAIT_NATIVE_CHILD_CLOSEOUT", "RECORDED_V3_7_NOT_CURRENT_HEALTH"),
        "market": (
            "A19",
            "WAIT_NATIVE_CHILD_CLOSEOUT",
            "RECORDED_V3_7_NOT_CURRENT_HEALTH",
        ),
        "security": (
            "A20",
            "WAIT_NATIVE_CHILD_CLOSEOUT",
            "RECORDED_V3_7_NOT_CURRENT_HEALTH",
        ),
    }
    source_identity = report["source_identity"]
    assert source_identity["candidate_base_head"] == source_identity["current_head"]
    assert source_identity["candidate_diff_sha256"].startswith("sha256:")
    assert report["runtime_truth"] is False
    assert report["activates_federation"] is False
    assert report["declared_scope_grants_authority"] is False
    assert report["grants_authority"] is False
    validate(report, "FederationOrientationReport")


def test_cli_labctl_federation_orient_emits_typed_json(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_passing_gate(monkeypatch, orientation_repo)
    report = federation_orientation_report(repo_root=orientation_repo)
    monkeypatch.setattr(cli_module, "federation_orientation_report", lambda **_kwargs: report)

    assert main(["labctl", "federation-orient", "NONE"]) == EXIT_OK
    emitted = _stdout_json(capsys)
    assert emitted == report
    orientation = emitted["orientation"]
    assert isinstance(orientation, dict)
    assert orientation["CURRENT_FEDERATION_RUNTIME"] == "NOT_CHARACTERIZED"
    assert orientation["DECLARED_WRITE_SCOPE"] == "NONE"


def test_cli_federation_orientation_error_is_one_json_record_without_path_leak(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(**_kwargs: object) -> dict[str, object]:
        raise FederationOrientationError("repository doctrine gate did not PASS")

    monkeypatch.setattr(cli_module, "federation_orientation_report", fail)
    assert main(["labctl", "federation-orient"]) == EXIT_ERROR
    error = _stderr_json(capsys)
    assert error == {
        "schema_version": "ErrorReport/v1",
        "error": "repository doctrine gate did not PASS",
        "command": "labctl federation-orient",
        "fail_reason": "CONTRACT_INVALID",
    }


def test_federation_orientation_rejects_unknown_policy_field_after_gate_pass(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_gate = _install_passing_gate(monkeypatch, orientation_repo)
    policy_path = orientation_repo / FEDERATION_POLICY_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["native_writer"] = "scientific-resource-lab"
    _write_json(policy_path, policy)
    refresh_gate()

    with pytest.raises(FederationOrientationError, match="policy shape"):
        federation_orientation_report(repo_root=orientation_repo)


def test_federation_orientation_rejects_tampered_policy_semantics(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_gate = _install_passing_gate(monkeypatch, orientation_repo)
    policy_path = orientation_repo / FEDERATION_POLICY_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["formal_invariants"]["global_sovereign_controller"] = "scientific-resource-lab"
    _write_json(policy_path, policy)
    refresh_gate()

    with pytest.raises(FederationOrientationError, match="not the safe draft"):
        federation_orientation_report(repo_root=orientation_repo)


def test_federation_orientation_rejects_self_recomputed_fake_release(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_gate = _install_passing_gate(monkeypatch, orientation_repo)
    release_path = orientation_repo / FEDERATION_RELEASE_RECEIPT_PATH
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["result"] = "DONE"
    release["release"] = {"published": True, "reason": "fake", "tag": "v2.0.0"}
    release["receipt_id"] = labctl_module._canonical_receipt_id(release)
    _write_json(release_path, release)
    refresh_gate()

    with pytest.raises(FederationOrientationError, match="not exact blocked evidence"):
        federation_orientation_report(repo_root=orientation_repo)


def test_federation_orientation_rejects_tampered_stage_with_recomputed_id(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_passing_gate(monkeypatch, orientation_repo)
    stage_path = orientation_repo / FEDERATION_STAGE_RECEIPTS["dual"]
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    stage["stage_id"] = "A19"
    stage["receipt_id"] = labctl_module._canonical_receipt_id(stage)
    _write_json(stage_path, stage)

    with pytest.raises(FederationOrientationError, match="dual stage receipt"):
        federation_orientation_report(repo_root=orientation_repo)


def test_federation_orientation_rejects_swapped_participant_stages(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_passing_gate(monkeypatch, orientation_repo)
    dual_path = orientation_repo / FEDERATION_STAGE_RECEIPTS["dual"]
    market_path = orientation_repo / FEDERATION_STAGE_RECEIPTS["market"]
    dual_raw = dual_path.read_bytes()
    market_raw = market_path.read_bytes()
    dual_path.write_bytes(market_raw)
    market_path.write_bytes(dual_raw)

    with pytest.raises(FederationOrientationError, match="dual stage receipt"):
        federation_orientation_report(repo_root=orientation_repo)


def test_federation_orientation_rejects_absolute_and_symlink_escape(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_passing_gate(monkeypatch, orientation_repo)
    with pytest.raises(FederationOrientationError, match="escapes the repository"):
        labctl_module._resolve_repo_input(
            orientation_repo,
            str((orientation_repo / FEDERATION_POLICY_PATH).resolve()),
            label="hostile input",
        )

    release_path = orientation_repo / FEDERATION_RELEASE_RECEIPT_PATH
    outside = tmp_path / "outside-release.json"
    shutil.copy2(release_path, outside)
    release_path.unlink()
    release_path.symlink_to(outside)
    with pytest.raises(FederationOrientationError, match="symbolic link"):
        federation_orientation_report(repo_root=orientation_repo)


def test_federation_orientation_rejects_missing_plan(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_passing_gate(monkeypatch, orientation_repo)
    (orientation_repo / FEDERATION_SUCCESSOR_PLAN_PATH).unlink()

    with pytest.raises(FederationOrientationError, match="successor plan is unavailable"):
        federation_orientation_report(repo_root=orientation_repo)


def test_cli_rejects_malformed_release_without_traceback_or_absolute_path(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    refresh_gate = _install_passing_gate(monkeypatch, orientation_repo)
    release_path = orientation_repo / FEDERATION_RELEASE_RECEIPT_PATH
    release_path.write_text("{not-json\n", encoding="utf-8")
    refresh_gate()

    def orient(*, write_scope: str) -> dict[str, object]:
        return federation_orientation_report(repo_root=orientation_repo, write_scope=write_scope)

    monkeypatch.setattr(cli_module, "federation_orientation_report", orient)
    assert main(["labctl", "federation-orient"]) == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert str(orientation_repo) not in captured.err
    error = json.loads(captured.err)
    assert error["schema_version"] == "ErrorReport/v1"
    assert error["fail_reason"] == "CONTRACT_INVALID"
    assert error["error"] == "V3.7 release receipt is not valid strict JSON"


@pytest.mark.parametrize(
    "scope",
    ["bad\u2028scope", "../escape", "space separated", "", "x" * 257],
)
def test_federation_orientation_rejects_non_allowlisted_scope(scope: str) -> None:
    with pytest.raises(FederationOrientationError, match="safe ASCII"):
        federation_orientation_report(write_scope=scope)


def test_federation_orientation_ignores_git_dir_spoofing(
    orientation_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_passing_gate(monkeypatch, orientation_repo)
    expected_head = _git(orientation_repo, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "spoofed-git-dir"))

    report = federation_orientation_report(repo_root=orientation_repo)

    assert report["status"] == "ORIENTED_READ_ONLY"
    assert report["source_identity"]["current_head"] == expected_head


def test_federation_orientation_requires_gate_script(
    orientation_repo: Path,
) -> None:
    assert not (orientation_repo / FEDERATION_DOCTRINE_GATE_PATH).exists()
    with pytest.raises(FederationOrientationError, match="doctrine gate is unavailable"):
        federation_orientation_report(repo_root=orientation_repo)


@pytest.mark.parametrize("failure_mode", ["not-pass", "missing-review", "unknown-field"])
def test_federation_orientation_rejects_nonexact_gate_report(
    orientation_repo: Path,
    failure_mode: str,
) -> None:
    gate = _passing_gate_report(orientation_repo)
    if failure_mode == "not-pass":
        gate["result"] = "FAIL"
    elif failure_mode == "missing-review":
        checks = gate["checks"]
        assert isinstance(checks, list)
        gate["checks"] = [
            item
            for item in checks
            if isinstance(item, dict) and item["check_id"] != "FDC-15-independent-review"
        ]
    else:
        gate["authority"] = "A2"
    gate["receipt_id"] = labctl_module._canonical_receipt_id(gate)

    with pytest.raises(FederationOrientationError, match="gate"):
        labctl_module._validate_gate_report(gate)


def test_solo_agent_docs_are_generated() -> None:
    """Generated S02 docs stay synchronized with ``srl.labctl``."""
    result = subprocess.run(
        [sys.executable, "scripts/docs/generate_solo_agent_docs.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
