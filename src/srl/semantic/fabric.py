"""Scientific object fabric: minting ScientificObjectEnvelope/v1 objects.

The fabric is the single entry point for producing a content-addressed SRL
scientific object. It wraps a type-specific payload into a
``ScientificObjectEnvelope/v1`` envelope, computes the object's identity
(``object_id``) over the canonical encoding of the object *without* the
``object_id`` field, sets the provenance (``created_utc``, ``parents``) and
the two safety consts (``canonical_writes=0``, ``grants_authority=false``),
and validates the result against the envelope schema.

Why a fabric (not bare dicts)
-----------------------------
The envelope's ``object_id`` is computed over the object *without* the id
itself (a self-hash would make the id unsatisfiable). A caller building the
envelope by hand has to remember to omit the id, hash, then re-insert — an
easy place to introduce a non-deterministic or self-referential id. The
fabric does this in one place, deterministically, so every object the system
produces has a well-formed identity.

Admission, not authorization
----------------------------
Minting an object admits it into the fabric (it is well-formed and
content-addressed). It does NOT mean the object is *true* or that it *grants
authority*: ``grants_authority`` is pinned to ``false`` by the schema, and a
supported claim is still an admission. See ``GOVERNANCE.md``.
"""

from __future__ import annotations

from typing import Any, Final

from srl.contracts.ids import object_id
from srl.contracts.schema import validate as schema_validate
from srl.contracts.timestamps import normalize as normalize_timestamp

# The envelope schema version this fabric produces.
_ENVELOPE_V1: Final[str] = "ScientificObjectEnvelope/v1"
# The schema name to validate the produced envelope against.
_ENVELOPE_SCHEMA: Final[str] = "ScientificObjectEnvelope"

# The object_type values that carry a payload schema. The envelope's
# object_type enum is wider (17 kinds); these twelve have a v1 payload schema
# today (the six WP-B11 object types, the two WP-B12 transformation objects,
# and the four WP-B13 evidence/run-receipt objects). The fabric accepts any
# envelope object_type for forward compatibility, but the documentation
# enumerates these.
SUPPORTED_OBJECT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "claim",
        "math_ir",
        "symbol_table",
        "condition_set",
        "constant_ref",
        "model_interface",
        "adapter_profile",
        "transformation_receipt",
        "evidence_assessment",
        "engine_receipt",
        "validation_receipt",
        "run_receipt",
    }
)


def mint_object(
    object_type: str,
    payload: dict[str, Any],
    parents: list[str] | None = None,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Mint a ScientificObjectEnvelope/v1 object around a type-specific payload.

    Computes the ``object_id`` over the canonical encoding of the envelope
    *without* the id field, sets the provenance and safety consts, and
    validates the result against ``ScientificObjectEnvelope``. The
    ``created_utc`` is normalized to canonical form (accepting ``z`` and
    ``+00:00``) so a caller can pass either.

    Parameters
    ----------
    object_type:
        The envelope ``object_type`` discriminator (selects the payload
        sub-schema). See :data:`SUPPORTED_OBJECT_TYPES`.
    payload:
        The type-specific payload (the wire dict for the object's schema, e.g.
        a ``ScientificClaim/v1`` dict). The fabric does not re-validate the
        payload against its sub-schema here; callers validate the payload
        separately (e.g. via :func:`srl.semantic.claims.validate`).
    parents:
        The ``object_id`` values of the objects this object derives from.
        Defaults to an empty list (a root object).
    created_utc:
        RFC 3339 UTC timestamp. Normalized to canonical form before minting.

    Returns
    -------
    dict[str, Any]
        A validated ``ScientificObjectEnvelope/v1`` dict with a computed
        ``object_id``.

    Raises
    ------
    ContractError
        If the envelope fails schema validation (propagated from
        :func:`srl.contracts.schema.validate`), or if ``created_utc`` is not a
        valid UTC timestamp.
    """
    normalized_utc = normalize_timestamp(created_utc)
    envelope: dict[str, Any] = {
        "schema_version": _ENVELOPE_V1,
        "object_type": object_type,
        "created_utc": normalized_utc,
        "parents": list(parents) if parents is not None else [],
        "payload": payload,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    # Compute identity over the envelope without the object_id field, then
    # insert. object_id rejects a self-referential field; because we have not
    # added object_id yet, this always succeeds.
    envelope["object_id"] = object_id(envelope)
    # Defense in depth: validate the final envelope against the schema.
    schema_validate(envelope, _ENVELOPE_SCHEMA)
    return envelope


__all__ = [
    "SUPPORTED_OBJECT_TYPES",
    "mint_object",
]
