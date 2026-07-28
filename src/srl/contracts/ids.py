"""Content-addressed object identity for SRL scientific artifacts.

Every scientific object the SRL fabric produces is content-addressed: its
identity is the SHA-256 of the canonical encoding of the object *without* its
own identity field. This makes identity a pure function of content — two
independent agents that build the same object compute the same id, with no
coordination.

Self-hash rejection
-------------------
The defining hazard of content-addressing is the **self-hash**: an object that
contains its own id field. A self-referential id is logically inconsistent
(the id depends on a field whose value is the id), so attempting to compute
one is a hard error. :func:`object_id` detects a pre-populated ``object_id``
field and raises :class:`SelfHashError` (typed ``CONTRACT_INVALID``) before
hashing. Callers must leave ``object_id`` absent (or send the object without
it) when computing the id, then set the field on a copy for storage.

Determinism
-----------
Identity is deterministic because the input to the hash is the canonical
encoding (see :mod:`srl.contracts.canonical`): sorted keys, compact
separators, UTF-8, no non-finite floats. The same object encoded on any
machine yields identical bytes and therefore an identical id.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# The field name that carries an object's own identity. Used both to detect a
# pre-populated self-hash and to place the id after computation.
OBJECT_ID_FIELD: Final[str] = "object_id"

# Identity prefix: every object id is "sha256:" + 64 lowercase hex.
OBJECT_ID_PREFIX: Final[str] = "sha256:"

# Pre-compiled shape for a canonical object id: "sha256:" + 64 lowercase hex.
_OBJECT_ID_RE: Final[re.Pattern[str]] = re.compile(r"sha256:[0-9a-f]{64}")

# The typed fail reason emitted by identity violations. Self-hash is a
# structural contract failure, so it shares ``CONTRACT_INVALID`` with the rest
# of the contract family.
IDENTITY_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON


class SelfHashError(ContractError):
    """Raised when computing an id for a self-referential object.

    The object already contains its own ``object_id`` field. Computing the id
    would create a fixed point (the hash depends on the hash), which is
    logically inconsistent. The caller must strip the field before hashing.

    Attributes
    ----------
    existing_id:
        The pre-populated ``object_id`` value found on the object (if any),
        captured for diagnostics.
    """


class IdentityError(ContractError):
    """Raised when a value is not a valid object id string.

    Used by :func:`validate_object_id` for ids that are not
    ``sha256:<64 lowercase hex>``.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = IDENTITY_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


def is_self_referential(obj: Any) -> bool:
    """Return True iff ``obj`` carries its own ``object_id`` field.

    "Self-referential" here means: the top-level dict has an ``object_id`` key
    whose value is itself a non-empty object-id string. An absent field, an
    empty value, or a non-id value is not treated as self-referential (the
    latter is a separate validation concern).
    """
    if not isinstance(obj, dict):
        return False
    existing = obj.get(OBJECT_ID_FIELD)
    if not isinstance(existing, str) or not existing:
        return False
    return True


def object_id(obj: Any) -> str:
    """Compute the content-addressed id for ``obj``.

    The id is ``"sha256:"`` + the SHA-256 hex of the canonical JSON encoding of
    ``obj``. The object must **not** already contain its own ``object_id``
    field; a pre-populated field raises :class:`SelfHashError` so the caller
    fixes the input rather than silently hashing a fixed point.

    Parameters
    ----------
    obj:
        The object to identify. Must be canonical-JSON-serializable and must
        not carry its own ``object_id`` field.

    Returns
    -------
    str
        The object id: ``"sha256:"`` + 64 lowercase hex digits.

    Raises
    ------
    SelfHashError
        If ``obj`` already contains its own ``object_id`` field.
    ContractError
        If ``obj`` cannot be canonicalized (propagated from
        :func:`srl.contracts.canonical.dumps`).
    """
    # Detect a pre-populated object_id inline so mypy narrows the type. The
    # is_self_referential() helper is the public predicate; here we replicate
    # its logic locally to give the type checker the dict narrowing it needs.
    if isinstance(obj, dict) and isinstance(obj.get(OBJECT_ID_FIELD), str) and obj[OBJECT_ID_FIELD]:
        existing = obj[OBJECT_ID_FIELD]
        msg = (
            f"cannot compute object_id: object already carries its own "
            f"{OBJECT_ID_FIELD!r} field ({existing!r}); strip the field before hashing"
        )
        raise SelfHashError(msg)
    blob = dumps(obj)
    digest = hashlib.sha256(blob).hexdigest()
    return OBJECT_ID_PREFIX + digest


def validate_object_id(value: Any) -> str:
    """Validate ``value`` as a canonical object id string.

    Parameters
    ----------
    value:
        Candidate object id.

    Returns
    -------
    str
        The validated id.

    Raises
    ------
    IdentityError
        If ``value`` is not ``"sha256:"`` + 64 lowercase hex.
    """
    if not isinstance(value, str):
        msg = f"object_id must be a string, got {type(value).__name__}"
        raise IdentityError(msg)
    if not _OBJECT_ID_RE.fullmatch(value):
        msg = f"object_id {value!r} must be 'sha256:' + 64 lowercase hex digits"
        raise IdentityError(msg)
    return value


__all__ = [
    "IDENTITY_FAIL_REASON",
    "OBJECT_ID_FIELD",
    "OBJECT_ID_PREFIX",
    "IdentityError",
    "SelfHashError",
    "is_self_referential",
    "object_id",
    "validate_object_id",
]
