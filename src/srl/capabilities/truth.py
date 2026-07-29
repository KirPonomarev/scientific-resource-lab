"""CapabilityTruthLedger/v1 for V3.7 activation truth accounting.

The ledger deliberately separates configuration, executable probes, scientific
smoke, cross-check evidence and final ACTIVE state. A package can be installed
and still be ineligible for release closure when the remaining evidence axes
are absent.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from srl.packs.adapters.native_algebra import run_a08_native_smoke
from srl.packs.adapters.p0_python_core import FLINT_WAIT_REASON, run_p0_python_core_smoke
from srl.packs.formal import independent_prover_pin_manifest_hash
from srl.packs.formal.lean import (
    default_corpus_pins,
    default_corpus_statements,
    default_lean_pins,
)

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
    "WAIT_COMPUTE_NODE",
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
_A13_CAUSAL_TRUE_EFFECT: Final[float] = 2.0
_A13_CAUSAL_EFFECT_TOLERANCE: Final[float] = 0.08
_A13_CAUSAL_FALSIFICATION_TOLERANCE: Final[float] = 0.25
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_A09_RECEIPT_PATH: Final[Path] = (
    _REPO_ROOT / "docs" / "verification" / "srf-v3-7-a09-lean-corpora-receipt.json"
)
_A10_RECEIPT_PATH: Final[Path] = (
    _REPO_ROOT / "docs" / "verification" / "srf-v3-7-a10-independent-provers-receipt.json"
)
_A11_RECEIPT_PATH: Final[Path] = (
    _REPO_ROOT / "docs" / "verification" / "srf-v3-7-a11-knowledge-graph-receipt.json"
)
_A12_RECEIPT_PATH: Final[Path] = (
    _REPO_ROOT / "docs" / "verification" / "srf-v3-7-a12-discovery-dynamics-receipt.json"
)
_A13_RECEIPT_PATH: Final[Path] = (
    _REPO_ROOT / "docs" / "verification" / "srf-v3-7-a13-applied-science-receipt.json"
)
_A14_RECEIPT_PATH: Final[Path] = (
    _REPO_ROOT / "docs" / "verification" / "srf-v3-7-a14-sciml-domain-receipt.json"
)
_EXPECTED_A09_COMPONENTS: Final[tuple[str, ...]] = (
    "lean",
    "lake",
    "mathlib",
    "cslib-index",
    "erdos-problems-metadata",
    "formal-conjectures",
)
_EXPECTED_A10_COMPONENTS: Final[tuple[str, ...]] = ("rocq", "isabelle", "hol4")
_EXPECTED_A10_TRANSLATION_MANIFESTS: Final[int] = 3
_EXPECTED_A11_COMPONENTS: Final[tuple[str, ...]] = (
    "openalex",
    "crossref",
    "arxiv",
    "oeis",
    "opencitations",
    "zbmath",
    "lmfdb",
    "cslib",
    "erdos_problems",
    "formal_conjectures",
)
_EXPECTED_A12_COMPONENTS: Final[tuple[str, ...]] = ("pysr", "pysindy", "pydmd")
_EXPECTED_A12_REPLACED: Final[tuple[str, ...]] = (
    "sr4mdl",
    "operon",
    "gplearn",
    "ai_feynman",
    "pykoopman",
    "dysts",
)
_EXPECTED_A13_COMPONENTS: Final[tuple[str, ...]] = (
    "ripser",
    "pyriemann",
    "cvxpy",
    "native_bayesian_conjugate",
    "native_causal_backdoor",
)
_EXPECTED_A13_REPLACED: Final[tuple[str, ...]] = (
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
_EXPECTED_A14_COMPONENTS: Final[tuple[str, ...]] = (
    "julia_sciml_ode",
    "python_diffrax_ode",
    "python_qutip_quantum",
    "python_astropy_astronomy",
    "python_cantera_combustion",
    "native_battery_rc",
    "python_quimb_many_body",
    "python_cotengra_tensor_network",
)
_EXPECTED_A14_REPLACED: Final[tuple[str, ...]] = (
    "julia_modelingtoolkit",
    "julia_datadrivendiffeq",
    "python_cadabra",
    "python_pybamm",
)
_EXPECTED_A15_COMPONENTS: Final[tuple[str, ...]] = (
    "petsc",
    "fenicsx",
    "pymor",
    "scikit-fem",
    "dedalus",
    "sagemath",
)


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


def _load_a09_receipt() -> dict[str, Any]:
    if not _A09_RECEIPT_PATH.exists():
        raise RuntimeError(f"A09 receipt missing: {_A09_RECEIPT_PATH.relative_to(_REPO_ROOT)}")
    receipt = json.loads(_A09_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("A09 receipt must be a JSON object")
    return receipt


def _check_a09_revision_bindings(proof_receipt: dict[str, Any], *, name: str) -> None:
    pins = default_lean_pins().to_dict()
    bindings = proof_receipt.get("revision_bindings")
    if bindings != pins:
        raise RuntimeError(f"{name} revision bindings do not match Lean/mathlib pins")


def _check_a09_corpus_pins(corpus_receipt: dict[str, Any]) -> None:
    expected_pins = [pin.to_dict() for pin in default_corpus_pins()]
    expected_statements = [statement.to_dict() for statement in default_corpus_statements()]
    if corpus_receipt.get("status") != "TRAVERSED":
        raise RuntimeError("A09 corpus traversal receipt is not TRAVERSED")
    if corpus_receipt.get("corpus_pins") != expected_pins:
        raise RuntimeError("A09 corpus pins do not match configured pins")
    checks = corpus_receipt.get("checks")
    if not isinstance(checks, list) or len(checks) != len(expected_statements):
        raise RuntimeError("A09 corpus checks do not match expected statement count")
    observed_statements = [item.get("statement") for item in checks if isinstance(item, dict)]
    if observed_statements != expected_statements:
        raise RuntimeError("A09 corpus statements do not match configured statements")
    if any(item.get("status") != "PASS" for item in checks if isinstance(item, dict)):
        raise RuntimeError("A09 corpus traversal contains a non-PASS check")


def _validated_a09_receipt(component_id: str) -> dict[str, Any]:  # noqa: C901, PLR0912
    receipt = _load_a09_receipt()
    if receipt.get("schema_version") != "StageCompletionReceipt/v1":
        raise RuntimeError("A09 receipt schema drifted")
    if receipt.get("stage_id") != "A09" or receipt.get("result") != "PASS":
        raise RuntimeError("A09 receipt is not a PASS receipt for stage A09")
    if receipt.get("stage_closure") != "A09_ACTIVE":
        raise RuntimeError("A09 receipt does not close A09_ACTIVE")
    if receipt.get("remaining_internal_waits") != []:
        raise RuntimeError("A09 receipt contains internal waits")
    active = receipt.get("active_packs")
    if not isinstance(active, list) or set(active) != set(_EXPECTED_A09_COMPONENTS):
        raise RuntimeError("A09 active_packs do not match expected components")
    if component_id not in active:
        raise RuntimeError(f"{component_id} is absent from A09 active_packs")

    checks = {
        str(item.get("check_id")): item
        for item in receipt.get("checks", [])
        if isinstance(item, dict)
    }
    if any(item.get("status") != "PASS" for item in checks.values()):
        raise RuntimeError("A09 receipt contains a non-PASS check")

    kernel = checks.get("A09-02-lean-kernel-accept-reject")
    if not isinstance(kernel, dict):
        raise RuntimeError("A09 kernel check missing")
    valid = kernel.get("valid_receipt")
    invalid = kernel.get("invalid_receipt")
    if not isinstance(valid, dict) or not isinstance(invalid, dict):
        raise RuntimeError("A09 kernel proof receipts missing")
    if valid.get("status") != "CHECKED" or valid.get("axioms") is None:
        raise RuntimeError("A09 valid theorem was not checked with axiom inventory")
    if invalid.get("status") != "REJECTED":
        raise RuntimeError("A09 invalid theorem was not rejected")
    _check_a09_revision_bindings(valid, name="valid theorem")
    _check_a09_revision_bindings(invalid, name="invalid theorem")

    mathlib = checks.get("A09-03-mathlib-import")
    if not isinstance(mathlib, dict) or not isinstance(mathlib.get("mathlib_receipt"), dict):
        raise RuntimeError("A09 mathlib check missing")
    mathlib_receipt = mathlib["mathlib_receipt"]
    if mathlib_receipt.get("status") != "CHECKED":
        raise RuntimeError("A09 mathlib theorem was not checked")
    if mathlib_receipt.get("uses_mathlib") is not True:
        raise RuntimeError("A09 mathlib receipt does not bind uses_mathlib=true")
    if mathlib_receipt.get("axioms") is None:
        raise RuntimeError("A09 mathlib receipt is missing axiom inventory")
    _check_a09_revision_bindings(mathlib_receipt, name="mathlib theorem")

    corpus = checks.get("A09-04-pinned-corpus-traversal")
    if not isinstance(corpus, dict) or not isinstance(corpus.get("corpus_receipt"), dict):
        raise RuntimeError("A09 corpus check missing")
    _check_a09_corpus_pins(corpus["corpus_receipt"])
    return receipt


def _smoke_a09_receipt(component_id: str) -> str:
    receipt = _validated_a09_receipt(component_id)
    return (
        f"A09 offline truth projection accepted {component_id} from "
        f"{receipt['receipt_id']} with Lean/mathlib pins and corpus hashes"
    )


def _smoke_a09_lean_kernel() -> str:
    return _smoke_a09_receipt("lean")


def _smoke_a09_lake() -> str:
    return _smoke_a09_receipt("lake")


def _smoke_a09_mathlib() -> str:
    return _smoke_a09_receipt("mathlib")


def _smoke_a09_cslib_index() -> str:
    return _smoke_a09_receipt("cslib-index")


def _smoke_a09_erdos_corpus() -> str:
    return _smoke_a09_receipt("erdos-problems-metadata")


def _smoke_a09_formal_conjectures() -> str:
    return _smoke_a09_receipt("formal-conjectures")


def _load_a10_receipt() -> dict[str, Any]:
    if not _A10_RECEIPT_PATH.exists():
        raise RuntimeError(f"A10 receipt missing: {_A10_RECEIPT_PATH.relative_to(_REPO_ROOT)}")
    receipt = json.loads(_A10_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("A10 receipt must be a JSON object")
    return receipt


def _validated_a10_receipt(component_id: str) -> dict[str, Any]:  # noqa: C901, PLR0912
    receipt = _load_a10_receipt()
    if receipt.get("schema_version") != "StageCompletionReceipt/v1":
        raise RuntimeError("A10 receipt schema drifted")
    if receipt.get("stage_id") != "A10" or receipt.get("result") != "PASS":
        raise RuntimeError("A10 receipt is not a PASS receipt for stage A10")
    if receipt.get("stage_closure") != "A10_ACTIVE":
        raise RuntimeError("A10 receipt does not close A10_ACTIVE")
    if receipt.get("remaining_internal_waits") != []:
        raise RuntimeError("A10 receipt contains internal waits")
    active = receipt.get("active_packs")
    if not isinstance(active, list) or set(active) != set(_EXPECTED_A10_COMPONENTS):
        raise RuntimeError("A10 active_packs do not match expected components")
    if component_id not in active:
        raise RuntimeError(f"{component_id} is absent from A10 active_packs")

    checks = {
        str(item.get("check_id")): item
        for item in receipt.get("checks", [])
        if isinstance(item, dict)
    }
    if any(item.get("status") != "PASS" for item in checks.values()):
        raise RuntimeError("A10 receipt contains a non-PASS check")
    pin_check = checks.get("A10-01-independent-prover-pins")
    if not isinstance(pin_check, dict):
        raise RuntimeError("A10 pin check missing")
    if pin_check.get("pin_manifest_sha256") != independent_prover_pin_manifest_hash():
        raise RuntimeError("A10 pin manifest hash mismatch")

    for check_id, prover_id in (
        ("A10-02-rocq-proof", "rocq"),
        ("A10-03-isabelle-proof", "isabelle"),
        ("A10-04-hol4-proof", "hol4"),
    ):
        check = checks.get(check_id)
        if not isinstance(check, dict) or not isinstance(check.get("proof_receipt"), dict):
            raise RuntimeError(f"{check_id} proof receipt missing")
        proof = check["proof_receipt"]
        if proof.get("prover_id") != prover_id:
            raise RuntimeError(f"{check_id} prover id mismatch")
        if proof.get("theorem_label") != "srl_a10_zero_add":
            raise RuntimeError(f"{check_id} theorem label mismatch")
        if proof.get("formal_check") != "checked":
            raise RuntimeError(f"{check_id} did not check the proof")
        if proof.get("canonical_writes") != 0 or proof.get("grants_authority") is not False:
            raise RuntimeError(f"{check_id} proof receipt is not authority-negative")
        for probe_name in ("version_probe", "proof_probe"):
            probe = proof.get(probe_name)
            if not isinstance(probe, dict) or probe.get("returncode") != 0:
                raise RuntimeError(f"{check_id} {probe_name} failed")

    semantic = checks.get("A10-05-semantic-gap-manifests")
    if not isinstance(semantic, dict) or not isinstance(semantic.get("admission_bundle"), dict):
        raise RuntimeError("A10 semantic-gap admission bundle missing")
    bundle = semantic["admission_bundle"]
    if bundle.get("automatic_equivalence_claims") != 0:
        raise RuntimeError("A10 bundle claims automatic equivalence")
    if bundle.get("wait_contour_ids") != []:
        raise RuntimeError("A10 bundle contains WAIT contours")
    manifests = bundle.get("translation_manifests")
    if not isinstance(manifests, list) or len(manifests) != _EXPECTED_A10_TRANSLATION_MANIFESTS:
        raise RuntimeError("A10 translation manifest count mismatch")
    if any(manifest.get("equivalence_claimed") is not False for manifest in manifests):
        raise RuntimeError("A10 translation manifest claimed equivalence")
    return receipt


def _smoke_a10_receipt(component_id: str) -> str:
    receipt = _validated_a10_receipt(component_id)
    return (
        f"A10 offline truth projection accepted {component_id} from "
        f"{receipt['receipt_id']} with real prover proof receipts and semantic-gap manifests"
    )


def _smoke_a10_rocq() -> str:
    return _smoke_a10_receipt("rocq")


def _smoke_a10_isabelle() -> str:
    return _smoke_a10_receipt("isabelle")


def _smoke_a10_hol4() -> str:
    return _smoke_a10_receipt("hol4")


def _load_a11_receipt() -> dict[str, Any]:
    if not _A11_RECEIPT_PATH.exists():
        raise RuntimeError(f"A11 receipt missing: {_A11_RECEIPT_PATH.relative_to(_REPO_ROOT)}")
    receipt = json.loads(_A11_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("A11 receipt must be a JSON object")
    return receipt


def _validated_a11_receipt(component_id: str) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    receipt = _load_a11_receipt()
    if receipt.get("schema_version") != "StageCompletionReceipt/v1":
        raise RuntimeError("A11 receipt schema drifted")
    if receipt.get("stage_id") != "A11" or receipt.get("result") != "PASS":
        raise RuntimeError("A11 receipt is not a PASS receipt for stage A11")
    if receipt.get("stage_closure") != "A11_ACTIVE":
        raise RuntimeError("A11 receipt does not close A11_ACTIVE")
    if receipt.get("remaining_internal_waits") != []:
        raise RuntimeError("A11 receipt contains internal waits")
    active = receipt.get("active_packs")
    if not isinstance(active, list) or set(active) != set(_EXPECTED_A11_COMPONENTS):
        raise RuntimeError("A11 active_packs do not match expected sources")
    if component_id not in active:
        raise RuntimeError(f"{component_id} is absent from A11 active_packs")

    checks = {
        str(item.get("check_id")): item
        for item in receipt.get("checks", [])
        if isinstance(item, dict)
    }
    if any(item.get("status") != "PASS" for item in checks.values()):
        raise RuntimeError("A11 receipt contains a non-PASS check")

    admission = checks.get("A11-01-source-policy-admission")
    if not isinstance(admission, dict) or admission.get("active_sources") != list(
        _EXPECTED_A11_COMPONENTS
    ):
        raise RuntimeError("A11 source policy admission does not match expected sources")

    live = checks.get("A11-02-live-source-probes-and-replay")
    if not isinstance(live, dict):
        raise RuntimeError("A11 live source check missing")
    source_results = live.get("source_results")
    if not isinstance(source_results, list) or len(source_results) != len(_EXPECTED_A11_COMPONENTS):
        raise RuntimeError("A11 source result count mismatch")
    by_endpoint = {
        item.get("endpoint_id"): item for item in source_results if isinstance(item, dict)
    }
    if set(by_endpoint) != set(_EXPECTED_A11_COMPONENTS):
        raise RuntimeError("A11 source result endpoints mismatch")
    for endpoint_id, item in by_endpoint.items():
        live_receipt = item.get("live_query_receipt")
        replay_receipt = item.get("offline_replay_receipt")
        if not isinstance(live_receipt, dict) or not isinstance(replay_receipt, dict):
            raise RuntimeError(f"A11 {endpoint_id} query receipts missing")
        if live_receipt.get("endpoint_id") != endpoint_id:
            raise RuntimeError(f"A11 {endpoint_id} live receipt endpoint mismatch")
        if replay_receipt.get("endpoint_id") != endpoint_id:
            raise RuntimeError(f"A11 {endpoint_id} replay receipt endpoint mismatch")
        if live_receipt.get("cached") is not False:
            raise RuntimeError(f"A11 {endpoint_id} live receipt was not a live fetch")
        if replay_receipt.get("cached") is not True:
            raise RuntimeError(f"A11 {endpoint_id} replay receipt was not cached")
        if live_receipt.get("response_sha256") != replay_receipt.get("response_sha256"):
            raise RuntimeError(f"A11 {endpoint_id} live/replay response hash mismatch")
        if not item.get("record_ids") or not item.get("source_uris"):
            raise RuntimeError(f"A11 {endpoint_id} parser emitted no records")

    graph = checks.get("A11-03-knowledge-graph-taint-and-citation-contract")
    if not isinstance(graph, dict) or not isinstance(graph.get("manifest"), dict):
        raise RuntimeError("A11 graph manifest missing")
    manifest = graph["manifest"]
    if set(manifest.get("active_source_ids", [])) != set(_EXPECTED_A11_COMPONENTS):
        raise RuntimeError("A11 graph manifest active sources mismatch")
    if manifest.get("wait_source_ids") != []:
        raise RuntimeError("A11 graph manifest contains WAIT sources")
    if not manifest.get("prompt_injection_fact_ids"):
        raise RuntimeError("A11 graph manifest did not quarantine malicious corpus")
    if manifest.get("raw_corpus_in_privileged_prompt") != 0:
        raise RuntimeError("A11 graph manifest allowed raw corpus in privileged prompt")
    return receipt


def _smoke_a11_receipt(component_id: str) -> str:
    receipt = _validated_a11_receipt(component_id)
    return (
        f"A11 offline truth projection accepted {component_id} from "
        f"{receipt['receipt_id']} with live source receipts, replay hashes and taint checks"
    )


def _make_a11_smoke(component_id: str) -> Callable[[], str]:
    def _smoke() -> str:
        return _smoke_a11_receipt(component_id)

    return _smoke


def _load_a12_receipt() -> dict[str, Any]:
    if not _A12_RECEIPT_PATH.exists():
        raise RuntimeError(f"A12 receipt missing: {_A12_RECEIPT_PATH.relative_to(_REPO_ROOT)}")
    receipt = json.loads(_A12_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("A12 receipt must be a JSON object")
    return receipt


def _validated_a12_receipt(component_id: str) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    receipt = _load_a12_receipt()
    if receipt.get("schema_version") != "StageCompletionReceipt/v1":
        raise RuntimeError("A12 receipt schema drifted")
    if receipt.get("stage_id") != "A12" or receipt.get("result") != "PASS":
        raise RuntimeError("A12 receipt is not a PASS receipt for stage A12")
    if receipt.get("stage_closure") != "A12_ACTIVE":
        raise RuntimeError("A12 receipt does not close A12_ACTIVE")
    if receipt.get("remaining_internal_waits") != []:
        raise RuntimeError("A12 receipt contains internal waits")
    active = receipt.get("active_packs")
    if active != list(_EXPECTED_A12_COMPONENTS):
        raise RuntimeError("A12 active_packs do not match expected packs")
    if component_id not in active:
        raise RuntimeError(f"{component_id} is absent from A12 active_packs")

    checks = {
        str(item.get("check_id")): item
        for item in receipt.get("checks", [])
        if isinstance(item, dict)
    }
    if any(item.get("status") != "PASS" for item in checks.values()):
        raise RuntimeError("A12 receipt contains a non-PASS check")

    activation = checks.get("A12-01-real-discovery-dynamics-smoke")
    if not isinstance(activation, dict) or not isinstance(
        activation.get("activation_receipt"), dict
    ):
        raise RuntimeError("A12 activation receipt missing")
    activation_receipt = activation["activation_receipt"]
    if activation_receipt.get("active_pack_ids") != list(_EXPECTED_A12_COMPONENTS):
        raise RuntimeError("A12 activation active pack ids mismatch")
    if activation_receipt.get("formally_replaced_pack_ids") != list(_EXPECTED_A12_REPLACED):
        raise RuntimeError("A12 formal replacement ids mismatch")
    if (
        activation_receipt.get("promotion_allowed") is not False
        or activation_receipt.get("automatic_scientific_promotion") is not False
        or activation_receipt.get("canonical_writes") != 0
        or activation_receipt.get("grants_authority") is not False
    ):
        raise RuntimeError("A12 activation receipt is not authority-negative")

    pack_receipts = activation_receipt.get("pack_receipts")
    if not isinstance(pack_receipts, list) or len(pack_receipts) != len(_EXPECTED_A12_COMPONENTS):
        raise RuntimeError("A12 pack receipt count mismatch")
    by_id = {item.get("pack_id"): item for item in pack_receipts if isinstance(item, dict)}
    if tuple(by_id) != _EXPECTED_A12_COMPONENTS:
        raise RuntimeError("A12 pack receipts do not match expected order")
    for pack_id, item in by_id.items():
        if item.get("status") != "ACTIVE" or item.get("observed_above_null") is not True:
            raise RuntimeError(f"A12 {pack_id} did not reach ACTIVE")
        if (
            item.get("promotion_allowed") is not False
            or item.get("automatic_scientific_promotion") is not False
            or item.get("canonical_writes") != 0
            or item.get("grants_authority") is not False
        ):
            raise RuntimeError(f"A12 {pack_id} receipt is not authority-negative")
        envelope = item.get("resource_envelope")
        if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
            raise RuntimeError(f"A12 {pack_id} missing bounded resource envelope")
        if not isinstance(item.get("candidate"), dict) or not isinstance(item.get("dataset"), dict):
            raise RuntimeError(f"A12 {pack_id} missing candidate or dataset binding")
        backend_versions = item.get("backend_versions")
        if not isinstance(backend_versions, dict) or not backend_versions.get("python_package"):
            raise RuntimeError(f"A12 {pack_id} missing backend version binding")
        if pack_id == "pysr" and not backend_versions.get("julia"):
            raise RuntimeError("A12 PySR receipt missing Julia version binding")

    public = activation_receipt.get("public_benchmark_receipt")
    if not isinstance(public, dict) or public.get("observed_above_null") is not True:
        raise RuntimeError("A12 public benchmark receipt missing or inconclusive")

    no_promotion = checks.get("A12-02-no-automatic-scientific-promotion")
    if not isinstance(no_promotion, dict) or no_promotion.get("status") != "PASS":
        raise RuntimeError("A12 no-promotion check missing or failed")
    return receipt


def _smoke_a12_receipt(component_id: str) -> str:
    receipt = _validated_a12_receipt(component_id)
    return (
        f"A12 offline truth projection accepted {component_id} from "
        f"{receipt['receipt_id']} with real discovery/dynamics receipts and null checks"
    )


def _make_a12_smoke(component_id: str) -> Callable[[], str]:
    def _smoke() -> str:
        return _smoke_a12_receipt(component_id)

    return _smoke


def _load_a13_receipt() -> dict[str, Any]:
    if not _A13_RECEIPT_PATH.exists():
        raise RuntimeError(f"A13 receipt missing: {_A13_RECEIPT_PATH.relative_to(_REPO_ROOT)}")
    receipt = json.loads(_A13_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("A13 receipt must be a JSON object")
    return receipt


def _validated_a13_receipt(component_id: str) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    receipt = _load_a13_receipt()
    if receipt.get("schema_version") != "StageCompletionReceipt/v1":
        raise RuntimeError("A13 receipt schema drifted")
    if receipt.get("stage_id") != "A13" or receipt.get("result") != "PASS":
        raise RuntimeError("A13 receipt is not a PASS receipt for stage A13")
    if receipt.get("stage_closure") != "A13_ACTIVE":
        raise RuntimeError("A13 receipt does not close A13_ACTIVE")
    if receipt.get("remaining_internal_waits") != []:
        raise RuntimeError("A13 receipt contains internal waits")
    active = receipt.get("active_packs")
    if active != list(_EXPECTED_A13_COMPONENTS):
        raise RuntimeError("A13 active_packs do not match expected packs")
    if component_id not in active:
        raise RuntimeError(f"{component_id} is absent from A13 active_packs")

    checks = {
        str(item.get("check_id")): item
        for item in receipt.get("checks", [])
        if isinstance(item, dict)
    }
    if any(item.get("status") != "PASS" for item in checks.values()):
        raise RuntimeError("A13 receipt contains a non-PASS check")

    activation = checks.get("A13-01-real-applied-science-workloads")
    if not isinstance(activation, dict) or not isinstance(
        activation.get("activation_receipt"), dict
    ):
        raise RuntimeError("A13 activation receipt missing")
    activation_receipt = activation["activation_receipt"]
    if activation_receipt.get("schema_version") != "AppliedScienceActivationReceipt/v1":
        raise RuntimeError("A13 activation receipt schema drifted")
    if activation_receipt.get("active_pack_ids") != list(_EXPECTED_A13_COMPONENTS):
        raise RuntimeError("A13 activation active pack ids mismatch")
    if activation_receipt.get("formally_replaced_pack_ids") != list(_EXPECTED_A13_REPLACED):
        raise RuntimeError("A13 formal replacement ids mismatch")
    if (
        activation_receipt.get("promotion_allowed") is not False
        or activation_receipt.get("automatic_scientific_promotion") is not False
        or activation_receipt.get("canonical_writes") != 0
        or activation_receipt.get("grants_authority") is not False
    ):
        raise RuntimeError("A13 activation receipt is not authority-negative")

    workload_receipts = activation_receipt.get("workload_receipts")
    if not isinstance(workload_receipts, list) or len(workload_receipts) != len(
        _EXPECTED_A13_COMPONENTS
    ):
        raise RuntimeError("A13 workload receipt count mismatch")
    by_id = {item.get("pack_id"): item for item in workload_receipts if isinstance(item, dict)}
    if tuple(by_id) != _EXPECTED_A13_COMPONENTS:
        raise RuntimeError("A13 workload receipts do not match expected order")
    for pack_id, item in by_id.items():
        if item.get("status") != "ACTIVE":
            raise RuntimeError(f"A13 {pack_id} did not reach ACTIVE")
        if (
            item.get("promotion_allowed") is not False
            or item.get("automatic_scientific_promotion") is not False
            or item.get("canonical_writes") != 0
            or item.get("grants_authority") is not False
        ):
            raise RuntimeError(f"A13 {pack_id} receipt is not authority-negative")
        envelope = item.get("resource_envelope")
        if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
            raise RuntimeError(f"A13 {pack_id} missing bounded resource envelope")
        if not isinstance(item.get("dataset"), dict):
            raise RuntimeError(f"A13 {pack_id} missing dataset binding")
        backend_versions = item.get("backend_versions")
        if not isinstance(backend_versions, dict) or not backend_versions:
            raise RuntimeError(f"A13 {pack_id} missing backend version binding")

    _check_a13_topology(by_id["ripser"])
    _check_a13_bayesian(by_id["native_bayesian_conjugate"])
    _check_a13_causal(by_id["native_causal_backdoor"])
    _check_a13_optimization(by_id["cvxpy"])

    diagnostics = checks.get("A13-02-diagnostics-falsification-license-and-no-promotion")
    if not isinstance(diagnostics, dict) or diagnostics.get("status") != "PASS":
        raise RuntimeError("A13 diagnostics/no-promotion check missing or failed")
    return receipt


def _check_a13_topology(item: dict[str, Any]) -> None:
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise RuntimeError("A13 topology diagnostics missing")
    if diagnostics.get("circle_long_lived_h1") != 1:
        raise RuntimeError("A13 topology did not detect expected H1 signal")
    if diagnostics.get("control_long_lived_h1") != 0:
        raise RuntimeError("A13 topology null control did not stay null")


def _check_a13_bayesian(item: dict[str, Any]) -> None:
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise RuntimeError("A13 Bayesian diagnostics missing")
    if diagnostics.get("convergence_claim") is not False:
        raise RuntimeError("A13 Bayesian workload made an MCMC convergence claim")
    if diagnostics.get("rhat") is not None or diagnostics.get("ess") is not None:
        raise RuntimeError("A13 Bayesian workload emitted fake MCMC diagnostics")
    tail = diagnostics.get("posterior_predictive_tail_probability")
    if not isinstance(tail, float) or not 0.0 <= tail <= 1.0:
        raise RuntimeError("A13 Bayesian posterior predictive diagnostic invalid")


def _check_a13_causal(item: dict[str, Any]) -> None:
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise RuntimeError("A13 causal diagnostics missing")
    if item.get("causal_identification") != "identified":
        raise RuntimeError("A13 causal workload did not identify the effect")
    adjusted = diagnostics.get("adjusted_treatment_effect")
    permuted = diagnostics.get("permuted_treatment_effect")
    if (
        not isinstance(adjusted, float)
        or abs(adjusted - _A13_CAUSAL_TRUE_EFFECT) > _A13_CAUSAL_EFFECT_TOLERANCE
    ):
        raise RuntimeError("A13 causal adjusted effect drifted")
    if not isinstance(permuted, float) or abs(permuted) > _A13_CAUSAL_FALSIFICATION_TOLERANCE:
        raise RuntimeError("A13 causal falsification failed")


def _check_a13_optimization(item: dict[str, Any]) -> None:
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise RuntimeError("A13 optimization diagnostics missing")
    if diagnostics.get("solve_status") != "optimal":
        raise RuntimeError("A13 optimization solver status is not optimal")
    if diagnostics.get("license_verified") is not True:
        raise RuntimeError("A13 optimization license was not verified")
    if diagnostics.get("denied_solvers") != ["cbc", "glpk"]:
        raise RuntimeError("A13 optimization denied solver matrix drifted")


def _smoke_a13_receipt(component_id: str) -> str:
    receipt = _validated_a13_receipt(component_id)
    return (
        f"A13 offline truth projection accepted {component_id} from "
        f"{receipt['receipt_id']} with applied workload receipts and diagnostics"
    )


def _make_a13_smoke(component_id: str) -> Callable[[], str]:
    def _smoke() -> str:
        return _smoke_a13_receipt(component_id)

    return _smoke


def _load_a14_receipt() -> dict[str, Any]:
    if not _A14_RECEIPT_PATH.exists():
        raise RuntimeError(f"A14 receipt missing: {_A14_RECEIPT_PATH.relative_to(_REPO_ROOT)}")
    receipt = json.loads(_A14_RECEIPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("A14 receipt must be a JSON object")
    return receipt


def _validated_a14_receipt(component_id: str) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    receipt = _load_a14_receipt()
    if receipt.get("schema_version") != "StageCompletionReceipt/v1":
        raise RuntimeError("A14 receipt schema drifted")
    if receipt.get("stage_id") != "A14" or receipt.get("result") != "PASS":
        raise RuntimeError("A14 receipt is not a PASS receipt for stage A14")
    if receipt.get("stage_closure") != "A14_ACTIVE":
        raise RuntimeError("A14 receipt does not close A14_ACTIVE")
    if receipt.get("remaining_internal_waits") != []:
        raise RuntimeError("A14 receipt contains internal waits")
    active = receipt.get("active_packs")
    if active != list(_EXPECTED_A14_COMPONENTS):
        raise RuntimeError("A14 active_packs do not match expected packs")
    if component_id not in active:
        raise RuntimeError(f"{component_id} is absent from A14 active_packs")
    if receipt.get("formally_replaced_packs") != list(_EXPECTED_A14_REPLACED):
        raise RuntimeError("A14 replacement packs do not match expected packs")

    checks = {
        str(item.get("check_id")): item
        for item in receipt.get("checks", [])
        if isinstance(item, dict)
    }
    if any(item.get("status") != "PASS" for item in checks.values()):
        raise RuntimeError("A14 receipt contains a non-PASS check")
    activation = checks.get("A14-01-real-sciml-domain-workloads")
    if not isinstance(activation, dict) or not isinstance(
        activation.get("activation_receipt"), dict
    ):
        raise RuntimeError("A14 activation receipt missing")
    activation_receipt = activation["activation_receipt"]
    if activation_receipt.get("schema_version") != "SciMLDomainActivationReceipt/v1":
        raise RuntimeError("A14 activation receipt schema drifted")
    if activation_receipt.get("active_pack_ids") != list(_EXPECTED_A14_COMPONENTS):
        raise RuntimeError("A14 activation active pack ids mismatch")
    if activation_receipt.get("formally_replaced_pack_ids") != list(_EXPECTED_A14_REPLACED):
        raise RuntimeError("A14 formal replacement ids mismatch")
    if (
        activation_receipt.get("promotion_allowed") is not False
        or activation_receipt.get("automatic_scientific_promotion") is not False
        or activation_receipt.get("canonical_writes") != 0
        or activation_receipt.get("grants_authority") is not False
    ):
        raise RuntimeError("A14 activation receipt is not authority-negative")

    workload_receipts = activation_receipt.get("workload_receipts")
    if not isinstance(workload_receipts, list) or len(workload_receipts) != len(
        _EXPECTED_A14_COMPONENTS
    ):
        raise RuntimeError("A14 workload receipt count mismatch")
    by_id = {item.get("pack_id"): item for item in workload_receipts if isinstance(item, dict)}
    if tuple(by_id) != _EXPECTED_A14_COMPONENTS:
        raise RuntimeError("A14 workload receipts do not match expected order")
    for pack_id, item in by_id.items():
        if item.get("status") != "ACTIVE":
            raise RuntimeError(f"A14 {pack_id} did not reach ACTIVE")
        if item.get("bitwise_identity_claimed") is not False:
            raise RuntimeError(f"A14 {pack_id} claimed bitwise identity")
        if (
            item.get("promotion_allowed") is not False
            or item.get("automatic_scientific_promotion") is not False
            or item.get("canonical_writes") != 0
            or item.get("grants_authority") is not False
        ):
            raise RuntimeError(f"A14 {pack_id} receipt is not authority-negative")
        envelope = item.get("resource_envelope")
        if not isinstance(envelope, dict) or envelope.get("bounded") is not True:
            raise RuntimeError(f"A14 {pack_id} missing bounded resource envelope")
        if not isinstance(item.get("backend_versions"), dict) or not item.get("backend_versions"):
            raise RuntimeError(f"A14 {pack_id} missing backend version binding")
        if not isinstance(item.get("solver"), dict):
            raise RuntimeError(f"A14 {pack_id} missing solver provenance")
        if not item.get("unit_bindings"):
            raise RuntimeError(f"A14 {pack_id} missing unit bindings")
        tolerance = item.get("tolerance")
        if not isinstance(tolerance, dict):
            raise RuntimeError(f"A14 {pack_id} missing tolerance")
        if not isinstance(item.get("dataset"), dict) or not isinstance(
            item.get("diagnostics"), dict
        ):
            raise RuntimeError(f"A14 {pack_id} missing dataset or diagnostics")
        if not isinstance(item.get("trace_sha256"), str):
            raise RuntimeError(f"A14 {pack_id} missing trace digest")

    cross_language = activation_receipt.get("cross_language_receipt")
    if not isinstance(cross_language, dict):
        raise RuntimeError("A14 cross-language receipt missing")
    if cross_language.get("bitwise_identity_claimed") is not False:
        raise RuntimeError("A14 cross-language receipt claimed bitwise identity")
    if cross_language.get("comparison_scope") != "bounded_real_workload_tolerance_only":
        raise RuntimeError("A14 cross-language scope drifted")
    if (
        cross_language.get("canonical_writes") != 0
        or cross_language.get("grants_authority") is not False
    ):
        raise RuntimeError("A14 cross-language receipt is not authority-negative")

    diagnostics = checks.get("A14-02-units-tolerances-domain-diagnostics-and-no-bitwise-claim")
    if not isinstance(diagnostics, dict) or diagnostics.get("status") != "PASS":
        raise RuntimeError("A14 diagnostics/no-bitwise check missing or failed")
    return receipt


def _smoke_a14_receipt(component_id: str) -> str:
    receipt = _validated_a14_receipt(component_id)
    return (
        f"A14 offline truth projection accepted {component_id} from "
        f"{receipt['receipt_id']} with SciML/domain workload receipts and tolerances"
    )


def _make_a14_smoke(component_id: str) -> Callable[[], str]:
    def _smoke() -> str:
        return _smoke_a14_receipt(component_id)

    return _smoke


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
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a09_lean_kernel,
    ),
    ComponentSpec(
        "lake",
        "a09_formal",
        "A09",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a09_lake,
    ),
    ComponentSpec(
        "mathlib",
        "a09_formal",
        "A09",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a09_mathlib,
    ),
    ComponentSpec(
        "cslib-index",
        "a09_formal_corpus",
        "A09",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a09_cslib_index,
    ),
    ComponentSpec(
        "erdos-problems-metadata",
        "a09_formal_corpus",
        "A09",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a09_erdos_corpus,
    ),
    ComponentSpec(
        "formal-conjectures",
        "a09_formal_corpus",
        "A09",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a09_formal_conjectures,
    ),
    ComponentSpec(
        "rocq",
        "a10_formal",
        "A10",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a10_rocq,
    ),
    ComponentSpec(
        "isabelle",
        "a10_formal",
        "A10",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a10_isabelle,
    ),
    ComponentSpec(
        "hol4",
        "a10_formal",
        "A10",
        "stage_receipt",
        activation_wait_state="WAIT_TOOLCHAIN",
        current_v101_active=True,
        smoke=_smoke_a10_hol4,
    ),
    *(
        ComponentSpec(
            source_id,
            "a11_knowledge_graph",
            "A11",
            "stage_receipt",
            activation_wait_state="WAIT_CAPABILITY",
            current_v101_active=True,
            smoke=_make_a11_smoke(source_id),
        )
        for source_id in _EXPECTED_A11_COMPONENTS
    ),
    *(
        ComponentSpec(
            pack_id,
            "a12_discovery_dynamics",
            "A12",
            "stage_receipt",
            activation_wait_state="WAIT_CAPABILITY",
            current_v101_active=True,
            smoke=_make_a12_smoke(pack_id),
        )
        for pack_id in _EXPECTED_A12_COMPONENTS
    ),
    *(
        ComponentSpec(
            pack_id,
            "a13_applied_science",
            "A13",
            "stage_receipt",
            activation_wait_state="WAIT_CAPABILITY",
            current_v101_active=True,
            smoke=_make_a13_smoke(pack_id),
        )
        for pack_id in _EXPECTED_A13_COMPONENTS
    ),
    *(
        ComponentSpec(
            pack_id,
            "a14_sciml_domain",
            "A14",
            "stage_receipt",
            activation_wait_state="WAIT_CAPABILITY",
            current_v101_active=True,
            smoke=_make_a14_smoke(pack_id),
        )
        for pack_id in _EXPECTED_A14_COMPONENTS
    ),
    *(
        ComponentSpec(
            pack_id,
            "a15_heavy_compute",
            "A15",
            "remote_compute_target",
            activation_wait_state="WAIT_COMPUTE_NODE",
        )
        for pack_id in _EXPECTED_A15_COMPONENTS
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


def _stage_receipt_probe(spec: ComponentSpec) -> tuple[bool, str | None, str | None]:
    try:
        if spec.stage == "A09":
            receipt = _validated_a09_receipt(spec.component_id)
            receipt_path = _receipt_display_path(_A09_RECEIPT_PATH)
        elif spec.stage == "A10":
            receipt = _validated_a10_receipt(spec.component_id)
            receipt_path = _receipt_display_path(_A10_RECEIPT_PATH)
        elif spec.stage == "A11":
            receipt = _validated_a11_receipt(spec.component_id)
            receipt_path = _receipt_display_path(_A11_RECEIPT_PATH)
        elif spec.stage == "A12":
            receipt = _validated_a12_receipt(spec.component_id)
            receipt_path = _receipt_display_path(_A12_RECEIPT_PATH)
        elif spec.stage == "A13":
            receipt = _validated_a13_receipt(spec.component_id)
            receipt_path = _receipt_display_path(_A13_RECEIPT_PATH)
        elif spec.stage == "A14":
            receipt = _validated_a14_receipt(spec.component_id)
            receipt_path = _receipt_display_path(_A14_RECEIPT_PATH)
        else:
            return False, None, f"stage receipt unsupported for {spec.stage}"
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    return True, f"{receipt_path}:{receipt['receipt_id']}", None


def _receipt_display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return path.name


def _probe(spec: ComponentSpec) -> dict[str, Any]:
    if spec.probe_kind == "python_import":
        ok, version_or_path, error = _python_probe(spec)
    elif spec.probe_kind == "native_executable":
        ok, version_or_path, error = _executable_probe(spec)
    elif spec.probe_kind == "stage_receipt":
        ok, version_or_path, error = _stage_receipt_probe(spec)
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
        evidence_axis = (
            "hash_bound_stage_receipt_and_scientific_smoke"
            if spec.probe_kind == "stage_receipt"
            else "nonfixture_executable_probe_and_scientific_smoke"
        )
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
        "a09_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A09" and item["state"] == "ACTIVE"
        ],
        "a09_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A09" and item["state"] != "ACTIVE"
        ],
        "a10_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A10" and item["state"] == "ACTIVE"
        ],
        "a10_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A10" and item["state"] != "ACTIVE"
        ],
        "a11_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A11" and item["state"] == "ACTIVE"
        ],
        "a11_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A11" and item["state"] != "ACTIVE"
        ],
        "a12_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A12" and item["state"] == "ACTIVE"
        ],
        "a12_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A12" and item["state"] != "ACTIVE"
        ],
        "a13_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A13" and item["state"] == "ACTIVE"
        ],
        "a13_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A13" and item["state"] != "ACTIVE"
        ],
        "a14_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A14" and item["state"] == "ACTIVE"
        ],
        "a14_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A14" and item["state"] != "ACTIVE"
        ],
        "a15_active_inventory_observed": [
            item["component_id"]
            for item in components
            if item["activation_stage"] == "A15" and item["state"] == "ACTIVE"
        ],
        "a15_parked_blockers": [
            f"{item['state']}:{item['component_id']}"
            for item in components
            if item["activation_stage"] == "A15" and item["state"] != "ACTIVE"
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
