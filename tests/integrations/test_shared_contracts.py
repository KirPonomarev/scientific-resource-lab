from __future__ import annotations

from typing import Any, cast

import pytest

from srl.integrations import (
    ConformanceVector,
    SharedContractError,
    build_shared_contract_child_mission_request,
    build_shared_contract_conformance_receipt,
    default_shared_contract_vectors,
    verify_shared_contract_child_mission_request,
)


def test_default_conformance_vectors_accept_and_reject_as_declared() -> None:
    receipt = build_shared_contract_conformance_receipt()

    assert receipt["schema_version"] == "SharedContractConformanceReceipt/v1"
    outcomes = cast(list[dict[str, Any]], receipt["outcomes"])
    assert [outcome["observed"] for outcome in outcomes] == [
        "ACCEPT",
        "ACCEPT",
        "REJECT",
    ]
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_conformance_receipt_rejects_mismatched_expected_accept() -> None:
    bad = ConformanceVector(
        vector_id="bad.accept",
        schema_name="ScientificResultEnvelope",
        expected="ACCEPT",
        instance=default_shared_contract_vectors()[-1].instance,
    )

    with pytest.raises(SharedContractError, match="should accept"):
        build_shared_contract_conformance_receipt(vectors=(bad,))


def test_child_mission_request_is_signed_wait_native_and_authority_negative() -> None:
    request = build_shared_contract_child_mission_request(
        source_head="510548ccf10a5ca556f72fe4c6b05d189c103c36",
        target_head="a3cc68227387954417931fe08f9d66b6212f3308",
        target_status="clean",
        signer_key_id="fixture-key",
        key_material=b"fixture-secret",
    )

    verify_shared_contract_child_mission_request(
        request,
        key_material_by_id={"fixture-key": b"fixture-secret"},
    )
    assert request["native_closeout_status"] == "WAIT_NATIVE_CHILD_CLOSEOUT"
    assert request["parent_direct_external_writes"] == 0
    assert request["canonical_writes"] == 0
    assert request["grants_authority"] is False
    schema_hashes = cast(dict[str, str], request["schema_hashes"])
    assert set(schema_hashes) == {
        "ScientificRequestEnvelope",
        "ScientificResultEnvelope",
    }


def test_child_mission_request_signature_detects_tamper() -> None:
    request = build_shared_contract_child_mission_request(
        source_head="510548ccf10a5ca556f72fe4c6b05d189c103c36",
        target_head="a3cc68227387954417931fe08f9d66b6212f3308",
        target_status="clean",
        signer_key_id="fixture-key",
        key_material=b"fixture-secret",
    )
    tampered = dict(request)
    tampered["target_head"] = "0" * 40

    with pytest.raises(SharedContractError, match="signature"):
        verify_shared_contract_child_mission_request(
            tampered,
            key_material_by_id={"fixture-key": b"fixture-secret"},
        )
