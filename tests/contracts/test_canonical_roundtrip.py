"""Property + unit tests for the canonical JSON contract (srl.contracts.canonical).

These tests pin the four invariants of the WP-B10 canonical form:

1. **Round-trip byte stability**: ``dumps(loads(dumps(x))) == dumps(x)`` for
   every JSON-able dict with string keys. Decoding canonical output and
   re-encoding yields identical bytes.
2. **No non-finite floats**: ``allow_nan=False`` means ``NaN``/``Infinity`` are
   never emitted by ``dumps`` and never accepted by ``loads``.
3. **Key-order independence**: two dicts with the same content but different
   insertion order encode to identical bytes.
4. **UTF-8 passthrough**: non-ASCII characters survive as UTF-8 bytes, not
   ``\\uXXXX`` escapes.

Hypothesis generates arbitrary JSON-able structures; the strategies restrict
floats to finite values so the generator itself does not produce inputs the
contract must reject (those are covered by dedicated negative tests).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from srl.contracts.canonical import (
    DECIMAL_STRING_PATTERN,
    CanonicalJSONError,
    DecimalPolicyError,
    decimal_to_str,
    dumps,
    loads,
    validate,
)

# JSON scalars. Floats without NaN/Inf so the generator stays within the
# contract's accepted set (non-finite floats are covered by negative tests).
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),  # safe JSON integer range
    st.floats(
        allow_nan=False,
        allow_infinity=False,
        min_value=-1e6,
        max_value=1e6,
    ),
    st.text(max_size=10),
)

# Recursive JSON value strategy. ``max_leaves`` bounds size for speed.
_json_values = st.recursive(
    _json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=5), children, max_size=5),
    ),
    max_leaves=10,
)


def _resort_dict_keys(value: Any) -> Any:
    """Return a copy of ``value`` with dict keys sorted recursively."""
    if isinstance(value, Mapping):
        return {k: _resort_dict_keys(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_resort_dict_keys(v) for v in value]
    return value


@given(_json_values)
@settings(max_examples=200)
def test_dumps_round_trips_byte_stable(value: Any) -> None:
    """dumps -> loads -> dumps yields identical bytes (byte stability)."""
    first = dumps(value)
    decoded = loads(first)
    second = dumps(decoded)
    assert first == second


@given(_json_values)
@settings(max_examples=200)
def test_dumps_decodes_to_input(value: Any) -> None:
    """Decoding canonical output reproduces the input (key-sorted)."""
    encoded = dumps(value)
    decoded = loads(encoded)
    assert decoded == _resort_dict_keys(value)


@given(st.dictionaries(st.text(min_size=1, max_size=5), _json_scalars, max_size=8))
@settings(max_examples=200)
def test_dumps_is_key_order_independent(value: dict[str, Any]) -> None:
    """Two dicts with the same content but different order encode alike."""
    reordered = {k: value[k] for k in reversed(list(value))}
    assert dumps(value) == dumps(reordered)


@given(_json_values)
@settings(max_examples=200)
def test_dumps_ends_with_single_newline(value: Any) -> None:
    """Canonical output ends with exactly one trailing newline."""
    blob = dumps(value)
    assert blob.endswith(b"\n")
    assert blob.count(b"\n") == 1


@given(_json_values)
@settings(max_examples=200)
def test_dumps_output_is_loadable_by_strict_parser(value: Any) -> None:
    """allow_nan=False: canonical output is always accepted by the strict loads.

    This is the precise guarantee of ``allow_nan=False``: the bytes ``dumps``
    emits never contain a non-finite float token, so re-parsing them with the
    strict parser (which rejects NaN/Infinity via ``parse_constant``) always
    succeeds. The string ``"NaN"`` is valid JSON and may legitimately appear as
    a string value; what must never appear is the bare ``NaN`` number token.
    """
    blob = dumps(value)
    # loads with the strict parse_constant hook must accept canonical output.
    assert loads(blob) == _resort_dict_keys(value)


def test_dumps_returns_bytes_not_str() -> None:
    """dumps returns bytes (the identity hash and byte count are over bytes)."""
    assert isinstance(dumps({"a": 1}), bytes)


def test_dumps_compact_separators() -> None:
    """No insignificant whitespace is emitted."""
    blob = dumps({"a": 1, "b": [1, 2]})
    assert b", " not in blob
    assert b": " not in blob


def test_dumps_unicode_passthrough() -> None:
    """Non-ASCII survives as UTF-8 bytes, not \\uXXXX escapes."""
    blob = dumps({"name": "café"})
    # 'é' is U+00E9 -> UTF-8 0xC3 0xA9; ensure_ascii would emit "\u00e9".
    assert "café".encode() in blob
    assert b"\\u" not in blob


def test_dumps_rejects_nan() -> None:
    """NaN is rejected at encode time (allow_nan=False)."""
    with pytest.raises(CanonicalJSONError):
        dumps({"value": float("nan")})


def test_dumps_rejects_infinity() -> None:
    """Infinity is rejected at encode time."""
    with pytest.raises(CanonicalJSONError):
        dumps({"value": float("inf")})


def test_dumps_rejects_negative_infinity() -> None:
    """-Infinity is rejected at encode time."""
    with pytest.raises(CanonicalJSONError):
        dumps({"value": float("-inf")})


def test_dumps_rejects_non_serializable() -> None:
    """A non-JSON value raises CanonicalJSONError."""
    with pytest.raises(CanonicalJSONError):
        dumps(object())  # type: ignore[arg-type]


def test_loads_rejects_nan_literal() -> None:
    """The NaN literal is rejected by loads (parse_constant hook)."""
    with pytest.raises(CanonicalJSONError):
        loads(b'{"value":NaN}')


def test_loads_rejects_infinity_literal() -> None:
    """The Infinity literal is rejected by loads."""
    with pytest.raises(CanonicalJSONError):
        loads(b'{"value":Infinity}')


def test_loads_accepts_bytes_and_str() -> None:
    """loads accepts both bytes (UTF-8) and str input."""
    blob = dumps({"a": 1})
    assert loads(blob) == loads(blob.decode("utf-8")) == {"a": 1}


def test_loads_rejects_invalid_utf8() -> None:
    """Invalid UTF-8 bytes are rejected."""
    with pytest.raises(CanonicalJSONError):
        loads(b'{"a":"\xff"}')


def test_validate_round_trips_and_returns_bytes() -> None:
    """validate returns the canonical bytes for a round-trippable value."""
    blob = validate({"b": 2, "a": 1})
    assert blob == dumps({"a": 1, "b": 2})


def test_validate_rejects_nan() -> None:
    """validate rejects a value that does not round-trip (NaN)."""
    with pytest.raises(CanonicalJSONError):
        validate({"value": float("nan")})


# --- Decimal policy helpers -------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        Decimal("3.14159"),
        Decimal("0"),
        Decimal("-0.000123"),
        Decimal("100"),
        Decimal("1.5E0"),  # exponent folds to "1.5"
        Decimal("1E3"),  # exponent folds to "1000"
    ],
)
def test_decimal_to_str_renders_policy_string(value: Decimal) -> None:
    """decimal_to_str renders a Decimal to the policy regex."""
    rendered = decimal_to_str(value)
    assert re.fullmatch(DECIMAL_STRING_PATTERN, rendered)


def test_decimal_to_str_int_passthrough() -> None:
    """An int passes through as its decimal form."""
    assert decimal_to_str(42) == "42"
    assert decimal_to_str(0) == "0"


def test_decimal_to_str_string_passthrough() -> None:
    """A valid policy string passes through unchanged."""
    assert decimal_to_str("3.14") == "3.14"


def test_decimal_to_str_rejects_bool() -> None:
    """A bool is not a number and is rejected."""
    with pytest.raises(DecimalPolicyError):
        decimal_to_str(True)  # type: ignore[arg-type]


def test_decimal_to_str_rejects_bad_string() -> None:
    """A string with an exponent is rejected."""
    with pytest.raises(DecimalPolicyError):
        decimal_to_str("1.5e2")


def test_decimal_to_str_rejects_nan_decimal() -> None:
    """A non-finite Decimal (NaN) is rejected."""
    with pytest.raises(DecimalPolicyError):
        decimal_to_str(Decimal("NaN"))


def test_decimal_to_str_rejects_unsupported_type() -> None:
    """An unsupported type (float) is rejected; callers must pre-render."""
    with pytest.raises(DecimalPolicyError):
        decimal_to_str(3.14)  # type: ignore[arg-type]


def test_canonical_roundtrip_preserves_decimal_string() -> None:
    """A decimal string survives a dumps/loads round trip as a string."""
    payload = {"measurement": "3.14159"}
    assert loads(dumps(payload)) == payload
