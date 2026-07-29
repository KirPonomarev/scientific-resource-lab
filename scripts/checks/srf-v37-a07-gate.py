#!/usr/bin/env python3
"""V3.7 A07 P0 Python core activation gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.capabilities.truth import build_truth_ledger  # noqa: E402
from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402
from srl.packs.adapters.p0_python_core import (  # noqa: E402
    FLINT_WAIT_REASON,
    run_p0_python_core_smoke,
)
from srl.packs.p0 import build_p0_admission_bundle  # noqa: E402

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A07"
FLINT_OPERATOR_ACTION: Final[Path] = (
    REPO_ROOT / "docs" / "target-binding" / "a07-python-flint-license-operator-action.json"
)


def _check_sympy_mpmath_active(ledger: dict[str, Any]) -> dict[str, Any]:
    components = {item["component_id"]: item for item in ledger["components"]}
    failures = []
    for component_id in ("sympy", "mpmath"):
        item = components.get(component_id)
        if item is None:
            failures.append(f"{component_id} missing from ledger")
            continue
        if item["state"] != "ACTIVE":
            failures.append(f"{component_id} state={item['state']}")
        for field in ("installed", "scientific_smoke_passed", "crosschecked"):
            if item[field] is not True:
                failures.append(f"{component_id} {field}={item[field]!r}")
    return {
        "check_id": "A07-01-sympy-mpmath-active",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "SymPy and mpmath reached ACTIVE through import, smoke and crosscheck",
    }


def _check_scientific_smoke() -> dict[str, Any]:
    smoke = run_p0_python_core_smoke().to_dict()
    failures = []
    if smoke["exact_factorization"] != "(x - 1)*(x + 1)*(x**2 + 1)":
        failures.append("unexpected SymPy factorization")
    if not str(smoke["high_precision_value"]).startswith("1.414213562373095048801688724209698"):
        failures.append("unexpected mpmath high-precision value")
    interval = smoke["interval_enclosure"]
    if not isinstance(interval, dict) or not (
        interval["lower"] <= smoke["high_precision_value"] <= interval["upper"]
    ):
        failures.append("interval enclosure does not contain high precision value")
    if smoke["dimensional_consistency"] != "parse_unit('kg*m/s^2') == parse_unit('N')":
        failures.append("dimensional consistency smoke failed")
    return {
        "check_id": "A07-02-scientific-smoke",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "exact factorization, high-precision eval, interval enclosure and units check passed",
        "smoke": smoke,
    }


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def _component_map(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, list):
        return {}
    components: dict[str, dict[str, object]] = {}
    for item in value:
        if isinstance(item, dict):
            components[str(item.get("component_id"))] = item
    return components


def _check_p0_bundle() -> dict[str, Any]:
    bundle = build_p0_admission_bundle()
    active = _string_set(bundle["active_component_ids"])
    waits = _string_set(bundle["wait_component_ids"])
    failures = []
    if not {"symbolic.sympy", "numeric.mpmath"} <= active:
        failures.append(f"missing active P0 ids: {active}")
    if "exact.flint" not in waits:
        failures.append("exact.flint is not parked as wait")
    components = _component_map(bundle["components"])
    flint = components["exact.flint"]
    if flint.get("license_spdx") != ["WAIT_LICENSE"]:
        failures.append(f"flint license marker drifted: {flint.get('license_spdx')}")
    return {
        "check_id": "A07-03-p0-bundle",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "P0 admission bundle activates SymPy/mpmath and parks FLINT at WAIT_LICENSE",
        "bundle_id": bundle["bundle_id"],
    }


def _check_license_inventory() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "scripts/checks/license_inventory.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "check_id": "A07-04-license-inventory-clean",
            "status": "FAIL",
            "detail": proc.stdout or proc.stderr,
            "exit_code": proc.returncode,
        }
    report = json.loads(proc.stdout)
    present = {str(item["name"]).lower() for item in report["packages"]}
    failures = []
    if "sympy" not in present:
        failures.append("sympy absent from license inventory")
    if "mpmath" not in present:
        failures.append("mpmath absent from license inventory")
    if "python-flint" in present:
        failures.append("python-flint leaked into default dependency closure")
    return {
        "check_id": "A07-04-license-inventory-clean",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "default dependency license inventory admits SymPy/mpmath and excludes FLINT",
        "exit_code": proc.returncode,
    }


def _check_flint_license_blocker() -> dict[str, Any]:
    payload = json.loads(FLINT_OPERATOR_ACTION.read_text(encoding="utf-8"))
    expression = str(payload.get("observed_license_expression") or "")
    has_lgpl = "LGPL" in expression.upper()
    return {
        "check_id": "A07-05-flint-wait-license",
        "status": "PASS" if has_lgpl else "FAIL",
        "detail": FLINT_WAIT_REASON
        if has_lgpl
        else f"unexpected python-flint license {expression}",
        "evidence_path": str(FLINT_OPERATOR_ACTION.relative_to(REPO_ROOT)),
        "observed_version": payload.get("observed_version"),
        "license_expression": expression,
    }


def main() -> int:
    ledger = build_truth_ledger()
    checks = [
        _check_sympy_mpmath_active(ledger),
        _check_scientific_smoke(),
        _check_p0_bundle(),
        _check_license_inventory(),
        _check_flint_license_blocker(),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "stage_closure": "A07_PARTIAL_ACTIVE_WAIT_FLINT_LICENSE",
        "active_packs": ["sympy", "mpmath"],
        "parked_packs": ["python-flint"],
        "protected_blockers": ["WAIT_LICENSE:A07_PYTHON_FLINT_LGPL_CLOSURE"],
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
