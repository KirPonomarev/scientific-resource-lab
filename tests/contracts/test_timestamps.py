"""Unit tests for the RFC 3339 UTC timestamp policy (srl.contracts.timestamps).

Pins:

1. ``validate`` accepts only the canonical ``YYYY-MM-DDTHH:MM:SSZ`` form.
2. ``normalize`` maps equivalent forms (lowercase ``z``, ``+00:00``) to ``Z``
   and rejects fractional seconds and non-UTC offsets.
3. Invalid calendar dates (``2026-02-30``) are rejected.
"""

from __future__ import annotations

import pytest

from srl.contracts.timestamps import (
    TIMESTAMP_FAIL_REASON,
    TimestampError,
    normalize,
    validate,
)


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-28T01:02:03Z",
        "2026-01-01T00:00:00Z",
        "2024-02-29T23:59:59Z",  # leap day
        "1999-12-31T23:59:59Z",
    ],
)
def test_validate_accepts_canonical(value: str) -> None:
    """Canonical RFC 3339 UTC timestamps are accepted."""
    assert validate(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-28T01:02:03.456Z",  # fractional seconds
        "2026-07-28T01:02:03+02:00",  # non-UTC offset
        "2026-07-28T01:02:03",  # missing Z
        "2026-07-28 01:02:03Z",  # space instead of T
        "2026-07-28T01:02Z",  # missing seconds
        "2026-07-28T25:02:03Z",  # bad hour
        "2026-13-28T01:02:03Z",  # bad month
        "2026-07-32T01:02:03Z",  # bad day
        "2026-07-28T01:02:03z",  # lowercase z (not canonical for validate)
        "2026-07-28T01:02:03+00:00",  # explicit offset (not canonical for validate)
    ],
)
def test_validate_rejects_non_canonical(value: str) -> None:
    """Non-canonical forms are rejected by validate."""
    with pytest.raises(TimestampError):
        validate(value)


def test_validate_rejects_invalid_calendar_date() -> None:
    """2026-02-30 is rejected (not a real date)."""
    with pytest.raises(TimestampError):
        validate("2026-02-30T00:00:00Z")


def test_validate_rejects_february_30_in_leap_year() -> None:
    """Feb 30 is rejected even in a leap year (Feb has 29 days max)."""
    with pytest.raises(TimestampError):
        validate("2024-02-30T00:00:00Z")


def test_validate_accepts_leap_day() -> None:
    """Feb 29 is accepted in a leap year (2024)."""
    assert validate("2024-02-29T12:00:00Z") == "2024-02-29T12:00:00Z"


def test_validate_rejects_leap_day_in_non_leap_year() -> None:
    """Feb 29 is rejected in a non-leap year (2023)."""
    with pytest.raises(TimestampError) as exc_info:
        validate("2023-02-29T12:00:00Z")
    assert exc_info.value.fail_reason == TIMESTAMP_FAIL_REASON


def test_validate_rejects_non_string() -> None:
    """A non-string is rejected."""
    with pytest.raises(TimestampError):
        validate(123)  # type: ignore[arg-type]


def test_normalize_maps_lowercase_z_to_uppercase() -> None:
    """A lowercase 'z' suffix normalizes to 'Z'."""
    assert normalize("2026-07-28T01:02:03z") == "2026-07-28T01:02:03Z"


def test_normalize_maps_explicit_offset_to_z() -> None:
    """A +00:00 offset normalizes to 'Z'."""
    assert normalize("2026-07-28T01:02:03+00:00") == "2026-07-28T01:02:03Z"


def test_normalize_passes_canonical_through() -> None:
    """The canonical form passes through normalize unchanged."""
    assert normalize("2026-07-28T01:02:03Z") == "2026-07-28T01:02:03Z"


def test_normalize_rejects_fractional_seconds() -> None:
    """Fractional seconds are rejected (not truncated)."""
    with pytest.raises(TimestampError) as exc_info:
        normalize("2026-07-28T01:02:03.456Z")
    assert "fractional" in str(exc_info.value).lower()


def test_normalize_rejects_non_utc_offset() -> None:
    """A non-UTC offset is rejected."""
    with pytest.raises(TimestampError) as exc_info:
        normalize("2026-07-28T01:02:03+02:00")
    assert "offset" in str(exc_info.value).lower()
