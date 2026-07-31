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
FLINT_LICENSE_RECEIPT: Final[Path] = (
    REPO_ROOT / "docs" / "verification" / "srf-v3-7-a07-python-flint-license-closure-receipt.json"
)


def _check_p0_components_active(ledger: dict[str, Any]) -> dict[str, Any]:
    components = {item["component_id"]: item for item in ledger["components"]}
    failures = []
    for component_id in ("sympy", "mpmath", "python-flint"):
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
        "check_id": "A07-01-p0-python-core-active",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "SymPy, mpmath and python-flint reached ACTIVE through import, smoke and crosscheck",
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
    if smoke["flint_status"] != "ACTIVE":
        failures.append(f"python-flint status={smoke['flint_status']!r}")
    if smoke["flint_integer_partition"] != "627":
        failures.append("unexpected python-flint partition value")
    if smoke["flint_rational_identity"] != "1/2":
        failures.append("unexpected python-flint rational identity")
    if smoke["flint_matrix_entry"] != "89":
        failures.append("unexpected python-flint matrix entry")
    return {
        "check_id": "A07-02-scientific-smoke",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "exact factorization, high-precision eval, interval enclosure, units and "
            "python-flint exact arithmetic checks passed"
        ),
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
    failures = []
    if not {"symbolic.sympy", "numeric.mpmath"} <= active:
        failures.append(f"missing active P0 ids: {active}")
    if "exact.flint" not in active:
        failures.append("exact.flint is not active after license closure")
    components = _component_map(bundle["components"])
    flint = components["exact.flint"]
    if flint.get("license_spdx") != ["MIT AND LGPL-3.0-or-later"]:
        failures.append(f"flint license marker drifted: {flint.get('license_spdx')}")
    return {
        "check_id": "A07-03-p0-bundle",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "P0 admission bundle activates SymPy/mpmath and exact.flint under A07 closure",
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
    by_name = {str(item["name"]).lower(): item for item in report["packages"]}
    flint = by_name.get("python-flint")
    if flint is None:
        failures.append("python-flint absent from default dependency closure after A07 closure")
    elif flint.get("policy_exception") != "A07_PYTHON_FLINT_LGPL_CLOSURE_ADR_0010":
        failures.append(f"python-flint policy exception drifted: {flint.get('policy_exception')}")
    return {
        "check_id": "A07-04-license-inventory-clean",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "default dependency license inventory admits FLINT only through the A07 exception",
        "exit_code": proc.returncode,
    }


def _check_flint_license_blocker() -> dict[str, Any]:
    payload = json.loads(FLINT_LICENSE_RECEIPT.read_text(encoding="utf-8"))
    expression = str(payload.get("observed_license_expression") or "")
    active = (
        payload.get("status") == "ACTIVE"
        and payload.get("observed_version") == "0.9.0"
        and expression == "MIT AND LGPL-3.0-or-later"
        and payload.get("obligations_accepted") is True
        and payload.get("default_lgpl_policy_broadened") is False
    )
    return {
        "check_id": "A07-05-flint-license-closure",
        "status": "PASS" if active else "FAIL",
        "detail": FLINT_WAIT_REASON if active else f"invalid python-flint closure {payload}",
        "evidence_path": str(FLINT_LICENSE_RECEIPT.relative_to(REPO_ROOT)),
        "operator_action_path": str(FLINT_OPERATOR_ACTION.relative_to(REPO_ROOT)),
        "observed_version": payload.get("observed_version"),
        "license_expression": expression,
    }


def main() -> int:
    ledger = build_truth_ledger()
    checks = [
        _check_p0_components_active(ledger),
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
        "stage_closure": "A07_ACTIVE_FLINT_LICENSE_CLOSED",
        "active_packs": ["sympy", "mpmath", "python-flint"],
        "parked_packs": [],
        "protected_blockers": [],
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
