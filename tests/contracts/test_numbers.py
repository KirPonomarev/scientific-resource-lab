"""Unit tests for strict numeric validation (srl.contracts.numbers).

Pins the three numeric contracts:

1. NaN / Infinity are rejected (never admitted as finite JSON numbers).
2. bool-as-int is rejected (a flag is not a quantity; ``True`` is not ``1``).
3. Decimal strings match the policy regex (no exponent), and integer byte
   counts are non-negative ints.
"""

from __future__ import annotations

import pytest

from srl.contracts.numbers import (
    NUMERIC_FAIL_REASON,
    NumericContractError,
    is_bool,
    reject_non_finite,
    validate_decimal_string,
    validate_integer,
    validate_integer_byte_count,
    validate_json_number,
)


def test_is_bool_distinguishes_bool_from_int() -> None:
    """is_bool is True for bool and False for int (even 0/1)."""
    assert is_bool(True)
    assert is_bool(False)
    assert not is_bool(0)
    assert not is_bool(1)
    assert not is_bool(1.0)
    assert not is_bool("true")


def test_reject_non_finite_rejects_nan() -> None:
    """NaN raises."""
    with pytest.raises(NumericContractError) as exc_info:
        reject_non_finite(float("nan"), field="x")
    assert exc_info.value.fail_reason == NUMERIC_FAIL_REASON


def test_reject_non_finite_rejects_infinity() -> None:
    """Infinity raises."""
    with pytest.raises(NumericContractError):
        reject_non_finite(float("inf"), field="x")


def test_reject_non_finite_rejects_negative_infinity() -> None:
    """-Infinity raises."""
    with pytest.raises(NumericContractError):
        reject_non_finite(float("-inf"), field="x")


def test_reject_non_finite_accepts_finite_float() -> None:
    """A finite float is accepted (no raise)."""
    reject_non_finite(3.14, field="x")  # should not raise
    reject_non_finite(0.0, field="x")


def test_reject_non_finite_ignores_non_floats() -> None:
    """Non-float values are accepted (the check is only about floats)."""
    reject_non_finite(42, field="x")
    reject_non_finite("3.14", field="x")
    reject_non_finite(None, field="x")


def test_validate_integer_byte_count_accepts_non_negative_int() -> None:
    """A non-negative int is accepted and returned."""
    assert validate_integer_byte_count(0, field="size") == 0
    assert validate_integer_byte_count(4096, field="size") == 4096


def test_validate_integer_byte_count_rejects_negative() -> None:
    """A negative int is rejected."""
    with pytest.raises(NumericContractError):
        validate_integer_byte_count(-1, field="size")


def test_validate_integer_byte_count_rejects_bool() -> None:
    """A bool is rejected (a flag is not a size)."""
    with pytest.raises(NumericContractError) as exc_info:
        validate_integer_byte_count(True, field="size")
    assert exc_info.value.field == "size"


def test_validate_integer_byte_count_rejects_float() -> None:
    """An integral float is rejected (5.0 is not 5 in JSON)."""
    with pytest.raises(NumericContractError):
        validate_integer_byte_count(5.0, field="size")


def test_validate_integer_byte_count_rejects_string() -> None:
    """A string is rejected."""
    with pytest.raises(NumericContractError):
        validate_integer_byte_count("5", field="size")  # type: ignore[arg-type]


def test_validate_integer_accepts_signed() -> None:
    """validate_integer accepts any int (including negative)."""
    assert validate_integer(-5, field="delta") == -5
    assert validate_integer(0, field="delta") == 0


def test_validate_integer_rejects_bool() -> None:
    """validate_integer rejects bool."""
    with pytest.raises(NumericContractError):
        validate_integer(False, field="delta")


@pytest.mark.parametrize(
    "value",
    ["0", "3.14159", "-0.000123", "100", "42", "-1", "9999999999"],
)
def test_validate_decimal_string_accepts_policy_strings(value: str) -> None:
    """Valid policy strings are accepted."""
    assert validate_decimal_string(value, field="m") == value


@pytest.mark.parametrize(
    "value",
    [
        "1.5e2",  # exponent
        "1E3",  # exponent
        "3.14.15",  # two dots
        "",  # empty
        "  3.14",  # leading whitespace
        "3.14  ",  # trailing whitespace
        "+5",  # leading plus
        "abc",  # non-numeric
        "0x10",  # hex
        "1_000",  # underscore
    ],
)
def test_validate_decimal_string_rejects_non_policy_strings(value: str) -> None:
    """Strings outside the policy regex are rejected."""
    with pytest.raises(NumericContractError):
        validate_decimal_string(value, field="m")


def test_validate_decimal_string_rejects_non_string() -> None:
    """A non-string is rejected."""
    with pytest.raises(NumericContractError):
        validate_decimal_string(3.14, field="m")  # type: ignore[arg-type]


def test_validate_json_number_accepts_int_and_float() -> None:
    """validate_json_number accepts finite int and float (not bool)."""
    assert validate_json_number(42, field="r") == 42
    assert validate_json_number(3.14, field="r") == 3.14


def test_validate_json_number_rejects_bool() -> None:
    """validate_json_number rejects bool."""
    with pytest.raises(NumericContractError):
        validate_json_number(True, field="r")


def test_validate_json_number_rejects_nan() -> None:
    """validate_json_number rejects NaN."""
    with pytest.raises(NumericContractError):
        validate_json_number(float("nan"), field="r")


def test_validate_json_number_rejects_non_number() -> None:
    """validate_json_number rejects a non-number."""
    with pytest.raises(NumericContractError):
        validate_json_number("3", field="r")  # type: ignore[arg-type]
