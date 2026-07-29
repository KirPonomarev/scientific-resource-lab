from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

RECEIPT_PATH = Path("docs/verification/s27-merge-receipt.json")
_SHA256_RE = re.compile(r"^[0-9a-f]{40}$")


def _receipt() -> dict[str, Any]:
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def _receipt_id(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_id"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


def test_s27_merge_receipt_is_content_addressed() -> None:
    receipt = _receipt()

    assert receipt["schema_version"] == "MergeReceipt/v1"
    assert receipt["stage_id"] == "S27"
    assert receipt["receipt_id"] == _receipt_id(receipt)


def test_s27_merge_receipt_binds_candidate_and_main() -> None:
    receipt = _receipt()
    pr = receipt["pull_request"]

    assert pr["number"] == 47
    assert pr["state"] == "MERGED"
    assert _SHA256_RE.fullmatch(pr["base_ref_oid"])
    assert _SHA256_RE.fullmatch(pr["head_ref_oid"])
    assert _SHA256_RE.fullmatch(pr["merge_commit"])
    assert receipt["candidate_checks"]["status"] == "PASS"
    assert receipt["main_post_merge_workflows"]["status"] == "PASS"


def test_s27_merge_receipt_is_authority_negative() -> None:
    receipt = _receipt()

    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
    assert receipt["live_actions"] == 0
    assert receipt["protected_actions"]["performed"] == []
