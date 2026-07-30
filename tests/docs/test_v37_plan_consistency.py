from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_v37_plan_consistency_gate_passes() -> None:
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
    assert receipt["repository_head_role"] == "accepted_main_after_a22"


def test_verify_orchestration_runs_v37_plan_consistency_gate() -> None:
    verify = Path("scripts/ci/verify-v37.py").read_text(encoding="utf-8")

    assert "scripts/checks/srf-v37-plan-consistency.py" in verify
