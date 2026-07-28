"""ScientificClaim/v1: typed scientific statements under epistemic discipline.

This module is the Python counterpart of the ``ScientificClaim/v1`` JSON Schema
(``src/srl/contracts/schemas/v1/scientific-claim.json``). The schema encodes
the epistemic invariants structurally via ``allOf``/``if-then``; this module
re-checks the same invariants in Python as **defense in depth**. A green
result from either layer is still only an admission — it never means a claim
is *true*, only that it is well-formed under the contract (see
``GOVERNANCE.md`` for the evidence rules).

The critical invariants (encoded in the schema AND here)
--------------------------------------------------------
1. **established_law_reference requires literature + support**: a claim with
   ``claim_class='established_law_reference'`` MUST have
   ``epistemic_source='literature'`` AND a non-empty ``support_refs``. An
   established physical law cannot be asserted from an operator's own
   derivation or experiment — it must be cited from the literature and backed
   by at least one supporting object.
2. **a candidate hypothesis cannot graduate to supported unsupported**: a
   claim with ``claim_class='candidate_hypothesis'`` and
   ``claim_status='supported'`` MUST have non-empty ``support_refs``. A bare
   proposal cannot declare itself supported.

These prevent two prohibited collapses the governance layer cares about:
turning a hypothesis into a law, and turning an assertion into evidence. Both
raise :class:`ClaimInvariantError` (fail reason ``CONTRACT_INVALID``).
"""

from __future__ import annotations

from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id

# The typed fail reason for a claim-invariant violation. Claim invariants are
# structural contract failures, not scientific judgments; the fail reason is
# ``CONTRACT_INVALID``.
CLAIM_INVARIANT_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# The claim_class value that triggers the literature+support requirement.
_ESTABLISHED_LAW_REFERENCE: Final[str] = "established_law_reference"
# The claim_class + claim_status combination that triggers the support
# requirement for a candidate hypothesis.
_CANDIDATE_HYPOTHESIS: Final[str] = "candidate_hypothesis"
_SUPPORTED: Final[str] = "supported"
_LITERATURE: Final[str] = "literature"

# Identity anchor.
_SCIENTIFIC_CLAIM_V1: Final[str] = "ScientificClaim/v1"


class ClaimInvariantError(ContractError):
    """Raised when a ScientificClaim violates an epistemic invariant.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and the name of
    the violated ``invariant`` for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: str = "",
        fail_reason: str = CLAIM_INVARIANT_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.invariant: str = invariant


def claim_id(claim: dict[str, Any]) -> str:
    """Compute the ``claim_id`` for a claim: sha256 over its canonical bytes.

    The id is computed over the canonical encoding of the claim *without* the
    ``claim_id`` field, so a claim carrying a pre-populated id is rejected as a
    self-hash (propagated from :func:`srl.contracts.ids.object_id`). The claim
    is validated first (defense in depth).
    """
    validate(claim)
    return object_id(claim)


def validate(claim: Any) -> dict[str, Any]:
    """Validate a ScientificClaim/v1 document (wire dict) and return it.

    Enforces the two epistemic invariants in Python (defense in depth; the
    schema enforces the same structurally). This does NOT re-run the JSON
    Schema validation — callers that need schema validation should call
    :func:`srl.contracts.schema.validate` with ``"ScientificClaim"`` first.

    Raises
    ------
    ClaimInvariantError
        If ``claim_class='established_law_reference'`` lacks
        ``epistemic_source='literature'`` or a non-empty ``support_refs``, or
        if a ``candidate_hypothesis`` with ``claim_status='supported'`` lacks
        ``support_refs``.
    ContractError
        If the claim is not an object, has the wrong schema version, or is
        missing a required field the invariants depend on.
    """
    if not isinstance(claim, dict):
        msg = f"ScientificClaim must be an object, got {type(claim).__name__}"
        raise ContractError(msg)
    if claim.get("schema_version") != _SCIENTIFIC_CLAIM_V1:
        msg = (
            "ScientificClaim schema_version must be "
            f"{_SCIENTIFIC_CLAIM_V1!r}, got {claim.get('schema_version')!r}"
        )
        raise ContractError(msg)

    claim_class = claim.get("claim_class")
    claim_status = claim.get("claim_status")
    epistemic_source = claim.get("epistemic_source")
    support_refs = claim.get("support_refs", [])

    # The support_refs field must be a list (the schema enforces the type; we
    # only read it here). Guard against a non-list so the invariant check below
    # does not raise a confusing TypeError.
    if not isinstance(support_refs, list):
        msg = "ScientificClaim 'support_refs' must be an array"
        raise ContractError(msg)
    has_support = len(support_refs) > 0

    # Invariant 1: established_law_reference => literature source + support.
    if claim_class == _ESTABLISHED_LAW_REFERENCE:
        if epistemic_source != _LITERATURE:
            msg = (
                "ScientificClaim invariant violated: claim_class "
                f"{_ESTABLISHED_LAW_REFERENCE!r} requires "
                f"epistemic_source={_LITERATURE!r}, got {epistemic_source!r}"
            )
            raise ClaimInvariantError(msg, invariant="established_law_requires_literature")
        if not has_support:
            msg = (
                "ScientificClaim invariant violated: claim_class "
                f"{_ESTABLISHED_LAW_REFERENCE!r} requires at least one support_ref"
            )
            raise ClaimInvariantError(msg, invariant="established_law_requires_support")

    # Invariant 2: candidate_hypothesis + supported => support.
    if claim_class == _CANDIDATE_HYPOTHESIS and claim_status == _SUPPORTED and not has_support:
        msg = (
            "ScientificClaim invariant violated: a "
            f"{_CANDIDATE_HYPOTHESIS!r} cannot carry claim_status "
            f"{_SUPPORTED!r} without at least one support_ref"
        )
        raise ClaimInvariantError(msg, invariant="candidate_supported_requires_support")

    return claim


__all__ = [
    "CLAIM_INVARIANT_FAIL_REASON",
    "ClaimInvariantError",
    "claim_id",
    "validate",
]
