#!/usr/bin/env python3
"""V3.7 mutable-state and A22 provenance consistency gate."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "docs/plans/scientific-reasoning-fabric-activation-master-plan-v3.7.md"
A22_RECEIPT_PATH = (
    REPO_ROOT / "docs/verification/srf-v3-7-a22-final-acceptance-blocked-receipt.json"
)
MISSION_CLOSEOUT_PATH = (
    REPO_ROOT / "docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json"
)

BEGIN = "<!-- BEGIN_MUTABLE_STATE_V3_7 -->"
END = "<!-- END_MUTABLE_STATE_V3_7 -->"
STALE_A22_BRANCH = "codex/srf-a22-final-acceptance"
STALE_PRE_A22_HEAD = "677b17baf3c8d49b7dad05c39616e5d1e2df7bcc"
COMMITTED_EVIDENCE_HEAD_ROLE = "committed_a22_evidence_head_at_generation"


def _grouped_sha256(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


def _mutable_state(text: str) -> str:
    try:
        return text.split(BEGIN, 1)[1].split(END, 1)[0]
    except IndexError as exc:
        raise ValueError("V3.7 mutable-state markers are missing") from exc


def _field(block: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}:\s*(.*?)\s*$", block, flags=re.MULTILINE)
    return match.group(1) if match else None


def _actual_current_state_hash(block: str) -> str:
    body = re.sub(
        r"^CURRENT_STATE_SHA256: .*\n",
        "",
        block,
        count=1,
        flags=re.MULTILINE,
    )
    return _grouped_sha256(body.encode("utf-8"))


def _receipt_id(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["receipt_id"])


def _git_rev_parse(revision: str) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    proc = subprocess.run(  # noqa: S603 - bounded read-only git rev-parse over fixed repo root.
        [git, "-C", str(REPO_ROOT), "rev-parse", "--verify", revision],
        capture_output=True,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _check(check_id: str, passed: bool, detail: str) -> dict[str, str]:
    return {"check_id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail}


def build_receipt() -> dict[str, Any]:
    text = PLAN_PATH.read_text(encoding="utf-8")
    block = _mutable_state(text)
    declared_hash = _field(block, "CURRENT_STATE_SHA256")
    active_branch = _field(block, "active_branch_or_null")
    repository_head = _field(block, "repository_head")
    repository_head_role = _field(block, "repository_head_role")
    runtime_checkout_head = _git_rev_parse("HEAD")
    runtime_origin_main_head = _git_rev_parse("origin/main")
    a22_receipt_id = _receipt_id(A22_RECEIPT_PATH)
    mission_closeout_id = _receipt_id(MISSION_CLOSEOUT_PATH)
    repository_head_is_runtime_head = (
        repository_head is not None and repository_head == runtime_checkout_head
    )

    checks = [
        _check(
            "V37-PLAN-01-current-state-hash",
            declared_hash == _actual_current_state_hash(block),
            "CURRENT_STATE_SHA256 matches the mutable-state bytes with its own line removed",
        ),
        _check(
            "V37-PLAN-02-no-active-merged-branch",
            active_branch == "null",
            "post-merge mutable state does not advertise a stale active work branch",
        ),
        _check(
            "V37-PLAN-03-repository-head-role-explicit",
            repository_head is not None
            and repository_head != STALE_PRE_A22_HEAD
            and repository_head_role == COMMITTED_EVIDENCE_HEAD_ROLE,
            "repository_head is explicitly a committed evidence head, not current checkout truth",
        ),
        _check(
            "V37-PLAN-04-a22-receipt-ids-current",
            f"A22: {a22_receipt_id}" in block
            and f"MissionCloseoutBlocked: {mission_closeout_id}" in block,
            "mutable state points at the committed A22 and blocked mission-closeout receipts",
        ),
        _check(
            "V37-PLAN-05-stale-a22-branch-not-current",
            f"active_branch_or_null: {STALE_A22_BRANCH}" not in block,
            "stale A22 implementation branch is not represented as the current active branch",
        ),
        _check(
            "V37-PLAN-06-runtime-checkout-head-resolved",
            runtime_checkout_head is not None,
            "plan consistency gate resolves the runtime checkout head dynamically",
        ),
        _check(
            "V37-PLAN-07-no-stale-head-masked-as-current",
            repository_head_is_runtime_head or repository_head_role == COMMITTED_EVIDENCE_HEAD_ROLE,
            (
                "a committed evidence head may differ from the runtime checkout "
                "only with non-current semantics"
            ),
        ),
    ]
    result = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": "V37PlanConsistencyReceipt/v1",
        "result": result,
        "plan_path": "docs/plans/scientific-reasoning-fabric-activation-master-plan-v3.7.md",
        "declared_current_state_sha256": declared_hash,
        "observed_current_state_sha256": _actual_current_state_hash(block),
        "active_branch_or_null": active_branch,
        "repository_head": repository_head,
        "repository_head_role": repository_head_role,
        "runtime_checkout_head": runtime_checkout_head,
        "runtime_origin_main_head": runtime_origin_main_head,
        "repository_head_is_runtime_head": repository_head_is_runtime_head,
        "a22_receipt_id": a22_receipt_id,
        "mission_closeout_blocked_receipt_id": mission_closeout_id,
        "checks": checks,
    }
    return receipt


def main() -> int:
    receipt = build_receipt()
    sys.stdout.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
