from __future__ import annotations

from typing import Any

import pytest

from srl.integrations import (
    DUAL_CONTOUR_CLOSEOUT_SCHEMA_VERSION,
    DUAL_CONTOUR_IMPORTED_STATUS,
    DUAL_CONTOUR_WAIT_STATUS,
    DualContourCloseoutError,
    build_dual_contour_closeout_import_receipt,
    build_shared_contract_child_mission_request,
    conformance_vectors_hash,
)


def _child_request() -> dict[str, Any]:
    return build_shared_contract_child_mission_request(
        source_head="1ede8d2fcec8c7bca61499ac49aeed0ea7f2690a",
        target_head="a3cc68227387954417931fe08f9d66b6212f3308",
        target_status="clean",
        signer_key_id="fixture-key",
        key_material=b"fixture-secret",
    )


def _startup(status: str = "FAIL") -> dict[str, Any]:
    return {
        "status": status,
        "command": "make contracts",
        "target_head": "a3cc68227387954417931fe08f9d66b6212f3308",
        "result": "provider proof identity or currentness is invalid",
    }


def _native_closeout(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": DUAL_CONTOUR_CLOSEOUT_SCHEMA_VERSION,
        "receipt_id": "sha256:" + "18" * 32,
        "mission_id": request["mission_id"],
        "child_request_id": request["request_id"],
        "source_project": request["source_project"],
        "source_head": request["source_head"],
        "target_project": request["target_project"],
        "target_head": request["target_head"],
        "schema_hashes": request["schema_hashes"],
        "conformance_vectors_hash": conformance_vectors_hash(request),
        "producer_suite": {
            "status": "PASS",
            "command": "uv run python scripts/checks/srf-v37-a18-gate.py",
            "receipt_id": "sha256:" + "19" * 32,
        },
        "consumer_suite": {
            "status": "PASS",
            "command": "make contracts && python3 tools/validate_srf_shared_contracts.py",
            "receipt_id": "sha256:" + "20" * 32,
        },
        "parent_direct_external_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "domain_authority_granted": False,
    }


def test_dual_contour_import_receipt_waits_without_native_closeout() -> None:
    request = _child_request()

    receipt = build_dual_contour_closeout_import_receipt(
        child_request=request,
        native_closeout=None,
        key_material_by_id={"fixture-key": b"fixture-secret"},
        native_startup_evidence=_startup(),
    )

    assert receipt["status"] == DUAL_CONTOUR_WAIT_STATUS
    assert receipt["native_closeout_payload_sha256"] is None
    assert receipt["parent_direct_external_writes"] == 0
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
    assert receipt["scientific_authority_granted"] is False
    assert receipt["domain_authority_granted"] is False


def test_dual_contour_import_accepts_hash_bound_native_closeout() -> None:
    request = _child_request()
    closeout = _native_closeout(request)

    receipt = build_dual_contour_closeout_import_receipt(
        child_request=request,
        native_closeout=closeout,
        key_material_by_id={"fixture-key": b"fixture-secret"},
        native_startup_evidence=_startup(status="PASS"),
    )

    assert receipt["status"] == DUAL_CONTOUR_IMPORTED_STATUS
    assert receipt["native_closeout_receipt_id"] == closeout["receipt_id"]
    assert receipt["producer_suite_status"] == "PASS"
    assert receipt["consumer_suite_status"] == "PASS"
    assert receipt["native_closeout_payload_sha256"]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("source_head", "0" * 40, "source_head"),
        ("target_head", "1" * 40, "target_head"),
        ("conformance_vectors_hash", "2" * 64, "conformance_vectors_hash"),
        ("grants_authority", True, "grants_authority"),
        ("scientific_authority_granted", True, "scientific_authority_granted"),
    ],
)
def test_dual_contour_import_rejects_mismatch_or_authority_claim(
    field: str,
    value: object,
    match: str,
) -> None:
    request = _child_request()
    closeout = _native_closeout(request)
    closeout[field] = value

    with pytest.raises(DualContourCloseoutError, match=match):
        build_dual_contour_closeout_import_receipt(
            child_request=request,
            native_closeout=closeout,
            key_material_by_id={"fixture-key": b"fixture-secret"},
            native_startup_evidence=_startup(status="PASS"),
        )


def test_dual_contour_import_rejects_failed_consumer_suite() -> None:
    request = _child_request()
    closeout = _native_closeout(request)
    closeout["consumer_suite"]["status"] = "FAIL"

    with pytest.raises(DualContourCloseoutError, match="consumer suite"):
        build_dual_contour_closeout_import_receipt(
            child_request=request,
            native_closeout=closeout,
            key_material_by_id={"fixture-key": b"fixture-secret"},
            native_startup_evidence=_startup(status="PASS"),
        )
