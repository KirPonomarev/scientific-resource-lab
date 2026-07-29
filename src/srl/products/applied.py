"""Applied geometry, topology, probability, causal and optimization admission."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "AppliedScienceAdmissionBundle/v1"
APPLIED_RESULT_RECEIPT_SCHEMA_VERSION: Final[str] = "AppliedResultReceipt/v1"
A13_APPLIED_RECEIPT_SCHEMA_VERSION: Final[str] = "AppliedScienceActivationReceipt/v1"
_ACTIVE_A13_PACKS: Final[tuple[str, ...]] = (
    "ripser",
    "pyriemann",
    "cvxpy",
    "native_bayesian_conjugate",
    "native_causal_backdoor",
)
_REPLACED_A13_PACKS: Final[tuple[str, ...]] = (
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
_GEOMETRY_TOLERANCE: Final[float] = 1e-9
_CAUSAL_TRUE_EFFECT: Final[float] = 2.0
_CAUSAL_EFFECT_TOLERANCE: Final[float] = 0.08
_CAUSAL_FALSIFICATION_TOLERANCE: Final[float] = 0.25
_SINGULAR_MATRIX_TOLERANCE: Final[float] = 1e-12


class AppliedScienceError(ContractError):
    """Raised when applied-science admission or result contracts are invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class AppliedPackStatus(StrEnum):
    """Applied pack status."""

    ACTIVE = "ACTIVE"
    WAIT_CAPABILITY = "WAIT_CAPABILITY"
    FORMALLY_REPLACED = "FORMALLY_REPLACED"


@dataclass(frozen=True)
class AppliedPackCard:
    """One applied pack admission card."""

    pack_id: str
    family: str
    status: AppliedPackStatus
    import_names: tuple[str, ...]
    capability: str
    diagnostic_policy: str
    reason: str

    def __post_init__(self) -> None:
        for field in ("pack_id", "family", "capability", "diagnostic_policy", "reason"):
            _require_non_empty(getattr(self, field), field)
        if not isinstance(self.import_names, tuple) or any(
            not isinstance(name, str) or not name for name in self.import_names
        ):
            raise AppliedScienceError("import_names must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible pack card."""
        return {
            "pack_id": self.pack_id,
            "family": self.family,
            "status": self.status.value,
            "import_names": list(self.import_names),
            "capability": self.capability,
            "diagnostic_policy": self.diagnostic_policy,
            "reason": self.reason,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def default_applied_pack_cards() -> tuple[AppliedPackCard, ...]:
    """Return A13 applied pack cards."""
    active = AppliedPackStatus.ACTIVE
    replaced = AppliedPackStatus.FORMALLY_REPLACED
    return (
        AppliedPackCard(
            pack_id="ripser",
            family="topology",
            status=active,
            import_names=("ripser",),
            capability="persistent_homology",
            diagnostic_policy="null controls required",
            reason="existing bounded adapter",
        ),
        AppliedPackCard(
            pack_id="pyriemann",
            family="geometry",
            status=active,
            import_names=("pyriemann",),
            capability="spd_geometry",
            diagnostic_policy="cross-validation diagnostics required",
            reason="existing bounded adapter",
        ),
        AppliedPackCard(
            pack_id="cvxpy",
            family="optimization",
            status=active,
            import_names=("cvxpy",),
            capability="convex_optimization",
            diagnostic_policy="solver status required",
            reason="existing bounded adapter",
        ),
        AppliedPackCard(
            pack_id="native_bayesian_conjugate",
            family="probability",
            status=active,
            import_names=(),
            capability="bounded_analytic_bayesian_diagnostics",
            diagnostic_policy="closed_form_posterior_predictive_and_no_mcmc_convergence_claim",
            reason=(
                "native bounded analytic Bayesian workload avoids optional LGPL transitive closure"
            ),
        ),
        AppliedPackCard(
            pack_id="native_causal_backdoor",
            family="causal",
            status=active,
            import_names=(),
            capability="backdoor_identification_and_falsification",
            diagnostic_policy="identification assumptions and permutation falsification required",
            reason=(
                "native bounded causal checker covers A13 identification/falsification acceptance"
            ),
        ),
        AppliedPackCard(
            pack_id="gudhi",
            family="topology",
            status=replaced,
            import_names=("gudhi",),
            capability="topological_data_analysis",
            diagnostic_policy="null controls required",
            reason="formally replaced for v2 by ripser persistent-homology workload",
        ),
        AppliedPackCard(
            pack_id="geomstats",
            family="geometry",
            status=replaced,
            import_names=("geomstats",),
            capability="riemannian_geometry",
            diagnostic_policy="metric diagnostics required",
            reason="formally replaced for v2 by pyriemann SPD geometry workload",
        ),
        AppliedPackCard(
            pack_id="pot",
            family="optimization",
            status=replaced,
            import_names=("ot",),
            capability="optimal_transport",
            diagnostic_policy="solver status required",
            reason="formally replaced for v2 by CVXPY bounded optimization solver matrix",
        ),
        AppliedPackCard(
            pack_id="pymanopt",
            family="optimization",
            status=replaced,
            import_names=("pymanopt",),
            capability="manifold_optimization",
            diagnostic_policy="solver status required",
            reason="formally replaced for v2 by CVXPY bounded optimization solver matrix",
        ),
        AppliedPackCard(
            pack_id="keplermapper",
            family="topology",
            status=replaced,
            import_names=("kmapper",),
            capability="mapper_graphs",
            diagnostic_policy="null controls required",
            reason="formally replaced for v2 by ripser topology workload and null controls",
        ),
        AppliedPackCard(
            pack_id="toponetx",
            family="topology",
            status=replaced,
            import_names=("toponetx",),
            capability="higher_order_topology",
            diagnostic_policy="null controls required",
            reason="formally replaced for v2 by ripser topology workload and null controls",
        ),
        AppliedPackCard(
            pack_id="regina",
            family="topology",
            status=replaced,
            import_names=("regina",),
            capability="3_manifold_topology",
            diagnostic_policy="exact certificate required",
            reason="formally replaced for v2; 3-manifold exact certificates are outside v2 scope",
        ),
        AppliedPackCard(
            pack_id="pymc",
            family="probability",
            status=replaced,
            import_names=("pymc",),
            capability="bayesian_modeling",
            diagnostic_policy="mcmc diagnostics required",
            reason=(
                "formally replaced for v2 by native conjugate Bayesian diagnostic; "
                "optional PyMC remains license-disclosed"
            ),
        ),
        AppliedPackCard(
            pack_id="arviz",
            family="probability",
            status=replaced,
            import_names=("arviz",),
            capability="mcmc_diagnostics",
            diagnostic_policy="rhat_ess required",
            reason=(
                "formally replaced for v2 by analytic diagnostics with no false MCMC "
                "convergence claim"
            ),
        ),
        AppliedPackCard(
            pack_id="dowhy",
            family="causal",
            status=replaced,
            import_names=("dowhy",),
            capability="causal_identification",
            diagnostic_policy="identification required",
            reason=(
                "formally replaced for v2 by native backdoor identification and "
                "falsification workload"
            ),
        ),
        AppliedPackCard(
            pack_id="tigramite",
            family="causal",
            status=replaced,
            import_names=("tigramite",),
            capability="time_series_causal_discovery",
            diagnostic_policy="falsification required",
            reason="formally replaced for v2 by native bounded causal falsification workload",
        ),
        AppliedPackCard(
            pack_id="econml",
            family="causal",
            status=replaced,
            import_names=("econml",),
            capability="heterogeneous_treatment_effects",
            diagnostic_policy="identification required",
            reason="formally replaced for v2 by native backdoor identification workload",
        ),
        AppliedPackCard(
            pack_id="jaxopt",
            family="optimization",
            status=replaced,
            import_names=("jaxopt",),
            capability="differentiable_optimization",
            diagnostic_policy="solver status required",
            reason="formally replaced for v2 by CVXPY bounded optimization solver matrix",
        ),
        AppliedPackCard(
            pack_id="botorch",
            family="optimization",
            status=replaced,
            import_names=("botorch",),
            capability="bayesian_optimization",
            diagnostic_policy="uncertainty diagnostics required",
            reason=(
                "formally replaced for v2 by native Bayesian diagnostics plus CVXPY solver matrix"
            ),
        ),
    )


def build_applied_science_admission_bundle(
    *,
    cards: tuple[AppliedPackCard, ...] | None = None,
) -> dict[str, object]:
    """Build deterministic applied-science admission status."""
    assessed = tuple(_assess(card) for card in (cards or default_applied_pack_cards()))
    body: dict[str, object] = {
        "schema_version": APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION,
        "pack_cards": [card.to_dict() for card in assessed],
        "active_pack_ids": [
            card.pack_id for card in assessed if card.status is AppliedPackStatus.ACTIVE
        ],
        "wait_pack_ids": [
            card.pack_id for card in assessed if card.status is AppliedPackStatus.WAIT_CAPABILITY
        ],
        "formally_replaced_pack_ids": [
            card.pack_id for card in assessed if card.status is AppliedPackStatus.FORMALLY_REPLACED
        ],
        "diagnostic_policy": "assumptions_diagnostics_uncertainty_and_solver_status_required",
        "causal_policy": "unidentified_effect_must_not_be_estimated",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def build_applied_result_receipt(  # noqa: PLR0913
    *,
    product: str,
    assumptions: tuple[str, ...],
    diagnostics: tuple[str, ...],
    solver_status: str,
    causal_identification: str = "not_applicable",
    effect_estimate: float | None = None,
) -> dict[str, object]:
    """Build an authority-negative applied result receipt."""
    _require_non_empty(product, "product")
    _require_tuple(assumptions, "assumptions")
    _require_tuple(diagnostics, "diagnostics")
    _require_non_empty(solver_status, "solver_status")
    _require_non_empty(causal_identification, "causal_identification")
    if causal_identification != "identified" and effect_estimate is not None:
        raise AppliedScienceError("unidentified causal effect must not carry an estimate")
    receipt: dict[str, object] = {
        "schema_version": APPLIED_RESULT_RECEIPT_SCHEMA_VERSION,
        "product": product,
        "assumptions": list(assumptions),
        "diagnostics": list(diagnostics),
        "solver_status": solver_status,
        "causal_identification": causal_identification,
        "effect_estimate": effect_estimate,
        "status": "inconclusive" if solver_status != "optimal" else "checked",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def run_a13_applied_science_smoke() -> dict[str, object]:
    """Run real bounded A13 applied-science workloads and return a receipt."""
    bundle = build_applied_science_admission_bundle()
    receipts = [
        _run_timed("ripser", _run_topology_workload),
        _run_timed("pyriemann", _run_geometry_workload),
        _run_timed("cvxpy", _run_optimization_workload),
        _run_timed("native_bayesian_conjugate", _run_bayesian_workload),
        _run_timed("native_causal_backdoor", _run_causal_workload),
    ]
    receipt: dict[str, object] = {
        "schema_version": A13_APPLIED_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A13",
        "admission_bundle": bundle,
        "active_pack_ids": list(_ACTIVE_A13_PACKS),
        "formally_replaced_pack_ids": list(_REPLACED_A13_PACKS),
        "workload_receipts": receipts,
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    _validate_a13_receipt(receipt)
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _run_timed(pack_id: str, workload: Callable[[], dict[str, object]]) -> dict[str, object]:
    started = time.monotonic()
    receipt = workload()
    elapsed = round(time.monotonic() - started, 3)
    receipt["pack_id"] = pack_id
    receipt["resource_envelope"] = {
        "elapsed_seconds": elapsed,
        "bounded": True,
        "canonical_writes": 0,
    }
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _run_topology_workload() -> dict[str, object]:
    from srl.packs.adapters.ripser_adapter import (  # noqa: PLC0415
        compute_persistence,
        long_lived_classes,
        max_finite_persistence,
        ripser_version,
    )

    circle = [
        [math.cos(2.0 * math.pi * idx / 24), math.sin(2.0 * math.pi * idx / 24)]
        for idx in range(24)
    ]
    control = [[((idx * 37) % 101) / 101.0, ((idx * 53) % 103) / 103.0] for idx in range(24)]
    circle_result = compute_persistence(circle, maxdim=1, seed=1301)
    control_result = compute_persistence(control, maxdim=1, seed=1301)
    circle_h1 = long_lived_classes(circle_result, 1, 0.45)
    control_h1 = long_lived_classes(control_result, 1, 0.45)
    circle_max = max_finite_persistence(circle_result, 1) or 0.0
    control_max = max_finite_persistence(control_result, 1) or 0.0
    if circle_h1 < 1 or control_h1 != 0:
        raise AppliedScienceError("topology workload failed circle/control null check")
    return _workload_receipt(
        family="topology",
        backend="ripser",
        backend_versions={
            "python_package": _distribution_version("ripser"),
            "core": ripser_version(),
        },
        dataset={"kind": "synthetic", "name": "unit_circle_vs_uniform_control", "samples": 48},
        diagnostics={
            "circle_long_lived_h1": circle_h1,
            "control_long_lived_h1": control_h1,
            "circle_max_h1_persistence": circle_max,
            "control_max_h1_persistence": control_max,
        },
        validation_metric={"name": "h1_signal_above_control", "value": circle_max - control_max},
        solver_status="checked",
    )


def _run_geometry_workload() -> dict[str, object]:
    from srl.packs.adapters.pyriemann_adapter import (  # noqa: PLC0415
        Metric,
        distance,
        log_euclidean_mean,
    )

    a = [[2.0, 0.0], [0.0, 3.0]]
    b = [[8.0, 0.0], [0.0, 12.0]]
    c = [[4.0, 0.2], [0.2, 5.0]]
    mean = log_euclidean_mean([a, b])
    expected = [[4.0, 0.0], [0.0, 6.0]]
    mean_error = _max_abs_matrix_error(mean.tolist(), expected)
    symmetry_error = abs(distance(a, b, Metric.RIEMANN) - distance(b, a, Metric.RIEMANN))
    triangle_slack = (
        distance(a, b, Metric.RIEMANN)
        + distance(b, c, Metric.RIEMANN)
        - distance(a, c, Metric.RIEMANN)
    )
    if (
        mean_error > _GEOMETRY_TOLERANCE
        or symmetry_error > _GEOMETRY_TOLERANCE
        or triangle_slack < -_GEOMETRY_TOLERANCE
    ):
        raise AppliedScienceError("geometry workload failed SPD metric diagnostics")
    return _workload_receipt(
        family="geometry",
        backend="pyriemann",
        backend_versions={
            "python_package": _distribution_version("pyriemann"),
            "numpy": _distribution_version("numpy"),
            "scipy": _distribution_version("scipy"),
        },
        dataset={"kind": "synthetic", "name": "commuting_spd_matrices", "samples": 3},
        diagnostics={
            "log_euclidean_mean_max_error": mean_error,
            "riemannian_symmetry_error": symmetry_error,
            "riemannian_triangle_slack": triangle_slack,
        },
        validation_metric={"name": "spd_geometry_diagnostics_passed", "value": 1.0},
        solver_status="checked",
    )


def _run_bayesian_workload() -> dict[str, object]:
    observations = [1.2, 0.9, 1.1, 1.4, 1.0, 1.3]
    prior_mu = 0.0
    prior_sigma = 2.0
    known_sigma = 0.5
    n = len(observations)
    mean_y = sum(observations) / n
    prior_precision = 1.0 / (prior_sigma**2)
    likelihood_precision = n / (known_sigma**2)
    posterior_var = 1.0 / (prior_precision + likelihood_precision)
    posterior_mean = posterior_var * (prior_mu * prior_precision + mean_y * likelihood_precision)
    posterior_sd = math.sqrt(posterior_var)
    posterior_predictive_sd = math.sqrt(known_sigma**2 + posterior_var)
    z_score = abs(mean_y - posterior_mean) / posterior_predictive_sd
    posterior_predictive_tail = math.erfc(z_score / math.sqrt(2.0))
    if not 0.0 <= posterior_predictive_tail <= 1.0 or posterior_sd <= 0.0:
        raise AppliedScienceError("Bayesian workload produced invalid diagnostics")
    return _workload_receipt(
        family="probability",
        backend="native_bayesian_conjugate",
        backend_versions={"python": "stdlib-math"},
        dataset={"kind": "synthetic", "name": "normal_mean_known_sigma", "samples": n},
        diagnostics={
            "posterior_mean": posterior_mean,
            "posterior_sd": posterior_sd,
            "posterior_predictive_tail_probability": posterior_predictive_tail,
            "rhat": None,
            "ess": None,
            "convergence_claim": False,
        },
        validation_metric={
            "name": "posterior_predictive_tail_probability",
            "value": posterior_predictive_tail,
        },
        solver_status="analytic_checked",
    )


def _run_causal_workload() -> dict[str, object]:
    rng = random.Random(1307)  # noqa: S311 - deterministic bounded synthetic workload
    rows = []
    true_effect = _CAUSAL_TRUE_EFFECT
    for idx in range(80):
        confounder = -1.0 + 2.0 * (idx / 79)
        treatment = 1.0 if confounder + rng.uniform(-0.45, 0.45) > 0.0 else 0.0
        outcome = true_effect * treatment + 0.7 * confounder + rng.uniform(-0.05, 0.05)
        rows.append((confounder, treatment, outcome))
    naive_effect = _difference_in_means(rows)
    adjusted_effect = _ols_treatment_effect(rows)
    shuffled = [
        (conf, rows[(idx * 17 + 5) % len(rows)][1], outcome)
        for idx, (conf, _, outcome) in enumerate(rows)
    ]
    falsification_effect = _ols_treatment_effect(shuffled)
    if (
        abs(adjusted_effect - true_effect) > _CAUSAL_EFFECT_TOLERANCE
        or abs(falsification_effect) > _CAUSAL_FALSIFICATION_TOLERANCE
    ):
        raise AppliedScienceError("causal workload failed backdoor or falsification check")
    return _workload_receipt(
        family="causal",
        backend="native_causal_backdoor",
        backend_versions={"python": "stdlib-linear-algebra"},
        dataset={
            "kind": "synthetic",
            "name": "confounded_backdoor_linear_effect",
            "samples": len(rows),
        },
        diagnostics={
            "identification": "backdoor_adjustment_observed_confounder",
            "falsification": "permuted_treatment_effect_near_zero",
            "naive_difference_in_means": naive_effect,
            "adjusted_treatment_effect": adjusted_effect,
            "permuted_treatment_effect": falsification_effect,
        },
        validation_metric={
            "name": "adjusted_effect_abs_error",
            "value": abs(adjusted_effect - true_effect),
        },
        solver_status="identified_and_falsified",
        causal_identification="identified",
    )


def _run_optimization_workload() -> dict[str, object]:
    from srl.packs.adapters.cvxpy_adapter import (  # noqa: PLC0415
        Solver,
        SolveStatus,
        clarabel_version,
        cvxpy_version,
        is_solver_allowed,
        osqp_version,
        solve,
    )

    result = solve(
        {
            "problem_type": "ridge",
            "A": [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            "b": [1.0, 2.0, 3.0],
            "lambda": 0.1,
            "constraints": [{"kind": "box", "lower": -10.0, "upper": 10.0}],
        },
        solver=Solver.CLARABEL,
        max_wall=10.0,
    )
    if result.status != SolveStatus.OPTIMAL or result.solution is None:
        raise AppliedScienceError(f"optimization workload did not solve: {result.status}")
    denied = {"glpk": is_solver_allowed("glpk"), "cbc": is_solver_allowed("cbc")}
    if any(denied.values()):
        raise AppliedScienceError("optimization solver license matrix allowed a denied solver")
    return _workload_receipt(
        family="optimization",
        backend="cvxpy",
        backend_versions={
            "python_package": cvxpy_version(),
            "clarabel": clarabel_version(),
            "osqp": osqp_version(),
        },
        dataset={"kind": "synthetic", "name": "bounded_ridge_regression", "samples": 3},
        diagnostics={
            "solve_status": str(result.status),
            "license_verified": result.license_verified,
            "allowed_solvers": [Solver.CLARABEL.value, Solver.OSQP.value],
            "denied_solvers": sorted(denied),
            "solution_digest": result.solution_digest,
        },
        validation_metric={"name": "objective_decimal", "value": result.objective_decimal},
        solver_status=str(result.status),
    )


def _workload_receipt(  # noqa: PLR0913
    *,
    family: str,
    backend: str,
    backend_versions: dict[str, object],
    dataset: dict[str, object],
    diagnostics: dict[str, object],
    validation_metric: dict[str, object],
    solver_status: str,
    causal_identification: str = "not_applicable",
) -> dict[str, object]:
    return {
        "schema_version": A13_APPLIED_RECEIPT_SCHEMA_VERSION,
        "family": family,
        "backend": backend,
        "backend_versions": backend_versions,
        "dataset": dataset,
        "diagnostics": diagnostics,
        "validation_metric": validation_metric,
        "solver_status": solver_status,
        "causal_identification": causal_identification,
        "status": "ACTIVE",
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _difference_in_means(rows: list[tuple[float, float, float]]) -> float:
    treated = [outcome for _, treatment, outcome in rows if treatment == 1.0]
    control = [outcome for _, treatment, outcome in rows if treatment == 0.0]
    return (sum(treated) / len(treated)) - (sum(control) / len(control))


def _max_abs_matrix_error(observed: list[list[float]], expected: list[list[float]]) -> float:
    return max(
        abs(observed_value - expected_value)
        for observed_row, expected_row in zip(observed, expected, strict=True)
        for observed_value, expected_value in zip(observed_row, expected_row, strict=True)
    )


def _ols_treatment_effect(rows: list[tuple[float, float, float]]) -> float:
    # Solve beta in y = beta0 + beta1*treatment + beta2*confounder by normal equations.
    matrix = [[1.0, treatment, confounder] for confounder, treatment, _ in rows]
    target = [outcome for _, _, outcome in rows]
    xtx = [[sum(row[i] * row[j] for row in matrix) for j in range(3)] for i in range(3)]
    xty = [sum(row[i] * y for row, y in zip(matrix, target, strict=True)) for i in range(3)]
    beta = _solve_3x3(xtx, xty)
    return beta[1]


def _solve_3x3(matrix: list[list[float]], vector: list[float]) -> list[float]:
    rows = [[*matrix[idx][:], vector[idx]] for idx in range(3)]
    for pivot in range(3):
        best = max(range(pivot, 3), key=lambda row: abs(rows[row][pivot]))
        rows[pivot], rows[best] = rows[best], rows[pivot]
        divisor = rows[pivot][pivot]
        if abs(divisor) < _SINGULAR_MATRIX_TOLERANCE:
            raise AppliedScienceError("causal OLS design matrix is singular")
        rows[pivot] = [value / divisor for value in rows[pivot]]
        for row_idx in range(3):
            if row_idx == pivot:
                continue
            factor = rows[row_idx][pivot]
            rows[row_idx] = [
                value - factor * pivot_value
                for value, pivot_value in zip(rows[row_idx], rows[pivot], strict=True)
            ]
    return [rows[idx][3] for idx in range(3)]


def _validate_a13_receipt(receipt: dict[str, object]) -> None:  # noqa: C901
    if receipt.get("active_pack_ids") != list(_ACTIVE_A13_PACKS):
        raise AppliedScienceError("A13 active pack ids drifted")
    if receipt.get("formally_replaced_pack_ids") != list(_REPLACED_A13_PACKS):
        raise AppliedScienceError("A13 replacement pack ids drifted")
    bundle = receipt.get("admission_bundle")
    if not isinstance(bundle, dict):
        raise AppliedScienceError("A13 admission bundle missing")
    if bundle.get("wait_pack_ids") != []:
        raise AppliedScienceError("A13 admission bundle still contains WAIT packs")
    if bundle.get("active_pack_ids") != list(_ACTIVE_A13_PACKS):
        raise AppliedScienceError("A13 admission active ids mismatch")
    if bundle.get("formally_replaced_pack_ids") != list(_REPLACED_A13_PACKS):
        raise AppliedScienceError("A13 admission replacement ids mismatch")
    workloads = receipt.get("workload_receipts")
    if not isinstance(workloads, list) or len(workloads) != len(_ACTIVE_A13_PACKS):
        raise AppliedScienceError("A13 workload receipt count mismatch")
    by_id = {item.get("pack_id"): item for item in workloads if isinstance(item, dict)}
    if tuple(by_id) != _ACTIVE_A13_PACKS:
        raise AppliedScienceError("A13 workload receipt order mismatch")
    for pack_id, item in by_id.items():
        if item.get("status") != "ACTIVE":
            raise AppliedScienceError(f"A13 {pack_id} is not ACTIVE")
        if (
            item.get("promotion_allowed") is not False
            or item.get("automatic_scientific_promotion") is not False
            or item.get("canonical_writes") != 0
            or item.get("grants_authority") is not False
        ):
            raise AppliedScienceError(f"A13 {pack_id} receipt is not authority-negative")
        envelope = item.get("resource_envelope")
        if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
            raise AppliedScienceError(f"A13 {pack_id} missing bounded resource envelope")


def _assess(card: AppliedPackCard) -> AppliedPackCard:
    missing = [name for name in card.import_names if importlib.util.find_spec(name) is None]
    if card.status is AppliedPackStatus.ACTIVE and missing:
        return AppliedPackCard(
            pack_id=card.pack_id,
            family=card.family,
            status=AppliedPackStatus.WAIT_CAPABILITY,
            import_names=card.import_names,
            capability=card.capability,
            diagnostic_policy=card.diagnostic_policy,
            reason=f"missing import(s): {', '.join(missing)}",
        )
    return card


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise AppliedScienceError(f"missing distribution {name}") from exc


def _object_id(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(dumps(value)).hexdigest()


def _require_tuple(values: object, field: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise AppliedScienceError(f"{field} must be a tuple of non-empty strings")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise AppliedScienceError(f"{field} must be a non-empty string")


__all__ = [
    "A13_APPLIED_RECEIPT_SCHEMA_VERSION",
    "APPLIED_RESULT_RECEIPT_SCHEMA_VERSION",
    "APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "AppliedPackCard",
    "AppliedPackStatus",
    "AppliedScienceError",
    "build_applied_result_receipt",
    "build_applied_science_admission_bundle",
    "default_applied_pack_cards",
    "run_a13_applied_science_smoke",
]
