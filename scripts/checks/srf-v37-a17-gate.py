#!/usr/bin/env python3
"""V3.7 A17 solo-agent entry activation gate."""

from __future__ import annotations

import json
import sys
import tempfile
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts.ids import object_id  # noqa: E402
from srl.solo_agent import acceptance_receipt  # noqa: E402

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A17"


def _build_stage_receipt() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="srl-a17-solo-") as tmp:
        solo_receipt = acceptance_receipt(Path(tmp) / "session")
    checks = list(solo_receipt["checks"])
    failures = [check for check in checks if check["status"] != "PASS"]
    result = "FAIL" if failures else "PASS"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": result,
        "stage_closure": "A17_ACTIVE" if result == "PASS" else "A17_OPEN",
        "solo_acceptance_receipt_id": solo_receipt["receipt_id"],
        "session_id": solo_receipt["session_id"],
        "result_id": solo_receipt["result_id"],
        "export_packet_id": solo_receipt["export_packet_id"],
        "commands": [
            "srlab labctl enter",
            "srlab labctl doctor",
            "srlab labctl submit <session-dir>",
            "srlab labctl status <session-dir>",
            "srlab labctl result <session-dir>",
            "srlab labctl export <session-dir>",
            "srlab labctl replay <session-dir>",
            "srlab labctl portal <session-dir>",
        ],
        "acceptance": solo_receipt,
        "remaining_internal_waits": [],
        "remaining_external_waits": [],
        "checks": checks,
        "live_actions": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="optional path for the generated A17 receipt")
    args = parser.parse_args()
    receipt = _build_stage_receipt()
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
