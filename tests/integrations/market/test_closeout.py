from __future__ import annotations

from typing import Any

import pytest

from srl.integrations import (
    MARKET_IMPORTED_STATUS,
    MARKET_NATIVE_CLOSEOUT_SCHEMA_VERSION,
    MARKET_OFFLINE_WAIT_STATUS,
    MARKET_WAIT_STATUS,
    MarketCloseoutError,
    build_market_closeout_import_receipt,
    build_native_bridge_child_request,
)

_SRF_HEAD = "2b0852e599cd4c38bffc88d23c775aad07e31da7"
_MARKET_HEAD = "448a47388ca31309e3dc2b263bf326ca90f234ae"
_ADAPTER_RECEIPT_ID = "sha256:" + "84" * 32


def _child_request() -> dict[str, Any]:
    return build_native_bridge_child_request(
        mission_id="market-bridge-child-v1",
        source_head=_SRF_HEAD,
        target_project="crypto-market-lab",
        target_head=_MARKET_HEAD,
        dependency_status="WAIT_RUNTIME_HEALTH:ORGANISM_RED",
        adapter_receipt_id=_ADAPTER_RECEIPT_ID,
        requested_action=(
            "native validate and merge inactive Market bridge only; "
            "activation stays native protected action"
        ),
        signer_key_id="fixture-key",
        key_material=b"fixture-child-key",
    )


def _bootstrap() -> dict[str, Any]:
    return {
        "status": "pass_operator_bootstrap",
        "runtime_head": _MARKET_HEAD,
        "organism_status": "RED",
        "autonomous_mode": "DEGRADED",
        "next_gate": "F5/refresh_adapter",
        "operator_required": True,
        "trading_allowed": False,
        "canonical_mutation_allowed": False,
    }


def _native_closeout(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": MARKET_NATIVE_CLOSEOUT_SCHEMA_VERSION,
        "receipt_id": "sha256:" + "19" * 32,
        "mission_id": request["mission_id"],
        "child_request_id": request["request_id"],
        "source_project": request["source_project"],
        "source_head": request["source_head"],
        "target_project": request["target_project"],
        "target_head": request["target_head"],
        "adapter_receipt_id": request["adapter_receipt_id"],
        "central_projector_reused": True,
        "native_suite": {
            "status": "PASS",
            "command": "make operator-bootstrap && make inactive-market-bridge-contracts",
            "receipt_id": "sha256:" + "20" * 32,
        },
        "srf_suite": {
            "status": "PASS",
            "command": "uv run python scripts/checks/srf-v37-a19-gate.py",
            "receipt_id": "sha256:" + "21" * 32,
        },
        "activation_state": "INACTIVE",
        "parent_direct_external_writes": 0,
        "market_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "trading_allowed": False,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "market_activation_authority_granted": False,
    }


def test_market_closeout_import_waits_without_native_closeout() -> None:
    receipt = build_market_closeout_import_receipt(
        child_request=_child_request(),
        native_closeout=None,
        key_material_by_id={"fixture-key": b"fixture-child-key"},
        native_bootstrap_evidence=_bootstrap(),
    )

    assert receipt["status"] == MARKET_WAIT_STATUS
    assert receipt["srf_offline_status"] == MARKET_OFFLINE_WAIT_STATUS
    assert receipt["native_closeout_payload_sha256"] is None
    assert receipt["activation_state"] == "INACTIVE"
    assert receipt["market_writes"] == 0
    assert receipt["live_actions"] == 0
    assert receipt["trading_allowed"] is False
    assert receipt["grants_authority"] is False
    assert receipt["scientific_authority_granted"] is False
    assert receipt["market_activation_authority_granted"] is False


def test_market_closeout_import_accepts_hash_bound_native_closeout() -> None:
    request = _child_request()
    closeout = _native_closeout(request)

    receipt = build_market_closeout_import_receipt(
        child_request=request,
        native_closeout=closeout,
        key_material_by_id={"fixture-key": b"fixture-child-key"},
        native_bootstrap_evidence=_bootstrap(),
    )

    assert receipt["status"] == MARKET_IMPORTED_STATUS
    assert receipt["native_closeout_receipt_id"] == closeout["receipt_id"]
    assert receipt["native_suite_status"] == "PASS"
    assert receipt["srf_suite_status"] == "PASS"
    assert receipt["central_projector_reused"] is True
    assert receipt["srf_offline_status"] == MARKET_OFFLINE_WAIT_STATUS


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("source_head", "0" * 40, "source_head"),
        ("target_head", "1" * 40, "target_head"),
        ("adapter_receipt_id", "sha256:" + "22" * 32, "adapter_receipt_id"),
        ("central_projector_reused", False, "central projector"),
        ("grants_authority", True, "grants_authority"),
        ("trading_allowed", True, "trading_allowed"),
        ("market_writes", 1, "market_writes"),
    ],
)
def test_market_closeout_import_rejects_mismatch_or_authority_claim(
    field: str,
    value: object,
    match: str,
) -> None:
    request = _child_request()
    closeout = _native_closeout(request)
    closeout[field] = value

    with pytest.raises(MarketCloseoutError, match=match):
        build_market_closeout_import_receipt(
            child_request=request,
            native_closeout=closeout,
            key_material_by_id={"fixture-key": b"fixture-child-key"},
            native_bootstrap_evidence=_bootstrap(),
        )


def test_market_closeout_import_rejects_failed_srf_suite() -> None:
    request = _child_request()
    closeout = _native_closeout(request)
    closeout["srf_suite"]["status"] = "FAIL"

    with pytest.raises(MarketCloseoutError, match="SRF suite"):
        build_market_closeout_import_receipt(
            child_request=request,
            native_closeout=closeout,
            key_material_by_id={"fixture-key": b"fixture-child-key"},
            native_bootstrap_evidence=_bootstrap(),
        )
