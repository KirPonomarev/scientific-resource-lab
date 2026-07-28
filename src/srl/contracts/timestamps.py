"""RFC 3339 UTC timestamp policy for SRL contract artifacts.

Every timestamp in an SRL contract artifact is an RFC 3339 UTC timestamp at
**seconds precision** with the canonical shape::

    YYYY-MM-DDTHH:MM:SSZ

This is the narrowest portable form: it has no fractional seconds, no offset,
and a mandatory trailing ``Z``. Two design goals drive the narrowness:

1. **Determinism.** A timestamp with a numeric offset (``+02:00``) or
   fractional seconds (``2026-07-28T01:02:03.456Z``) encodes the same instant
   in more than one way, which would break byte-stable identity hashes. The
   canonical form has exactly one representation per instant.
2. **Portability.** Seconds-precision UTC with ``Z`` is the most widely
   understood RFC 3339 profile and round-trips cleanly through every JSON
   toolchain without timezone database assumptions.

Normalization
-------------
:func:`normalize` accepts the narrow canonical form and a small set of
equivalent inputs (lowercase ``z``, an explicit ``+00:00`` offset) and
returns the canonical ``...Z`` form. It does **not** accept fractional
seconds or non-UTC offsets; those are rejected, not silently truncated,
because truncating would lose information the caller meant to record.
"""

from __future__ import annotations

import re
from typing import Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# The typed fail reason emitted by timestamp violations.
TIMESTAMP_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Canonical RFC 3339 UTC pattern: YYYY-MM-DDTHH:MM:SSZ (seconds precision).
# The date/time components are bounded to plausible ranges (month 01-12,
# day 01-31, hour 00-23, minute/second 00-59) so the regex does most of the
# structural work before the calendar check.
_CANONICAL_PATTERN: Final[str] = (
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
_CANONICAL_RE: Final[re.Pattern[str]] = re.compile(_CANONICAL_PATTERN)

# Lenient form accepted by normalize(): same shape but with a trailing
# lowercase 'z' or an explicit +00:00 offset in place of 'Z'. Fractional
# seconds and other offsets are intentionally NOT accepted here.
_NORMALIZE_PATTERN: Final[str] = (
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(Z|z|\+00:00)$"
)
_NORMALIZE_RE: Final[re.Pattern[str]] = re.compile(_NORMALIZE_PATTERN)

# Calendar bounds for the time-of-day and month checks. The regex already
# bounds the digits structurally; these constants drive the semantic range
# check so the comparison reads as English and is free of magic-value lint.
_MAX_HOUR: Final[int] = 23
_MAX_MINUTE_OR_SECOND: Final[int] = 59
_MONTHS_IN_YEAR: Final[int] = 12
_FIRST_MONTH: Final[int] = 1
_FEBRUARY: Final[int] = 2


class TimestampError(ContractError):
    """Raised when a value is not a canonical RFC 3339 UTC timestamp.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and the offending
    ``value`` for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        value: str = "",
        fail_reason: str = TIMESTAMP_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.value: str = value


def validate(value: str) -> str:
    """Validate ``value`` as a canonical RFC 3339 UTC timestamp.

    Parameters
    ----------
    value:
        Candidate timestamp. Must match ``YYYY-MM-DDTHH:MM:SSZ`` exactly
        (seconds precision, trailing ``Z``, no offset, no fractional seconds).

    Returns
    -------
    str
        The validated timestamp (unchanged).

    Raises
    ------
    TimestampError
        If ``value`` is not a string, does not match the canonical shape, or
        is not a real calendar date/time (e.g. month 13, day 32, or
        ``2026-02-30``).
    """
    _require_str(value)
    if not _CANONICAL_RE.fullmatch(value):
        _raise_shape(value)
    _check_calendar(value)
    return value


def normalize(value: str) -> str:
    """Normalize an accepted RFC 3339 UTC timestamp to canonical form.

    Accepts the canonical ``...Z`` form plus the equivalent lowercase ``z``
    and explicit ``+00:00`` offset, and returns the canonical ``...Z`` form.
    Rejects fractional seconds and any non-UTC offset.

    Parameters
    ----------
    value:
        Candidate timestamp.

    Returns
    -------
    str
        The canonical ``YYYY-MM-DDTHH:MM:SSZ`` form.

    Raises
    ------
    TimestampError
        If ``value`` is not accepted (wrong shape, fractional seconds,
        non-UTC offset, or not a real calendar date/time).
    """
    _require_str(value)
    if not _NORMALIZE_RE.fullmatch(value):
        # Distinguish the common rejection reasons for a clearer message.
        if _looks_fractional(value):
            msg = (
                f"timestamp {value!r} has fractional seconds; "
                "canonical timestamps are seconds-precision (YYYY-MM-DDTHH:MM:SSZ)"
            )
            raise TimestampError(msg, value=value)
        if _has_non_utc_offset(value):
            msg = (
                f"timestamp {value!r} has a non-UTC offset; "
                "canonical timestamps are UTC only (trailing 'Z')"
            )
            raise TimestampError(msg, value=value)
        _raise_shape(value)
    _check_calendar(value)
    canonical = value
    # Map the two equivalent non-canonical suffixes to 'Z'.
    if canonical.endswith(("z", "+00:00")):
        canonical = canonical.removesuffix("+00:00").removesuffix("z") + "Z"
    return canonical


def _require_str(value: object) -> None:
    """Raise :class:`TimestampError` if ``value`` is not a string."""
    if not isinstance(value, str):
        msg = f"timestamp must be a string, got {type(value).__name__}"
        raise TimestampError(msg, value="")


def _raise_shape(value: str) -> None:
    """Raise the canonical shape error for ``value``."""
    msg = (
        f"timestamp {value!r} is not canonical RFC 3339 UTC "
        "(expected YYYY-MM-DDTHH:MM:SSZ, seconds precision, trailing 'Z')"
    )
    raise TimestampError(msg, value=value)


def _looks_fractional(value: str) -> bool:
    """Heuristic: True if ``value`` has a fractional-seconds component.

    Used only to produce a clearer error message; the canonical regex already
    rejects the value.
    """
    # A '.' between the time and the zone suffix indicates fractional seconds.
    if "T" not in value:
        return False
    tail = value.split("T", 1)[1]
    return "." in tail


def _has_non_utc_offset(value: str) -> bool:
    """Heuristic: True if ``value`` carries a non-UTC numeric offset.

    Recognizes ``+hh:mm`` / ``-hh:mm`` other than ``+00:00`` (which normalize
    accepts). Used only for error messaging.
    """
    offset_re = re.compile(r"([+-])([01][0-9]|2[0-3]):[0-5][0-9]$")
    match = offset_re.search(value)
    if match is None:
        return False
    return value[match.start() :] not in ("+00:00",)


def _check_calendar(value: str) -> None:
    """Verify the validated timestamp is a real calendar date/time.

    The regex bounds components structurally but cannot reject ``2026-02-30``.
    A lightweight check validates the month/day range against month lengths,
    including the leap-year rule for February.
    """
    # Format is fixed: YYYY-MM-DDTHH:MM:SSZ. Slice by position for speed.
    year = int(value[0:4])
    month = int(value[5:7])
    day = int(value[8:10])
    hour = int(value[11:13])
    minute = int(value[14:16])
    second = int(value[17:19])
    if hour > _MAX_HOUR or minute > _MAX_MINUTE_OR_SECOND or second > _MAX_MINUTE_OR_SECOND:
        msg = f"timestamp {value!r} has an out-of-range time component"
        raise TimestampError(msg, value=value)
    if day > _days_in_month(year, month):
        msg = f"timestamp {value!r} is not a valid calendar date"
        raise TimestampError(msg, value=value)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in ``month`` of ``year`` (leap-aware)."""
    # Standard month lengths; February is patched for leap years below.
    lengths = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if month < _FIRST_MONTH or month > _MONTHS_IN_YEAR:
        return 0
    if month == _FEBRUARY and _is_leap(year):
        return 29
    return lengths[month - _FIRST_MONTH]


def _is_leap(year: int) -> bool:
    """Return True iff ``year`` is a Gregorian leap year."""
    # Divisible by 4, except centuries not divisible by 400.
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


__all__ = ["TIMESTAMP_FAIL_REASON", "TimestampError", "normalize", "validate"]
