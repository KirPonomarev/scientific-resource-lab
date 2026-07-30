from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from srl.health.final_acceptance import (
    A22_OPERATOR_ACTION_ID,
    A22_TARGET_RELEASE,
    A22_TARGET_RESULT,
    A22_TERMINAL_STATE,
    build_a22_final_acceptance_receipt,
    build_a22_operator_action,
    resolve_a22_head_provenance,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_a22_blocks_done_and_v2_release_without_declared_wait_release() -> None:
    receipt = build_a22_final_acceptance_receipt(repo_root=REPO_ROOT, git_head="0" * 40)

    assert receipt["result"] == "PASS"
    assert receipt["target_release"] == A22_TARGET_RELEASE
    assert receipt["target_result"] == A22_TARGET_RESULT
    assert receipt["terminal_state"] == A22_TERMINAL_STATE
    assert receipt["release_truth_decision"]["verdict"] == "REJECT"
    assert receipt["release_published"] is False
    closeout = receipt["mission_closeout_receipt"]
    assert closeout["result"] == A22_TERMINAL_STATE
    assert closeout["release"]["published"] is False
    assert "RELEASED_WITH_DECLARED_WAITS" in closeout["forbidden_terminal_states"]
    assert "DONE" in closeout["forbidden_terminal_states"]
    assert closeout["source_git_head"] == "0" * 40
    assert closeout["generator_head"] == "0" * 40
    assert closeout["git_head"] == closeout["source_git_head"]
    assert "accepted_release_head" in closeout
    assert "accepted-main release truth" in closeout["git_head_semantics"]


def test_a22_preserves_mandatory_waits_as_release_blockers() -> None:
    receipt = build_a22_final_acceptance_receipt(repo_root=REPO_ROOT, git_head="0" * 40)

    assert receipt["remaining_internal_waits"] == []
    blockers = set(receipt["release_truth_decision"]["blockers"])
    for item in receipt["mandatory_wait_capability_or_toolchain"]:
        assert item["state"] in {"WAIT_CAPABILITY", "WAIT_TOOLCHAIN"}
        assert f"MANDATORY_NOT_ACTIVE:{item['component_id']}:{item['state']}" in blockers
    assert "PRODUCTION_SIGNER_NOT_ED25519_NATIVE" in blockers
    assert "SANDBOX_NOT_ENFORCED_T2_T3" in blockers
    assert "T7_NOT_ACTIVE" in blockers
    assert any(blocker.startswith("MANDATORY_WAIT_LICENSE:python-flint") for blocker in blockers)
    assert any(
        blocker.startswith("MANDATORY_NOT_ACTIVE:petsc:WAIT_COMPUTE_NODE") for blocker in blockers
    )


def test_a22_single_decision_packet_is_non_authorizing() -> None:
    action = build_a22_operator_action()

    assert action["schema_version"] == "ProtectedOperatorAction/v1"
    assert action["action_id"] == A22_OPERATOR_ACTION_ID
    assert action["authority_required"] is True
    assert action["grants_authority"] is False
    assert "publish_v2_0_0" in action["forbidden_without_authority"]
    assert "emit_MissionCloseoutReceipt_DONE" in action["forbidden_without_authority"]
    assert len(action["blocked_until"]) >= 10


def test_a22_head_provenance_prefers_explicit_then_env_then_local_git(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "1" * 40)
    provenance = resolve_a22_head_provenance(repo_root=REPO_ROOT, git_head="2" * 40)

    assert provenance["source_git_head"] == "2" * 40
    assert provenance["source_git_head_source"] == "explicit_git_head"
    assert provenance["generator_head"] == "2" * 40
    assert provenance["self_referential_commit_claimed"] is False

    monkeypatch.delenv("GITHUB_SHA", raising=False)
    git = shutil.which("git")
    assert git is not None
    expected = subprocess.run(  # noqa: S603
        [git, "-C", str(REPO_ROOT), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    receipt = build_a22_final_acceptance_receipt(repo_root=REPO_ROOT)

    assert receipt["head_provenance"]["source_git_head"] == expected
    assert receipt["head_provenance"]["source_git_head_source"] == "git_rev_parse_HEAD"
    assert receipt["mission_closeout_receipt"]["source_git_head"] == expected
    assert "UNKNOWN" not in json.dumps(receipt["head_provenance"], sort_keys=True)


def test_a22_receipt_covers_a00_through_a21_public_stage_receipts() -> None:
    receipt = build_a22_final_acceptance_receipt(repo_root=REPO_ROOT, git_head="0" * 40)
    stages = {item["stage_id"]: item for item in receipt["stage_receipts"]}

    assert set(stages) == {f"A{index:02d}" for index in range(22)}
    for stage_id, item in stages.items():
        assert item["status"] == "PASS", stage_id
        assert item["path"].startswith("docs/verification/"), stage_id
        assert Path(item["path"]).exists(), stage_id
        assert str(item["sha256"]).startswith("sha256:"), stage_id


def test_a22_receipt_does_not_publish_machine_paths() -> None:
    receipt = build_a22_final_acceptance_receipt(repo_root=REPO_ROOT, git_head="0" * 40)
    rendered = json.dumps(receipt, sort_keys=True)

    assert "/Users/" not in rendered
    assert "/Volumes/" not in rendered
    assert "PRIVATE_PATH_MARKER" not in rendered


def test_a22_committed_artifacts_preserve_blocked_terminal_semantics() -> None:
    action = json.loads(
        (REPO_ROOT / "docs/target-binding/a22-v2-release-blockers-operator-action.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = json.loads(
        (
            REPO_ROOT / "docs/verification/srf-v3-7-a22-final-acceptance-blocked-receipt.json"
        ).read_text(encoding="utf-8")
    )
    closeout = json.loads(
        (REPO_ROOT / "docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json").read_text(
            encoding="utf-8"
        )
    )

    assert action == build_a22_operator_action()
    assert receipt["result"] == "PASS"
    assert receipt["terminal_state"] == A22_TERMINAL_STATE
    assert receipt["release_truth_decision"]["verdict"] == "REJECT"
    assert closeout["result"] == A22_TERMINAL_STATE
    assert closeout["release"]["published"] is False
    assert receipt["head_provenance"]["schema_version"] == "A22HeadProvenance/v1"
    assert receipt["head_provenance"]["source_git_head"] != "UNKNOWN"
    assert closeout["source_git_head"] != "546d292731045aaaf0475341f947ce283480b6f6"
    assert closeout["accepted_release_head"] != "UNKNOWN"
    assert closeout["git_head_semantics"] == receipt["head_provenance"]["legacy_git_head_semantics"]
