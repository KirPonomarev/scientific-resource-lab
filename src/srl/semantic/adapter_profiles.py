"""AdapterSemanticProfile/v1: a typed semantic profile for a backend adapter.

This module is the Python counterpart of the ``AdapterSemanticProfile/v1`` JSON
Schema (``src/srl/contracts/schemas/v1/adapter-semantic-profile.json``). It
provides three things:

1. **A typed model** for an adapter profile (the dict-of-fields wire form) with
   a ``profile_id`` helper computing its content-addressed identity.
2. **A validator** (:func:`validate_profile`) that re-checks the contract
   invariants in Python as **defense in depth**:
   - every entry in ``supported_cds`` is a member of
     :data:`~srl.semantic.ir.MATH_IR_ALLOWLIST` (a profile cannot claim support
     for an operator the IR does not admit — the allowlist is closed);
   - no entry in ``unsupported_features`` names an operator also present in
     ``supported_cds`` (an operator is either supported or it is not).
3. **A builder** (:func:`build_profile`) that validates and computes the
   ``profile_id`` in one call.

Admission, not authorization
----------------------------
A validated profile admits a backend adapter's *contract* into the fabric. It
does NOT mean the adapter may run: ``grants_authority`` is pinned to ``false``
by the schema, and whether an adapter executes is a governance decision (see
``GOVERNANCE.md``). The profile is the input the projection machinery
(:mod:`srl.semantic.transforms`) consults to decide how an IR tree maps onto a
backend's supported operator subset.
"""

from __future__ import annotations

from typing import Any, Final

from srl.contracts.artifact_refs import (
    ArtifactRefError,
    validate_artifact_ref,
)
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id
from srl.semantic.ir import MATH_IR_ALLOWLIST

# The pack_ref is carried inline as a structural ArtifactRef/v1 object (see the
# schema); the full ArtifactRef field contract — including the portable-path
# rejection — is enforced here at the Python layer, defense in depth. This
# mirrors the repo convention (inline structural shapes + python validators,
# never cross-schema $ref, so validation works offline).

# The typed fail reason for a profile-invariant violation. Profile invariants
# are structural contract failures; the fail reason is ``CONTRACT_INVALID``.
PROFILE_INVARIANT_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Identity anchor.
_ADAPTER_PROFILE_V1: Final[str] = "AdapterSemanticProfile/v1"

# The cd-level wildcard suffix a profile may use in unsupported_features to
# declare behavior for an entire content dictionary at once (e.g. 'calculus1.*').
_CD_WILDCARD_SUFFIX: Final[str] = ".*"


class ProfileInvariantError(ContractError):
    """Raised when an AdapterSemanticProfile violates a contract invariant.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and the name of
    the violated ``invariant`` for diagnostics.

    Attributes
    ----------
    invariant:
        The name of the violated invariant (e.g.
        ``supported_op_outside_allowlist``).
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: str = "",
        fail_reason: str = PROFILE_INVARIANT_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.invariant: str = invariant


def _validate_supported_cds(supported_cds: Any) -> list[str]:
    """Validate ``supported_cds`` is a subset of the MathIR allowlist.

    Returns the validated list (a copy). Raises
    :class:`ProfileInvariantError` (invariant
    ``supported_op_outside_allowlist``) if any entry is outside the allowlist.
    """
    if not isinstance(supported_cds, list):
        msg = "AdapterSemanticProfile 'supported_cds' must be an array"
        raise ContractError(msg)
    out: list[str] = []
    for op in supported_cds:
        if not isinstance(op, str) or op not in MATH_IR_ALLOWLIST:
            msg = (
                f"AdapterSemanticProfile 'supported_cds' entry {op!r} is not a "
                f"member of MATH_IR_ALLOWLIST; a profile may only claim support "
                f"for operators the IR admits (the allowlist is closed)"
            )
            raise ProfileInvariantError(msg, invariant="supported_op_outside_allowlist")
        out.append(op)
    return out


def _validate_unsupported_features(
    unsupported_features: Any, supported: list[str]
) -> list[dict[str, Any]]:
    """Validate ``unsupported_features``: shape + no overlap with supported.

    Each entry must be an object with a ``feature`` and a ``behavior`` (and an
    optional ``note``); the ``behavior`` must be one of the three declared
    values. A feature that exactly names an operator in ``supported`` is a
    contradiction (an operator cannot be both supported and unsupported) and
    raises :class:`ProfileInvariantError` (invariant
    ``feature_both_supported_and_unsupported``).

    Returns the validated list (a copy of the dicts).
    """
    if not isinstance(unsupported_features, list):
        msg = "AdapterSemanticProfile 'unsupported_features' must be an array"
        raise ContractError(msg)
    allowed_behaviors = frozenset({"reject", "approximate", "drop"})
    supported_set = frozenset(supported)
    out: list[dict[str, Any]] = []
    for entry in unsupported_features:
        if not isinstance(entry, dict):
            msg = (
                "AdapterSemanticProfile 'unsupported_features' entries must be "
                f"objects, got {type(entry).__name__}"
            )
            raise ContractError(msg)
        feature = entry.get("feature")
        behavior = entry.get("behavior")
        if not isinstance(feature, str) or not feature:
            msg = (
                "AdapterSemanticProfile 'unsupported_features' entry is missing "
                "a non-empty 'feature' string"
            )
            raise ContractError(msg)
        if behavior not in allowed_behaviors:
            msg = (
                f"AdapterSemanticProfile unsupported feature {feature!r} has "
                f"behavior {behavior!r}; must be one of "
                f"{sorted(allowed_behaviors)}"
            )
            raise ContractError(msg)
        # A bare op (not a cd wildcard) that is also in supported is a
        # contradiction. A cd wildcard ('calculus1.*') overlaps by design and
        # is allowed even if some calculus1 op is supported (the wildcard
        # covers the rest of the cd); only the exact-op contradiction is an
        # error.
        if not feature.endswith(_CD_WILDCARD_SUFFIX) and feature in supported_set:
            msg = (
                f"AdapterSemanticProfile feature {feature!r} is declared "
                "unsupported but is also in 'supported_cds'; an operator is "
                "either supported or unsupported, not both"
            )
            raise ProfileInvariantError(msg, invariant="feature_both_supported_and_unsupported")
        out.append(dict(entry))
    return out


def validate_profile(profile: Any) -> dict[str, Any]:
    """Validate an AdapterSemanticProfile/v1 document (wire dict) and return it.

    Enforces the contract invariants in Python (defense in depth; the schema
    enforces structure). This does NOT re-run the JSON Schema validation —
    callers that need schema validation should call
    :func:`srl.contracts.schema.validate` with ``"AdapterSemanticProfile"``
    first.

    The two invariants checked here are:

    - every ``supported_cds`` entry is a member of
      :data:`~srl.semantic.ir.MATH_IR_ALLOWLIST` (the allowlist is closed;
      a profile cannot claim support for an operator the IR does not admit);
    - no ``unsupported_features`` entry names an exact operator also present
      in ``supported_cds`` (an operator is either supported or unsupported).

    Raises
    ------
    ProfileInvariantError
        If a ``supported_cds`` entry is outside the allowlist, or an
        ``unsupported_features`` entry contradicts a ``supported_cds`` entry.
    ContractError
        If the profile is not an object, has the wrong schema version, or a
        field the invariants depend on is malformed.
    """
    if not isinstance(profile, dict):
        msg = f"AdapterSemanticProfile must be an object, got {type(profile).__name__}"
        raise ContractError(msg)
    if profile.get("schema_version") != _ADAPTER_PROFILE_V1:
        msg = (
            "AdapterSemanticProfile schema_version must be "
            f"{_ADAPTER_PROFILE_V1!r}, got {profile.get('schema_version')!r}"
        )
        raise ContractError(msg)

    supported = _validate_supported_cds(profile.get("supported_cds", []))
    _validate_unsupported_features(profile.get("unsupported_features", []), supported)
    # Defense in depth: validate the inline pack_ref against the full
    # ArtifactRef/v1 contract (the schema carries only the structural shape).
    _validate_pack_ref(profile.get("pack_ref"))
    return profile


def _validate_pack_ref(pack_ref: Any) -> None:
    """Validate the inline ``pack_ref`` as an ArtifactRef/v1 (defense in depth).

    The schema carries the structural shape of the pack_ref; this enforces the
    full ArtifactRef field contract (media-type shape, digest policy, non-negative
    integer byte count, portable path) by delegating to
    :func:`srl.contracts.artifact_refs.validate_artifact_ref`.
    """
    if not isinstance(pack_ref, dict):
        msg = "AdapterSemanticProfile 'pack_ref' must be an object (ArtifactRef/v1)"
        raise ContractError(msg)
    try:
        validate_artifact_ref(pack_ref)
    except ArtifactRefError as exc:
        msg = f"AdapterSemanticProfile 'pack_ref' is not a valid ArtifactRef/v1: {exc}"
        raise ContractError(msg) from exc


def profile_id(profile: dict[str, Any]) -> str:
    """Compute the ``profile_id`` for a profile: sha256 over its canonical bytes.

    The id is computed over the canonical encoding of the profile *without* the
    ``profile_id`` field (the field is stripped here, since the content-addressing
    helper only guards a field literally named ``object_id``). This makes the
    id idempotent: calling ``profile_id`` on a profile with or without its id
    field yields the same value, and a projection binding ``adapter_profile_ref``
    always records the profile's true identity. The profile is validated first
    (defense in depth).
    """
    validate_profile(profile)
    doc = {k: v for k, v in profile.items() if k != "profile_id"}
    return object_id(doc)


def build_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate a profile and inject its computed ``profile_id``.

    Validates the profile (so an out-of-allowlist ``supported_cds`` raises at
    build time), then returns a new dict with ``profile_id`` set to the
    content-addressed id. The input must NOT already carry a ``profile_id``
    (a self-hash is rejected).
    """
    validate_profile(profile)
    doc = dict(profile)
    doc["profile_id"] = profile_id(profile)
    return doc


__all__ = [
    "PROFILE_INVARIANT_FAIL_REASON",
    "ProfileInvariantError",
    "build_profile",
    "profile_id",
    "validate_profile",
]
