#!/usr/bin/env python3
"""V3.7 A12 discovery and dynamics activation gate."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts.ids import object_id  # noqa: E402
from srl.products.discovery_dynamics import (  # noqa: E402
    A12_DISCOVERY_RECEIPT_SCHEMA_VERSION,
    DiscoveryDynamicsError,
    run_a12_discovery_dynamics_smoke,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A12"
EXPECTED_A12: Final[tuple[str, ...]] = ("pysr", "pysindy", "pydmd")
EXPECTED_REPLACED: Final[tuple[str, ...]] = (
    "sr4mdl",
    "operon",
    "gplearn",
    "ai_feynman",
    "pykoopman",
    "dysts",
)


def _default_julia_depot() -> tuple[str | None, str]:
    if "JULIA_DEPOT_PATH" in os.environ:
        return os.environ["JULIA_DEPOT_PATH"], "explicit_env"
    if os.environ.get("CI") == "true":
        return str(REPO_ROOT / ".cache" / "srl-a12-julia-depot"), "ci_exact_cache"
    return None, "default_or_runtime_env"


def _check_activation_receipt() -> dict[str, Any]:
    julia_depot, depot_role = _default_julia_depot()
    try:
        receipt = run_a12_discovery_dynamics_smoke(julia_depot_path=julia_depot)
    except DiscoveryDynamicsError as exc:
        return {
            "check_id": "A12-01-real-discovery-dynamics-smoke",
            "status": "FAIL",
            "detail": str(exc),
            "julia_depot_role": depot_role,
            "activation_receipt": None,
        }
    failures = _activation_receipt_failures(receipt)
    return {
        "check_id": "A12-01-real-discovery-dynamics-smoke",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "PySR, PySINDy and PyDMD executed real bounded discovery/dynamics tasks",
        "julia_depot_role": depot_role,
        "activation_receipt": receipt,
    }


def _activation_receipt_failures(receipt: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if receipt.get("schema_version") != A12_DISCOVERY_RECEIPT_SCHEMA_VERSION:
        failures.append("activation receipt schema mismatch")
    if receipt.get("active_pack_ids") != list(EXPECTED_A12):
        failures.append("active pack ids mismatch")
    if receipt.get("formally_replaced_pack_ids") != list(EXPECTED_REPLACED):
        failures.append("replacement ids mismatch")
    if receipt.get("promotion_allowed") is not False:
        failures.append("A12 receipt allowed promotion")
    failures.extend(_pack_receipt_failures(receipt.get("pack_receipts")))
    public = receipt.get("public_benchmark_receipt")
    if not isinstance(public, dict) or public.get("observed_above_null") is not True:
        failures.append("public benchmark receipt missing or inconclusive")
    return failures


def _pack_receipt_failures(raw_pack_receipts: object) -> list[str]:
    failures: list[str] = []
    pack_receipts = raw_pack_receipts
    if not isinstance(pack_receipts, list) or len(pack_receipts) != len(EXPECTED_A12):
        failures.append("pack receipt count mismatch")
        return failures
    by_id = {item.get("pack_id"): item for item in pack_receipts if isinstance(item, dict)}
    if tuple(by_id) != EXPECTED_A12:
        failures.append("pack receipt order mismatch")
    for pack_id in EXPECTED_A12:
        item = by_id.get(pack_id)
        if not isinstance(item, dict):
            failures.append(f"{pack_id} receipt missing")
            continue
        failures.extend(_single_pack_receipt_failures(pack_id, item))
    return failures


def _single_pack_receipt_failures(pack_id: str, item: dict[str, Any]) -> list[str]:
    failures = []
    if item.get("status") != "ACTIVE":
        failures.append(f"{pack_id} not ACTIVE")
    if item.get("observed_above_null") is not True:
        failures.append(f"{pack_id} did not beat null")
    if item.get("promotion_allowed") is not False:
        failures.append(f"{pack_id} allowed promotion")
    envelope = item.get("resource_envelope")
    if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
        failures.append(f"{pack_id} missing bounded resource envelope")
    return failures


def _check_no_promotion(check: dict[str, Any]) -> dict[str, Any]:
    receipt = check.get("activation_receipt")
    failures = []
    if not isinstance(receipt, dict):
        failures.append("activation receipt missing")
    else:
        if receipt.get("canonical_writes") != 0 or receipt.get("grants_authority") is not False:
            failures.append("A12 receipt is not authority-negative")
        if receipt.get("automatic_scientific_promotion") is not False:
            failures.append("A12 allowed automatic scientific promotion")
        for item in receipt.get("pack_receipts", []):
            if not isinstance(item, dict):
                continue
            if item.get("automatic_scientific_promotion") is not False:
                failures.append(f"{item.get('pack_id')} allowed automatic promotion")
            if item.get("canonical_writes") != 0 or item.get("grants_authority") is not False:
                failures.append(f"{item.get('pack_id')} is not authority-negative")
    return {
        "check_id": "A12-02-no-automatic-scientific-promotion",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "candidate laws remain candidate-only and authority-negative",
    }


def _build_stage_receipt() -> dict[str, Any]:
    activation = _check_activation_receipt()
    promotion = _check_no_promotion(activation)
    checks = [activation, promotion]
    failures = [check for check in checks if check["status"] != "PASS"]
    result = "FAIL" if failures else "PASS"
    active_packs = list(EXPECTED_A12) if result == "PASS" else []
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": result,
        "stage_closure": "A12_ACTIVE" if result == "PASS" else "A12_OPEN",
        "active_packs": active_packs,
        "parked_packs": [],
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
    receipt = _build_stage_receipt()
    sys.stdout.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
