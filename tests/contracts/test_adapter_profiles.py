"""Unit tests for the AdapterSemanticProfile/v1 validator (srl.semantic.adapter_profiles).

Pins:

1. **Allowlist closure**: a profile's ``supported_cds`` MUST be a subset of
   :data:`~srl.semantic.ir.MATH_IR_ALLOWLIST`; an entry outside it is rejected
   with :class:`ProfileInvariantError` (invariant
   ``supported_op_outside_allowlist``, fail reason ``CONTRACT_INVALID``).
2. **Supported/unsupported contradiction**: a feature declared in
   ``unsupported_features`` that is also in ``supported_cds`` is rejected
   (invariant ``feature_both_supported_and_unsupported``).
3. **Identity**: ``profile_id`` is the sha256 over the canonical bytes of the
   profile without the ``profile_id`` field, and is idempotent.
4. **Schema round-trips**: the positive fixture validates against the
   ``AdapterSemanticProfile`` schema and round-trips the Python validator.
5. **pack_ref defense in depth**: the inline ``pack_ref`` is validated against
   the full ``ArtifactRef/v1`` contract (portable-path rejection etc.).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.contracts.schema import ContractValidationError
from srl.contracts.schema import validate as schema_validate
from srl.semantic.adapter_profiles import (
    PROFILE_INVARIANT_FAIL_REASON,
    ProfileInvariantError,
    build_profile,
    profile_id,
    validate_profile,
)
from srl.semantic.ir import MATH_IR_ALLOWLIST

# Fixtures directory (repo-relative for the round-trip tests).
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "conformance" / "transformations"

# A canonical sha256 digest used across fixture profiles / pack digests.
_DIGEST = "sha256:" + "a" * 64


def _good_profile() -> dict[str, object]:
    """A minimal valid AdapterSemanticProfile/v1 base (without profile_id)."""
    return {
        "schema_version": "AdapterSemanticProfile/v1",
        "adapter_id": "test-solver",
        "pack_ref": {
            "schema_version": "ArtifactRef/v1",
            "media_type": "application/vnd.srlab.adapter-pack+json",
            "digest": _DIGEST,
            "size_bytes": 4096,
        },
        "supported_cds": ["arith1.plus", "arith1.minus", "relation1.eq"],
        "unsupported_features": [
            {"feature": "calculus1.diff", "behavior": "drop", "note": "no diff"}
        ],
        "input_contract": "MathIR",
        "output_contract": "MathIR",
        "deterministic": True,
        "network_access": "none",
        "license_spdx": "Apache-2.0",
        "canonical_writes": 0,
        "grants_authority": False,
    }


# ---------------------------------------------------------------------------
# Pins: allowlist closure.
# ---------------------------------------------------------------------------


def test_supported_cds_subset_of_allowlist_validates() -> None:
    """A supported_cds subset of MATH_IR_ALLOWLIST validates."""
    profile = _good_profile()
    validate_profile(profile)  # should not raise


@pytest.mark.parametrize("op", sorted(MATH_IR_ALLOWLIST))
def test_every_allowlisted_op_accepted_in_supported_cds(op: str) -> None:
    """Every allowlisted op is accepted as a supported_cds entry."""
    profile = _good_profile()
    # Clear the default unsupported_features so the single supported op cannot
    # contradict a feature declaration (the parametrized op varies).
    profile["supported_cds"] = [op]
    profile["unsupported_features"] = []
    validate_profile(profile)  # should not raise


def test_op_outside_allowlist_rejected() -> None:
    """An op outside MATH_IR_ALLOWLIST is rejected (supported_op_outside_allowlist)."""
    profile = _good_profile()
    profile["supported_cds"] = ["arith1.plus", "transc1.exp"]
    with pytest.raises(ProfileInvariantError) as exc_info:
        validate_profile(profile)
    assert exc_info.value.fail_reason == PROFILE_INVARIANT_FAIL_REASON
    assert exc_info.value.invariant == "supported_op_outside_allowlist"
    assert "transc1.exp" in str(exc_info.value)


def test_unknown_cd_in_supported_rejected() -> None:
    """An entirely unknown cd in supported_cds is rejected."""
    profile = _good_profile()
    profile["supported_cds"] = ["foo1.bar"]
    with pytest.raises(ProfileInvariantError) as exc_info:
        validate_profile(profile)
    assert exc_info.value.invariant == "supported_op_outside_allowlist"


# ---------------------------------------------------------------------------
# Pins: supported/unsupported contradiction.
# ---------------------------------------------------------------------------


def test_feature_both_supported_and_unsupported_rejected() -> None:
    """An exact op in both supported_cds and unsupported_features is a contradiction."""
    profile = _good_profile()
    profile["supported_cds"] = ["arith1.plus", "calculus1.diff"]
    profile["unsupported_features"] = [{"feature": "calculus1.diff", "behavior": "drop"}]
    with pytest.raises(ProfileInvariantError) as exc_info:
        validate_profile(profile)
    assert exc_info.value.invariant == "feature_both_supported_and_unsupported"


def test_cd_wildcard_allowed_alongside_supported() -> None:
    """A cd wildcard ('calculus1.*') overlaps by design and is allowed."""
    profile = _good_profile()
    # calculus1.partialdiff is supported, but a calculus1.* wildcard for the
    # rest of the cd is allowed (the wildcard covers the unsupported remainder).
    profile["supported_cds"] = ["arith1.plus", "calculus1.partialdiff"]
    profile["unsupported_features"] = [{"feature": "calculus1.*", "behavior": "drop"}]
    validate_profile(profile)  # should not raise


# ---------------------------------------------------------------------------
# Pins: identity + schema round-trips.
# ---------------------------------------------------------------------------


def test_profile_id_is_sha256_without_id_field() -> None:
    """profile_id is sha256 over the canonical bytes of the profile without profile_id."""
    built = build_profile(_good_profile())
    without_id = {k: v for k, v in built.items() if k != "profile_id"}
    expected = "sha256:" + hashlib.sha256(dumps(without_id)).hexdigest()
    assert built["profile_id"] == expected


def test_profile_id_is_idempotent() -> None:
    """profile_id computed on a profile with or without its id field is equal."""
    built = build_profile(_good_profile())
    assert profile_id(built) == built["profile_id"]
    without_id = {k: v for k, v in built.items() if k != "profile_id"}
    assert profile_id(without_id) == built["profile_id"]


def test_profile_id_is_deterministic() -> None:
    """The same inputs yield the same profile_id on every build."""
    a = build_profile(_good_profile())
    b = build_profile(_good_profile())
    assert a == b
    assert a["profile_id"] == b["profile_id"]


def test_positive_fixture_validates_and_round_trips() -> None:
    """The p02 profile fixture validates + round-trips the Python validator."""
    path = _FIXTURES / "p02-profile-solver-no-calculus.input.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    schema_validate(doc, "AdapterSemanticProfile")
    validate_profile(doc)
    assert profile_id(doc) == doc["profile_id"]


def test_negative_fixture_outside_allowlist_rejected() -> None:
    """The n03 profile (op outside allowlist) is rejected by validate_profile."""
    path = _FIXTURES / "negative" / "n03-profile-op-outside-allowlist.input.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(ProfileInvariantError) as exc_info:
        validate_profile(doc)
    assert exc_info.value.invariant == "supported_op_outside_allowlist"


# ---------------------------------------------------------------------------
# Pins: pack_ref defense in depth + schema-level rejections.
# ---------------------------------------------------------------------------


def test_pack_ref_non_portable_path_rejected() -> None:
    """A pack_ref with a non-portable path is rejected (ArtifactRef defense in depth)."""
    profile = _good_profile()
    profile["pack_ref"] = {
        "schema_version": "ArtifactRef/v1",
        "media_type": "application/vnd.srlab.adapter-pack+json",
        "digest": _DIGEST,
        "size_bytes": 4096,
        "path": "/etc/passwd",  # absolute path -> non-portable
    }
    with pytest.raises(ContractError):
        validate_profile(profile)


def test_profile_rejects_grants_authority_true_schema() -> None:
    """grants_authority=true is rejected by the schema (safety const)."""
    profile = build_profile(_good_profile())  # carry profile_id so 'required' doesn't mask
    profile["grants_authority"] = True
    with pytest.raises(ContractValidationError) as exc_info:
        schema_validate(profile, "AdapterSemanticProfile")
    assert exc_info.value.validator == "const"
    assert "grants_authority" in exc_info.value.json_path


def test_profile_rejects_nonzero_canonical_writes_schema() -> None:
    """canonical_writes != 0 is rejected by the schema (safety const)."""
    profile = build_profile(_good_profile())  # carry profile_id so 'required' doesn't mask
    profile["canonical_writes"] = 1
    with pytest.raises(ContractValidationError) as exc_info:
        schema_validate(profile, "AdapterSemanticProfile")
    assert exc_info.value.validator == "const"


def test_profile_rejects_bad_behavior_schema() -> None:
    """An unsupported_features behavior outside the enum is rejected by the schema."""
    profile = build_profile(_good_profile())  # carry profile_id so 'required' doesn't mask
    profile["unsupported_features"] = [{"feature": "calculus1.diff", "behavior": "ignore"}]
    with pytest.raises(ContractValidationError) as exc_info:
        schema_validate(profile, "AdapterSemanticProfile")
    assert exc_info.value.validator == "enum"


def test_validate_rejects_wrong_schema_version() -> None:
    """A wrong schema_version is rejected."""
    profile = _good_profile()
    profile["schema_version"] = "AdapterSemanticProfile/v2"
    with pytest.raises(ContractError):
        validate_profile(profile)
