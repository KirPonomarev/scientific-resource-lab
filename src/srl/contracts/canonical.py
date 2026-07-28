"""Canonical JSON encoding for SRL contract artifacts.

All shared SRL contracts (the scientific IR, receipts, transformation records,
catalogs) are JSON-first. A canonical encoding makes two independent agents
produce byte-identical output for equal data, which is the prerequisite for
content-addressed identity (see :mod:`srl.contracts.ids`) and reproducible
comparison.

Canonical form (WP-B10)
-----------------------
The canonical form is intentionally restrictive and stricter than the Phase-A
``srl.canonical`` helper:

- UTF-8 output via ``ensure_ascii=False`` (non-ASCII passes through, then is
  encoded to bytes as UTF-8);
- sorted object keys (deterministic ordering, independent of insertion order);
- compact separators (no insignificant whitespace);
- ``allow_nan=False`` so ``NaN`` / ``Infinity`` are a hard error rather than
  silently emitted as non-standard JSON tokens;
- a single trailing ``\\n`` (the SRL line contract: one record per line);
- the return type is :class:`bytes`, because the identity hash and the byte
  count are computed over the serialized bytes, not over a locale-dependent
  ``str``.

Decimal policy
--------------
Precision-sensitive values (measurements, constants, monetary-style amounts)
are carried as JSON **strings** matching ``^-?[0-9]+(\\.[0-9]+)?$`` so that
they survive a serialize / parse round trip with no float coercion or
exponent drift. The :func:`decimal_to_str` helper renders a :class:`Decimal`
to that policy string and rejects values that cannot be expressed without an
exponent. See :mod:`srl.contracts.numbers` for the validation counterpart.

Backward compatibility
----------------------
The Phase-A module :mod:`srl.canonical` (ASCII-only, ``str`` return) remains
the wire format for the autonomy receipts emitted in Phase A. This module is
the canonical form for the scientific contracts layer and for new receipts.
The legacy helpers re-export from here unchanged for callers that still use
them.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Final

from srl.contracts.errors import ContractError

# Compact separators: no insignificant whitespace. Extracted as constants so the
# canonical form is declared in one place and free of magic-value lint.
_CANONICAL_SEPARATORS: Final[tuple[str, str]] = (",", ":")
# Non-ASCII passes through; the str is then encoded to UTF-8 bytes by dumps().
_CANONICAL_ENSURE_ASCII: Final[bool] = False
_CANONICAL_SORT_KEYS: Final[bool] = True
# NaN / Infinity / -Infinity are rejected at encode time. allow_nan=False makes
# json.dumps raise ValueError on them instead of emitting non-standard tokens.
_CANONICAL_ALLOW_NAN: Final[bool] = False
_TRAILING_NEWLINE: Final[str] = "\n"
# SRL artifacts are UTF-8 on the wire.
_CANONICAL_ENCODING: Final[str] = "utf-8"

# Regex (as a string, for re-use by schema documents and consumers) for the
# decimal-string policy. Kept here next to the rendering helper so the policy
# has one home. The pre-compiled form is private; consumers use the string.
DECIMAL_STRING_PATTERN: Final[str] = r"^-?[0-9]+(\.[0-9]+)?$"
_DECIMAL_STRING_RE: Final[re.Pattern[str]] = re.compile(DECIMAL_STRING_PATTERN)


class CanonicalJSONError(ContractError):
    """Raised when a value cannot be encoded as canonical JSON.

    A :class:`ContractError` (which is a :class:`ValueError`) so callers that
    already handle malformed input via ``except ValueError`` still catch it.
    The ``fail_reason`` is ``CONTRACT_INVALID``.
    """


class DecimalPolicyError(ContractError):
    """Raised when a :class:`Decimal` cannot be rendered to the policy string.

    The policy string is ``^-?[0-9]+(\\.[0-9]+)?$``: optional sign, integer
    digits, optional fractional digits, no exponent. A :class:`Decimal` in
    engineering or scientific notation (a non-zero exponent that cannot be
    folded into the coefficient without losing trailing-zero semantics) is
    rejected so the wire form is unambiguous.
    """


def dumps(obj: Any) -> bytes:
    """Encode ``obj`` as canonical JSON bytes with a trailing newline.

    Parameters
    ----------
    obj:
        Any :mod:`json`-serializable value (dict, list, str, int, float, bool,
        ``None``, and nested combinations). Precision-sensitive values must be
        pre-rendered to decimal strings via :func:`decimal_to_str` (or passed
        through as strings).

    Returns
    -------
    bytes
        Canonical JSON encoded as UTF-8: sorted keys, compact separators,
        non-ASCII passthrough, no ``NaN``/``Infinity``, a single trailing
        ``\\n``.

    Raises
    ------
    CanonicalJSONError
        If ``obj`` is not serializable, or contains ``NaN`` / ``Infinity``,
        or contains a key that is not a string.

    Notes
    -----
    The return type is :class:`bytes` (not :class:`str`) so callers can hash
    it and count bytes without an extra encode step. Sorting is handled by
    :func:`json.dumps` with ``sort_keys=True``.
    """
    try:
        text = json.dumps(
            obj,
            sort_keys=_CANONICAL_SORT_KEYS,
            separators=_CANONICAL_SEPARATORS,
            ensure_ascii=_CANONICAL_ENSURE_ASCII,
            allow_nan=_CANONICAL_ALLOW_NAN,
        )
    except (TypeError, ValueError) as exc:
        msg = "value is not canonical-JSON serializable"
        raise CanonicalJSONError(msg) from exc
    return (text + _TRAILING_NEWLINE).encode(_CANONICAL_ENCODING)


def loads(data: bytes | str) -> Any:
    """Parse canonical JSON with strict numeric rejection.

    Parameters
    ----------
    data:
        Canonical JSON as :class:`bytes` (decoded as UTF-8) or :class:`str`.

    Returns
    -------
    Any
        The parsed JSON value (dict, list, str, int, float, bool, ``None``).

    Raises
    ------
    CanonicalJSONError
        If ``data`` is not valid JSON, is not valid UTF-8 (for bytes), or
        contains ``NaN`` / ``Infinity`` / ``-Infinity`` literals (which the
        standard JSON grammar does not admit).

    Notes
    -----
    ``parse_constant`` turns the non-standard ``NaN``/``Infinity`` tokens into
    an immediate error rather than silently materializing a Python float that
    :func:`dumps` would then refuse. This makes the round trip
    ``loads(dumps(x))`` refuse exactly what ``dumps`` refuses.
    """
    if isinstance(data, bytes):
        try:
            text = data.decode(_CANONICAL_ENCODING)
        except UnicodeDecodeError as exc:
            msg = "canonical JSON bytes are not valid UTF-8"
            raise CanonicalJSONError(msg) from exc
    else:
        text = data
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        msg = f"value is not valid canonical JSON: {exc}"
        raise CanonicalJSONError(msg) from exc


def _reject_constant(name: str) -> Any:
    """Hook for :func:`json.loads` ``parse_constant``: reject NaN/Infinity.

    The JSON grammar admits no constant tokens. Python's decoder accepts
    ``NaN`` / ``Infinity`` / ``-Infinity`` by default for compatibility with
    some JS engines; we treat them as malformed input so canonical JSON never
    round-trips a non-finite float.
    """
    msg = f"canonical JSON must not contain the constant {name!r}"
    raise CanonicalJSONError(msg)


def validate(obj: Any) -> bytes:
    """Round-trip validate ``obj``: encode then decode then re-encode.

    A value is canonical-JSON-valid iff encoding it, decoding the result, and
    re-encoding yields byte-identical bytes. This catches non-serializable
    values, non-finite floats, and (via the re-encode) any value whose decoded
    form would not re-stabilize.

    Parameters
    ----------
    obj:
        Any value to validate.

    Returns
    -------
    bytes
        The canonical bytes for ``obj``.

    Raises
    ------
    CanonicalJSONError
        If ``obj`` fails to canonicalize or round-trip.
    """
    first = dumps(obj)
    decoded = loads(first)
    second = dumps(decoded)
    if first != second:
        msg = "value does not round-trip to identical canonical bytes"
        raise CanonicalJSONError(msg)
    return first


def decimal_to_str(value: Decimal | int | str) -> str:
    """Render a precision-sensitive value to the decimal-string policy.

    The policy string matches ``^-?[0-9]+(\\.[0-9]+)?$``: an optional sign,
    one or more integer digits, an optional fractional part of one or more
    digits, and no exponent. :class:`int` and digit-strings pass through after
    a shape check. A :class:`Decimal` with a non-zero exponent is accepted
    only if it folds cleanly into a coefficient (e.g. ``Decimal("1.5E0")``);
    otherwise it is rejected, because the canonical string form must not carry
    an exponent.

    Parameters
    ----------
    value:
        A :class:`Decimal`, :class:`int`, or ``str`` to render.

    Returns
    -------
    str
        The decimal-string policy form.

    Raises
    ------
    DecimalPolicyError
        If ``value`` cannot be expressed as the policy string (exponent that
        cannot be folded, non-numeric string, etc.).
    """
    if isinstance(value, int) and not isinstance(value, bool):
        # int -> policy string is just its decimal form. bool is excluded: a
        # bool is not a number and must not be silently coerced into "0"/"1".
        return str(value)
    if isinstance(value, str):
        # Validate the shape directly; we do not trust the caller to have
        # normalized the string. Reject anything with an exponent or sign char
        # in the wrong position.
        _check_decimal_string_shape(value)
        return value
    if isinstance(value, Decimal):
        # Normalize the exponent away: format(Decimal) uses engineering
        # notation for large exponents, so we walk through the sign / digits /
        # exponent tuple and rebuild a plain decimal string only when the
        # exponent folds cleanly.
        sign, digits, exponent = value.as_tuple()
        if not isinstance(exponent, int):
            # NaN/sNaN/Infinity carry a non-int exponent (string "F","n","N").
            msg = f"Decimal {value!r} is not finite and cannot be a policy string"
            raise DecimalPolicyError(msg)
        return _decimal_tuple_to_str(sign, digits, exponent)
    msg = (
        f"value of type {type(value).__name__!r} is not a Decimal/int/str; "
        "precision-sensitive fields must be rendered to a decimal string"
    )
    raise DecimalPolicyError(msg)


def _check_decimal_string_shape(value: str) -> None:
    """Raise :class:`DecimalPolicyError` if ``value`` is not a policy string.

    A policy string matches ``^-?[0-9]+(\\.[0-9]+)?$``. This is stricter than
    :class:`Decimal` parsing: it rejects exponents, underscores, leading
    whitespace, and a bare sign with no digits.
    """
    if not _DECIMAL_STRING_RE.fullmatch(value):
        msg = (
            f"string {value!r} is not a decimal policy string "
            f"(must match {DECIMAL_STRING_PATTERN!r})"
        )
        raise DecimalPolicyError(msg)


def _decimal_tuple_to_str(sign: int, digits: tuple[int, ...], exponent: int) -> str:
    """Rebuild a plain decimal string from a :class:`Decimal` tuple.

    The tuple form is ``(sign, digits, exponent)`` where ``digits`` is the
    coefficient's digits and ``exponent`` is the power of ten to multiply by.
    We fold the exponent into the coefficient position to produce a plain
    ``[-]int[.frac]`` string. Exponents that would require leading-zero
    padding beyond a sane bound (or that would require scientific notation)
    are folded literally; the result still matches the policy regex because
    we only ever insert digits and at most one dot.
    """
    coefficient = "".join(str(d) for d in digits) if digits else "0"
    # Position of the decimal point relative to the right end of coefficient.
    # exponent > 0 -> append zeros; exponent < 0 -> insert a dot.
    if exponent >= 0:
        whole = coefficient + ("0" * exponent)
        rendered = whole
    else:
        frac_len = -exponent
        if len(coefficient) > frac_len:
            whole = coefficient[:-frac_len]
            frac = coefficient[-frac_len:]
        else:
            # Pad the integer part with leading zeros (e.g. 1E-3 -> 0.001).
            whole = "0"
            frac = ("0" * (frac_len - len(coefficient))) + coefficient
        rendered = f"{whole}.{frac}" if frac else whole
    if sign:
        rendered = "-" + rendered
    # Final shape guard: the fold above always yields digits and at most one
    # dot, but assert the policy explicitly so a future tuple change cannot
    # silently emit a malformed string.
    _check_decimal_string_shape(rendered)
    return rendered


__all__ = [
    "DECIMAL_STRING_PATTERN",
    "CanonicalJSONError",
    "DecimalPolicyError",
    "decimal_to_str",
    "dumps",
    "loads",
    "validate",
]
