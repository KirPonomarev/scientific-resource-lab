from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RECEIPT_PATH = Path("docs/verification/system-acceptance-receipt.json")

_PLAN_HASH = "947d1858c8cf110f3c6bdb07c70a8ff132459f9e7b6448d1afbf84d4270c1ff0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$|^[0-9a-f]{8}(-[0-9a-f]{8}){7}$")
_REQUIRED_COMMANDS = {
    "exact_hash_review",
    "lint",
    "typecheck",
    "full_pytest",
    "corpus",
    "router_determinism",
    "repro_check",
    "public_boundary",
    "secret_scan",
    "gate_wp03",
    "gate_wp10",
    "gate_wp11",
    "gate_wp12",
    "gate_wp13",
    "gate_wp14",
    "gate_wp20",
    "gate_wp21",
    "gate_wp22",
    "gate_wp23",
    "gate_wp24",
    "gate_wp30",
    "gate_wp31",
    "gate_wp32",
    "gate_wp33",
    "gate_wp34",
    "gate_wp40",
    "gate_wp41",
    "gate_wp42",
    "gate_wp43",
    "gate_wp44",
    "gate_wp45",
    "gate_wp50",
    "gate_wp51",
    "gate_wp52",
    "gate_wp60",
    "gate_wp70",
    "gate_wp71a",
    "gate_wp71b",
    "gate_wp72",
    "gate_wp73",
    "gate_wp80",
}
_REQUIRED_CHAOS = {
    "crash",
    "duplicate",
    "revoke",
    "corrupt",
    "stale",
    "injection",
    "low_disk",
}


def _receipt() -> dict[str, Any]:
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def _normalize_digest(value: str) -> str:
    return value.replace("-", "")


def test_system_acceptance_receipt_identity_and_authority_negative() -> None:
    receipt = _receipt()

    assert receipt["schema_version"] == "SystemAcceptanceReceipt/v1"
    assert receipt["stage_id"] == "S25"
    assert receipt["result"] == "PASS_WITH_DECLARED_WAITS"
    assert _normalize_digest(receipt["plan_hash"]) == _PLAN_HASH
    assert _SHA256_RE.fullmatch(receipt["receipt_id"])
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
    assert receipt["live_actions"] == 0
    assert receipt["protected_actions"]["performed"] == []


def test_validation_matrix_covers_every_required_layer() -> None:
    receipt = _receipt()
    commands = {item["command_id"]: item for item in receipt["validation_matrix"]}

    assert _REQUIRED_COMMANDS <= set(commands)
    for command_id in _REQUIRED_COMMANDS:
        item = commands[command_id]
        assert item["status"] == "PASS", command_id
        assert item["exit_code"] == 0, command_id
        assert item["command"], command_id


def test_focused_chaos_receipts_are_executable_and_green() -> None:
    receipt = _receipt()
    chaos = receipt["chaos_receipts"]

    assert _REQUIRED_CHAOS == set(chaos)
    for chaos_id, item in chaos.items():
        assert item["status"] == "PASS", chaos_id
        assert item["evidence_command"], chaos_id
        for path in item["evidence_paths"]:
            assert Path(path).exists(), f"{chaos_id}: missing evidence path {path}"


def test_declared_waits_are_machine_visible_not_hidden_failures() -> None:
    receipt = _receipt()
    waits = set(receipt["declared_wait_states"])

    assert "WAIT_T7_BINDING" in waits
    assert "WAIT_COMPUTE_NODE" in waits
    assert "WAIT_RUNTIME_HEALTH:MARKET_RED_F8" in waits
    assert "WAIT_SECURITY_HEALTH:BOOTSTRAP_UNAVAILABLE" in waits
    assert receipt["limitations_machine_visible"] is True


def test_receipt_paths_are_public_repository_paths() -> None:
    receipt = _receipt()
    private_markers = ("/Users/", "/Volumes/", "PRIVATE_PATH_MARKER")

    for section in ("evidence_paths", "manifest_paths"):
        for value in receipt[section]:
            assert not any(marker in value for marker in private_markers), value
            assert Path(value).exists(), value
