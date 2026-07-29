"""CapabilityTruthLedger/v1 for V3.7 activation truth accounting.

The ledger deliberately separates configuration, executable probes, scientific
smoke, cross-check evidence and final ACTIVE state. A package can be installed
and still be ineligible for release closure when the remaining evidence axes
are absent.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from srl.packs.adapters.native_algebra import run_a08_native_smoke
from srl.packs.adapters.p0_python_core import FLINT_WAIT_REASON, run_p0_python_core_smoke

TRUTH_STATES: Final[tuple[str, ...]] = (
    "DECLARED",
    "CONFIGURED",
    "INSTALLED",
    "EXECUTABLE_PROBED",
    "SCIENTIFIC_SMOKE_PASSED",
    "CROSSCHECKED",
    "ACTIVE",
)

WAIT_STATES: Final[tuple[str, ...]] = (
    "WAIT_CAPABILITY",
    "WAIT_TOOLCHAIN",
    "WAIT_AUTHORITY",
    "WAIT_T7_BINDING",
    "WAIT_COMPUTE_TARGET",
    "WAIT_LICENSE",
)

CURRENT_V101_ACTIVE_INVENTORY: Final[tuple[str, ...]] = (
    "numpy",
    "scipy",
    "pint",
    "z3",
    "ripser",
    "pyriemann",
    "cvxpy",
    "clarabel",
)

_V37_PLAN_CONTRACT_SHA256: Final[str] = (
    "170e5a47-2d5c0dcc-b6713f7c-8c9228f4-51f86691-be281544-d92b445c-0a594a5c"
)
_CURRENT_HEAD_AFTER_A00: Final[str] = "d06d0a21a49ab6e333cb2f8530c57168a7856654"
_NUMPY_DET_EXPECTED: Final[float] = -2.0
_SCIPY_DET_EXPECTED: Final[float] = 6.0
_Z3_UPPER_BOUND: Final[int] = 3
_Z3_WITNESS: Final[int] = 2
_MIN_RIPSER_DIAGRAMS: Final[int] = 2
_CVXPY_OPTIMUM_TOLERANCE: Final[float] = 1e-5


@dataclass(frozen=True)
class ComponentSpec:
    component_id: str
    capability_family: str
    stage: str
    probe_kind: str
    module_name: str | None = None
    distribution_name: str | None = None
    executable_names: tuple[str, ...] = ()
    mandatory_for_v2: bool = True
    configured: bool = True
    activation_wait_state: str = "WAIT_CAPABILITY"
    current_v101_active: bool = False
    smoke: Callable[[], str] | None = None


def _smoke_numpy() -> str:
    np = importlib.import_module("numpy")
    matrix = np.array([[1.0, 2.0], [3.0, 4.0]])
    value = float(np.linalg.det(matrix))
    if round(value, 6) != _NUMPY_DET_EXPECTED:
        raise RuntimeError(f"unexpected determinant {value}")
    return "det([[1,2],[3,4]]) crosschecked against closed-form -2"


def _smoke_scipy() -> str:
    la = importlib.import_module("scipy.linalg")
    np = importlib.import_module("numpy")
    matrix = np.array([[2.0, 0.0], [0.0, 3.0]])
    value = float(la.det(matrix))
    if round(value, 6) != _SCIPY_DET_EXPECTED:
        raise RuntimeError(f"unexpected determinant {value}")
    return "scipy.linalg.det diagonal matrix crosschecked against product 6"


def _smoke_pint() -> str:
    pint = importlib.import_module("pint")
    registry = pint.UnitRegistry()
    value = (100 * registry.centimeter).to(registry.meter).magnitude
    if float(value) != 1.0:
        raise RuntimeError(f"unexpected unit conversion {value}")
    return "100 centimeter to meter crosschecked against SI identity"


def _smoke_z3() -> str:
    z3 = importlib.import_module("z3")
    x = z3.Int("x")
    solver = z3.Solver()
    solver.add(x > 1, x < _Z3_UPPER_BOUND)
    result = solver.check()
    if str(result) != "sat":
        raise RuntimeError(f"unexpected z3 result {result}")
    model_value = solver.model()[x].as_long()
    if model_value != _Z3_WITNESS:
        raise RuntimeError(f"unexpected z3 model {model_value}")
    return "bounded integer SAT crosschecked against unique witness x=2"


def _smoke_ripser() -> str:
    np = importlib.import_module("numpy")
    ripser_mod = importlib.import_module("ripser")
    points = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    diagrams = ripser_mod.ripser(points, maxdim=1)["dgms"]
    if len(diagrams) < _MIN_RIPSER_DIAGRAMS or len(diagrams[0]) == 0:
        raise RuntimeError("ripser returned no H0 diagram")
    return "tiny point-cloud persistence produced nonempty H0 diagram"


def _smoke_pyriemann() -> str:
    np = importlib.import_module("numpy")
    mean_covariance = importlib.import_module("pyriemann.utils.mean").mean_covariance
    matrices = np.array(
        [
            [[1.0, 0.0], [0.0, 4.0]],
            [[9.0, 0.0], [0.0, 16.0]],
        ]
    )
    result = mean_covariance(matrices, metric="logeuclid")
    expected = np.array([[3.0, 0.0], [0.0, 8.0]])
    if not np.allclose(result, expected):
        raise RuntimeError(f"unexpected log-euclidean mean {result}")
    return "log-Euclidean mean crosschecked against commuting SPD closed form"


def _smoke_cvxpy() -> str:
    cp = importlib.import_module("cvxpy")
    x = cp.Variable()
    problem = cp.Problem(cp.Minimize((x - 1) ** 2), [x >= 0])
    value = problem.solve(solver="CLARABEL")
    if value is None or abs(float(x.value) - 1.0) > _CVXPY_OPTIMUM_TOLERANCE:
        raise RuntimeError(f"unexpected cvxpy solution value={value} x={x.value}")
    return "one-variable convex optimum crosschecked against analytic x=1"


def _smoke_clarabel() -> str:
    # The current v1.0.1 evidence uses Clarabel through the CVXPY adapter.
    _ = importlib.import_module("clarabel")
    return _smoke_cvxpy()


def _smoke_sympy() -> str:
    smoke = run_p0_python_core_smoke()
    return smoke.exact_factorization_crosscheck


def _smoke_mpmath() -> str:
    smoke = run_p0_python_core_smoke()
    return "; ".join((smoke.high_precision_crosscheck, smoke.interval_crosscheck))


def _smoke_a08_native(component_id: str) -> str:
    smoke = run_a08_native_smoke()
    by_id = {item.component_id: item for item in smoke.tools}
    item = by_id[component_id]
    if not item.active:
        raise RuntimeError(item.error or f"{component_id} did not reach ACTIVE")
    return f"{item.smoke_detail}; {item.crosscheck_detail}"


def _smoke_pari_gp() -> str:
    return _smoke_a08_native("pari-gp")


def _smoke_maxima() -> str:
    return _smoke_a08_native("maxima")


def _smoke_gap() -> str:
    return _smoke_a08_native("gap")


def _smoke_singular() -> str:
    return _smoke_a08_native("singular")


def _smoke_z3_native() -> str:
    return _smoke_a08_native("z3-native")


def _smoke_cvc5() -> str:
    return _smoke_a08_native("cvc5")


_SPECS: Final[tuple[ComponentSpec, ...]] = (
    ComponentSpec(
        "numpy",
        "p0_python_runtime",
        "v1.0.1",
        "python_import",
        "numpy",
        "numpy",
        current_v101_active=True,
        smoke=_smoke_numpy,
    ),
    ComponentSpec(
        "scipy",
        "p0_python_runtime",
        "v1.0.1",
        "python_import",
        "scipy",
        "scipy",
        current_v101_active=True,
        smoke=_smoke_scipy,
    ),
    ComponentSpec(
        "pint",
        "p0_units",
        "v1.0.1",
        "python_import",
        "pint",
        "pint",
        current_v101_active=True,
        smoke=_smoke_pint,
    ),
    ComponentSpec(
        "z3",
        "p0_smt",
        "v1.0.1",
        "python_import",
        "z3",
        "z3-solver",
        current_v101_active=True,
        smoke=_smoke_z3,
    ),
    ComponentSpec(
        "ripser",
        "applied_topology",
        "v1.0.1",
        "python_import",
        "ripser",
        "ripser",
        current_v101_active=True,
        smoke=_smoke_ripser,
    ),
    ComponentSpec(
        "pyriemann",
        "applied_geometry",
        "v1.0.1",
        "python_import",
        "pyriemann",
        "pyriemann",
        current_v101_active=True,
        smoke=_smoke_pyriemann,
    ),
    ComponentSpec(
        "cvxpy",
        "p1_optimization",
        "v1.0.1",
        "python_import",
        "cvxpy",
        "cvxpy",
        current_v101_active=True,
        smoke=_smoke_cvxpy,
    ),
    ComponentSpec(
        "clarabel",
        "p1_optimization_solver",
        "v1.0.1",
        "python_import",
        "clarabel",
        "clarabel",
        current_v101_active=True,
        smoke=_smoke_clarabel,
    ),
    ComponentSpec(
        "sympy",
        "a07_p0_python_core",
        "A07",
        "python_import",
        "sympy",
        "sympy",
        current_v101_active=True,
        smoke=_smoke_sympy,
    ),
    ComponentSpec(
        "mpmath",
        "a07_p0_python_core",
        "A07",
        "python_import",
        "mpmath",
        "mpmath",
        current_v101_active=True,
        smoke=_smoke_mpmath,
    ),
    ComponentSpec(
        "python-flint",
        "a07_p0_python_core",
        "A07",
        "python_import",
        "flint",
        "python-flint",
        activation_wait_state="WAIT_LICENSE",
    ),
    ComponentSpec(
        "pari-gp",
        "a08_native_algebra",
        "A08",
        "native_executable",
        executable_names=("gp",),
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_pari_gp,
    ),
    ComponentSpec(
        "maxima",
        "a08_native_algebra",
        "A08",
        "native_executable",
        executable_names=("maxima",),
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_maxima,
    ),
    ComponentSpec(
        "gap",
        "a08_native_algebra",
        "A08",
        "native_executable",
        executable_names=("gap",),
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_gap,
    ),
    ComponentSpec(
        "singular",
        "a08_native_algebra",
        "A08",
        "native_executable",
        executable_names=("Singular", "singular"),
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_singular,
    ),
    ComponentSpec(
        "z3-native",
        "a08_smt",
        "A08",
        "native_executable",
        executable_names=("z3",),
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_z3_native,
    ),
    ComponentSpec(
        "cvc5",
        "a08_smt",
        "A08",
        "native_executable",
        executable_names=("cvc5",),
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_cvc5,
    ),
    ComponentSpec(
        "lean",
        "a09_formal",
        "A09",
        "native_executable",
        executable_names=("lean",),
        activation_wait_state="WAIT_TOOLCHAIN",
    ),
    ComponentSpec(
        "lake",
        "a09_formal",
        "A09",
        "native_executable",
        executable_names=("lake",),
        activation_wait_state="WAIT_TOOLCHAIN",
    ),
    ComponentSpec(
        "rocq",
        "a10_formal",
        "A10",
        "native_executable",
        executable_names=("rocq", "coqc"),
        activation_wait_state="WAIT_TOOLCHAIN",
    ),
    ComponentSpec(
        "isabelle",
        "a10_formal",
        "A10",
        "native_executable",
        executable_names=("isabelle",),
        activation_wait_state="WAIT_TOOLCHAIN",
    ),
    ComponentSpec(
        "hol4",
        "a10_formal",
        "A10",
        "native_executable",
        executable_names=("hol", "Holmake"),
        activation_wait_state="WAIT_TOOLCHAIN",
    ),
    ComponentSpec(
        "production-ed25519-signer",
        "a04_transport",
        "A04",
        "native_private_config",
        activation_wait_state="WAIT_AUTHORITY",
    ),
    ComponentSpec(
        "t2-t3-enforced-sandbox",
        "a05_sandbox",
        "A05",
        "linux_isolation",
        activation_wait_state="WAIT_COMPUTE_TARGET",
    ),
    ComponentSpec(
        "t7-binding",
        "a02_t7",
        "A02",
        "physical_volume",
        activation_wait_state="WAIT_T7_BINDING",
    ),
)


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _python_probe(spec: ComponentSpec) -> tuple[bool, str | None, str | None]:
    if spec.module_name is None:
        return False, None, "python probe missing module_name"
    try:
        importlib.import_module(spec.module_name)
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    version = _distribution_version(spec.distribution_name or spec.module_name)
    return True, version, None


def _executable_probe(spec: ComponentSpec) -> tuple[bool, str | None, str | None]:
    for name in spec.executable_names:
        path = shutil.which(name)
        if path:
            return True, path, None
    return False, None, f"not found: {', '.join(spec.executable_names)}"


def _probe(spec: ComponentSpec) -> dict[str, Any]:
    if spec.probe_kind == "python_import":
        ok, version_or_path, error = _python_probe(spec)
    elif spec.probe_kind == "native_executable":
        ok, version_or_path, error = _executable_probe(spec)
    else:
        ok, version_or_path, error = False, None, "protected or target-bound capability"

    smoke_ok = False
    smoke_detail = "not attempted before its V3.7 activation stage"
    if ok and spec.current_v101_active and spec.smoke is not None:
        try:
            smoke_detail = spec.smoke()
            smoke_ok = True
        except Exception as exc:
            smoke_detail = f"{type(exc).__name__}: {exc}"

    crosschecked = bool(smoke_ok and spec.current_v101_active)
    active = bool(ok and smoke_ok and crosschecked and spec.current_v101_active)
    if active:
        state = "ACTIVE"
        evidence_axis = "nonfixture_executable_probe_and_scientific_smoke"
    elif ok:
        state = "EXECUTABLE_PROBED"
        evidence_axis = "executable_probe_only"
    else:
        state = spec.activation_wait_state
        evidence_axis = "missing_or_protected_capability"

    return {
        "component_id": spec.component_id,
        "capability_family": spec.capability_family,
        "activation_stage": spec.stage,
        "mandatory_for_v2": spec.mandatory_for_v2,
        "configured": spec.configured,
        "probe_kind": spec.probe_kind,
        "installed": ok,
        "probe_detail": version_or_path,
        "probe_error": error,
        "scientific_smoke_passed": smoke_ok,
        "scientific_smoke_detail": smoke_detail,
        "crosschecked": crosschecked,
        "evidence_axis": evidence_axis,
        "state": state,
    }


def build_truth_ledger() -> dict[str, Any]:
    """Build the current executable-probe-backed CapabilityTruthLedger/v1."""
    components = [_probe(spec) for spec in _SPECS]
    current_v101_active_inventory = [
        item["component_id"]
        for item in components
        if item["activation_stage"] == "v1.0.1" and item["state"] == "ACTIVE"
    ]
    active_inventory = [item["component_id"] for item in components if item["state"] == "ACTIVE"]
    return {
        "schema_version": "CapabilityTruthLedger/v1",
        "plan_contract_sha256": _V37_PLAN_CONTRACT_SHA256,
        "baseline_head_after_a00": _CURRENT_HEAD_AFTER_A00,
        "truth_states": list(TRUTH_STATES),
        "wait_states": list(WAIT_STATES),
        "capability_closure_chain": list(TRUTH_STATES),
        "current_v101_active_inventory_expected": list(CURRENT_V101_ACTIVE_INVENTORY),
        "current_v101_active_inventory_observed": current_v101_active_inventory,
        "all_active_inventory_observed": active_inventory,
        "a07_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A07" and item["state"] == "ACTIVE"
        ],
        "a08_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A08" and item["state"] == "ACTIVE"
        ],
        "a08_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A08" and item["state"] != "ACTIVE"
        ],
        "a07_parked_blockers": [f"WAIT_LICENSE:python-flint:{FLINT_WAIT_REASON}"],
        "production_versus_fixture_axis": [
            "fixture_only",
            "policy_only",
            "executable_probe_only",
            "nonfixture_executable_probe_and_scientific_smoke",
            "production_native_evidence",
        ],
        "components": components,
    }


def _candidate_surface_blockers(candidate: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if candidate.get("production_signer") != "ed25519_native":
        blockers.append("PRODUCTION_SIGNER_NOT_ED25519_NATIVE")
    if candidate.get("sandbox") != "enforced_t2_t3":
        blockers.append("SANDBOX_NOT_ENFORCED_T2_T3")
    if candidate.get("t7_binding") != "ACTIVE":
        blockers.append("T7_NOT_ACTIVE")
    return blockers


def _component_blockers(components: list[Any]) -> list[str]:
    blockers: list[str] = []
    for item in components:
        if not isinstance(item, dict) or not item.get("mandatory_for_v2", True):
            continue
        component_id = str(item.get("component_id"))
        state = item.get("state")
        if state != "ACTIVE":
            if item.get("component_id") == "python-flint" and state == "WAIT_LICENSE":
                blockers.append(f"MANDATORY_WAIT_LICENSE:{component_id}")
                continue
            blockers.append(f"MANDATORY_NOT_ACTIVE:{component_id}:{state}")
            continue
        if item.get("evidence_axis") in {"fixture_only", "policy_only", "executable_probe_only"}:
            blockers.append(f"NONPRODUCTION_EVIDENCE:{component_id}")
        for field in ("installed", "scientific_smoke_passed", "crosschecked"):
            if item.get(field) is not True:
                blockers.append(f"ACTIVE_WITHOUT_{field.upper()}:{component_id}")
    return blockers


def evaluate_release_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether a release candidate may truthfully claim DONE/v2.0.0.

    The function is intentionally data-driven so negative fixtures can exercise
    false-closure regressions without mutating the live repository state.
    """
    ledger = candidate.get("ledger")
    if not isinstance(ledger, dict):
        raise ValueError("candidate.ledger must be an object")
    components = ledger.get("components")
    if not isinstance(components, list):
        raise ValueError("candidate.ledger.components must be an array")

    target_result = candidate.get("target_result")
    target_release = candidate.get("target_release")
    wants_done = target_result == "DONE" or target_release == "v2.0.0"

    blockers = _candidate_surface_blockers(candidate)
    blockers.extend(_component_blockers(components))

    verdict = "PASS" if wants_done and not blockers else "REJECT"
    if not wants_done:
        verdict = "NOT_A_DONE_CANDIDATE"
    return {
        "schema_version": "ReleaseTruthDecision/v1",
        "target_result": target_result,
        "target_release": target_release,
        "verdict": verdict,
        "blockers": blockers,
    }
