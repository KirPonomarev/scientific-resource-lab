"""A14 SciML and domain-science activation receipts."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import math
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, cast

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

A14_SCIML_DOMAIN_RECEIPT_SCHEMA_VERSION: Final[str] = "SciMLDomainActivationReceipt/v1"
_JULIA_DEPOT_PATH: Final[str] = "JULIA_DEPOT_PATH"
_ACTIVE_A14_PACKS: Final[tuple[str, ...]] = (
    "julia_sciml_ode",
    "python_diffrax_ode",
    "python_qutip_quantum",
    "python_astropy_astronomy",
    "python_cantera_combustion",
    "native_battery_rc",
    "python_quimb_many_body",
    "python_cotengra_tensor_network",
)
_REPLACED_A14_PACKS: Final[tuple[str, ...]] = (
    "julia_modelingtoolkit",
    "julia_datadrivendiffeq",
    "python_cadabra",
    "python_pybamm",
)
_ODE_ABS_TOLERANCE: Final[float] = 5e-7
_ODE_REL_TOLERANCE: Final[float] = 5e-6
_QUTIP_TRANSFER_MIN: Final[float] = 0.999
_CANTERA_FLAME_TEMP_MIN: Final[float] = 1800.0
_BATTERY_FINAL_SOC_MIN: Final[float] = 0.79
_BATTERY_FINAL_SOC_MAX: Final[float] = 0.81
_GALACTIC_LONGITUDE_MIN: Final[float] = 0.0
_GALACTIC_LONGITUDE_MAX: Final[float] = 360.0
_GALACTIC_LATITUDE_MIN: Final[float] = -90.0
_GALACTIC_LATITUDE_MAX: Final[float] = 90.0
_HEISENBERG_GROUND_EXPECTED: Final[float] = -0.75
_HEISENBERG_GROUND_TOLERANCE: Final[float] = 1e-9


class SciMLDomainActivationError(ContractError):
    """Raised when A14 activation evidence is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


@dataclass(frozen=True)
class A14JuliaContext:
    """Resolved Julia executable and isolated project for the SciML smoke."""

    julia_executable: str
    julia_version: str
    julia_project_dir: Path
    julia_depot_role: str
    project_toml_sha256: str
    manifest_toml_sha256: str


def resolve_a14_julia_runtime(
    *,
    julia_executable: str | None = None,
    julia_project_dir: str | Path | None = None,
    julia_depot_path: str | None = None,
) -> A14JuliaContext:
    """Resolve an explicit Julia runtime and prepared SciML project."""

    candidate = julia_executable or os.environ.get("SRL_A14_JULIA_EXE") or shutil.which("julia")
    if not candidate:
        raise SciMLDomainActivationError("A14 requires explicit Julia executable for SciML")
    executable = str(candidate)
    path = Path(executable)
    if path.is_absolute() and (not path.exists() or not os.access(path, os.X_OK)):
        raise SciMLDomainActivationError(f"Julia executable is not executable: {path.name}")
    proc = subprocess.run(  # noqa: S603
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise SciMLDomainActivationError(f"Julia version probe failed: {proc.stderr.strip()}")

    project = Path(
        julia_project_dir
        or os.environ.get("SRL_A14_JULIA_PROJECT_DIR", "")
        or ".cache/srl-a14-julia-project"
    )
    if not project.is_absolute():
        project = Path.cwd() / project
    project_toml = project / "Project.toml"
    manifest_toml = project / "Manifest.toml"
    if not project_toml.exists() or not manifest_toml.exists():
        raise SciMLDomainActivationError(
            "A14 Julia project is not prepared; run srf-v37-a14-prepare-julia.py first"
        )
    if julia_depot_path:
        os.environ[_JULIA_DEPOT_PATH] = julia_depot_path
        depot_role = "explicit_env"
    elif os.environ.get(_JULIA_DEPOT_PATH):
        depot_role = "inherited_env"
    else:
        depot_role = "default_julia_depot"
    return A14JuliaContext(
        julia_executable=executable,
        julia_version=proc.stdout.strip(),
        julia_project_dir=project,
        julia_depot_role=depot_role,
        project_toml_sha256=_file_sha256(project_toml),
        manifest_toml_sha256=_file_sha256(manifest_toml),
    )


def prepare_a14_julia_project(
    *,
    julia_executable: str | None = None,
    julia_project_dir: str | Path | None = None,
    julia_depot_path: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, object]:
    """Prepare the isolated Julia project used by the A14 SciML smoke."""

    candidate = julia_executable or os.environ.get("SRL_A14_JULIA_EXE") or shutil.which("julia")
    if not candidate:
        raise SciMLDomainActivationError("A14 requires explicit Julia executable for SciML")
    executable = str(candidate)
    project = Path(
        julia_project_dir
        or os.environ.get("SRL_A14_JULIA_PROJECT_DIR", "")
        or ".cache/srl-a14-julia-project"
    )
    if not project.is_absolute():
        project = Path.cwd() / project
    project.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if julia_depot_path:
        env[_JULIA_DEPOT_PATH] = julia_depot_path
    env["SRL_A14_JULIA_PROJECT_DIR"] = str(project)
    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603
        [
            executable,
            "--startup-file=no",
            "--history-file=no",
            "-e",
            _JULIA_PREPARE_SCRIPT,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )
    elapsed = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise SciMLDomainActivationError(f"A14 Julia SciML prepare failed: {stderr}")
    context = resolve_a14_julia_runtime(
        julia_executable=executable,
        julia_project_dir=project,
        julia_depot_path=env.get(_JULIA_DEPOT_PATH),
    )
    receipt: dict[str, object] = {
        "schema_version": "A14JuliaProjectPrepareReceipt/v1",
        "stage_id": "A14",
        "prepared": True,
        "julia_version": context.julia_version,
        "julia_project_role": "isolated_stage_project",
        "julia_depot_role": context.julia_depot_role,
        "project_toml_sha256": context.project_toml_sha256,
        "manifest_toml_sha256": context.manifest_toml_sha256,
        "packages": ["SciMLBase", "OrdinaryDiffEq"],
        "resource_envelope": {
            "elapsed_seconds": elapsed,
            "timeout_seconds": timeout_seconds,
            "bounded": True,
            "canonical_writes": 0,
        },
        "promotion_allowed": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def run_a14_sciml_domain_smoke(
    *,
    julia_executable: str | None = None,
    julia_project_dir: str | Path | None = None,
    julia_depot_path: str | None = None,
) -> dict[str, object]:
    """Run real bounded A14 SciML/domain probes and return a hash-bound receipt."""

    julia = resolve_a14_julia_runtime(
        julia_executable=julia_executable,
        julia_project_dir=julia_project_dir,
        julia_depot_path=julia_depot_path,
    )
    workload_receipts = [
        _run_timed("julia_sciml_ode", lambda: _run_julia_sciml_ode(julia)),
        _run_timed("python_diffrax_ode", _run_diffrax_ode),
        _run_timed("python_qutip_quantum", _run_qutip_quantum),
        _run_timed("python_astropy_astronomy", _run_astropy_astronomy),
        _run_timed("python_cantera_combustion", _run_cantera_combustion),
        _run_timed("native_battery_rc", _run_native_battery_rc),
        _run_timed("python_quimb_many_body", _run_quimb_many_body),
        _run_timed("python_cotengra_tensor_network", _run_cotengra_tensor_network),
    ]
    cross_language = _build_cross_language_ode_receipt(workload_receipts)
    receipt: dict[str, object] = {
        "schema_version": A14_SCIML_DOMAIN_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A14",
        "active_pack_ids": list(_ACTIVE_A14_PACKS),
        "formally_replaced_pack_ids": list(_REPLACED_A14_PACKS),
        "workload_receipts": workload_receipts,
        "cross_language_receipt": cross_language,
        "unit_policy": "unit_bindings_required_no_unit_loss",
        "tolerance_policy": "absolute_or_relative_tolerance_required_no_bitwise_claims",
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    _validate_a14_receipt(receipt)
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _run_timed(pack_id: str, probe: Callable[[], dict[str, object]]) -> dict[str, object]:
    started = time.monotonic()
    receipt = probe()
    elapsed = round(time.monotonic() - started, 3)
    receipt["pack_id"] = pack_id
    receipt["status"] = "ACTIVE"
    receipt["resource_envelope"] = {
        "elapsed_seconds": elapsed,
        "bounded": True,
        "canonical_writes": 0,
    }
    receipt["promotion_allowed"] = False
    receipt["automatic_scientific_promotion"] = False
    receipt["canonical_writes"] = 0
    receipt["grants_authority"] = False
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _run_julia_sciml_ode(context: A14JuliaContext) -> dict[str, object]:
    env = os.environ.copy()
    if _JULIA_DEPOT_PATH in os.environ:
        env[_JULIA_DEPOT_PATH] = os.environ[_JULIA_DEPOT_PATH]
    proc = subprocess.run(  # noqa: S603
        [
            context.julia_executable,
            f"--project={context.julia_project_dir}",
            "--startup-file=no",
            "--history-file=no",
            "-e",
            _JULIA_SCIML_SMOKE_SCRIPT,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if proc.returncode != 0:
        raise SciMLDomainActivationError(f"Julia SciML smoke failed: {proc.stderr.strip()}")
    values = _parse_key_values(proc.stdout)
    terminal = _require_float(values, "terminal")
    expected = _require_float(values, "expected")
    abs_error = abs(terminal - expected)
    if abs_error > _ODE_ABS_TOLERANCE:
        raise SciMLDomainActivationError(f"Julia SciML ODE error too large: {abs_error}")
    trace = {
        "t": [0.0, 0.5, 1.0],
        "terminal": terminal,
        "expected": expected,
        "abs_error": abs_error,
    }
    return _domain_receipt(
        family="sciml",
        language="julia",
        backend_versions={
            "julia": context.julia_version,
            "sciml_project_toml_sha256": context.project_toml_sha256,
            "sciml_manifest_toml_sha256": context.manifest_toml_sha256,
            "julia_depot_role": context.julia_depot_role,
        },
        solver={"name": values.get("solver", "Tsit5"), "family": "ode_explicit_runge_kutta"},
        unit_bindings=("time:s", "state:dimensionless"),
        tolerance={"abs": _ODE_ABS_TOLERANCE, "rel": _ODE_REL_TOLERANCE},
        dataset={"kind": "synthetic", "model": "du/dt=-2u", "initial_state": 1.0},
        diagnostics={"terminal": terminal, "expected": expected, "abs_error": abs_error},
        trace=trace,
    )


def _run_diffrax_ode() -> dict[str, object]:
    diffrax = _import_module("diffrax")
    jax = _import_module("jax")
    jnp = _import_module("jax.numpy")
    cast(Any, jax).config.update("jax_enable_x64", True)
    term = diffrax.ODETerm(lambda _t, y, _args: -2.0 * y)
    save_times = jnp.array([0.0, 0.5, 1.0])
    solution = diffrax.diffeqsolve(
        term,
        diffrax.Tsit5(),
        t0=0.0,
        t1=1.0,
        dt0=0.05,
        y0=jnp.array(1.0),
        saveat=diffrax.SaveAt(ts=save_times),
        stepsize_controller=diffrax.PIDController(rtol=1e-8, atol=1e-10),
        max_steps=64,
    )
    values = [float(item) for item in list(solution.ys)]
    expected = math.exp(-2.0)
    abs_error = abs(values[-1] - expected)
    if abs_error > _ODE_ABS_TOLERANCE:
        raise SciMLDomainActivationError(f"Diffrax ODE error too large: {abs_error}")
    trace = {"t": [0.0, 0.5, 1.0], "values": values, "expected_terminal": expected}
    return _domain_receipt(
        family="sciml",
        language="python",
        backend_versions={
            "diffrax": _distribution_version("diffrax"),
            "jax": _distribution_version("jax"),
            "jaxlib": _distribution_version("jaxlib"),
        },
        solver={"name": "Tsit5", "family": "ode_explicit_runge_kutta"},
        unit_bindings=("time:s", "state:dimensionless"),
        tolerance={"abs": _ODE_ABS_TOLERANCE, "rel": _ODE_REL_TOLERANCE},
        dataset={"kind": "synthetic", "model": "dy/dt=-2y", "initial_state": 1.0},
        diagnostics={"terminal": values[-1], "expected": expected, "abs_error": abs_error},
        trace=trace,
    )


def _run_qutip_quantum() -> dict[str, object]:
    np = _import_module("numpy")
    qt = _import_module("qutip")
    hamiltonian = 0.5 * math.pi * qt.sigmax()
    psi0 = qt.basis(2, 0)
    tlist = np.array([0.0, 0.5, 1.0])
    result = qt.sesolve(hamiltonian, psi0, tlist)
    probability_one = float(abs(qt.basis(2, 1).dag() * result.states[-1]) ** 2)
    if probability_one < _QUTIP_TRANSFER_MIN:
        raise SciMLDomainActivationError(f"QuTiP state transfer too small: {probability_one}")
    trace = {"t": [0.0, 0.5, 1.0], "terminal_probability_one": probability_one}
    return _domain_receipt(
        family="quantum",
        language="python",
        backend_versions={"qutip": _distribution_version("qutip")},
        solver={"name": "sesolve", "family": "schrodinger_ode"},
        unit_bindings=("time:s", "hamiltonian:rad/s", "probability:dimensionless"),
        tolerance={"abs": 1e-6, "rel": 1e-6},
        dataset={"kind": "synthetic", "model": "two_level_pi_pulse"},
        diagnostics={"terminal_probability_one": probability_one},
        trace=trace,
    )


def _run_astropy_astronomy() -> dict[str, object]:
    coordinates = _import_module("astropy.coordinates")
    units = _import_module("astropy.units")
    sky = coordinates.SkyCoord(ra=10 * units.degree, dec=20 * units.degree, frame="icrs")
    galactic = sky.galactic
    l_degree = float(galactic.l.degree)
    b_degree = float(galactic.b.degree)
    if not (
        _GALACTIC_LONGITUDE_MIN <= l_degree < _GALACTIC_LONGITUDE_MAX
        and _GALACTIC_LATITUDE_MIN <= b_degree <= _GALACTIC_LATITUDE_MAX
    ):
        raise SciMLDomainActivationError("Astropy coordinate transform produced invalid range")
    trace: dict[str, object] = {
        "icrs": {"ra_deg": 10.0, "dec_deg": 20.0},
        "galactic": {"l": l_degree, "b": b_degree},
    }
    return _domain_receipt(
        family="astronomy",
        language="python",
        backend_versions={"astropy": _distribution_version("astropy")},
        solver={"name": "SkyCoord.transform_to", "family": "coordinate_transform"},
        unit_bindings=("right_ascension:deg", "declination:deg", "galactic_longitude:deg"),
        tolerance={"abs": 1e-10, "rel": 1e-10},
        dataset={"kind": "synthetic", "frame": "icrs_single_coordinate"},
        diagnostics={"galactic_l_deg": l_degree, "galactic_b_deg": b_degree},
        trace=trace,
    )


def _run_cantera_combustion() -> dict[str, object]:
    ct = _import_module("cantera")
    gas = ct.Solution("gri30.yaml")
    gas.TPX = 1000.0, ct.one_atm, "CH4:1,O2:2,N2:7.52"
    gas.equilibrate("HP")
    flame_temperature = float(gas.T)
    co2_fraction = float(gas["CO2"].X[0])
    h2o_fraction = float(gas["H2O"].X[0])
    if flame_temperature < _CANTERA_FLAME_TEMP_MIN or co2_fraction <= 0.0 or h2o_fraction <= 0.0:
        raise SciMLDomainActivationError("Cantera HP equilibrium did not ignite methane mix")
    trace: dict[str, object] = {
        "initial_temperature_K": 1000.0,
        "final_temperature_K": flame_temperature,
        "co2_mole_fraction": co2_fraction,
        "h2o_mole_fraction": h2o_fraction,
    }
    return _domain_receipt(
        family="combustion",
        language="python",
        backend_versions={"cantera": _distribution_version("cantera")},
        solver={"name": "equilibrate_HP", "family": "chemical_equilibrium"},
        unit_bindings=("temperature:K", "pressure:Pa", "composition:mole_fraction"),
        tolerance={"abs": 1e-8, "rel": 1e-8},
        dataset={"kind": "synthetic", "mechanism": "gri30", "mixture": "CH4/O2/N2"},
        diagnostics={
            "flame_temperature_K": flame_temperature,
            "co2_mole_fraction": co2_fraction,
            "h2o_mole_fraction": h2o_fraction,
        },
        trace=trace,
    )


def _run_native_battery_rc() -> dict[str, object]:
    dt_seconds = 60.0
    capacity_coulomb = 3600.0
    current_ampere = 0.2
    internal_resistance_ohm = 0.05
    soc = 1.0
    voltages: list[float] = []
    for _ in range(60):
        soc -= current_ampere * dt_seconds / capacity_coulomb
        open_circuit_voltage = 3.0 + 1.2 * soc
        voltages.append(open_circuit_voltage - current_ampere * internal_resistance_ohm)
    if not (_BATTERY_FINAL_SOC_MIN <= soc <= _BATTERY_FINAL_SOC_MAX):
        raise SciMLDomainActivationError(f"battery SOC drifted: {soc}")
    if any(a < b for a, b in pairwise(voltages)):
        raise SciMLDomainActivationError("battery voltage did not monotonically decrease")
    trace: dict[str, object] = {
        "final_soc": soc,
        "terminal_voltage": voltages[-1],
        "steps": len(voltages),
    }
    return _domain_receipt(
        family="battery",
        language="python",
        backend_versions={"native": "srl-a14-rc-battery-v1"},
        solver={"name": "explicit_euler", "family": "bounded_state_space_model"},
        unit_bindings=("time:s", "current:A", "capacity:C", "voltage:V", "resistance:ohm"),
        tolerance={"abs": 1e-12, "rel": 1e-12},
        dataset={"kind": "synthetic", "model": "single_cell_rc_discharge"},
        diagnostics={"final_soc": soc, "terminal_voltage": voltages[-1]},
        trace=trace,
    )


def _run_quimb_many_body() -> dict[str, object]:
    np = _import_module("numpy")
    qu = _import_module("quimb")
    hamiltonian = qu.ham_heis(2, j=1.0, b=0.0, sparse=False)
    eigenvalues = [float(item) for item in np.linalg.eigvalsh(np.asarray(hamiltonian))]
    ground = min(eigenvalues)
    if abs(ground - _HEISENBERG_GROUND_EXPECTED) > _HEISENBERG_GROUND_TOLERANCE:
        raise SciMLDomainActivationError(f"unexpected Heisenberg ground state: {ground}")
    trace = {"eigenvalues": eigenvalues, "ground_state_energy": ground}
    return _domain_receipt(
        family="quantum_many_body",
        language="python",
        backend_versions={"quimb": _distribution_version("quimb")},
        solver={"name": "eigvalsh", "family": "exact_diagonalization"},
        unit_bindings=("energy:dimensionless", "spin:dimensionless"),
        tolerance={"abs": 1e-9, "rel": 1e-9},
        dataset={"kind": "synthetic", "model": "two_site_heisenberg_chain"},
        diagnostics={"ground_state_energy": ground},
        trace=trace,
    )


def _run_cotengra_tensor_network() -> dict[str, object]:
    ctg = _import_module("cotengra")
    inputs = [("a", "b"), ("b", "c"), ("c", "d")]
    output = ("a", "d")
    size_dict = {"a": 2, "b": 3, "c": 4, "d": 5}
    tree = ctg.array_contract_tree(inputs, output, size_dict, optimize="greedy")
    cost = float(tree.contraction_cost())
    width = float(tree.contraction_width())
    if cost <= 0.0 or width <= 0.0:
        raise SciMLDomainActivationError("Cotengra contraction path metrics invalid")
    trace: dict[str, object] = {"contraction_cost": cost, "contraction_width": width}
    return _domain_receipt(
        family="tensor_networks",
        language="python",
        backend_versions={"cotengra": _distribution_version("cotengra")},
        solver={"name": "array_contract_tree_greedy", "family": "tensor_contraction_path"},
        unit_bindings=("bond_dimension:count", "flop_cost:operation_count"),
        tolerance={"abs": 0.0, "rel": 1e-12},
        dataset={"kind": "synthetic", "network": "three_tensor_chain"},
        diagnostics={"contraction_cost": cost, "contraction_width": width},
        trace=trace,
    )


def _domain_receipt(  # noqa: PLR0913
    *,
    family: str,
    language: str,
    backend_versions: dict[str, object],
    solver: dict[str, object],
    unit_bindings: tuple[str, ...],
    tolerance: dict[str, float],
    dataset: dict[str, object],
    diagnostics: dict[str, object],
    trace: dict[str, object],
) -> dict[str, object]:
    trace_sha256 = hashlib.sha256(dumps(trace)).hexdigest()
    return {
        "family": family,
        "language": language,
        "backend_versions": backend_versions,
        "solver": solver,
        "unit_bindings": list(unit_bindings),
        "tolerance": tolerance,
        "dataset": dataset,
        "diagnostics": diagnostics,
        "trace_sha256": trace_sha256,
        "trace_digest_algorithm": "sha256",
        "bitwise_identity_claimed": False,
    }


def _build_cross_language_ode_receipt(
    workload_receipts: list[dict[str, object]],
) -> dict[str, object]:
    by_id = {str(item.get("pack_id")): item for item in workload_receipts}
    julia = by_id["julia_sciml_ode"]
    python = by_id["python_diffrax_ode"]
    j_diag = cast(dict[str, object], julia["diagnostics"])
    p_diag = cast(dict[str, object], python["diagnostics"])
    delta = abs(float(cast(float, j_diag["terminal"])) - float(cast(float, p_diag["terminal"])))
    if delta > _ODE_ABS_TOLERANCE:
        raise SciMLDomainActivationError(f"cross-language ODE delta too large: {delta}")
    receipt: dict[str, object] = {
        "schema_version": "A14CrossLanguageToleranceReceipt/v1",
        "comparison_label": "julia_sciml_vs_python_diffrax_ode",
        "receipt_ids": [julia["receipt_id"], python["receipt_id"]],
        "languages": ["julia", "python"],
        "solver_families": ["ode_explicit_runge_kutta"],
        "tolerance_abs": _ODE_ABS_TOLERANCE,
        "tolerance_rel": _ODE_REL_TOLERANCE,
        "observed_delta": delta,
        "comparison_scope": "bounded_real_workload_tolerance_only",
        "bitwise_identity_claimed": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def _validate_a14_receipt(receipt: dict[str, object]) -> None:  # noqa: C901
    if receipt.get("schema_version") != A14_SCIML_DOMAIN_RECEIPT_SCHEMA_VERSION:
        raise SciMLDomainActivationError("A14 receipt schema drifted")
    if receipt.get("active_pack_ids") != list(_ACTIVE_A14_PACKS):
        raise SciMLDomainActivationError("A14 active pack ids drifted")
    if receipt.get("formally_replaced_pack_ids") != list(_REPLACED_A14_PACKS):
        raise SciMLDomainActivationError("A14 replacement ids drifted")
    workloads = receipt.get("workload_receipts")
    if not isinstance(workloads, list) or len(workloads) != len(_ACTIVE_A14_PACKS):
        raise SciMLDomainActivationError("A14 workload receipt count mismatch")
    for item in workloads:
        if not isinstance(item, dict):
            raise SciMLDomainActivationError("A14 workload receipt is not an object")
        if item.get("status") != "ACTIVE":
            raise SciMLDomainActivationError(f"A14 {item.get('pack_id')} is not ACTIVE")
        if item.get("bitwise_identity_claimed") is not False:
            raise SciMLDomainActivationError(f"A14 {item.get('pack_id')} claimed bitwise identity")
        if not item.get("unit_bindings") or not isinstance(item.get("solver"), dict):
            raise SciMLDomainActivationError(f"A14 {item.get('pack_id')} missing units or solver")
        tolerance = item.get("tolerance")
        if not isinstance(tolerance, dict) or (
            float(cast(float, tolerance.get("abs", 0.0))) == 0.0
            and float(cast(float, tolerance.get("rel", 0.0))) == 0.0
        ):
            raise SciMLDomainActivationError(f"A14 {item.get('pack_id')} missing tolerances")
        if (
            item.get("promotion_allowed") is not False
            or item.get("automatic_scientific_promotion") is not False
            or item.get("canonical_writes") != 0
            or item.get("grants_authority") is not False
        ):
            raise SciMLDomainActivationError(f"A14 {item.get('pack_id')} is not authority-negative")
    cross = receipt.get("cross_language_receipt")
    if not isinstance(cross, dict) or cross.get("bitwise_identity_claimed") is not False:
        raise SciMLDomainActivationError("A14 cross-language receipt is invalid")


def _parse_key_values(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _require_float(values: dict[str, str], key: str) -> float:
    try:
        return float(values[key])
    except (KeyError, ValueError) as exc:
        raise SciMLDomainActivationError(f"Julia SciML smoke missing {key}") from exc


def _import_module(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise SciMLDomainActivationError(f"A14 optional runtime missing: {module_name}") from exc


def _distribution_version(distribution_name: str) -> str:
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise SciMLDomainActivationError(f"distribution missing: {distribution_name}") from exc


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object_id(payload: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(dumps(payload)).hexdigest()


_JULIA_PREPARE_SCRIPT: Final[str] = r"""
import Pkg
project = ENV["SRL_A14_JULIA_PROJECT_DIR"]
Pkg.activate(project; shared=false)
Pkg.add([
    Pkg.PackageSpec(name="SciMLBase"),
    Pkg.PackageSpec(name="OrdinaryDiffEq"),
])
Pkg.instantiate()
Pkg.precompile()
"""

_JULIA_SCIML_SMOKE_SCRIPT: Final[str] = r"""
using SciMLBase
using OrdinaryDiffEq
f(u, p, t) = -p[1] * u
prob = ODEProblem(f, 1.0, (0.0, 1.0), [2.0])
sol = solve(prob, Tsit5(); abstol=1e-9, reltol=1e-9, saveat=[0.0, 0.5, 1.0])
println("solver=Tsit5")
println("points=$(length(sol.u))")
println("terminal=$(sol.u[end])")
println("expected=$(exp(-2.0))")
"""

__all__ = [
    "A14_SCIML_DOMAIN_RECEIPT_SCHEMA_VERSION",
    "A14JuliaContext",
    "SciMLDomainActivationError",
    "prepare_a14_julia_project",
    "resolve_a14_julia_runtime",
    "run_a14_sciml_domain_smoke",
]
