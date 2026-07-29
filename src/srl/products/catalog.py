"""A16 scientific product catalog over hash-bound stage receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id

A16_PRODUCTS_RECEIPT_SCHEMA_VERSION: Final[str] = "ScientificProductsActivationReceipt/v1"
PRODUCT_RECEIPT_SCHEMA_VERSION: Final[str] = "ScientificProductReceipt/v1"
PRODUCT_REQUEST_SCHEMA_VERSION: Final[str] = "ScientificProductRequest/v1"
PRODUCT_RESULT_SCHEMA_VERSION: Final[str] = "ScientificProductResult/v1"

EXPECTED_A16_PRODUCTS: Final[tuple[str, ...]] = (
    "lawminer",
    "formal_verification_lab",
    "geometry_physics_compiler",
    "causal_economy_lab",
    "literature_to_knowledge_graph",
)
MIN_PRODUCT_BACKENDS: Final[int] = 2


class ProductCatalogError(ContractError):
    """Raised when product activation evidence is incomplete or overclaims."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def load_stage_receipts(root: Path) -> dict[str, dict[str, Any]]:
    """Load the committed A09-A14 stage receipts needed by A16."""

    paths = {
        "A09": root / "docs/verification/srf-v3-7-a09-lean-corpora-receipt.json",
        "A10": root / "docs/verification/srf-v3-7-a10-independent-provers-receipt.json",
        "A11": root / "docs/verification/srf-v3-7-a11-knowledge-graph-receipt.json",
        "A12": root / "docs/verification/srf-v3-7-a12-discovery-dynamics-receipt.json",
        "A13": root / "docs/verification/srf-v3-7-a13-applied-science-receipt.json",
        "A14": root / "docs/verification/srf-v3-7-a14-sciml-domain-receipt.json",
    }
    receipts: dict[str, dict[str, Any]] = {}
    for stage_id, path in paths.items():
        try:
            receipts[stage_id] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProductCatalogError(f"missing A16 input receipt: {path.as_posix()}") from exc
        except json.JSONDecodeError as exc:
            raise ProductCatalogError(f"invalid A16 input receipt JSON: {path.as_posix()}") from exc
    return receipts


def build_a16_products_receipt(
    stage_receipts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the authority-negative A16 product activation receipt."""

    _validate_stage_receipts(stage_receipts)
    products = [
        _lawminer(stage_receipts),
        _formal_verification_lab(stage_receipts),
        _geometry_physics_compiler(stage_receipts),
        _causal_economy_lab(stage_receipts),
        _literature_to_knowledge_graph(stage_receipts),
    ]
    receipt: dict[str, Any] = {
        "schema_version": A16_PRODUCTS_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A16",
        "product_ids": [product["product_id"] for product in products],
        "products": products,
        "request_result_receipt_chain": "complete_per_product",
        "disagreement_policy": "preserve_inconclusive_and_disagreement_paths",
        "ledger_policy": "consumes_stage_receipts_no_second_ledger",
        "authority_policy": "proposal_only_no_canonical_authority",
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
        "creates_second_ledger": False,
    }
    validate_a16_products_receipt(receipt)
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def validate_a16_products_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate A16 product evidence without running scientific backends."""

    if receipt.get("schema_version") != A16_PRODUCTS_RECEIPT_SCHEMA_VERSION:
        raise ProductCatalogError("A16 receipt schema mismatch")
    if receipt.get("stage_id") != "A16":
        raise ProductCatalogError("A16 receipt stage mismatch")
    if receipt.get("product_ids") != list(EXPECTED_A16_PRODUCTS):
        raise ProductCatalogError("A16 product order or coverage drifted")
    if receipt.get("creates_second_ledger") is not False:
        raise ProductCatalogError("A16 product layer attempted to create a second ledger")
    _assert_authority_negative(receipt, "A16 receipt")
    products = receipt.get("products")
    if not isinstance(products, list) or len(products) != len(EXPECTED_A16_PRODUCTS):
        raise ProductCatalogError("A16 product receipt count mismatch")
    for product in products:
        if not isinstance(product, Mapping):
            raise ProductCatalogError("A16 product receipt must be an object")
        _validate_product(product)


def _validate_stage_receipts(stage_receipts: Mapping[str, Mapping[str, Any]]) -> None:
    for stage_id in ("A09", "A10", "A11", "A12", "A13", "A14"):
        receipt = stage_receipts.get(stage_id)
        if not isinstance(receipt, Mapping):
            raise ProductCatalogError(f"{stage_id} stage receipt missing")
        if receipt.get("schema_version") != "StageCompletionReceipt/v1":
            raise ProductCatalogError(f"{stage_id} stage receipt schema mismatch")
        if receipt.get("stage_id") != stage_id:
            raise ProductCatalogError(f"{stage_id} stage receipt id mismatch")
        if receipt.get("result") != "PASS":
            raise ProductCatalogError(f"{stage_id} stage receipt is not PASS")
        if receipt.get("canonical_writes") != 0 or receipt.get("grants_authority") is not False:
            raise ProductCatalogError(f"{stage_id} stage receipt is not authority-negative")


def _lawminer(stage_receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    a12 = stage_receipts["A12"]
    activation = _check(a12, "A12-01-real-discovery-dynamics-smoke")["activation_receipt"]
    pack_receipts = cast(Sequence[Mapping[str, Any]], activation["pack_receipts"])
    backends = _require_pack_ids(pack_receipts, ("pysr", "pysindy", "pydmd"))
    result = {
        "candidate_artifacts": [
            _pack_result(item, "candidate", "validation_metric", "null_metric")
            for item in pack_receipts
        ],
        "public_benchmark_receipt_id": cast(
            Mapping[str, Any], activation["public_benchmark_receipt"]
        )["receipt_id"],
        "inconclusive_path": "null_or_worse_candidate_remains_inconclusive",
    }
    return _product_receipt(
        product_id="lawminer",
        request_summary=(
            "discover bounded symbolic and dynamical candidate laws with holdout/null controls"
        ),
        stage_refs=[_stage_ref(a12)],
        backend_ids=backends,
        result=result,
    )


def _formal_verification_lab(stage_receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    a09 = stage_receipts["A09"]
    a10 = stage_receipts["A10"]
    lean_valid = _check(a09, "A09-02-lean-kernel-accept-reject")["valid_receipt"]
    mathlib = _check(a09, "A09-03-mathlib-import")["mathlib_receipt"]
    proof_checks = [
        _check(a10, "A10-02-rocq-proof"),
        _check(a10, "A10-03-isabelle-proof"),
        _check(a10, "A10-04-hol4-proof"),
    ]
    proof_receipts = [cast(Mapping[str, Any], check["proof_receipt"]) for check in proof_checks]
    manifests = cast(
        Mapping[str, Any],
        _check(a10, "A10-05-semantic-gap-manifests")["admission_bundle"],
    )["translation_manifests"]
    if any(
        cast(Mapping[str, Any], item).get("equivalence_claimed") is not False for item in manifests
    ):
        raise ProductCatalogError("formal verification product claimed automatic equivalence")
    result = {
        "formal_checks": [
            _proof_result(cast(Mapping[str, Any], lean_valid)),
            _proof_result(cast(Mapping[str, Any], mathlib)),
            *[_proof_result(item) for item in proof_receipts],
        ],
        "translation_manifest_count": len(cast(Sequence[Any], manifests)),
        "disagreement_path": "semantic_gap_manifest_requires_independent_review",
    }
    return _product_receipt(
        product_id="formal_verification_lab",
        request_summary=(
            "cross-check a declared theorem across Lean/mathlib and independent HOL/CIC contours"
        ),
        stage_refs=[_stage_ref(a09), _stage_ref(a10)],
        backend_ids=("lean", "mathlib", "rocq", "isabelle", "hol4"),
        result=result,
    )


def _geometry_physics_compiler(stage_receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    a13 = stage_receipts["A13"]
    a14 = stage_receipts["A14"]
    a13_workloads = cast(
        Sequence[Mapping[str, Any]],
        _check(a13, "A13-01-real-applied-science-workloads")["activation_receipt"][
            "workload_receipts"
        ],
    )
    a14_workloads = cast(
        Sequence[Mapping[str, Any]],
        _check(a14, "A14-01-real-sciml-domain-workloads")["activation_receipt"][
            "workload_receipts"
        ],
    )
    selected = [
        *_select(a13_workloads, ("ripser", "pyriemann", "cvxpy")),
        *_select(
            a14_workloads,
            (
                "julia_sciml_ode",
                "python_diffrax_ode",
                "python_qutip_quantum",
                "python_astropy_astronomy",
                "python_cantera_combustion",
                "native_battery_rc",
                "python_quimb_many_body",
                "python_cotengra_tensor_network",
            ),
        ),
    ]
    result = {
        "compiled_artifacts": [
            _pack_result(item, "diagnostics", "validation_metric", "dataset") for item in selected
        ],
        "unit_policy": "unit_bindings_required_no_unit_loss",
        "tolerance_policy": "tolerance_checked_no_bitwise_identity_claim",
    }
    return _product_receipt(
        product_id="geometry_physics_compiler",
        request_summary=(
            "compile geometry, topology and physics models through bounded scientific backends"
        ),
        stage_refs=[_stage_ref(a13), _stage_ref(a14)],
        backend_ids=tuple(str(item["pack_id"]) for item in selected),
        result=result,
    )


def _causal_economy_lab(stage_receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    a13 = stage_receipts["A13"]
    workloads = cast(
        Sequence[Mapping[str, Any]],
        _check(a13, "A13-01-real-applied-science-workloads")["activation_receipt"][
            "workload_receipts"
        ],
    )
    selected = _select(workloads, ("native_causal_backdoor", "cvxpy", "native_bayesian_conjugate"))
    causal = selected[0]
    if causal.get("causal_identification") != "identified":
        raise ProductCatalogError("causal economy product lacks identified causal receipt")
    result = {
        "economic_assessment": [
            _pack_result(item, "diagnostics", "validation_metric", "solver_status")
            for item in selected
        ],
        "inconclusive_path": "unidentified_effect_must_not_be_estimated",
        "falsification_path": "permuted_treatment_effect_near_zero_required",
    }
    return _product_receipt(
        product_id="causal_economy_lab",
        request_summary=(
            "identify and falsify a bounded causal effect with optimization "
            "and uncertainty diagnostics"
        ),
        stage_refs=[_stage_ref(a13)],
        backend_ids=tuple(str(item["pack_id"]) for item in selected),
        result=result,
    )


def _literature_to_knowledge_graph(
    stage_receipts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    a11 = stage_receipts["A11"]
    source_check = _check(a11, "A11-02-live-source-probes-and-replay")
    graph_check = _check(a11, "A11-03-knowledge-graph-taint-and-citation-contract")
    source_results = cast(Sequence[Mapping[str, Any]], source_check["source_results"])
    manifest = cast(Mapping[str, Any], graph_check["manifest"])
    backend_ids = tuple(str(item["endpoint_id"]) for item in source_results)
    if len(backend_ids) < MIN_PRODUCT_BACKENDS:
        raise ProductCatalogError("knowledge-graph product needs at least two sources")
    result = {
        "source_receipts": [
            {
                "endpoint_id": item["endpoint_id"],
                "live_query_receipt_id": cast(Mapping[str, Any], item["live_query_receipt"])[
                    "receipt_id"
                ],
                "offline_replay_receipt_id": cast(
                    Mapping[str, Any], item["offline_replay_receipt"]
                )["receipt_id"],
                "record_ids": item["record_ids"],
            }
            for item in source_results
        ],
        "graph_manifest_id": manifest["manifest_id"],
        "citation_edges": manifest["citation_edges"],
        "taint_policy": "source_uri_and_citation_required_for_every_fact",
    }
    return _product_receipt(
        product_id="literature_to_knowledge_graph",
        request_summary=(
            "turn source-grounded literature and corpus records into a taint-preserving graph"
        ),
        stage_refs=[_stage_ref(a11)],
        backend_ids=backend_ids,
        result=result,
    )


def _product_receipt(
    *,
    product_id: str,
    request_summary: str,
    stage_refs: Sequence[Mapping[str, Any]],
    backend_ids: Sequence[str],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if len(tuple(backend_ids)) < MIN_PRODUCT_BACKENDS:
        raise ProductCatalogError(f"{product_id} does not bind at least two backends")
    request = {
        "schema_version": PRODUCT_REQUEST_SCHEMA_VERSION,
        "product_id": product_id,
        "request_summary": request_summary,
        "requested_stage_refs": list(stage_refs),
        "canonical_writes": 0,
        "grants_authority": False,
    }
    request_id = object_id(request)
    result_body = {
        "schema_version": PRODUCT_RESULT_SCHEMA_VERSION,
        "product_id": product_id,
        "request_id": request_id,
        "backend_ids": list(backend_ids),
        "result": dict(result),
        "status": "checked",
        "inconclusive_and_disagreement_preserved": True,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    result_id = object_id(result_body)
    receipt: dict[str, Any] = {
        "schema_version": PRODUCT_RECEIPT_SCHEMA_VERSION,
        "product_id": product_id,
        "request": request,
        "request_id": request_id,
        "result": result_body,
        "result_id": result_id,
        "stage_refs": list(stage_refs),
        "backend_ids": list(backend_ids),
        "receipt_chain_complete": True,
        "creates_second_ledger": False,
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    _validate_product(receipt)
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def _validate_product(product: Mapping[str, Any]) -> None:
    product_id = product.get("product_id")
    if product.get("schema_version") != PRODUCT_RECEIPT_SCHEMA_VERSION:
        raise ProductCatalogError(f"{product_id} product receipt schema mismatch")
    if product.get("receipt_chain_complete") is not True:
        raise ProductCatalogError(f"{product_id} product receipt chain incomplete")
    if product.get("creates_second_ledger") is not False:
        raise ProductCatalogError(f"{product_id} created a second ledger")
    if product.get("promotion_allowed") is not False:
        raise ProductCatalogError(f"{product_id} allowed promotion")
    _assert_authority_negative(product, f"{product_id} product receipt")
    backend_ids = product.get("backend_ids")
    if not isinstance(backend_ids, list) or len(backend_ids) < MIN_PRODUCT_BACKENDS:
        raise ProductCatalogError(f"{product_id} lacks two backend ids")
    request = product.get("request")
    result = product.get("result")
    if not isinstance(request, Mapping) or object_id(request) != product.get("request_id"):
        raise ProductCatalogError(f"{product_id} request id mismatch")
    if not isinstance(result, Mapping) or object_id(result) != product.get("result_id"):
        raise ProductCatalogError(f"{product_id} result id mismatch")
    _assert_authority_negative(request, f"{product_id} request")
    _assert_authority_negative(result, f"{product_id} result")
    if result.get("inconclusive_and_disagreement_preserved") is not True:
        raise ProductCatalogError(f"{product_id} collapsed inconclusive/disagreement paths")


def _check(stage_receipt: Mapping[str, Any], check_id: str) -> Mapping[str, Any]:
    checks = stage_receipt.get("checks")
    if not isinstance(checks, list):
        raise ProductCatalogError(f"{stage_receipt.get('stage_id')} checks missing")
    for check in checks:
        if isinstance(check, Mapping) and check.get("check_id") == check_id:
            if check.get("status") != "PASS":
                raise ProductCatalogError(f"{check_id} is not PASS")
            return check
    raise ProductCatalogError(f"missing check {check_id}")


def _stage_ref(stage_receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stage_id": stage_receipt["stage_id"],
        "stage_closure": stage_receipt["stage_closure"],
        "receipt_id": stage_receipt["receipt_id"],
    }


def _require_pack_ids(
    receipts: Sequence[Mapping[str, Any]],
    expected: Sequence[str],
) -> tuple[str, ...]:
    found = tuple(str(item.get("pack_id")) for item in receipts)
    if found != tuple(expected):
        raise ProductCatalogError(f"pack ids mismatch: {found}")
    return found


def _select(
    receipts: Sequence[Mapping[str, Any]], pack_ids: Sequence[str]
) -> list[Mapping[str, Any]]:
    by_id = {str(item.get("pack_id")): item for item in receipts}
    selected: list[Mapping[str, Any]] = []
    for pack_id in pack_ids:
        item = by_id.get(pack_id)
        if item is None:
            raise ProductCatalogError(f"missing product backend receipt: {pack_id}")
        selected.append(item)
    return selected


def _pack_result(item: Mapping[str, Any], *fields: str) -> dict[str, Any]:
    _assert_authority_negative(item, f"{item.get('pack_id')} backend receipt")
    envelope = item.get("resource_envelope")
    if not isinstance(envelope, Mapping) or envelope.get("bounded") is not True:
        raise ProductCatalogError(f"{item.get('pack_id')} backend receipt is unbounded")
    result = {
        "pack_id": item["pack_id"],
        "backend": item.get("backend", item["pack_id"]),
        "receipt_id": item["receipt_id"],
        "resource_envelope": envelope,
    }
    for field in fields:
        if field in item:
            result[field] = item[field]
    return result


def _proof_result(item: Mapping[str, Any]) -> dict[str, Any]:
    _assert_authority_negative(item, f"{item.get('prover_id', 'lean')} proof receipt")
    if item.get("formal_check") not in {"checked", "CHECKED"}:
        raise ProductCatalogError(f"{item.get('prover_id', 'lean')} proof was not checked")
    return {
        "prover_id": item.get("prover_id", "lean"),
        "theorem_label": item.get("theorem_label", item.get("theorem_name")),
        "formal_check": item["formal_check"],
        "formal_scope": item["formal_scope"],
        "receipt_id": item.get("receipt_id") or object_id(dict(item)),
        "source_sha256": item["source_sha256"],
    }


def _assert_authority_negative(item: Mapping[str, Any], label: str) -> None:
    if item.get("canonical_writes") != 0 or item.get("grants_authority") is not False:
        raise ProductCatalogError(f"{label} is not authority-negative")


__all__ = [
    "A16_PRODUCTS_RECEIPT_SCHEMA_VERSION",
    "EXPECTED_A16_PRODUCTS",
    "MIN_PRODUCT_BACKENDS",
    "PRODUCT_RECEIPT_SCHEMA_VERSION",
    "PRODUCT_REQUEST_SCHEMA_VERSION",
    "PRODUCT_RESULT_SCHEMA_VERSION",
    "ProductCatalogError",
    "build_a16_products_receipt",
    "load_stage_receipts",
    "validate_a16_products_receipt",
]
