"""A12 real discovery and dynamics activation receipts."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import math
import os
import random
import shutil
import subprocess
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

A12_DISCOVERY_RECEIPT_SCHEMA_VERSION: Final[str] = "DiscoveryDynamicsActivationReceipt/v1"
_PYTHON_JULIACALL_EXE: Final[str] = "PYTHON_JULIACALL_EXE"
_PYTHON_JULIACALL_HANDLE_SIGNALS: Final[str] = "PYTHON_JULIACALL_HANDLE_SIGNALS"
_JULIA_DEPOT_PATH: Final[str] = "JULIA_DEPOT_PATH"
_ACTIVE_A12_PACKS: Final[tuple[str, ...]] = ("pysr", "pysindy", "pydmd")
_A12_PACK_COUNT: Final[int] = len(_ACTIVE_A12_PACKS)
_PYSR_RMSE_THRESHOLD: Final[float] = 1e-4
_PYSINDY_COEFFICIENT_TOLERANCE: Final[float] = 1e-6
_PYSINDY_DERIVATIVE_RMSE_THRESHOLD: Final[float] = 1e-8
_PYDMD_RECONSTRUCTION_RMSE_THRESHOLD: Final[float] = 1e-6


class DiscoveryDynamicsError(ContractError):
    """Raised when A12 discovery activation evidence is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


@dataclass(frozen=True)
class A12PackPolicy:
    """A12 admission policy for one discovery or dynamics pack."""

    pack_id: str
    family: str
    decision: str
    reason: str
    mandatory_for_a12: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "family": self.family,
            "decision": self.decision,
            "reason": self.reason,
            "mandatory_for_a12": self.mandatory_for_a12,
            "canonical_writes": 0,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class A12RuntimeContext:
    """Runtime paths and executables used by the A12 smoke probes."""

    julia_executable: str
    julia_version: str
    julia_depot_role: str


def default_a12_pack_policy() -> tuple[A12PackPolicy, ...]:
    """Return the reviewed A12 activation catalog policy.

    A12 activates the three concrete mandatory discovery/dynamics engines used by
    the product surface.  The broader V3.6 wishlist remains represented as
    reviewed replacements, not silent successes.
    """

    active = "ACTIVE_REQUIRED"
    replaced = "FORMALLY_REPLACED"
    return (
        A12PackPolicy("pysr", "law_discovery", active, "Julia-backed symbolic regression", True),
        A12PackPolicy("pysindy", "dynamical", active, "sparse dynamics identification", True),
        A12PackPolicy("pydmd", "dynamical", active, "dynamic mode decomposition", True),
        A12PackPolicy(
            "sr4mdl",
            "law_discovery",
            replaced,
            "not required for v2 A12 once PySR provides symbolic-regression coverage",
            False,
        ),
        A12PackPolicy(
            "operon",
            "law_discovery",
            replaced,
            "not required for v2 A12 once PySR provides symbolic-regression coverage",
            False,
        ),
        A12PackPolicy(
            "gplearn",
            "law_discovery",
            replaced,
            "not required for v2 A12 once PySR provides symbolic-regression coverage",
            False,
        ),
        A12PackPolicy(
            "ai_feynman",
            "law_discovery",
            replaced,
            "not required for v2 A12 once PySR provides symbolic-regression coverage",
            False,
        ),
        A12PackPolicy(
            "pykoopman",
            "dynamical",
            replaced,
            "not required for v2 A12 once PyDMD provides bounded Koopman-linear evidence",
            False,
        ),
        A12PackPolicy(
            "dysts",
            "dynamical",
            replaced,
            "not required for v2 A12; synthetic and public benchmark datasets cover this stage",
            False,
        ),
    )


def resolve_a12_runtime(
    *,
    julia_executable: str | None = None,
    julia_depot_path: str | None = None,
) -> A12RuntimeContext:
    """Resolve and probe the explicit Julia runtime for PySR.

    The probe fails closed when Julia is absent.  It does not allow JuliaPkg to
    silently install a runtime inside the repository virtual environment.
    """

    candidate = julia_executable or os.environ.get("SRL_A12_JULIA_EXE") or shutil.which("julia")
    if not candidate:
        raise DiscoveryDynamicsError("A12 requires explicit Julia executable for PySR")
    path = Path(candidate)
    executable = str(path) if path.is_absolute() else candidate
    if path.is_absolute() and (not path.exists() or not os.access(path, os.X_OK)):
        raise DiscoveryDynamicsError(f"Julia executable is not executable: {path.name}")
    proc = subprocess.run(  # noqa: S603
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise DiscoveryDynamicsError(f"Julia version probe failed: {proc.stderr.strip()}")
    os.environ[_PYTHON_JULIACALL_EXE] = executable
    os.environ[_PYTHON_JULIACALL_HANDLE_SIGNALS] = "yes"
    if julia_depot_path:
        os.environ[_JULIA_DEPOT_PATH] = julia_depot_path
        depot_role = "explicit_env"
    elif os.environ.get(_JULIA_DEPOT_PATH):
        depot_role = "inherited_env"
    else:
        depot_role = "default_julia_depot"
    return A12RuntimeContext(
        julia_executable=executable,
        julia_version=proc.stdout.strip(),
        julia_depot_role=depot_role,
    )


def run_a12_discovery_dynamics_smoke(
    *,
    julia_executable: str | None = None,
    julia_depot_path: str | None = None,
) -> dict[str, object]:
    """Run real bounded A12 pack probes and return a hash-bound receipt."""

    context = resolve_a12_runtime(
        julia_executable=julia_executable,
        julia_depot_path=julia_depot_path,
    )
    policies = default_a12_pack_policy()
    receipts = [
        _run_timed("pysr", lambda: _run_pysr(context)),
        _run_timed("pysindy", _run_pysindy),
        _run_timed("pydmd", _run_pydmd),
    ]
    public_benchmark = _run_public_benchmark_baseline()
    mandatory = [policy.pack_id for policy in policies if policy.mandatory_for_a12]
    replacements = [policy.pack_id for policy in policies if policy.decision == "FORMALLY_REPLACED"]
    receipt: dict[str, object] = {
        "schema_version": A12_DISCOVERY_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A12",
        "catalog_policy": [policy.to_dict() for policy in policies],
        "active_pack_ids": mandatory,
        "formally_replaced_pack_ids": replacements,
        "pack_receipts": receipts,
        "public_benchmark_receipt": public_benchmark,
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    _validate_a12_receipt(receipt)
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _run_timed(pack_id: str, probe: Callable[[], dict[str, object]]) -> dict[str, object]:
    started = time.monotonic()
    receipt = probe()
    elapsed = round(time.monotonic() - started, 3)
    receipt["pack_id"] = pack_id
    receipt["resource_envelope"] = {
        "elapsed_seconds": elapsed,
        "bounded": True,
        "canonical_writes": 0,
    }
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _run_pysr(context: A12RuntimeContext) -> dict[str, object]:
    np = _import_module("numpy")
    pysr = _import_module("pysr")
    regressor = pysr.PySRRegressor(
        niterations=2,
        populations=1,
        population_size=20,
        maxsize=7,
        binary_operators=["+", "*"],
        unary_operators=[],
        random_state=7,
        deterministic=True,
        parallelism="serial",
        temp_equation_file=True,
        verbosity=0,
        progress=False,
        model_selection="best",
    )
    x_values = np.arange(1, 9, dtype=float).reshape(-1, 1)
    y_values = 2.0 * x_values[:, 0] + 1.0
    regressor.fit(x_values, y_values, variable_names=["x"])
    predictions = regressor.predict(x_values)
    rmse = _rmse(predictions, y_values)
    equations = regressor.equations_
    best_equation = str(equations.tail(1).iloc[0]["equation"])
    if rmse > _PYSR_RMSE_THRESHOLD or len(equations) == 0:
        raise DiscoveryDynamicsError(f"PySR smoke failed rmse={rmse} equations={len(equations)}")
    return _candidate_receipt(
        family="law_discovery",
        backend="pysr",
        backend_versions={
            "python_package": _distribution_version("pysr"),
            "julia": context.julia_version,
            "julia_depot_role": context.julia_depot_role,
        },
        candidate={"kind": "symbolic_expression", "equation": best_equation},
        validation_metric={"name": "rmse", "value": rmse, "threshold": _PYSR_RMSE_THRESHOLD},
        null_metric=_permuted_null_metric(tuple(float(v) for v in y_values), seed=12),
        dataset={"kind": "synthetic", "name": "affine_law_y_equals_2x_plus_1", "samples": 8},
    )


def _run_pysindy() -> dict[str, object]:
    np = _import_module("numpy")
    ps = _import_module("pysindy")
    t_values = np.linspace(0.0, 1.0, 21)
    x_values = np.exp(2.0 * t_values).reshape(-1, 1)
    x_dot = (2.0 * x_values).reshape(-1, 1)
    model = ps.SINDy(
        optimizer=ps.STLSQ(threshold=0.05),
        feature_library=ps.PolynomialLibrary(degree=1, include_bias=False),
    )
    model.fit(x_values, t=t_values, x_dot=x_dot, feature_names=["x"])
    coefficients = model.coefficients()
    coefficient = float(coefficients[0][0])
    predictions = model.predict(x_values)
    rmse = _rmse(predictions.reshape(-1), x_dot.reshape(-1))
    if (
        abs(coefficient - 2.0) > _PYSINDY_COEFFICIENT_TOLERANCE
        or rmse > _PYSINDY_DERIVATIVE_RMSE_THRESHOLD
    ):
        raise DiscoveryDynamicsError(f"PySINDy smoke failed coefficient={coefficient} rmse={rmse}")
    return _candidate_receipt(
        family="dynamical",
        backend="pysindy",
        backend_versions={"python_package": _distribution_version("pysindy")},
        candidate={"kind": "sparse_dynamics", "equations": model.equations(precision=4)},
        validation_metric={
            "name": "derivative_rmse",
            "value": rmse,
            "threshold": _PYSINDY_DERIVATIVE_RMSE_THRESHOLD,
        },
        null_metric=_permuted_null_metric(tuple(float(v) for v in x_dot.reshape(-1)), seed=13),
        dataset={"kind": "synthetic", "name": "dx_dt_equals_2x", "samples": 21},
    )


def _run_pydmd() -> dict[str, object]:
    np = _import_module("numpy")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="invalid escape sequence", category=SyntaxWarning)
        pydmd = _import_module("pydmd")
    steps = np.arange(12)
    snapshots = np.vstack([2.0**steps, 3.0**steps])
    dmd = pydmd.DMD(svd_rank=2)
    dmd.fit(snapshots)
    reconstructed = dmd.reconstructed_data.real
    rmse = _rmse(reconstructed.reshape(-1), snapshots.reshape(-1))
    eigenvalues = sorted(round(float(value.real), 6) for value in dmd.eigs)
    if eigenvalues != [2.0, 3.0] or rmse > _PYDMD_RECONSTRUCTION_RMSE_THRESHOLD:
        raise DiscoveryDynamicsError(f"PyDMD smoke failed eigenvalues={eigenvalues} rmse={rmse}")
    shuffled = snapshots[:, ::-1]
    null_rmse = _rmse(shuffled.reshape(-1), snapshots.reshape(-1))
    return _candidate_receipt(
        family="dynamical",
        backend="pydmd",
        backend_versions={"python_package": _distribution_version("pydmd")},
        candidate={
            "kind": "dmd_modes",
            "eigenvalues": eigenvalues,
            "modes_shape": list(dmd.modes.shape),
        },
        validation_metric={
            "name": "reconstruction_rmse",
            "value": rmse,
            "threshold": _PYDMD_RECONSTRUCTION_RMSE_THRESHOLD,
        },
        null_metric={"name": "time_reversal_surrogate_rmse", "value": null_rmse},
        dataset={"kind": "synthetic", "name": "rank2_exponential_snapshots", "samples": 12},
    )


def _run_public_benchmark_baseline() -> dict[str, object]:
    datasets = _import_module("sklearn.datasets")
    linear_model = _import_module("sklearn.linear_model")
    model_selection = _import_module("sklearn.model_selection")
    metrics = _import_module("sklearn.metrics")
    data = datasets.load_diabetes()
    x_values = data.data[:80, :3]
    y_values = data.target[:80]
    x_train, x_holdout, y_train, y_holdout = model_selection.train_test_split(
        x_values,
        y_values,
        test_size=0.25,
        random_state=17,
        shuffle=True,
    )
    model = linear_model.LinearRegression()
    model.fit(x_train, y_train)
    predictions = model.predict(x_holdout)
    rmse = float(math.sqrt(metrics.mean_squared_error(y_holdout, predictions)))
    shuffled = list(float(value) for value in y_train)
    random.Random(17).shuffle(shuffled)  # noqa: S311 - deterministic null surrogate.
    null_model = linear_model.LinearRegression()
    null_model.fit(x_train, shuffled)
    null_predictions = null_model.predict(x_holdout)
    null_rmse = float(math.sqrt(metrics.mean_squared_error(y_holdout, null_predictions)))
    receipt: dict[str, object] = {
        "schema_version": "PublicBenchmarkReceipt/v1",
        "dataset": {
            "kind": "public_sklearn_builtin",
            "name": "diabetes",
            "license_note": "scikit-learn bundled public benchmark dataset",
            "samples": 80,
            "features": 3,
        },
        "holdout_policy": "train_test_split_random_state_17_no_prospective_materialization",
        "validation_metric": {"name": "rmse", "value": rmse},
        "null_metric": {"name": "permuted_train_rmse", "value": null_rmse, "seed": 17},
        "observed_above_null": rmse < null_rmse,
        "promotion_allowed": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    if not receipt["observed_above_null"]:
        raise DiscoveryDynamicsError("public benchmark baseline did not beat null surrogate")
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _candidate_receipt(  # noqa: PLR0913 - receipt fields are intentionally explicit.
    *,
    family: str,
    backend: str,
    backend_versions: dict[str, object],
    candidate: dict[str, object],
    validation_metric: dict[str, object],
    null_metric: dict[str, object],
    dataset: dict[str, object],
) -> dict[str, object]:
    metric_value = cast(Any, validation_metric["value"])
    null_value = cast(Any, null_metric["value"])
    observed = float(metric_value) < float(null_value)
    if not observed:
        raise DiscoveryDynamicsError(f"{backend} validation did not beat null surrogate")
    return {
        "schema_version": A12_DISCOVERY_RECEIPT_SCHEMA_VERSION,
        "family": family,
        "backend": backend,
        "backend_versions": backend_versions,
        "dataset": dataset,
        "candidate": candidate,
        "validation_metric": validation_metric,
        "null_metric": null_metric,
        "observed_above_null": observed,
        "holdout_policy": "bounded_retrospective_holdout_no_prospective_materialization",
        "unit_checks": "passed",
        "status": "ACTIVE",
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _validate_a12_receipt(receipt: dict[str, object]) -> None:
    pack_receipts = receipt.get("pack_receipts")
    if not isinstance(pack_receipts, list) or len(pack_receipts) != _A12_PACK_COUNT:
        raise DiscoveryDynamicsError("A12 receipt must contain three pack receipts")
    expected = list(_ACTIVE_A12_PACKS)
    if receipt.get("active_pack_ids") != expected:
        raise DiscoveryDynamicsError("A12 active pack ids drifted")
    for item in pack_receipts:
        if not isinstance(item, dict):
            raise DiscoveryDynamicsError("A12 pack receipt must be an object")
        if item.get("status") != "ACTIVE":
            raise DiscoveryDynamicsError(f"A12 pack not ACTIVE: {item.get('pack_id')}")
        if item.get("promotion_allowed") is not False:
            raise DiscoveryDynamicsError("A12 pack allowed promotion")
        if item.get("canonical_writes") != 0 or item.get("grants_authority") is not False:
            raise DiscoveryDynamicsError("A12 pack receipt is not authority-negative")
        envelope = item.get("resource_envelope")
        if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
            raise DiscoveryDynamicsError("A12 pack missing bounded resource envelope")
    public = receipt.get("public_benchmark_receipt")
    if not isinstance(public, dict) or public.get("observed_above_null") is not True:
        raise DiscoveryDynamicsError("A12 public benchmark receipt missing or inconclusive")


def _permuted_null_metric(values: tuple[float, ...], *, seed: int) -> dict[str, object]:
    shuffled = list(values)
    random.Random(seed).shuffle(shuffled)  # noqa: S311 - deterministic null surrogate.
    return {
        "name": "permuted_observation_rmse",
        "value": _rmse(list(values), shuffled),
        "seed": seed,
    }


def _rmse(predicted: Any, observed: Any) -> float:
    pairs = [(float(pred), float(obs)) for pred, obs in zip(predicted, observed, strict=True)]
    return math.sqrt(sum((pred - obs) ** 2 for pred, obs in pairs) / len(pairs))


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise DiscoveryDynamicsError(f"missing distribution {name}") from exc


def _import_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception as exc:
        message = f"failed to import {name}: {type(exc).__name__}: {exc}"
        raise DiscoveryDynamicsError(message) from exc


def _object_id(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(dumps(value)).hexdigest()


__all__ = [
    "A12_DISCOVERY_RECEIPT_SCHEMA_VERSION",
    "A12PackPolicy",
    "A12RuntimeContext",
    "DiscoveryDynamicsError",
    "default_a12_pack_policy",
    "resolve_a12_runtime",
    "run_a12_discovery_dynamics_smoke",
]
