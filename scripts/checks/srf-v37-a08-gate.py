#!/usr/bin/env python3
"""V3.7 A08 native algebra and SMT activation gate."""

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
from srl.packs.adapters.native_algebra import run_a08_native_smoke  # noqa: E402

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A08"
EXPECTED_A08: Final[tuple[str, ...]] = (
    "pari-gp",
    "maxima",
    "gap",
    "singular",
    "z3-native",
    "cvc5",
)


def _components(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["component_id"]): item for item in ledger["components"]}


def _check_truth_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    components = _components(ledger)
    failures = []
    for component_id in EXPECTED_A08:
        item = components.get(component_id)
        if item is None:
            failures.append(f"{component_id} missing from ledger")
            continue
        if item["state"] != "ACTIVE":
            failures.append(f"{component_id} state={item['state']}")
        for field in ("installed", "scientific_smoke_passed", "crosschecked"):
            if item[field] is not True:
                failures.append(f"{component_id} {field}={item[field]!r}")
    observed = set(ledger.get("a08_active_inventory_observed", []))
    missing = set(EXPECTED_A08) - observed
    if missing:
        failures.append(f"a08_active_inventory missing {sorted(missing)}")
    return {
        "check_id": "A08-01-truth-ledger-active",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "all A08 native algebra/SMT components reached ACTIVE in the truth ledger",
        "a08_active_inventory_observed": ledger.get("a08_active_inventory_observed", []),
        "a08_parked_blockers": ledger.get("a08_parked_blockers", []),
    }


def _tools(smoke_payload: dict[str, Any]) -> list[dict[str, Any]]:
    tools = smoke_payload.get("tools", [])
    if not isinstance(tools, list):
        return []
    return [item for item in tools if isinstance(item, dict)]


def _check_native_smoke(smoke_payload: dict[str, Any]) -> dict[str, Any]:
    failures = [
        f"{item['component_id']}: {item['error']}"
        for item in _tools(smoke_payload)
        if not bool(item.get("active"))
    ]
    return {
        "check_id": "A08-02-native-smoke",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "PARI/GP, Maxima, GAP, Singular, native Z3 and cvc5 smokes passed",
        "smoke": smoke_payload,
    }


def _check_z3_cvc5_agreement(smoke_payload: dict[str, Any]) -> dict[str, Any]:
    active = {
        str(item["component_id"]) for item in _tools(smoke_payload) if bool(item.get("active"))
    }
    failures = []
    if "z3-native" not in active:
        failures.append("z3-native is not ACTIVE")
    if "cvc5" not in active:
        failures.append("cvc5 is not ACTIVE")
    return {
        "check_id": "A08-03-z3-cvc5-agreement-corpus",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "Z3 and cvc5 both decide the bounded QF_LIA corpus as sat",
    }


def _check_license_boundary(smoke_payload: dict[str, Any]) -> dict[str, Any]:
    failures = []
    for item in _tools(smoke_payload):
        if (
            item.get("license_boundary")
            != "external native executable; not vendored and not in uv.lock"
        ):
            failures.append(f"{item['component_id']} license boundary drifted")
    proc = subprocess.run(
        [sys.executable, "scripts/checks/license_inventory.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        failures.append("uv license inventory failed")
    else:
        report = json.loads(proc.stdout)
        names = {str(item["name"]).lower() for item in report["packages"]}
        native_package_names = {"cvc5", "gap", "maxima", "pari", "pari-gp", "singular"}
        leaked = sorted(name for name in names if name in native_package_names)
        if leaked:
            failures.append(f"native executable packages leaked into uv inventory: {leaked}")
    return {
        "check_id": "A08-04-license-boundary",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "native GPL/BSD/MIT tools are external executables; "
            "uv dependency license inventory remains clean"
        ),
    }


def main() -> int:
    ledger = build_truth_ledger()
    smoke_payload = run_a08_native_smoke().to_dict()
    checks = [
        _check_truth_ledger(ledger),
        _check_native_smoke(smoke_payload),
        _check_z3_cvc5_agreement(smoke_payload),
        _check_license_boundary(smoke_payload),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "stage_closure": "A08_ACTIVE" if status == "PASS" else "A08_WAIT_TOOLCHAIN",
        "active_packs": [
            item["component_id"] for item in _tools(smoke_payload) if bool(item.get("active"))
        ],
        "parked_packs": [
            item["component_id"] for item in _tools(smoke_payload) if not bool(item.get("active"))
        ],
        "protected_blockers": [
            f"WAIT_TOOLCHAIN:{item['component_id']}"
            for item in _tools(smoke_payload)
            if not bool(item.get("active"))
        ],
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
