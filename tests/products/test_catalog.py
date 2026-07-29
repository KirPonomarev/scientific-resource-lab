from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from srl.products.catalog import (
    EXPECTED_A16_PRODUCTS,
    ProductCatalogError,
    build_a16_products_receipt,
    load_stage_receipts,
    validate_a16_products_receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_a16_products_bind_stage_receipts_and_complete_chains() -> None:
    receipt = build_a16_products_receipt(load_stage_receipts(REPO_ROOT))

    assert receipt["stage_id"] == "A16"
    assert receipt["product_ids"] == list(EXPECTED_A16_PRODUCTS)
    assert receipt["request_result_receipt_chain"] == "complete_per_product"
    assert receipt["creates_second_ledger"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False

    products = cast(list[dict[str, Any]], receipt["products"])
    assert [item["product_id"] for item in products] == list(EXPECTED_A16_PRODUCTS)
    for product in products:
        assert len(cast(list[str], product["backend_ids"])) >= 2
        assert product["receipt_chain_complete"] is True
        assert product["request_id"].startswith("sha256:")
        assert product["result_id"].startswith("sha256:")
        assert product["receipt_id"].startswith("sha256:")
        result = cast(dict[str, Any], product["result"])
        assert result["inconclusive_and_disagreement_preserved"] is True


def test_a16_formal_product_preserves_semantic_gap_manifests() -> None:
    receipt = build_a16_products_receipt(load_stage_receipts(REPO_ROOT))
    by_product = {
        item["product_id"]: item for item in cast(list[dict[str, Any]], receipt["products"])
    }
    formal = by_product["formal_verification_lab"]

    assert formal["backend_ids"] == ["lean", "mathlib", "rocq", "isabelle", "hol4"]
    formal_result = cast(dict[str, Any], cast(dict[str, Any], formal["result"])["result"])
    assert formal_result["translation_manifest_count"] == 3
    assert formal_result["disagreement_path"] == "semantic_gap_manifest_requires_independent_review"
    checks = cast(list[dict[str, Any]], formal_result["formal_checks"])
    assert all(str(item["receipt_id"]).startswith("sha256:") for item in checks)


def test_a16_rejects_product_with_single_backend() -> None:
    receipt = build_a16_products_receipt(load_stage_receipts(REPO_ROOT))
    broken = deepcopy(receipt)
    product = cast(list[dict[str, Any]], broken["products"])[0]
    product["backend_ids"] = ["pysr"]

    with pytest.raises(ProductCatalogError, match="lacks two backend"):
        validate_a16_products_receipt(broken)


def test_a16_rejects_second_ledger_or_authority() -> None:
    receipt = build_a16_products_receipt(load_stage_receipts(REPO_ROOT))
    broken = deepcopy(receipt)
    broken["creates_second_ledger"] = True

    with pytest.raises(ProductCatalogError, match="second ledger"):
        validate_a16_products_receipt(broken)


def test_a16_rejects_incomplete_product_chain() -> None:
    receipt = build_a16_products_receipt(load_stage_receipts(REPO_ROOT))
    broken = deepcopy(receipt)
    product = cast(list[dict[str, Any]], broken["products"])[1]
    product["receipt_chain_complete"] = False

    with pytest.raises(ProductCatalogError, match="chain incomplete"):
        validate_a16_products_receipt(broken)
