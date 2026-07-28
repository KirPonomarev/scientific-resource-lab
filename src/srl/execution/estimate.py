"""Resource estimate for a single scientific execution step.

A :class:`ResourceEstimate` is the pre-run statement of what a bounded step is
expected to consume: wall-clock time, resident memory, scratch (working-set)
bytes, and CPU cores. It is the input to admission (see
:mod:`srl.execution.policy`): the runner compares an estimate against the
resource policy and admits the step to the default envelope, admits it to the
exception envelope, or parks it for a remote executor.

The estimate is a pure value object. It carries no authority (it never grants
anything) and performs no I/O. Its canonical serialization and SHA-256 digest
make two independent producers of the same estimate produce the same bytes and
therefore the same digest, so an admission decision is reproducible from the
estimate alone.

Design notes
------------
This module is intentionally standard library only, mirroring the autonomy
primitives in :mod:`srl.autonomy`. The canonical JSON helper is kept local so
the module has no intra-package dependency that would couple it to the
scientific contracts layer (and its ``jsonschema`` dependency). The byte-count
fields are real integers ``>= 0``; ``bool`` is rejected (a flag is not a
quantity) so a stray ``True`` can never be admitted as ``1``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final

# Canonical JSON separators and newline contract, mirroring srl.contracts.canonical
# but kept local so this module is dependency-free and vendored as a unit. The
# values match the canonical form exactly: sorted keys, compact separators,
# ensure_ascii=False (UTF-8 passthrough), no NaN/Infinity.
_SEP: Final[tuple[str, str]] = (",", ":")
_NEWLINE: Final[str] = "\n"
_ENCODING: Final[str] = "utf-8"

# The prefix and length for a SHA-256 digest string, matching the object-id
# convention used across the SRL fabric (see srl.contracts.ids).
_DIGEST_PREFIX: Final[str] = "sha256:"

# The typed fail reason for an estimate validation failure. Mirrors the
# ``CONTRACT_INVALID`` entry in automation/fail-reasons.json (class ``contract``).
ESTIMATE_FAIL_REASON: Final[str] = "CONTRACT_INVALID"


class ResourceEstimateError(ValueError):
    """Raised when a resource estimate is structurally invalid.

    A :class:`ValueError` (not an :class:`Exception`) so a caller handling
    malformed input via ``except ValueError`` still catches the estimate family,
    mirroring :class:`srl.autonomy.policy.PolicyError`. The ``fail_reason`` is
    always ``CONTRACT_INVALID`` so the failure routes through the resume and
    fail-reason machinery as a deterministic, non-retriable contract failure.

    Attributes
    ----------
    fail_reason:
        Typed fail reason (always ``CONTRACT_INVALID`` for estimate violations).
    """

    def __init__(self, message: str, *, fail_reason: str = ESTIMATE_FAIL_REASON) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


def _is_bool(value: object) -> bool:
    """Return True iff ``value`` is a Python ``bool`` (and not a plain int).

    Extracted as a named helper so the "is this a bool?" predicate has one home
    and reads as English at the call site. ``bool`` is checked because
    ``isinstance(True, int)`` is ``True`` in Python and a flag must never be
    admitted as a quantity.
    """
    return isinstance(value, bool)


def _validate_non_negative_int(value: object, *, field: str) -> int:
    """Validate ``value`` as a non-negative integer (rejecting bool).

    A resource quantity is a real integer ``>= 0``. ``bool`` is rejected (a flag
    is not a quantity) and floats are rejected even when integral, so a quantity
    is never silently coerced and the canonical digest never depends on the
    float/int distinction.

    Raises :class:`ResourceEstimateError` (``CONTRACT_INVALID``) on rejection.
    """
    if _is_bool(value):
        msg = f"estimate field {field!r} must be an int, got bool"
        raise ResourceEstimateError(msg)
    if not isinstance(value, int):
        msg = f"estimate field {field!r} must be an int, got {type(value).__name__}"
        raise ResourceEstimateError(msg)
    if value < 0:
        msg = f"estimate field {field!r} must be >= 0, got {value}"
        raise ResourceEstimateError(msg)
    return value


@dataclass(frozen=True)
class ResourceEstimate:
    """The resource demand of a single bounded execution step.

    All four fields are non-negative integers. The estimate is a pure forecast;
    the actual consumption is recorded on the engine receipt by WP-B13. The
    estimate admits or parks the step; it never authorizes anything.

    Attributes
    ----------
    wall_seconds:
        Forecast wall-clock duration in seconds (``>= 0``).
    rss_bytes:
        Forecast resident set size in bytes (``>= 0``).
    scratch_bytes:
        Forecast working-set / scratch bytes (``>= 0``).
    cpu_cores:
        Forecast CPU cores required (``>= 0``).
    """

    wall_seconds: int
    rss_bytes: int
    scratch_bytes: int
    cpu_cores: int

    def __post_init__(self) -> None:
        """Validate every field as a non-negative integer (rejecting bool).

        Validation runs at construction so an invalid estimate can never exist
        long enough to be admitted or serialized. Each field is checked through
        :func:`_validate_non_negative_int` for a uniform contract.
        """
        object.__setattr__(
            self,
            "wall_seconds",
            _validate_non_negative_int(self.wall_seconds, field="wall_seconds"),
        )
        object.__setattr__(
            self, "rss_bytes", _validate_non_negative_int(self.rss_bytes, field="rss_bytes")
        )
        object.__setattr__(
            self,
            "scratch_bytes",
            _validate_non_negative_int(self.scratch_bytes, field="scratch_bytes"),
        )
        object.__setattr__(
            self, "cpu_cores", _validate_non_negative_int(self.cpu_cores, field="cpu_cores")
        )

    def to_canonical_dict(self) -> dict[str, int]:
        """Return the estimate as a canonical-key-order dict for serialization.

        The key order is fixed (not sorted at encode time) so the canonical
        bytes are independent of dataclass field ordering and stable across
        implementations. The canonical encoder sorts keys again as a belt-and-
        braces guarantee, but this dict is already in the documented order.
        """
        return {
            "cpu_cores": self.cpu_cores,
            "rss_bytes": self.rss_bytes,
            "scratch_bytes": self.scratch_bytes,
            "wall_seconds": self.wall_seconds,
        }

    def canonical_bytes(self) -> bytes:
        """Return the canonical JSON encoding of the estimate as UTF-8 bytes.

        The encoding is the SRL canonical form: sorted keys, compact separators,
        non-ASCII passthrough, no ``NaN``/``Infinity``, and a single trailing
        newline. The return type is :class:`bytes` so the digest and byte count
        are computed over the serialized bytes, not over a locale-dependent str.
        """
        text = json.dumps(
            self.to_canonical_dict(),
            sort_keys=True,
            separators=_SEP,
            ensure_ascii=False,
            allow_nan=False,
        )
        return (text + _NEWLINE).encode(_ENCODING)

    def digest(self) -> str:
        """Return the SHA-256 digest of the canonical encoding.

        The digest is ``"sha256:"`` + 64 lowercase hex digits. It is a pure
        function of the estimate's content, so two independent producers of the
        same estimate compute the same digest with no coordination.
        """
        return _DIGEST_PREFIX + hashlib.sha256(self.canonical_bytes()).hexdigest()


__all__ = ["ESTIMATE_FAIL_REASON", "ResourceEstimate", "ResourceEstimateError"]
