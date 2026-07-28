"""Unit tests for the science-lab run receipts and the claim_id regression fix.

Pins:

1. **Engine receipt** (``ScienceLabEngineReceipt/v1``): the probe-is-not-compute
   invariant (``exercise_level=import_probe`` forbids non-empty
   ``output_object_ids``), the safety consts, and identity idempotency.
2. **Validation receipt** (``ScienceLabValidationReceipt/v1``): the
   proven-requires-certificate invariant and the empirical-axis independence
   (a proven formal check does not claim statistical/causal support by itself).
3. **Run receipt** (``ScienceLabRunReceipt/v1``): the terminal-status enum and
   the aggregate resource-usage shape.
4. **Receipt safety consts** (``scripts/checks/receipt-invariants``): every
   receipt schema pins ``canonical_writes=0`` and ``grants_authority=false``
   as ``const``.
5. **claim_id regression** (WP-B13 bugfix): building the same claim twice
   yields the same ``claim_id``; a claim whose ``claim_id`` was computed over
   itself-with-id is rejected.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.contracts.schema import validate as schema_validate
from srl.semantic.claims import (
    CLAIM_INVARIANT_FAIL_REASON,
    ClaimInvariantError,
    claim_id,
)
from srl.semantic.claims import (
    validate as validate_claim,
)
from srl.semantic.evidence import (
    build_engine_receipt,
    build_run_receipt,
    build_validation_receipt,
)

# A canonical sha256 digest used across fixture receipts / object ids.
_DIGEST = "sha256:" + "a" * 64
_PACK_REF = {
    "schema_version": "ArtifactRef/v1",
    "media_type": "application/vnd.srlab.adapter-pack+json",
    "digest": _DIGEST,
    "size_bytes": 4096,
}
_CERT_REF = {
    "schema_version": "ArtifactRef/v1",
    "media_type": "application/vnd.srlab.formal-certificate+json",
    "digest": _DIGEST,
    "size_bytes": 512,
}

# Fixtures directory (repo-relative for the round-trip tests).
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "conformance" / "evidence"


# --- Pins: engine receipt -------------------------------------------------


def test_engine_receipt_safety_consts() -> None:
    """An engine receipt pins canonical_writes=0 and grants_authority=false."""
    er = build_engine_receipt(
        run_request_id=_DIGEST,
        adapter_id="solver",
        pack_ref=_PACK_REF,
        engine_execution="completed",
        exercise_level="actual_compute",
        wall_seconds=1,
        rss_bytes=1,
    )
    assert er["canonical_writes"] == 0
    assert er["grants_authority"] is False


def test_engine_receipt_id_is_sha256_without_id_field() -> None:
    """The engine receipt_id is sha256 over the receipt without the id field."""
    er = build_engine_receipt(
        run_request_id=_DIGEST,
        adapter_id="solver",
        pack_ref=_PACK_REF,
        engine_execution="completed",
        exercise_level="actual_compute",
        wall_seconds=1,
        rss_bytes=1,
    )
    without_id = {k: v for k, v in er.items() if k != "receipt_id"}
    expected = "sha256:" + hashlib.sha256(dumps(without_id)).hexdigest()
    assert er["receipt_id"] == expected


def test_engine_receipt_probe_no_outputs_valid() -> None:
    """An import_probe receipt with no outputs is valid."""
    er = build_engine_receipt(
        run_request_id=_DIGEST,
        adapter_id="solver",
        pack_ref=_PACK_REF,
        engine_execution="failed",
        exercise_level="import_probe",
        wall_seconds=0,
        rss_bytes=0,
    )
    schema_validate(er, "ScienceLabEngineReceipt")
    assert er["output_object_ids"] == []


def test_engine_receipt_rejects_bool_resource() -> None:
    """A bool resource-usage value is rejected (a flag is not a count)."""
    with pytest.raises(ContractError):
        build_engine_receipt(
            run_request_id=_DIGEST,
            adapter_id="solver",
            pack_ref=_PACK_REF,
            engine_execution="completed",
            exercise_level="actual_compute",
            wall_seconds=True,  # type: ignore[arg-type]
            rss_bytes=1,
        )


# --- Pins: validation receipt ---------------------------------------------


def test_validation_receipt_proven_carries_certificate() -> None:
    """A proven validation receipt carries a non-null certificate."""
    vr = build_validation_receipt(
        engine_receipt_id=_DIGEST,
        validator_id="v",
        scientific_check="checked",
        formal_check="proven",
        formal_certificate_ref=_CERT_REF,
    )
    assert vr["formal_certificate_ref"] == _CERT_REF


def test_validation_receipt_proven_does_not_imply_statistical() -> None:
    """A proven formal check does not, by itself, claim statistical support.

    The statistical/causal axes are carried explicitly and independently; a
    proven formal check leaves them at their caller-supplied values (default
    none / not_applicable). Formal proof is not empirical truth.
    """
    vr = build_validation_receipt(
        engine_receipt_id=_DIGEST,
        validator_id="v",
        scientific_check="checked",
        formal_check="proven",
        formal_certificate_ref=_CERT_REF,
    )
    assert vr["formal_check"] == "proven"
    assert vr["statistical_support"] == "none"
    assert vr["causal_identification"] == "not_applicable"


def test_validation_receipt_rejects_unknown_scientific_check() -> None:
    """An unknown scientific_check value is rejected."""
    with pytest.raises(ContractError):
        build_validation_receipt(
            engine_receipt_id=_DIGEST,
            validator_id="v",
            scientific_check="bogus",
            formal_check="unchecked",
        )


def test_validation_receipt_safety_consts() -> None:
    """A validation receipt pins canonical_writes=0 and grants_authority=false."""
    vr = build_validation_receipt(
        engine_receipt_id=_DIGEST,
        validator_id="v",
        scientific_check="checked",
        formal_check="checked",
    )
    assert vr["canonical_writes"] == 0
    assert vr["grants_authority"] is False


# --- Pins: run receipt ----------------------------------------------------


def test_run_receipt_null_validation_allowed() -> None:
    """A run receipt with a null validation_receipt_id is valid (no validation)."""
    rr = build_run_receipt(
        run_request_id=_DIGEST,
        engine_receipt_id=_DIGEST,
        validation_receipt_id=None,
        terminal_status="inconclusive",
        resource_usage={"wall_seconds": 1, "rss_bytes": 1, "output_bytes": 1},
    )
    schema_validate(rr, "ScienceLabRunReceipt")
    assert rr["validation_receipt_id"] is None


def test_run_receipt_safety_consts() -> None:
    """A run receipt pins canonical_writes=0 and grants_authority=false."""
    rr = build_run_receipt(
        run_request_id=_DIGEST,
        engine_receipt_id=_DIGEST,
        validation_receipt_id=None,
        terminal_status="failed",
        resource_usage={"wall_seconds": 0, "rss_bytes": 0, "output_bytes": 0},
    )
    assert rr["canonical_writes"] == 0
    assert rr["grants_authority"] is False


def test_run_receipt_rejects_extra_resource_key() -> None:
    """An unexpected resource_usage key is rejected."""
    with pytest.raises(ContractError):
        build_run_receipt(
            run_request_id=_DIGEST,
            engine_receipt_id=_DIGEST,
            validation_receipt_id=None,
            terminal_status="inconclusive",
            resource_usage={"wall_seconds": 0, "rss_bytes": 0, "output_bytes": 0, "extra": 1},
        )


# --- Pins: positive fixtures round-trip -----------------------------------


def test_receipt_positive_fixtures_validate() -> None:
    """The engine/validation/run receipt positive fixtures validate."""
    mapping = {
        "p03-engine-receipt-compute": "ScienceLabEngineReceipt",
        "p04-validation-receipt-proven-cert": "ScienceLabValidationReceipt",
        "p05-run-receipt-completed": "ScienceLabRunReceipt",
    }
    for name, schema in mapping.items():
        doc = json.loads((_FIXTURES / f"{name}.input.json").read_text(encoding="utf-8"))
        schema_validate(doc, schema)


# --- claim_id regression (WP-B13 bugfix) ----------------------------------
#
# The claim_id self-hash / idempotency gap: claim_id previously hashed the
# claim including its own claim_id field. The fix strips the field before
# hashing (mirroring transforms.receipt_id / adapter_profiles.profile_id) and
# validate gains a claim_id_consistent invariant that rejects a self-hash id.


def _claim_fields() -> dict[str, object]:
    """Return a valid established_law_reference claim WITHOUT a claim_id."""
    return {
        "schema_version": "ScientificClaim/v1",
        "statement": {"subject": "F", "predicate": "equals", "object": "m*a"},
        "claim_class": "established_law_reference",
        "claim_status": "supported",
        "epistemic_source": "literature",
        "support_refs": [_DIGEST],
        "created_utc": "2026-07-28T01:02:03Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def test_claim_id_idempotent_with_and_without_id() -> None:
    """Building the same claim twice yields the same claim_id.

    The idempotency property: claim_id(claim_without_id) ==
    claim_id(claim_with_correct_id). The pre-fix code hashed the id field into
    its own hash, breaking this.
    """
    computed = claim_id(_claim_fields())
    claim_with_id = dict(_claim_fields())
    claim_with_id["claim_id"] = computed
    assert claim_id(claim_with_id) == computed


def test_claim_id_rejects_self_hash_id() -> None:
    """A claim whose claim_id was computed over the claim WITH its id is rejected.

    A self-hash id is a logically inconsistent identity (the id depends on a
    field whose value is the id). validate rejects it with the
    claim_id_consistent invariant.
    """
    claim_with_placeholder = dict(_claim_fields())
    claim_with_placeholder["claim_id"] = _DIGEST  # a placeholder id
    # The bug: computing the id over the claim INCLUDING its id field.
    buggy_id = "sha256:" + hashlib.sha256(dumps(claim_with_placeholder)).hexdigest()
    buggy_claim = dict(_claim_fields())
    buggy_claim["claim_id"] = buggy_id
    with pytest.raises(ClaimInvariantError) as exc_info:
        validate_claim(buggy_claim)
    assert exc_info.value.fail_reason == CLAIM_INVARIANT_FAIL_REASON
    assert exc_info.value.invariant == "claim_id_consistent"


def test_claim_id_accepts_consistent_id() -> None:
    """A claim carrying a claim_id matching its content-addressed id is valid."""
    claim = dict(_claim_fields())
    claim["claim_id"] = claim_id(_claim_fields())
    assert validate_claim(claim) == claim
