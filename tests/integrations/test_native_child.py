from __future__ import annotations

import pytest

from srl.integrations import (
    NativeChildError,
    build_native_bridge_child_request,
    build_native_bridge_wait_receipt,
    verify_native_bridge_child_request,
)


def _request() -> dict[str, object]:
    return build_native_bridge_child_request(
        mission_id="market-bridge-child-v1",
        source_head="efb902a111111111111111111111111111111111",
        target_project="market",
        target_head="448a47388ca31309e3dc2b263bf326ca90f234ae",
        dependency_status="WAIT_RUNTIME_HEALTH:RED_F8",
        adapter_receipt_id="sha256:" + "1" * 64,
        requested_action="native merge inactive bridge only",
        signer_key_id="fixture-key",
        key_material=b"fixture-child-key",
    )


def test_native_child_request_is_signed_and_authority_negative() -> None:
    request = _request()

    verify_native_bridge_child_request(
        request,
        key_material_by_id={"fixture-key": b"fixture-child-key"},
    )
    assert request["native_closeout_status"] == "WAIT_NATIVE_CHILD_CLOSEOUT"
    assert request["activation_state"] == "INACTIVE"
    assert request["parent_direct_external_writes"] == 0
    assert request["live_actions"] == 0
    assert request["canonical_writes"] == 0
    assert request["grants_authority"] is False


def test_native_child_wait_receipt_is_authority_negative() -> None:
    receipt = build_native_bridge_wait_receipt(
        child_request=_request(),
        wait_state="WAIT_RUNTIME_HEALTH:RED_F8",
        next_native_gate="F8/resume_interrupted_durable_job",
    )

    assert receipt["wait_state"] == "WAIT_RUNTIME_HEALTH:RED_F8"
    assert receipt["next_native_gate"] == "F8/resume_interrupted_durable_job"
    assert receipt["parent_direct_external_writes"] == 0
    assert receipt["live_actions"] == 0
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_native_child_request_signature_detects_tamper() -> None:
    request = _request()
    tampered = dict(request)
    tampered["target_head"] = "0" * 40

    with pytest.raises(NativeChildError, match="signature"):
        verify_native_bridge_child_request(
            tampered,
            key_material_by_id={"fixture-key": b"fixture-child-key"},
        )
