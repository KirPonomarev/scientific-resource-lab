"""Tests for :mod:`srl.packs.admission`.

All tests are hermetic: they exercise the admission state machine with synthetic
evidence dicts and never touch the network or the real pack store.
"""

from __future__ import annotations

from typing import Any

import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.packs import (
    ACTUAL_COMPUTE_FAILED_REASON,
    DEPENDENCY_LOCK_DRIFT_REASON,
    LICENSE_INCOMPATIBLE_REASON,
    LICENSE_UNKNOWN_REASON,
    PACK_INTEGRITY_FAILURE_REASON,
    PACK_PROBE_ONLY_REASON,
    UPSTREAM_SOURCE_UNVERIFIED_REASON,
    AdmissionError,
    AdmissionState,
    PackStageReceipt,
    advance,
    initial_state,
)
from srl.packs.receipts import STAGES


def _valid_evidence(stage: str) -> dict[str, Any]:
    """Return evidence that passes the gate for ``stage``."""
    evidence_by_stage: dict[str, dict[str, Any]] = {
        "DISCOVERED": {},
        "SOURCE_VERIFIED": {"kind": "source_verification", "verified": True},
        "LICENSE_CLEARED": {"kind": "license_clearance", "status": "allowed", "spdx": "MIT"},
        "LOCKED": {"kind": "lock_digest", "drift": False},
        "BUILT": {"kind": "build_manifest", "valid": True},
        "BYTE_VERIFIED": {"kind": "tree_hash", "matched": True},
        "RUNTIME_PROBED": {"kind": "runtime_probe", "passed": True},
        "ACTUAL_COMPUTE_PROBED": {"kind": "actual_compute_probe", "passed": True},
        "EXPERIMENTAL_ACCEPTED": {"kind": "experimental_accept", "detail": "admitted"},
    }
    return evidence_by_stage[stage]


def _advance_all(pack_id: str = "test.pack") -> AdmissionState:
    """Advance a pack through all eight transitions to EXPERIMENTAL_ACCEPTED."""
    state = initial_state(pack_id)
    for stage in STAGES[1:]:
        state, _ = advance(state, stage, _valid_evidence(stage))
    return state


def test_initial_state_is_discovered() -> None:
    """The initial state is DISCOVERED with no receipts."""
    state = initial_state("test.pack")
    assert state.current_stage == "DISCOVERED"
    assert state.receipts == ()
    assert state.pack_id == "test.pack"


def test_advance_through_all_stages_emits_eight_receipts() -> None:
    """Advancing through all eight transitions emits exactly eight receipts."""
    state = _advance_all()
    assert state.current_stage == "EXPERIMENTAL_ACCEPTED"
    assert len(state.receipts) == 8
    reached = [r.stage for r in state.receipts]
    assert reached == list(STAGES[1:])
    for receipt in state.receipts:
        assert isinstance(receipt, PackStageReceipt)
        assert receipt.schema_version == "PackStageReceipt/v1"
        assert receipt.receipt_id.startswith("sha256:")
        assert receipt.pack_id == "test.pack"
        assert receipt.canonical_writes == 0
        assert receipt.grants_authority is False


def test_skip_rejected_with_contract_invalid() -> None:
    """DISCOVERED -> BUILT is a skip and raises CONTRACT_INVALID naming the stage."""
    state = initial_state("test.pack")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "BUILT", _valid_evidence("BUILT"))
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON
    assert "LOCKED" in str(exc_info.value) or "BUILT" in str(exc_info.value)
    assert "skip" in str(exc_info.value).lower() or "missing" in str(exc_info.value).lower()


def test_regression_rejected() -> None:
    """Moving backwards is a structural contract error."""
    state = _advance_all()
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "BUILT", _valid_evidence("BUILT"))
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_unknown_stage_rejected() -> None:
    """An unknown stage name raises CONTRACT_INVALID."""
    state = initial_state("test.pack")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "NOT_A_STAGE", {"kind": "none"})
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_source_verification_failure() -> None:
    """Failed source verification raises UPSTREAM_SOURCE_UNVERIFIED."""
    state = initial_state("test.pack")
    with pytest.raises(AdmissionError) as exc_info:
        advance(
            state,
            "SOURCE_VERIFIED",
            {"kind": "source_verification", "verified": False},
        )
    assert exc_info.value.fail_reason == UPSTREAM_SOURCE_UNVERIFIED_REASON


def test_license_unknown_terminal() -> None:
    """An unknown license raises LICENSE_UNKNOWN."""
    state = initial_state("test.pack")
    state, _ = advance(state, "SOURCE_VERIFIED", _valid_evidence("SOURCE_VERIFIED"))
    with pytest.raises(AdmissionError) as exc_info:
        advance(
            state,
            "LICENSE_CLEARED",
            {"kind": "license_clearance", "status": "unknown", "spdx": "Weird-License"},
        )
    assert exc_info.value.fail_reason == LICENSE_UNKNOWN_REASON


def test_license_incompatible_terminal() -> None:
    """An incompatible license raises LICENSE_INCOMPATIBLE."""
    state = initial_state("test.pack")
    state, _ = advance(state, "SOURCE_VERIFIED", _valid_evidence("SOURCE_VERIFIED"))
    with pytest.raises(AdmissionError) as exc_info:
        advance(
            state,
            "LICENSE_CLEARED",
            {"kind": "license_clearance", "status": "incompatible", "spdx": "GPL-3.0"},
        )
    assert exc_info.value.fail_reason == LICENSE_INCOMPATIBLE_REASON


def test_license_invalid_status_contract_invalid() -> None:
    """A malformed license clearance status raises CONTRACT_INVALID."""
    state = initial_state("test.pack")
    state, _ = advance(state, "SOURCE_VERIFIED", _valid_evidence("SOURCE_VERIFIED"))
    with pytest.raises(AdmissionError) as exc_info:
        advance(
            state,
            "LICENSE_CLEARED",
            {"kind": "license_clearance", "status": "maybe", "spdx": "MIT"},
        )
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_lock_drift_terminal() -> None:
    """Lock drift raises DEPENDENCY_LOCK_DRIFT."""
    state = initial_state("test.pack")
    state, _ = advance(state, "SOURCE_VERIFIED", _valid_evidence("SOURCE_VERIFIED"))
    state, _ = advance(state, "LICENSE_CLEARED", _valid_evidence("LICENSE_CLEARED"))
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "LOCKED", {"kind": "lock_digest", "drift": True})
    assert exc_info.value.fail_reason == DEPENDENCY_LOCK_DRIFT_REASON


def test_build_manifest_invalid() -> None:
    """A failed manifest build raises PACK_INTEGRITY_FAILURE."""
    state = _advance_to("LOCKED")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "BUILT", {"kind": "build_manifest", "valid": False})
    assert exc_info.value.fail_reason == PACK_INTEGRITY_FAILURE_REASON


def test_byte_verification_mismatch() -> None:
    """A byte tree mismatch raises PACK_INTEGRITY_FAILURE."""
    state = _advance_to("BUILT")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "BYTE_VERIFIED", {"kind": "tree_hash", "matched": False})
    assert exc_info.value.fail_reason == PACK_INTEGRITY_FAILURE_REASON


def test_runtime_probe_failure() -> None:
    """A failed runtime probe raises ACTUAL_COMPUTE_FAILED."""
    state = _advance_to("BYTE_VERIFIED")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "RUNTIME_PROBED", {"kind": "runtime_probe", "passed": False})
    assert exc_info.value.fail_reason == ACTUAL_COMPUTE_FAILED_REASON


def test_actual_compute_probe_failure() -> None:
    """A failed actual compute probe raises ACTUAL_COMPUTE_FAILED."""
    state = _advance_to("RUNTIME_PROBED")
    with pytest.raises(AdmissionError) as exc_info:
        advance(
            state,
            "ACTUAL_COMPUTE_PROBED",
            {"kind": "actual_compute_probe", "passed": False},
        )
    assert exc_info.value.fail_reason == ACTUAL_COMPUTE_FAILED_REASON


def test_probe_only_cannot_reach_experimental_accepted() -> None:
    """RUNTIME_PROBED -> EXPERIMENTAL_ACCEPTED raises PACK_PROBE_ONLY."""
    state = _advance_to("RUNTIME_PROBED")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "EXPERIMENTAL_ACCEPTED", _valid_evidence("EXPERIMENTAL_ACCEPTED"))
    assert exc_info.value.fail_reason == PACK_PROBE_ONLY_REASON


def test_evidence_wrong_kind_contract_invalid() -> None:
    """Evidence with the wrong kind for the stage raises CONTRACT_INVALID."""
    state = _advance_to("LICENSE_CLEARED")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "LOCKED", {"kind": "source_verification", "drift": False})
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_malformed_evidence_contract_invalid() -> None:
    """Evidence without a string kind raises CONTRACT_INVALID."""
    state = _advance_to("SOURCE_VERIFIED")
    with pytest.raises(AdmissionError) as exc_info:
        advance(state, "LICENSE_CLEARED", {"kind": 123})
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_resume_idempotent() -> None:
    """Re-advancing the current stage returns the existing receipt unchanged."""
    state = _advance_to("SOURCE_VERIFIED")
    first_receipt = state.receipts[-1]

    resumed_state, resumed_receipt = advance(
        state,
        "SOURCE_VERIFIED",
        _valid_evidence("SOURCE_VERIFIED"),
    )
    assert resumed_state is state
    assert resumed_receipt.receipt_id == first_receipt.receipt_id
    assert resumed_receipt.created_utc == first_receipt.created_utc
    assert len(resumed_state.receipts) == len(state.receipts)


def test_advance_to_built_creates_state_with_pack_id() -> None:
    """Intermediate states carry the pack_id and current stage."""
    state = _advance_to("BUILT")
    assert state.pack_id == "test.pack"
    assert state.current_stage == "BUILT"
    assert len(state.receipts) == 4


def test_admission_state_receipt_chain_validation() -> None:
    """Building a state from a broken receipt chain raises AdmissionError."""
    state = _advance_to("ACTUAL_COMPUTE_PROBED")
    good_receipts = state.receipts
    # Mutate the from_stage of the last receipt to create a broken chain.
    broken_receipts = (
        *good_receipts[:-1],
        PackStageReceipt(
            schema_version=good_receipts[-1].schema_version,
            receipt_id=good_receipts[-1].receipt_id,
            pack_id=good_receipts[-1].pack_id,
            stage=good_receipts[-1].stage,
            from_stage="DISCOVERED",  # wrong previous stage
            evidence=good_receipts[-1].evidence,
            created_utc=good_receipts[-1].created_utc,
            canonical_writes=good_receipts[-1].canonical_writes,
            grants_authority=good_receipts[-1].grants_authority,
        ),
    )
    with pytest.raises(AdmissionError) as exc_info:
        AdmissionState(
            pack_id="test.pack",
            current_stage="ACTUAL_COMPUTE_PROBED",
            receipts=broken_receipts,
        )
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_advance_from_experimental_accepted_is_terminal() -> None:
    """Re-advancing the terminal stage returns the existing receipt unchanged."""
    state = _advance_all()
    resumed_state, resumed_receipt = advance(
        state,
        "EXPERIMENTAL_ACCEPTED",
        _valid_evidence("EXPERIMENTAL_ACCEPTED"),
    )
    assert resumed_state is state
    assert resumed_receipt.stage == "EXPERIMENTAL_ACCEPTED"


def _advance_to(stage: str) -> AdmissionState:
    """Advance the test pack to ``stage`` (inclusive)."""
    state = initial_state("test.pack")
    for s in STAGES[1:]:
        state, _ = advance(state, s, _valid_evidence(s))
        if s == stage:
            return state
    return state
