from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

RECEIPT_PATH = Path("docs/verification/mission-closeout-receipt.json")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def _receipt() -> dict[str, Any]:
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def _receipt_id(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_id"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


def test_mission_closeout_receipt_is_content_addressed() -> None:
    receipt = _receipt()

    assert receipt["schema_version"] == "MissionCloseoutReceipt/v1"
    assert receipt["stage_id"] == "S28"
    assert receipt["receipt_id"] == _receipt_id(receipt)


def test_mission_closeout_binds_release_artifacts() -> None:
    receipt = _receipt()
    release = receipt["release"]

    assert receipt["result"] == "RELEASED_WITH_DECLARED_WAITS"
    assert release["tag"] == "v1.0.1"
    assert _SHA40_RE.fullmatch(release["target_commit"])
    assert set(release["artifact_hashes"]) == {
        "srlab-1.0.1-py3-none-any.whl",
        "srlab-1.0.1.tar.gz",
    }
    assert receipt["checks"]["main_post_merge_workflows"] == "PASS"
    assert receipt["checks"]["install_smoke"].startswith("PASS:")


def test_mission_closeout_keeps_residual_waits_and_authority_negative() -> None:
    receipt = _receipt()
    waits = set(receipt["declared_wait_states"])
    authority = receipt["authority_negative"]

    assert "WAIT_T7_BINDING" in waits
    assert "WAIT_RUNTIME_HEALTH:MARKET_RED_F8" in waits
    assert "WAIT_SECURITY_HEALTH:BOOTSTRAP_UNAVAILABLE" in waits
    assert authority["canonical_writes"] == 0
    assert authority["grants_authority"] is False
    assert authority["live_actions"] == 0
    assert authority["protected_actions_performed"] == []
