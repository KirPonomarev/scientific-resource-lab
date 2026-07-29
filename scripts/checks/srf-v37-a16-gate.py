#!/usr/bin/env python3
"""V3.7 A16 scientific products activation gate."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts.ids import object_id  # noqa: E402
from srl.products.catalog import (  # noqa: E402
    EXPECTED_A16_PRODUCTS,
    MIN_PRODUCT_BACKENDS,
    ProductCatalogError,
    build_a16_products_receipt,
    load_stage_receipts,
    validate_a16_products_receipt,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A16"


def _check_product_receipts() -> dict[str, Any]:
    try:
        stage_receipts = load_stage_receipts(REPO_ROOT)
        products_receipt = build_a16_products_receipt(stage_receipts)
    except ProductCatalogError as exc:
        return {
            "check_id": "A16-01-product-request-result-receipt-chain",
            "status": "FAIL",
            "detail": str(exc),
            "products_receipt": None,
        }
    return {
        "check_id": "A16-01-product-request-result-receipt-chain",
        "status": "PASS",
        "detail": (
            "five scientific products carry complete request/result/receipt chains "
            "over hash-bound A09-A14 stage evidence"
        ),
        "products_receipt": products_receipt,
    }


def _check_backend_coverage(check: dict[str, Any]) -> dict[str, Any]:
    receipt = check.get("products_receipt")
    failures: list[str] = []
    backend_counts: dict[str, int] = {}
    stage_refs: dict[str, list[str]] = {}
    if not isinstance(receipt, dict):
        failures.append("products receipt missing")
    else:
        try:
            validate_a16_products_receipt(receipt)
        except ProductCatalogError as exc:
            failures.append(str(exc))
        for product in receipt.get("products", []):
            if not isinstance(product, dict):
                failures.append("product entry is not object")
                continue
            product_id = str(product.get("product_id"))
            backends = product.get("backend_ids")
            refs = product.get("stage_refs")
            if not isinstance(backends, list) or len(backends) < MIN_PRODUCT_BACKENDS:
                failures.append(f"{product_id} lacks at least two backend ids")
                continue
            backend_counts[product_id] = len(backends)
            stage_refs[product_id] = (
                [str(item.get("stage_id")) for item in refs if isinstance(item, dict)]
                if isinstance(refs, list)
                else []
            )
    return {
        "check_id": "A16-02-real-backend-coverage",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "each A16 product binds at least two real backend receipts where applicable",
        "backend_counts": backend_counts,
        "stage_refs": stage_refs,
    }


def _check_honesty_guards(check: dict[str, Any]) -> dict[str, Any]:
    receipt = check.get("products_receipt")
    failures: list[str] = []
    if not isinstance(receipt, dict):
        failures.append("products receipt missing")
    else:
        if receipt.get("canonical_writes") != 0 or receipt.get("grants_authority") is not False:
            failures.append("A16 receipt is not authority-negative")
        if receipt.get("creates_second_ledger") is not False:
            failures.append("A16 receipt creates a second ledger")
        if receipt.get("automatic_scientific_promotion") is not False:
            failures.append("A16 receipt allows automatic scientific promotion")
        for product in receipt.get("products", []):
            if isinstance(product, dict):
                failures.extend(_product_honesty_failures(product))
    return {
        "check_id": "A16-03-no-second-ledger-or-authority",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "A16 products remain authority-negative and preserve inconclusive/disagreement paths",
    }


def _product_honesty_failures(product: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    product_id = product.get("product_id")
    if product.get("creates_second_ledger") is not False:
        failures.append(f"{product_id} creates a second ledger")
    if product.get("promotion_allowed") is not False:
        failures.append(f"{product_id} allows promotion")
    if product.get("receipt_chain_complete") is not True:
        failures.append(f"{product_id} chain incomplete")
    result = product.get("result")
    if (
        not isinstance(result, dict)
        or result.get("inconclusive_and_disagreement_preserved") is not True
    ):
        failures.append(f"{product_id} collapsed inconclusive/disagreement path")
    return failures


def _build_stage_receipt() -> dict[str, Any]:
    chain = _check_product_receipts()
    coverage = _check_backend_coverage(chain)
    honesty = _check_honesty_guards(chain)
    checks = [chain, coverage, honesty]
    failures = [check for check in checks if check["status"] != "PASS"]
    result = "FAIL" if failures else "PASS"
    products_receipt = chain.get("products_receipt")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": result,
        "stage_closure": "A16_ACTIVE" if result == "PASS" else "A16_OPEN",
        "active_products": list(EXPECTED_A16_PRODUCTS) if result == "PASS" else [],
        "products_receipt_id": products_receipt.get("receipt_id")
        if isinstance(products_receipt, dict)
        else None,
        "parked_products": [],
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
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="optional path for the generated A16 receipt")
    args = parser.parse_args()
    receipt = _build_stage_receipt()
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
