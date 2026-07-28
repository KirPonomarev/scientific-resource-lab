"""Strict numeric validation for SRL contract fields.

SRL scientific artifacts carry numeric values of three kinds:

1. **Integer byte counts** — sizes, offsets, counts. These must be real
   integers ``>= 0`` and, critically, must not be a Python ``bool`` (``bool``
   subclasses ``int``; a stray ``True`` must not be accepted as ``1``).
2. **Decimal strings** — precision-sensitive measurements and constants,
   rendered to ``^-?[0-9]+(\\.[0-9]+)?$`` and never carried as a float.
3. **Plain JSON numbers** — counts and small integers that may legitimately be
   floats but must never be ``NaN`` / ``Infinity``.

This module centralizes the validation for all three so the scientific IR
schemas (and the runtime validators in :mod:`srl.contracts.artifact_refs`) can
call one typed helper per kind.

Why reject ``bool`` explicitly
-----------------------------
JSON distinguishes ``true``/``false`` from numbers. Python conflates them:
``isinstance(True, int)`` is ``True``. A naive ``isinstance(x, int)`` check
silently admits ``True`` where an integer byte count is expected, which would
corrupt identity hashes (the canonical encoding of ``True`` differs from ``1``)
and mislabel a flag as a quantity. Every numeric checker here rejects ``bool``
first.
"""

from __future__ import annotations

import math
import re
from typing import Any, Final

from srl.contracts.canonical import DECIMAL_STRING_PATTERN
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# The typed fail reason emitted by numeric violations. Mirrors the
# ``CONTRACT_INVALID`` entry in ``automation/fail-reasons.json``.
NUMERIC_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Pre-compiled decimal-string policy pattern. Reused from canonical.py so the
# policy has exactly one definition.
_DECIMAL_STRING_RE: Final[re.Pattern[str]] = re.compile(DECIMAL_STRING_PATTERN)


class NumericContractError(ContractError):
    """Raised when a numeric value violates the strict numeric contract.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and the offending
    ``field`` name for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        field: str = "",
        fail_reason: str = NUMERIC_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.field: str = field


def is_bool(value: Any) -> bool:
    """Return True iff ``value`` is a Python ``bool`` (and not a plain int).

    Extracted as a named helper so the "is this a bool?" predicate has one
    home and reads as English at the call site.
    """
    # bool check first: isinstance(True, int) is True in Python, so we must
    # distinguish them explicitly everywhere a number is expected.
    return isinstance(value, bool)


def reject_non_finite(value: Any, *, field: str = "") -> None:
    """Raise if ``value`` is a non-finite float (``NaN`` / ``Infinity``).

    Standard JSON has no representation for non-finite numbers. The canonical
    encoder (:func:`srl.contracts.canonical.dumps`) refuses them at encode
    time via ``allow_nan=False``; this helper provides the same refusal at
    validate time so a non-finite value never reaches the encoder.

    Parameters
    ----------
    value:
        The value to check. Non-float values are accepted (the contract is
        only about floats here).
    field:
        Field name for diagnostics.

    Raises
    ------
    NumericContractError
        If ``value`` is a float and is not finite.
    """
    if isinstance(value, float) and not math.isfinite(value):
        tag = "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
        msg = f"numeric field {field!r} must be finite, got {tag}"
        raise NumericContractError(msg, field=field)


def validate_integer_byte_count(value: Any, *, field: str = "") -> int:
    """Validate ``value`` as a non-negative integer byte count.

    A byte count is a real integer ``>= 0``. ``bool`` is rejected (a flag is
    not a size). Floats are rejected even when integral (``5.0`` is not ``5``
    in JSON, and identity hashes must not depend on the float/int distinction).

    Parameters
    ----------
    value:
        Candidate byte count.
    field:
        Field name for diagnostics.

    Returns
    -------
    int
        The validated non-negative integer.

    Raises
    ------
    NumericContractError
        If ``value`` is a bool, a float, a non-int, or a negative int.
    """
    if is_bool(value):
        msg = f"byte-count field {field!r} must be an int, got bool"
        raise NumericContractError(msg, field=field)
    if not isinstance(value, int):
        msg = f"byte-count field {field!r} must be an int, got {type(value).__name__}"
        raise NumericContractError(msg, field=field)
    if value < 0:
        msg = f"byte-count field {field!r} must be >= 0, got {value}"
        raise NumericContractError(msg, field=field)
    return value


def validate_integer(value: Any, *, field: str = "") -> int:
    """Validate ``value`` as a real integer (rejecting bool-as-int).

    Like :func:`validate_integer_byte_count` but permits negative values.
    Used for signed integer fields (offsets, deltas) that are not sizes.

    Raises
    ------
    NumericContractError
        If ``value`` is a bool, a float, or a non-int.
    """
    if is_bool(value):
        msg = f"integer field {field!r} must be an int, got bool"
        raise NumericContractError(msg, field=field)
    if not isinstance(value, int):
        msg = f"integer field {field!r} must be an int, got {type(value).__name__}"
        raise NumericContractError(msg, field=field)
    return value


def validate_decimal_string(value: Any, *, field: str = "") -> str:
    """Validate ``value`` as a decimal-string policy value.

    Precision-sensitive fields are carried as JSON strings matching
    ``^-?[0-9]+(\\.[0-9]+)?$`` (optional sign, integer digits, optional
    fractional digits, no exponent). This helper enforces the shape and
    rejects exponents, leading/trailing whitespace, and a bare sign.

    Parameters
    ----------
    value:
        Candidate decimal string.
    field:
        Field name for diagnostics.

    Returns
    -------
    str
        The validated decimal string.

    Raises
    ------
    NumericContractError
        If ``value`` is not a string or does not match the policy pattern.
    """
    if not isinstance(value, str):
        msg = (
            f"decimal-string field {field!r} must be a string matching "
            f"{DECIMAL_STRING_PATTERN!r}, got {type(value).__name__}"
        )
        raise NumericContractError(msg, field=field)
    if not _DECIMAL_STRING_RE.fullmatch(value):
        msg = (
            f"decimal-string field {field!r}={value!r} must match "
            f"{DECIMAL_STRING_PATTERN!r} (no exponent)"
        )
        raise NumericContractError(msg, field=field)
    return value


def validate_json_number(value: Any, *, field: str = "") -> int | float:
    """Validate ``value`` as a finite JSON number (int or float, not bool).

    A general numeric field that may legitimately be a float (e.g. a ratio)
    but must never be ``NaN``/``Infinity`` or a bool. Use this for "any finite
    number"; use :func:`validate_integer_byte_count` for sizes and
    :func:`validate_decimal_string` for precision-sensitive values.

    Raises
    ------
    NumericContractError
        If ``value`` is a bool, a non-number, or a non-finite float.
    """
    if is_bool(value):
        msg = f"numeric field {field!r} must be a number, got bool"
        raise NumericContractError(msg, field=field)
    if isinstance(value, bool | int | float):
        # Narrowed: not bool by the check above; int or float from here.
        reject_non_finite(value, field=field)
        return value
    msg = f"numeric field {field!r} must be a number, got {type(value).__name__}"
    raise NumericContractError(msg, field=field)


__all__ = [
    "NUMERIC_FAIL_REASON",
    "NumericContractError",
    "is_bool",
    "reject_non_finite",
    "validate_decimal_string",
    "validate_integer",
    "validate_integer_byte_count",
    "validate_json_number",
]
