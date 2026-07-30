from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_v37_plan_consistency_gate_passes() -> None:
    git = shutil.which("git")
    assert git is not None
    current_head = subprocess.run(  # noqa: S603 - bounded read-only git rev-parse.
        [git, "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    proc = subprocess.run(
        [sys.executable, "scripts/checks/srf-v37-plan-consistency.py"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout
    receipt = json.loads(proc.stdout)
    assert receipt["result"] == "PASS"
    assert receipt["active_branch_or_null"] == "null"
    assert receipt["repository_head_role"] == "committed_a22_evidence_head_at_generation"
    assert receipt["runtime_checkout_head"] == current_head
    assert receipt["runtime_checkout_head"] != "UNKNOWN"


def test_v37_plan_consistency_does_not_mask_committed_head_as_current() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/checks/srf-v37-plan-consistency.py"],
        capture_output=True,
        check=True,
        text=True,
    )

    receipt = json.loads(proc.stdout)
    if receipt["repository_head"] != receipt["runtime_checkout_head"]:
        assert receipt["repository_head_is_runtime_head"] is False
        assert receipt["repository_head_role"] == "committed_a22_evidence_head_at_generation"


def test_verify_orchestration_runs_v37_plan_consistency_gate() -> None:
    verify = Path("scripts/ci/verify-v37.py").read_text(encoding="utf-8")

    assert "scripts/checks/srf-v37-plan-consistency.py" in verify
