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


def _claim_fields(**overrides: object) -> dict[str, object]:
    """Return the claim fields WITHOUT a claim_id, with optional overrides.

    The claim_id is intentionally absent so callers either delete it (the
    idempotent build path) or compute the correct one via :func:`claim_id`. A
    placeholder id would now fail the ``claim_id_consistent`` invariant.
    """
    base: dict[str, object] = {
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
    base.update(overrides)
    return base


def _good_claim(**overrides: object) -> dict[str, object]:
    """Return a valid established_law_reference claim, with optional overrides.

    The ``claim_id`` is computed correctly (content-addressed over the claim
    WITHOUT the id field) so the ``claim_id_consistent`` invariant passes. If
    the overrides make the claim intentionally invalid (so the id cannot be
    computed), no id is set — the caller is testing a validation rejection, not
    id consistency, and will either delete the id or assert the validator
    raises. A caller that wants to test an inconsistent id can override
    ``claim_id`` after construction.
    """
    fields = _claim_fields(**overrides)
    without_id = {k: v for k, v in fields.items() if k != "claim_id"}
    try:
        fields["claim_id"] = claim_id(without_id)
    except ClaimInvariantError:
        # The overrides make the claim invalid; the caller is testing a
        # rejection, so a computed id is neither available nor needed.
        pass
    return fields


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
    claim = _claim_fields(support_refs=[])
    with pytest.raises(ClaimInvariantError):
        claim_id(claim)


# --- Pins: claim_id idempotency regression (WP-B13 bugfix) -----------------
#
# Regression for the claim_id self-hash / idempotency gap. claim_id previously
# hashed the claim including its own claim_id field (object_id only guards a
# field literally named 'object_id'), so computing claim_id on a claim with a
# populated id yielded a different, self-referential value than on the same
# claim without the id. The fix strips the claim_id field before hashing,
# mirroring srl.semantic.transforms.receipt_id and
# srl.semantic.adapter_profiles.profile_id, and validate now rejects a present
# claim_id that was computed over the claim including itself (invariant
# claim_id_consistent).


def test_claim_id_idempotent_with_and_without_id_field() -> None:
    """Building the same claim twice yields the same claim_id.

    The idempotency property: claim_id(claim_without_id) ==
    claim_id(claim_with_correct_id). This is the load-bearing property that
    lets two independent builders agree on a claim's identity with no
    coordination. The pre-fix code hashed the claim_id field into its own
    hash, breaking this.
    """
    claim = _good_claim()
    del claim["claim_id"]  # type: ignore[typeddict-item]
    computed = claim_id(claim)
    # The same claim, now carrying its correctly-computed id, must yield the
    # same id when claim_id is called again.
    claim_with_id = dict(claim)
    claim_with_id["claim_id"] = computed
    assert claim_id(claim_with_id) == computed


def test_claim_id_strips_self_before_hashing() -> None:
    """claim_id is computed over the claim WITHOUT the claim_id field."""
    claim = _good_claim()
    del claim["claim_id"]  # type: ignore[typeddict-item]
    expected = "sha256:" + hashlib.sha256(dumps(claim)).hexdigest()
    # A claim carrying its own claim_id must still hash to the same id (the id
    # field is stripped before hashing, so it cannot influence its own value).
    claim_with_id = dict(claim)
    claim_with_id["claim_id"] = expected
    assert claim_id(claim_with_id) == expected


def test_validate_rejects_self_hashed_claim_id() -> None:
    """A claim whose claim_id was computed over the claim WITH its id is rejected.

    A self-hash id is a logically inconsistent identity (the id depends on a
    field whose value is the id). validate rejects it with the
    claim_id_consistent invariant (defense in depth for the idempotency
    property).
    """
    claim = _good_claim()
    # Compute the id over the claim INCLUDING its claim_id field (the bug).
    buggy_id = "sha256:" + hashlib.sha256(dumps(_good_claim())).hexdigest()
    assert buggy_id != _good_claim()["claim_id"]  # confirm it differs
    claim["claim_id"] = buggy_id
    with pytest.raises(ClaimInvariantError) as exc_info:
        validate(claim)
    assert exc_info.value.fail_reason == CLAIM_INVARIANT_FAIL_REASON
    assert exc_info.value.invariant == "claim_id_consistent"


def test_claim_id_rejects_self_hashed_claim_id() -> None:
    """claim_id() rejects a claim carrying a self-hash id (via validate)."""
    claim = _good_claim()
    buggy_id = "sha256:" + hashlib.sha256(dumps(_good_claim())).hexdigest()
    claim["claim_id"] = buggy_id
    with pytest.raises(ClaimInvariantError) as exc_info:
        claim_id(claim)
    assert exc_info.value.invariant == "claim_id_consistent"


def test_validate_accepts_consistent_claim_id() -> None:
    """A claim carrying a claim_id matching its content-addressed id is valid."""
    claim = _good_claim()
    del claim["claim_id"]  # type: ignore[typeddict-item]
    correct = claim_id(claim)
    claim["claim_id"] = correct
    assert validate(claim) == claim
