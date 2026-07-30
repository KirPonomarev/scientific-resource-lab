from __future__ import annotations

from typing import Any

import pytest

from srl.integrations import (
    SECURITY_IMPORTED_STATUS,
    SECURITY_NATIVE_CLOSEOUT_SCHEMA_VERSION,
    SECURITY_OFFLINE_WAIT_STATUS,
    SECURITY_WAIT_STATUS,
    SecurityCloseoutError,
    build_native_bridge_child_request,
    build_security_closeout_import_receipt,
)

_SRF_HEAD = "9c44d299a6940153e90dd14b4b49d2217112bb3c"
_SECURITY_HEAD = "c5e8349b05b601c3d2976da7bad58bf756600185"
_ADAPTER_RECEIPT_ID = "sha256:" + "34" * 32


def _child_request() -> dict[str, Any]:
    return build_native_bridge_child_request(
        mission_id="security-bridge-child-v1",
        source_head=_SRF_HEAD,
        target_project="security-research-os",
        target_head=_SECURITY_HEAD,
        dependency_status="WAIT_SECURITY_HEALTH:ORGANISM_RED",
        adapter_receipt_id=_ADAPTER_RECEIPT_ID,
        requested_action=(
            "native validate and merge inactive Security bridge only; "
            "target actions and scanner control stay native protected actions through ebashim"
        ),
        signer_key_id="fixture-key",
        key_material=b"fixture-child-key",
    )


def _bootstrap() -> dict[str, Any]:
    return {
        "status": "DEGRADED",
        "runtime_head": _SECURITY_HEAD,
        "organism_status": "RED",
        "technical_health": "RED",
        "next_gate": "review_knowledge_batch",
        "operator_required": True,
        "no_live_authority": True,
        "root_reason_code": "forbidden_checkout_data_entry:crypto_kb.db",
    }


def _native_closeout(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SECURITY_NATIVE_CLOSEOUT_SCHEMA_VERSION,
        "receipt_id": "sha256:" + "20" * 32,
        "mission_id": request["mission_id"],
        "child_request_id": request["request_id"],
        "source_project": request["source_project"],
        "source_head": request["source_head"],
        "target_project": request["target_project"],
        "target_head": request["target_head"],
        "adapter_receipt_id": request["adapter_receipt_id"],
        "native_suite": {
            "status": "PASS",
            "command": "python3 tools/superbrain_health.py --json",
            "receipt_id": "sha256:" + "21" * 32,
        },
        "srf_suite": {
            "status": "PASS",
            "command": "uv run python scripts/checks/srf-v37-a20-gate.py",
            "receipt_id": "sha256:" + "22" * 32,
        },
        "containment_suite": {
            "status": "PASS",
            "command": "pytest tests/integrations/security",
            "receipt_id": "sha256:" + "23" * 32,
        },
        "activation_state": "INACTIVE",
        "native_executor_boundary": "ebashim",
        "ebashim_preserved": True,
        "D0_D1_only_transport": True,
        "parent_direct_external_writes": 0,
        "security_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "security_actions": 0,
        "target_actions": 0,
        "D2_D3_transfers": 0,
        "credential_transfers": 0,
        "private_evidence_transfers": 0,
        "direct_scanner_control": False,
        "target_material_crossed": False,
        "exploit_material_crossed": False,
        "credential_material_crossed": False,
        "private_evidence_crossed": False,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "security_activation_authority_granted": False,
    }


def test_security_closeout_import_waits_without_native_closeout() -> None:
    receipt = build_security_closeout_import_receipt(
        child_request=_child_request(),
        native_closeout=None,
        key_material_by_id={"fixture-key": b"fixture-child-key"},
        native_bootstrap_evidence=_bootstrap(),
    )

    assert receipt["status"] == SECURITY_WAIT_STATUS
    assert receipt["srf_offline_status"] == SECURITY_OFFLINE_WAIT_STATUS
    assert receipt["native_closeout_payload_sha256"] is None
    assert receipt["activation_state"] == "INACTIVE"
    assert receipt["native_executor_boundary"] == "ebashim"
    assert receipt["security_actions"] == 0
    assert receipt["target_actions"] == 0
    assert receipt["D2_D3_transfers"] == 0
    assert receipt["direct_scanner_control"] is False
    assert receipt["grants_authority"] is False


def test_security_closeout_import_accepts_hash_bound_native_closeout() -> None:
    request = _child_request()
    closeout = _native_closeout(request)

    receipt = build_security_closeout_import_receipt(
        child_request=request,
        native_closeout=closeout,
        key_material_by_id={"fixture-key": b"fixture-child-key"},
        native_bootstrap_evidence=_bootstrap(),
    )

    assert receipt["status"] == SECURITY_IMPORTED_STATUS
    assert receipt["native_closeout_receipt_id"] == closeout["receipt_id"]
    assert receipt["native_suite_status"] == "PASS"
    assert receipt["srf_suite_status"] == "PASS"
    assert receipt["containment_suite_status"] == "PASS"
    assert receipt["ebashim_preserved"] is True
    assert receipt["D0_D1_only_transport"] is True


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("source_head", "0" * 40, "source_head"),
        ("target_head", "1" * 40, "target_head"),
        ("adapter_receipt_id", "sha256:" + "24" * 32, "adapter_receipt_id"),
        ("grants_authority", True, "grants_authority"),
        ("security_actions", 1, "security_actions"),
        ("target_actions", 1, "target_actions"),
        ("D2_D3_transfers", 1, "D2_D3_transfers"),
        ("credential_transfers", 1, "credential_transfers"),
        ("direct_scanner_control", True, "direct_scanner_control"),
        ("native_executor_boundary", "direct-scanner", "ebashim"),
        ("D0_D1_only_transport", False, "D0/D1"),
    ],
)
def test_security_closeout_import_rejects_mismatch_or_boundary_violation(
    field: str,
    value: object,
    match: str,
) -> None:
    request = _child_request()
    closeout = _native_closeout(request)
    closeout[field] = value

    with pytest.raises(SecurityCloseoutError, match=match):
        build_security_closeout_import_receipt(
            child_request=request,
            native_closeout=closeout,
            key_material_by_id={"fixture-key": b"fixture-child-key"},
            native_bootstrap_evidence=_bootstrap(),
        )


def test_security_closeout_import_rejects_failed_containment_suite() -> None:
    request = _child_request()
    closeout = _native_closeout(request)
    closeout["containment_suite"]["status"] = "FAIL"

    with pytest.raises(SecurityCloseoutError, match="containment suite"):
        build_security_closeout_import_receipt(
            child_request=request,
            native_closeout=closeout,
            key_material_by_id={"fixture-key": b"fixture-child-key"},
            native_bootstrap_evidence=_bootstrap(),
        )
