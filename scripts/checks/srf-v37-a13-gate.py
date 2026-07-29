#!/usr/bin/env python3
"""V3.7 A13 applied science activation gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts.ids import object_id  # noqa: E402
from srl.products.applied import (  # noqa: E402
    A13_APPLIED_RECEIPT_SCHEMA_VERSION,
    AppliedScienceError,
    run_a13_applied_science_smoke,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A13"
EXPECTED_A13: Final[tuple[str, ...]] = (
    "ripser",
    "pyriemann",
    "cvxpy",
    "native_bayesian_conjugate",
    "native_causal_backdoor",
)
EXPECTED_REPLACED: Final[tuple[str, ...]] = (
    "gudhi",
    "geomstats",
    "pot",
    "pymanopt",
    "keplermapper",
    "toponetx",
    "regina",
    "pymc",
    "arviz",
    "dowhy",
    "tigramite",
    "econml",
    "jaxopt",
    "botorch",
)
CAUSAL_TRUE_EFFECT: Final[float] = 2.0
CAUSAL_EFFECT_TOLERANCE: Final[float] = 0.08
CAUSAL_FALSIFICATION_TOLERANCE: Final[float] = 0.25


def _check_activation_receipt() -> dict[str, Any]:
    try:
        receipt = run_a13_applied_science_smoke()
    except AppliedScienceError as exc:
        return {
            "check_id": "A13-01-real-applied-science-workloads",
            "status": "FAIL",
            "detail": str(exc),
            "activation_receipt": None,
        }
    failures = _activation_receipt_failures(receipt)
    return {
        "check_id": "A13-01-real-applied-science-workloads",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "Topology, geometry, optimization, analytic Bayesian and causal "
            "workloads executed with bounded real adapters/checkers"
        ),
        "activation_receipt": receipt,
    }


def _activation_receipt_failures(receipt: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if receipt.get("schema_version") != A13_APPLIED_RECEIPT_SCHEMA_VERSION:
        failures.append("activation receipt schema mismatch")
    if receipt.get("active_pack_ids") != list(EXPECTED_A13):
        failures.append("active pack ids mismatch")
    if receipt.get("formally_replaced_pack_ids") != list(EXPECTED_REPLACED):
        failures.append("replacement ids mismatch")
    if receipt.get("promotion_allowed") is not False:
        failures.append("A13 receipt allowed promotion")
    if (
        receipt.get("automatic_scientific_promotion") is not False
        or receipt.get("canonical_writes") != 0
        or receipt.get("grants_authority") is not False
    ):
        failures.append("A13 receipt is not authority-negative")
    failures.extend(_workload_receipt_failures(receipt.get("workload_receipts")))
    return failures


def _workload_receipt_failures(raw_workloads: object) -> list[str]:
    failures: list[str] = []
    workloads = raw_workloads
    if not isinstance(workloads, list) or len(workloads) != len(EXPECTED_A13):
        failures.append("workload receipt count mismatch")
        return failures
    by_id = {item.get("pack_id"): item for item in workloads if isinstance(item, dict)}
    if tuple(by_id) != EXPECTED_A13:
        failures.append("workload receipt order mismatch")
    for pack_id in EXPECTED_A13:
        item = by_id.get(pack_id)
        if not isinstance(item, dict):
            failures.append(f"{pack_id} receipt missing")
            continue
        failures.extend(_single_workload_receipt_failures(pack_id, item))
    return failures


def _single_workload_receipt_failures(pack_id: str, item: dict[str, Any]) -> list[str]:
    failures = []
    if item.get("status") != "ACTIVE":
        failures.append(f"{pack_id} not ACTIVE")
    if item.get("promotion_allowed") is not False:
        failures.append(f"{pack_id} allowed promotion")
    if (
        item.get("automatic_scientific_promotion") is not False
        or item.get("canonical_writes") != 0
        or item.get("grants_authority") is not False
    ):
        failures.append(f"{pack_id} is not authority-negative")
    envelope = item.get("resource_envelope")
    if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
        failures.append(f"{pack_id} missing bounded resource envelope")
    backend_versions = item.get("backend_versions")
    if not isinstance(backend_versions, dict) or not backend_versions:
        failures.append(f"{pack_id} missing backend version binding")
    dataset = item.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("kind") != "synthetic":
        failures.append(f"{pack_id} missing bounded synthetic dataset binding")
    return failures


def _check_diagnostics_and_no_promotion(check: dict[str, Any]) -> dict[str, Any]:
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
        failures.extend(_topology_failures(cast(dict[str, Any] | None, by_id.get("ripser"))))
        failures.extend(
            _bayesian_failures(cast(dict[str, Any] | None, by_id.get("native_bayesian_conjugate")))
        )
        failures.extend(
            _causal_failures(cast(dict[str, Any] | None, by_id.get("native_causal_backdoor")))
        )
        failures.extend(_optimization_failures(cast(dict[str, Any] | None, by_id.get("cvxpy"))))
    return {
        "check_id": "A13-02-diagnostics-falsification-license-and-no-promotion",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "A13 diagnostics include topology null control, analytic Bayesian no-MCMC "
            "claim, causal identification/falsification and explicit solver/license matrix"
        ),
    }


def _topology_failures(item: dict[str, Any] | None) -> list[str]:
    if item is None:
        return ["ripser receipt missing for topology diagnostics"]
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return ["ripser diagnostics missing"]
    failures = []
    if diagnostics.get("circle_long_lived_h1") != 1:
        failures.append("topology signal H1 was not detected")
    if diagnostics.get("control_long_lived_h1") != 0:
        failures.append("topology null control produced long-lived H1")
    metric = item.get("validation_metric")
    if not isinstance(metric, dict) or float(cast(float, metric.get("value", 0.0))) <= 0.0:
        failures.append("topology validation metric did not beat control")
    return failures


def _bayesian_failures(item: dict[str, Any] | None) -> list[str]:
    if item is None:
        return ["Bayesian receipt missing"]
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return ["Bayesian diagnostics missing"]
    failures = []
    if diagnostics.get("convergence_claim") is not False:
        failures.append("Bayesian workload made an MCMC convergence claim")
    if diagnostics.get("rhat") is not None or diagnostics.get("ess") is not None:
        failures.append("Bayesian analytic workload emitted fake MCMC rhat/ess")
    tail = diagnostics.get("posterior_predictive_tail_probability")
    if not isinstance(tail, float) or not 0.0 <= tail <= 1.0:
        failures.append("Bayesian posterior predictive diagnostic invalid")
    return failures


def _causal_failures(item: dict[str, Any] | None) -> list[str]:
    if item is None:
        return ["causal receipt missing"]
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return ["causal diagnostics missing"]
    failures = []
    if item.get("causal_identification") != "identified":
        failures.append("causal workload did not declare backdoor identification")
    adjusted = diagnostics.get("adjusted_treatment_effect")
    permuted = diagnostics.get("permuted_treatment_effect")
    if (
        not isinstance(adjusted, float)
        or abs(adjusted - CAUSAL_TRUE_EFFECT) > CAUSAL_EFFECT_TOLERANCE
    ):
        failures.append("causal adjusted effect drifted from known synthetic truth")
    if not isinstance(permuted, float) or abs(permuted) > CAUSAL_FALSIFICATION_TOLERANCE:
        failures.append("causal falsification permutation was not near zero")
    return failures


def _optimization_failures(item: dict[str, Any] | None) -> list[str]:
    if item is None:
        return ["cvxpy receipt missing"]
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return ["cvxpy diagnostics missing"]
    failures = []
    if diagnostics.get("solve_status") != "optimal":
        failures.append("CVXPY solver status is not optimal")
    if diagnostics.get("license_verified") is not True:
        failures.append("CVXPY result did not verify solver license")
    if diagnostics.get("denied_solvers") != ["cbc", "glpk"]:
        failures.append("CVXPY denied solver matrix changed")
    return failures


def _build_stage_receipt() -> dict[str, Any]:
    activation = _check_activation_receipt()
    diagnostics = _check_diagnostics_and_no_promotion(activation)
    checks = [activation, diagnostics]
    failures = [check for check in checks if check["status"] != "PASS"]
    result = "FAIL" if failures else "PASS"
    active_packs = list(EXPECTED_A13) if result == "PASS" else []
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": result,
        "stage_closure": "A13_ACTIVE" if result == "PASS" else "A13_OPEN",
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
