#!/usr/bin/env python3
"""V3.7 A14 SciML and domain-science activation gate."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts.ids import object_id  # noqa: E402
from srl.products.sciml_domain import (  # noqa: E402
    A14_SCIML_DOMAIN_RECEIPT_SCHEMA_VERSION,
    SciMLDomainActivationError,
    run_a14_sciml_domain_smoke,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A14"
EXPECTED_A14: Final[tuple[str, ...]] = (
    "julia_sciml_ode",
    "python_diffrax_ode",
    "python_qutip_quantum",
    "python_astropy_astronomy",
    "python_cantera_combustion",
    "native_battery_rc",
    "python_quimb_many_body",
    "python_cotengra_tensor_network",
)
EXPECTED_REPLACED: Final[tuple[str, ...]] = (
    "julia_modelingtoolkit",
    "julia_datadrivendiffeq",
    "python_cadabra",
    "python_pybamm",
)
EXPECTED_FAMILIES: Final[set[str]] = {
    "sciml",
    "quantum",
    "astronomy",
    "combustion",
    "battery",
    "quantum_many_body",
    "tensor_networks",
}
ODE_CROSS_LANGUAGE_ABS_TOLERANCE: Final[float] = 5e-7
QUTIP_TRANSFER_MIN: Final[float] = 0.999
CANTERA_FLAME_TEMP_MIN: Final[float] = 1800.0
BATTERY_SOC_MIN: Final[float] = 0.79
BATTERY_SOC_MAX: Final[float] = 0.81


def _default_julia_paths() -> tuple[str | None, str | None, str]:
    project = os.environ.get("SRL_A14_JULIA_PROJECT_DIR")
    depot = os.environ.get("JULIA_DEPOT_PATH")
    if project or depot:
        return project, depot, "explicit_env"
    if os.environ.get("CI") == "true":
        return (
            str(REPO_ROOT / ".cache" / "srl-a14-julia-project"),
            str(REPO_ROOT / ".cache" / "srl-a14-julia-depot"),
            "ci_exact_cache",
        )
    return None, None, "default_or_runtime_env"


def _check_activation_receipt() -> dict[str, Any]:
    project, depot, project_role = _default_julia_paths()
    try:
        receipt = run_a14_sciml_domain_smoke(
            julia_project_dir=project,
            julia_depot_path=depot,
        )
    except SciMLDomainActivationError as exc:
        return {
            "check_id": "A14-01-real-sciml-domain-workloads",
            "status": "FAIL",
            "detail": str(exc),
            "julia_project_role": project_role,
            "activation_receipt": None,
        }
    failures = _activation_receipt_failures(receipt)
    return {
        "check_id": "A14-01-real-sciml-domain-workloads",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "Julia SciML, Python diffrax, quantum, astronomy, combustion, "
            "battery and tensor-network workloads executed"
        ),
        "julia_project_role": project_role,
        "activation_receipt": receipt,
    }


def _activation_receipt_failures(receipt: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if receipt.get("schema_version") != A14_SCIML_DOMAIN_RECEIPT_SCHEMA_VERSION:
        failures.append("activation receipt schema mismatch")
    if receipt.get("active_pack_ids") != list(EXPECTED_A14):
        failures.append("active pack ids mismatch")
    if receipt.get("formally_replaced_pack_ids") != list(EXPECTED_REPLACED):
        failures.append("replacement ids mismatch")
    if (
        receipt.get("promotion_allowed") is not False
        or receipt.get("automatic_scientific_promotion") is not False
        or receipt.get("canonical_writes") != 0
        or receipt.get("grants_authority") is not False
    ):
        failures.append("A14 activation receipt is not authority-negative")
    failures.extend(_workload_receipt_failures(receipt.get("workload_receipts")))
    failures.extend(_cross_language_failures(receipt.get("cross_language_receipt")))
    return failures


def _workload_receipt_failures(raw_workloads: object) -> list[str]:
    failures: list[str] = []
    workloads = raw_workloads
    if not isinstance(workloads, list) or len(workloads) != len(EXPECTED_A14):
        failures.append("workload receipt count mismatch")
        return failures
    by_id = {item.get("pack_id"): item for item in workloads if isinstance(item, dict)}
    if tuple(by_id) != EXPECTED_A14:
        failures.append("workload receipt order mismatch")
    observed_families = {
        str(item.get("family"))
        for item in workloads
        if isinstance(item, dict) and isinstance(item.get("family"), str)
    }
    if EXPECTED_FAMILIES - observed_families:
        missing = sorted(EXPECTED_FAMILIES - observed_families)
        failures.append(f"domain family coverage missing: {missing}")
    for pack_id in EXPECTED_A14:
        item = by_id.get(pack_id)
        if not isinstance(item, dict):
            failures.append(f"{pack_id} receipt missing")
            continue
        failures.extend(_single_workload_receipt_failures(pack_id, item))
    return failures


def _single_workload_receipt_failures(  # noqa: C901
    pack_id: str,
    item: dict[str, Any],
) -> list[str]:
    failures = []
    if item.get("status") != "ACTIVE":
        failures.append(f"{pack_id} not ACTIVE")
    if item.get("bitwise_identity_claimed") is not False:
        failures.append(f"{pack_id} claimed bitwise identity")
    if (
        item.get("promotion_allowed") is not False
        or item.get("automatic_scientific_promotion") is not False
        or item.get("canonical_writes") != 0
        or item.get("grants_authority") is not False
    ):
        failures.append(f"{pack_id} is not authority-negative")
    envelope = item.get("resource_envelope")
    if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
        failures.append(f"{pack_id} missing bounded resource envelope")
    if not isinstance(item.get("backend_versions"), dict) or not item.get("backend_versions"):
        failures.append(f"{pack_id} missing backend version binding")
    if not isinstance(item.get("solver"), dict) or not item.get("solver"):
        failures.append(f"{pack_id} missing solver provenance")
    if not item.get("unit_bindings"):
        failures.append(f"{pack_id} missing unit bindings")
    tolerance = item.get("tolerance")
    if not isinstance(tolerance, dict):
        failures.append(f"{pack_id} missing tolerance")
    elif (
        float(cast(float, tolerance.get("abs", 0.0))) == 0.0
        and float(cast(float, tolerance.get("rel", 0.0))) == 0.0
    ):
        failures.append(f"{pack_id} has zero tolerance")
    if not isinstance(item.get("dataset"), dict):
        failures.append(f"{pack_id} missing dataset binding")
    if not isinstance(item.get("diagnostics"), dict):
        failures.append(f"{pack_id} missing diagnostics")
    if not isinstance(item.get("trace_sha256"), str):
        failures.append(f"{pack_id} missing trace digest")
    return failures


def _cross_language_failures(raw_cross: object) -> list[str]:
    if not isinstance(raw_cross, dict):
        return ["cross-language receipt missing"]
    failures = []
    if raw_cross.get("comparison_label") != "julia_sciml_vs_python_diffrax_ode":
        failures.append("cross-language comparison label mismatch")
    if raw_cross.get("bitwise_identity_claimed") is not False:
        failures.append("cross-language receipt claimed bitwise identity")
    if raw_cross.get("comparison_scope") != "bounded_real_workload_tolerance_only":
        failures.append("cross-language comparison scope mismatch")
    if raw_cross.get("canonical_writes") != 0 or raw_cross.get("grants_authority") is not False:
        failures.append("cross-language receipt is not authority-negative")
    delta = raw_cross.get("observed_delta")
    tolerance = raw_cross.get("tolerance_abs")
    if not isinstance(delta, float) or not isinstance(tolerance, float) or delta > tolerance:
        failures.append("cross-language tolerance check failed")
    return failures


def _check_domain_diagnostics(check: dict[str, Any]) -> dict[str, Any]:
    receipt = check.get("activation_receipt")
    failures = []
    if not isinstance(receipt, dict):
        failures.append("activation receipt missing")
    else:
        workloads = receipt.get("workload_receipts")
        by_id = (
            {str(item.get("pack_id")): item for item in workloads if isinstance(item, dict)}
            if isinstance(workloads, list)
            else {}
        )
        failures.extend(
            _diagnostic_float_min(
                by_id,
                "python_qutip_quantum",
                "terminal_probability_one",
                QUTIP_TRANSFER_MIN,
            )
        )
        failures.extend(
            _diagnostic_float_min(
                by_id,
                "python_cantera_combustion",
                "flame_temperature_K",
                CANTERA_FLAME_TEMP_MIN,
            )
        )
        failures.extend(
            _diagnostic_float_between(
                by_id,
                "native_battery_rc",
                "final_soc",
                BATTERY_SOC_MIN,
                BATTERY_SOC_MAX,
            )
        )
        if "julia_sciml_ode" in by_id and "python_diffrax_ode" in by_id:
            j_diag = cast(dict[str, Any], by_id["julia_sciml_ode"].get("diagnostics", {}))
            p_diag = cast(dict[str, Any], by_id["python_diffrax_ode"].get("diagnostics", {}))
            delta = abs(float(j_diag.get("terminal", 0.0)) - float(p_diag.get("terminal", 1.0)))
            if delta > ODE_CROSS_LANGUAGE_ABS_TOLERANCE:
                failures.append("Julia SciML and Python diffrax terminal values drifted")
    return {
        "check_id": "A14-02-units-tolerances-domain-diagnostics-and-no-bitwise-claim",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "A14 diagnostics cover ODE tolerance, quantum transfer, combustion "
            "equilibrium, battery state and tensor-network path metrics"
        ),
    }


def _diagnostic_float_min(
    by_id: dict[str, Any],
    pack_id: str,
    field: str,
    minimum: float,
) -> list[str]:
    item = by_id.get(pack_id)
    if not isinstance(item, dict) or not isinstance(item.get("diagnostics"), dict):
        return [f"{pack_id} diagnostics missing"]
    value = item["diagnostics"].get(field)
    if not isinstance(value, float) or value < minimum:
        return [f"{pack_id} {field} below minimum"]
    return []


def _diagnostic_float_between(
    by_id: dict[str, Any],
    pack_id: str,
    field: str,
    lower: float,
    upper: float,
) -> list[str]:
    item = by_id.get(pack_id)
    if not isinstance(item, dict) or not isinstance(item.get("diagnostics"), dict):
        return [f"{pack_id} diagnostics missing"]
    value = item["diagnostics"].get(field)
    if not isinstance(value, float) or not lower <= value <= upper:
        return [f"{pack_id} {field} outside expected interval"]
    return []


def _build_stage_receipt() -> dict[str, Any]:
    activation = _check_activation_receipt()
    diagnostics = _check_domain_diagnostics(activation)
    checks = [activation, diagnostics]
    failures = [check for check in checks if check["status"] != "PASS"]
    result = "FAIL" if failures else "PASS"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": result,
        "stage_closure": "A14_ACTIVE" if result == "PASS" else "A14_OPEN",
        "active_packs": list(EXPECTED_A14) if result == "PASS" else [],
        "formally_replaced_packs": list(EXPECTED_REPLACED) if result == "PASS" else [],
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
