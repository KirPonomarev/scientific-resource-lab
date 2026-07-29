#!/usr/bin/env python3
"""V3.7 A01 truth-ledger and release-closure gate."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
FIXTURES = REPO_ROOT / "fixtures" / "conformance" / "a01-truth-ledger"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.capabilities.truth import (  # noqa: E402
    CURRENT_V101_ACTIVE_INVENTORY,
    TRUTH_STATES,
    build_truth_ledger,
    evaluate_release_candidate,
)
from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A01"


def _check_inventory(ledger: dict[str, Any]) -> dict[str, Any]:
    expected = list(CURRENT_V101_ACTIVE_INVENTORY)
    observed = ledger["current_v101_active_inventory_observed"]
    if observed != expected:
        return {
            "check_id": "A01-01-current-v101-inventory",
            "status": "FAIL",
            "detail": f"observed {observed!r}, expected {expected!r}",
        }
    return {
        "check_id": "A01-01-current-v101-inventory",
        "status": "PASS",
        "detail": "v1.0.1 active inventory reproduced exactly",
    }


def _check_state_chain(ledger: dict[str, Any]) -> dict[str, Any]:
    if ledger["truth_states"] != list(TRUTH_STATES):
        return {
            "check_id": "A01-02-state-chain",
            "status": "FAIL",
            "detail": "truth state chain drifted",
        }
    for item in ledger["components"]:
        if item["state"] == "ACTIVE":
            missing = [
                name
                for name in ("installed", "scientific_smoke_passed", "crosschecked")
                if item[name] is not True
            ]
            if missing:
                return {
                    "check_id": "A01-02-state-chain",
                    "status": "FAIL",
                    "detail": f"{item['component_id']} ACTIVE with missing {missing}",
                }
    return {
        "check_id": "A01-02-state-chain",
        "status": "PASS",
        "detail": "ACTIVE requires installed, scientific smoke and crosscheck evidence",
    }


def _candidate_from_fixture(path: Path, live_ledger: dict[str, Any]) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path} must be a JSON object")
    candidate = copy.deepcopy(doc["candidate"])
    candidate["ledger"] = copy.deepcopy(live_ledger)
    for override in doc.get("component_overrides", []):
        component_id = override["component_id"]
        for item in candidate["ledger"]["components"]:
            if item["component_id"] == component_id:
                item.update(override["patch"])
                break
        else:
            raise ValueError(f"{path}: no ledger component {component_id!r}")
    return candidate


def _check_negative_fixtures(ledger: dict[str, Any]) -> dict[str, Any]:
    results = []
    for path in sorted(FIXTURES.glob("*.json")):
        candidate = _candidate_from_fixture(path, ledger)
        decision = evaluate_release_candidate(candidate)
        expect = json.loads(path.read_text(encoding="utf-8"))["expected_verdict"]
        status = "PASS" if decision["verdict"] == expect else "FAIL"
        results.append(
            {
                "fixture": path.name,
                "status": status,
                "expected": expect,
                "actual": decision["verdict"],
                "blockers": decision["blockers"],
            }
        )
    if not results or any(item["status"] != "PASS" for item in results):
        return {
            "check_id": "A01-03-negative-fixtures",
            "status": "FAIL",
            "detail": "one or more false-closure fixtures were not rejected",
            "results": results,
        }
    return {
        "check_id": "A01-03-negative-fixtures",
        "status": "PASS",
        "detail": f"{len(results)} false-closure fixtures rejected",
        "results": results,
    }


def _check_current_release_gate(ledger: dict[str, Any]) -> dict[str, Any]:
    candidate = {
        "target_release": "v2.0.0",
        "target_result": "DONE",
        "production_signer": "missing",
        "sandbox": "policy_only",
        "t7_binding": "WAIT_T7_BINDING",
        "ledger": ledger,
    }
    decision = evaluate_release_candidate(candidate)
    blockers = set(decision["blockers"])
    required = {
        "PRODUCTION_SIGNER_NOT_ED25519_NATIVE",
        "SANDBOX_NOT_ENFORCED_T2_T3",
        "T7_NOT_ACTIVE",
    }
    has_missing_mandatory = any(item.startswith("MANDATORY_NOT_ACTIVE:") for item in blockers)
    if decision["verdict"] != "REJECT" or not required <= blockers or not has_missing_mandatory:
        return {
            "check_id": "A01-04-release-gate",
            "status": "FAIL",
            "detail": "current incomplete V3.7 state did not reject DONE/v2.0.0",
            "decision": decision,
        }
    return {
        "check_id": "A01-04-release-gate",
        "status": "PASS",
        "detail": "DONE/v2.0.0 rejects missing signer, sandbox, T7 and mandatory toolchains",
        "blocker_count": len(decision["blockers"]),
    }


def _check_docs_agree() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "scripts/docs/generate_capability_truth_ledger.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "check_id": "A01-05-docs-agree",
            "status": "FAIL",
            "detail": proc.stdout or proc.stderr,
            "exit_code": proc.returncode,
        }
    return {
        "check_id": "A01-05-docs-agree",
        "status": "PASS",
        "detail": "generated docs agree with machine ledger",
        "exit_code": proc.returncode,
    }


def main() -> int:
    ledger = build_truth_ledger()
    checks = [
        _check_inventory(ledger),
        _check_state_chain(ledger),
        _check_negative_fixtures(ledger),
        _check_current_release_gate(ledger),
        _check_docs_agree(),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "ledger_schema_version": ledger["schema_version"],
        "current_v101_active_inventory_observed": ledger["current_v101_active_inventory_observed"],
        "capability_closure_chain": ledger["capability_closure_chain"],
        "production_versus_fixture_axis": ledger["production_versus_fixture_axis"],
        "checks": checks,
        "canonical_writes": 0,
        "grants_authority": False,
        "live_actions": 0,
    }
    receipt["receipt_id"] = object_id(
        {key: value for key, value in receipt.items() if key != "receipt_id"}
    )
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
