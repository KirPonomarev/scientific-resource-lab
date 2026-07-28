"""Unit tests for ScientificClaim/v1 epistemic invariants (srl.semantic.claims).

Pins the two critical invariants (encoded in the schema AND re-enforced in
Python as defense in depth):

1. **established_law_reference requires literature + support**: a claim with
   ``claim_class='established_law_reference'`` MUST have
   ``epistemic_source='literature'`` AND a non-empty ``support_refs``. A
   violation raises :class:`ClaimInvariantError` (fail reason
   ``CONTRACT_INVALID``) with the named invariant.
2. **candidate_hypothesis supported requires support**: a claim with
   ``claim_class='candidate_hypothesis'`` and ``claim_status='supported'`` MUST
   have non-empty ``support_refs``.
3. **claim_id**: the content-addressed id is sha256 over the canonical bytes
   of the claim without the id field, and is deterministic.
"""

from __future__ import annotations

import hashlib

import pytest

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.semantic.claims import (
    CLAIM_INVARIANT_FAIL_REASON,
    ClaimInvariantError,
    claim_id,
    validate,
)

# A canonical sha256 digest used for support refs / claim ids.
_DIGEST = "sha256:" + "a" * 64


def _good_claim(**overrides: object) -> dict[str, object]:
    """Return a valid established_law_reference claim, with optional overrides."""
    base: dict[str, object] = {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": {"subject": "F", "predicate": "equals", "object": "m*a"},
        "claim_class": "established_law_reference",
        "claim_status": "supported",
        "epistemic_source": "literature",
        "support_refs": [_DIGEST],
        "created_utc": "2026-07-28T01:02:03Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    base.update(overrides)
    return base


# --- Pins: happy paths ----------------------------------------------------


def test_validate_accepts_established_law() -> None:
    """A valid established_law_reference claim passes Python validation."""
    claim = _good_claim()
    assert validate(claim) == claim


def test_validate_accepts_candidate_hypothesis_proposed() -> None:
    """A candidate_hypothesis (proposed, unsupported) is valid."""
    claim = _good_claim(
        claim_class="candidate_hypothesis",
        claim_status="proposed",
        epistemic_source="operator",
        support_refs=[],
    )
    assert validate(claim) == claim


def test_validate_accepts_candidate_hypothesis_supported_with_support() -> None:
    """A candidate_hypothesis with status=supported AND support_refs is valid."""
    claim = _good_claim(
        claim_class="candidate_hypothesis",
        claim_status="supported",
        epistemic_source="experiment",
        support_refs=[_DIGEST],
    )
    assert validate(claim) == claim


def test_validate_accepts_definition() -> None:
    """A definition claim (tautological) is valid without support."""
    claim = _good_claim(
        claim_class="definition",
        claim_status="supported",
        epistemic_source="operator",
        support_refs=[],
    )
    assert validate(claim) == claim


# --- Pins: invariant 1 — established_law_reference ------------------------


def test_established_law_without_support_rejects() -> None:
    """established_law_reference with empty support_refs is rejected."""
    with pytest.raises(ClaimInvariantError) as exc_info:
        validate(_good_claim(support_refs=[]))
    assert exc_info.value.fail_reason == CLAIM_INVARIANT_FAIL_REASON
    assert exc_info.value.invariant == "established_law_requires_support"


def test_established_law_wrong_source_rejects() -> None:
    """established_law_reference with a non-literature source is rejected."""
    with pytest.raises(ClaimInvariantError) as exc_info:
        validate(_good_claim(epistemic_source="operator"))
    assert exc_info.value.fail_reason == CLAIM_INVARIANT_FAIL_REASON
    assert exc_info.value.invariant == "established_law_requires_literature"


@pytest.mark.parametrize("source", ["operator", "derivation", "experiment"])
def test_established_law_rejects_every_non_literature_source(source: str) -> None:
    """Every non-literature source is rejected for an established law."""
    with pytest.raises(ClaimInvariantError):
        validate(_good_claim(epistemic_source=source))


# --- Pins: invariant 2 — candidate_hypothesis supported -------------------


def test_candidate_supported_without_support_rejects() -> None:
    """candidate_hypothesis + supported + empty support_refs is rejected."""
    with pytest.raises(ClaimInvariantError) as exc_info:
        validate(
            _good_claim(
                claim_class="candidate_hypothesis",
                claim_status="supported",
                epistemic_source="operator",
                support_refs=[],
            )
        )
    assert exc_info.value.fail_reason == CLAIM_INVARIANT_FAIL_REASON
    assert exc_info.value.invariant == "candidate_supported_requires_support"


def test_candidate_refuted_without_support_ok() -> None:
    """A refuted candidate hypothesis needs no support (only supported does)."""
    claim = _good_claim(
        claim_class="candidate_hypothesis",
        claim_status="refuted",
        epistemic_source="experiment",
        support_refs=[],
    )
    assert validate(claim) == claim


# --- Pins: structural validation ------------------------------------------


def test_validate_rejects_non_object() -> None:
    """A non-object is rejected."""
    with pytest.raises(ContractError):
        validate([1, 2])  # type: ignore[arg-type]


def test_validate_rejects_wrong_version() -> None:
    """A wrong schema_version is rejected."""
    with pytest.raises(ContractError):
        validate(_good_claim(schema_version="ScientificClaim/v2"))


def test_validate_rejects_non_list_support_refs() -> None:
    """A non-list support_refs is rejected (the invariant read must not TypeError)."""
    with pytest.raises(ContractError):
        validate(_good_claim(support_refs="sha256:x"))  # type: ignore[dict-item]


# --- Pins: claim_id --------------------------------------------------------


def test_claim_id_is_sha256_of_canonical_bytes() -> None:
    """claim_id is sha256 over the canonical bytes of the claim without the id."""
    claim = _good_claim()
    del claim["claim_id"]  # type: ignore[typeddict-item]
    expected = "sha256:" + hashlib.sha256(dumps(claim)).hexdigest()
    assert claim_id(claim) == expected


def test_claim_id_is_deterministic() -> None:
    """The same claim yields the same id on every call."""
    claim = _good_claim()
    del claim["claim_id"]  # type: ignore[typeddict-item]
    assert claim_id(claim) == claim_id(claim)


def test_claim_id_validates_first() -> None:
    """claim_id validates the claim; an invariant violation gets no id."""
    claim = _good_claim(support_refs=[])
    del claim["claim_id"]  # type: ignore[typeddict-item]
    with pytest.raises(ClaimInvariantError):
        claim_id(claim)
