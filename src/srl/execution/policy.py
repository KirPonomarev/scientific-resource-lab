"""Resource policy and admission semantics for bounded execution (M1).

``ResourcePolicy/v1`` is the machine-checkable admission policy for a scientific
execution runner. It declares two envelopes — a strict **default** envelope and
a looser **exception** envelope — plus an overflow action. A runner admits a
:class:`~srl.execution.estimate.ResourceEstimate` against the policy via
:func:`admit`, which is a pure function: an estimate over the default caps is
admitted **only** through the explicit exception envelope, and an estimate over
the exception caps is never run locally — it parks as ``WAIT_REMOTE_EXECUTOR``.

No silent downgrade
-------------------
The load-bearing property of admission is that a larger estimate is never
silently admitted under a smaller envelope. Concretely:

- an estimate within the default caps -> ``ADMITTED_DEFAULT``;
- an estimate over the default caps but within the exception caps is
  ``ADMITTED_EXCEPTION`` *only* when the caller passes ``use_exception=True``;
  the same estimate with ``use_exception=False`` is ``WAIT_REMOTE_EXECUTOR``;
- an estimate over the exception caps is ``WAIT_REMOTE_EXECUTOR`` regardless of
  the exception flag.

This means the exception envelope is an explicit, opt-in widening — never an
automatic one.

Exception envelope is bounded
-----------------------------
The exception envelope is strictly bounded by absolute caps (see
:data:`_EXCEPTION_CAPS`): ``cpu_cores <= 2``, ``rss_bytes <= 2 GiB``,
``wall_seconds <= 900``, and ``scratch_bytes`` must be ``<=`` the default
scratch (the exception never widens scratch beyond the default). Any exception
value beyond these absolute caps is rejected at load with
:class:`PolicyError` (``CONTRACT_INVALID``), so a policy file cannot silently
raise the ceiling.

Design notes
------------
This module is intentionally standard library only, mirroring the autonomy
primitives in :mod:`srl.autonomy`. The policy is loaded as a validated
:class:`ResourcePolicy` dataclass; the on-disk JSON is the artifact a mission
runs against, and the embedded expectation here is the authority for what the
policy may contain. If the two drift, the loader refuses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from srl.execution.estimate import ResourceEstimate

# Schema identity. Bumping this is a governance change (see GOVERNANCE.md).
RESOURCE_POLICY_SCHEMA_VERSION: Final[str] = "ResourcePolicy/v1"

# The typed fail reason for a policy load/validation failure. Mirrors the
# ``CONTRACT_INVALID`` entry in automation/fail-reasons.json (class ``contract``).
POLICY_FAIL_REASON: Final[str] = "CONTRACT_INVALID"

# Canonical JSON separators and newline contract, mirroring srl.contracts.canonical
# but kept local so this module is dependency-free and vendored as a unit.
_SEP: Final[tuple[str, str]] = (",", ":")
_ENCODING: Final[str] = "utf-8"

# The overflow action admitted by the M1 policy. A larger job is never run
# locally; it parks for a remote executor that WP-D31 will wire.
OVERFLOW_ACTION: Final[str] = "WAIT_REMOTE_EXECUTOR"

# The absolute caps on the exception envelope. Any exception value beyond these
# is rejected at load with PolicyError(CONTRACT_INVALID). The exception may be
# stronger (looser) than the default only where listed here; on scratch it may
# never exceed the default scratch.
_GIB: Final[int] = 1024**3
_EXCEPTION_CAPS: Final[dict[str, int]] = {
    "cpu_cores": 2,
    "rss_bytes": 2 * _GIB,  # 2 GiB = 2147483648
    "wall_seconds": 900,
}

# The default-policy fields that must be non-negative integers, in sorted order
# for stable diagnostics. ``concurrency``, ``canonical_writes`` and
# ``required_free_disk_bytes`` are also validated as ints below.
_INT_FIELDS: Final[tuple[str, ...]] = (
    "concurrency",
    "cpu_cores",
    "required_free_disk_bytes",
    "rss_bytes",
    "scratch_bytes",
    "wall_seconds",
)

# The keys of the exception sub-object, for stable validation.
_EXCEPTION_FIELDS: Final[tuple[str, ...]] = (
    "cpu_cores",
    "rss_bytes",
    "scratch_bytes",
    "wall_seconds",
)


class PolicyError(ValueError):
    """Raised when a resource policy document fails validation.

    A :class:`ValueError` (not an :class:`Exception`) so a caller handling
    malformed input via ``except ValueError`` still catches the policy family,
    mirroring :class:`srl.autonomy.policy.PolicyError`. The ``fail_reason`` is
    always ``CONTRACT_INVALID`` so the failure routes through the resume and
    fail-reason machinery as a deterministic, non-retriable contract failure.

    Attributes
    ----------
    fail_reason:
        Typed fail reason (always ``CONTRACT_INVALID`` for policy violations).
    """

    def __init__(self, message: str, *, fail_reason: str = POLICY_FAIL_REASON) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


class AdmissionDecision(StrEnum):
    """The outcome of admitting an estimate against a policy.

    ``StrEnum`` keeps the serialized form a plain JSON string
    (``"ADMITTED_DEFAULT"``) while giving us enum membership tests. The three
    members cover every admission outcome; there is no fourth "silently
    downgraded" state by construction.
    """

    ADMITTED_DEFAULT = "ADMITTED_DEFAULT"
    ADMITTED_EXCEPTION = "ADMITTED_EXCEPTION"
    WAIT_REMOTE_EXECUTOR = "WAIT_REMOTE_EXECUTOR"


@dataclass(frozen=True)
class _Envelope:
    """A resource envelope: four caps shared by default and exception.

    Extracted as a value object so the default and exception envelopes share one
    shape and the admission comparison reads as plain field-wise ``<=``.
    """

    cpu_cores: int
    rss_bytes: int
    scratch_bytes: int
    wall_seconds: int


@dataclass(frozen=True)
class ResourcePolicy:
    """A validated ``ResourcePolicy/v1``.

    The policy is immutable in flight (``canonical_writes`` is ``0`` and
    ``grants_authority`` is ``false``). It exposes the default and exception
    envelopes as :class:`_Envelope` value objects and carries the overflow
    action, the free-disk floor, and the WIP concurrency limit.

    Attributes
    ----------
    name:
        Human-readable policy name (e.g. ``m1-default``).
    concurrency:
        Maximum in-flight (WIP) execution steps admitted locally. M1 fixes this
        at 1; the runner (WP-D31) enforces it.
    default:
        The strict default envelope.
    exception:
        The bounded exception envelope (strictly weaker-or-equal to the absolute
        caps; scratch never exceeds the default).
    overflow_action:
        What to do with an estimate over the exception caps. M1 fixes this at
        ``WAIT_REMOTE_EXECUTOR``.
    required_free_disk_bytes:
        The free-disk floor enforced by preflight (see
        :mod:`srl.execution.platform_probe`).
    canonical_writes:
        Always ``0`` (safety const; a resource policy never writes).
    grants_authority:
        Always ``False`` (safety const; admitting a job never grants authority).
    """

    name: str
    concurrency: int
    default: _Envelope
    exception: _Envelope
    overflow_action: str
    required_free_disk_bytes: int
    canonical_writes: int
    grants_authority: bool


# ---------------------------------------------------------------------------
# Internal validation helpers.
# ---------------------------------------------------------------------------


def _is_bool(value: object) -> bool:
    """Return True iff ``value`` is a Python ``bool`` (and not a plain int)."""
    return isinstance(value, bool)


def _as_int(value: object, *, field: str) -> int:
    """Validate ``value`` as an int (rejecting bool); return it.

    Raises :class:`PolicyError` (``CONTRACT_INVALID``) on rejection. Used for
    every integer field in the policy, including those that may be 0.
    """
    if _is_bool(value):
        msg = f"policy field {field!r} must be an int, got bool"
        raise PolicyError(msg)
    if not isinstance(value, int):
        msg = f"policy field {field!r} must be an int, got {type(value).__name__}"
        raise PolicyError(msg)
    return value


def _as_non_negative_int(value: object, *, field: str) -> int:
    """Validate ``value`` as a non-negative int (rejecting bool); return it."""
    n = _as_int(value, field=field)
    if n < 0:
        msg = f"policy field {field!r} must be >= 0, got {n}"
        raise PolicyError(msg)
    return n


def _as_bool(value: object, *, field: str) -> bool:
    """Validate ``value`` as a JSON bool; return it.

    Raises :class:`PolicyError` (``CONTRACT_INVALID``) if ``value`` is not a
    bool. An int is not accepted even if it is 0/1: a flag is not a quantity.
    """
    if not isinstance(value, bool):
        msg = f"policy field {field!r} must be a bool, got {type(value).__name__}"
        raise PolicyError(msg)
    return value


def _as_str(value: object, *, field: str) -> str:
    """Validate ``value`` as a non-empty str; return it."""
    if not isinstance(value, str) or not value:
        msg = f"policy field {field!r} must be a non-empty string"
        raise PolicyError(msg)
    return value


def _validate_exception(exception: object, default: _Envelope) -> _Envelope:
    """Validate the exception sub-object and bound it against the absolute caps.

    The exception must be a dict with exactly the four envelope fields, each a
    non-negative int. It is then bounded: ``cpu_cores <= 2``, ``rss_bytes <=
    2 GiB``, ``wall_seconds <= 900`` (the absolute caps in
    :data:`_EXCEPTION_CAPS`), and ``scratch_bytes <= default.scratch_bytes``
    (the exception never widens scratch beyond the default). Any value beyond
    these caps is rejected with :class:`PolicyError` (``CONTRACT_INVALID``).
    """
    if not isinstance(exception, dict):
        msg = "policy field 'exception' must be an object"
        raise PolicyError(msg)
    actual_keys = set(exception.keys())
    expected_keys = set(_EXCEPTION_FIELDS)
    missing = sorted(expected_keys - actual_keys)
    if missing:
        msg = f"policy exception missing key(s): {missing}"
        raise PolicyError(msg)
    extra = sorted(actual_keys - expected_keys)
    if extra:
        msg = f"policy exception has unexpected key(s): {extra}"
        raise PolicyError(msg)

    env = _Envelope(
        cpu_cores=_as_non_negative_int(exception["cpu_cores"], field="exception.cpu_cores"),
        rss_bytes=_as_non_negative_int(exception["rss_bytes"], field="exception.rss_bytes"),
        scratch_bytes=_as_non_negative_int(
            exception["scratch_bytes"], field="exception.scratch_bytes"
        ),
        wall_seconds=_as_non_negative_int(
            exception["wall_seconds"], field="exception.wall_seconds"
        ),
    )

    # Bound each exception field against its absolute cap. scratch is bounded by
    # the default scratch (the exception never widens scratch).
    for field, cap in _EXCEPTION_CAPS.items():
        v = getattr(env, field)
        if v > cap:
            msg = (
                f"policy exception.{field}={v} exceeds the absolute cap {cap}; "
                "the exception envelope may not be widened beyond its bounds"
            )
            raise PolicyError(msg)
    if env.scratch_bytes > default.scratch_bytes:
        msg = (
            f"policy exception.scratch_bytes={env.scratch_bytes} exceeds the default "
            f"scratch_bytes={default.scratch_bytes}; scratch is never widened by the exception"
        )
        raise PolicyError(msg)
    return env


def _validate_policy_dict(doc: dict[str, Any]) -> ResourcePolicy:
    """Validate a parsed policy dict and build a :class:`ResourcePolicy`.

    Checks run in a deterministic order: schema version, scalar fields, the
    default envelope, then the bounded exception envelope. A failure at any step
    raises :class:`PolicyError` with a message naming the offending field.
    """
    if doc.get("schema_version") != RESOURCE_POLICY_SCHEMA_VERSION:
        msg = (
            f"policy schema_version is {doc.get('schema_version')!r}, "
            f"expected {RESOURCE_POLICY_SCHEMA_VERSION!r}"
        )
        raise PolicyError(msg)

    # Scalar int fields (default envelope + concurrency + free-disk floor).
    concurrency = _as_non_negative_int(doc.get("concurrency"), field="concurrency")
    default = _Envelope(
        cpu_cores=_as_non_negative_int(doc.get("cpu_cores"), field="cpu_cores"),
        rss_bytes=_as_non_negative_int(doc.get("rss_bytes"), field="rss_bytes"),
        scratch_bytes=_as_non_negative_int(doc.get("scratch_bytes"), field="scratch_bytes"),
        wall_seconds=_as_non_negative_int(doc.get("wall_seconds"), field="wall_seconds"),
    )
    required_free_disk = _as_non_negative_int(
        doc.get("required_free_disk_bytes"), field="required_free_disk_bytes"
    )
    canonical_writes = _as_int(doc.get("canonical_writes"), field="canonical_writes")
    if canonical_writes != 0:
        msg = f"policy canonical_writes must be 0 (safety const), got {canonical_writes}"
        raise PolicyError(msg)
    grants_authority = _as_bool(doc.get("grants_authority"), field="grants_authority")
    if grants_authority:
        msg = "policy grants_authority must be false (a resource policy never grants authority)"
        raise PolicyError(msg)
    name = _as_str(doc.get("name"), field="name")
    overflow = _as_str(doc.get("overflow_action"), field="overflow_action")

    exception = _validate_exception(doc.get("exception"), default)

    return ResourcePolicy(
        name=name,
        concurrency=concurrency,
        default=default,
        exception=exception,
        overflow_action=overflow,
        required_free_disk_bytes=required_free_disk,
        canonical_writes=canonical_writes,
        grants_authority=grants_authority,
    )


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def load_policy(path: str | Path) -> ResourcePolicy:
    """Load and validate the resource policy document at ``path``.

    Parameters
    ----------
    path:
        Filesystem path to a canonical ``ResourcePolicy/v1`` JSON document.

    Returns
    -------
    ResourcePolicy
        The validated policy as an immutable dataclass. The default and
        exception envelopes are bounded; the overflow action and safety consts
        are pinned.

    Raises
    ------
    PolicyError
        If the file is missing, is not valid JSON, is not an object, or does not
        match the ``ResourcePolicy/v1`` contract (wrong schema version, wrong
        types, an exception value beyond its absolute cap, or a violated safety
        const). The ``fail_reason`` is always ``CONTRACT_INVALID``.
    """
    p = Path(path)
    if not p.is_file():
        msg = f"policy file not found: {p}"
        raise PolicyError(msg)
    try:
        raw = p.read_text(encoding=_ENCODING)
    except OSError as exc:
        msg = f"could not read policy file {p}: {exc}"
        raise PolicyError(msg) from exc
    # Canonical JSON rejects NaN/Infinity at parse time so a non-finite value
    # can never reach the field validators.
    try:
        parsed = json.loads(raw, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        msg = f"policy file {p} is not valid JSON: {exc}"
        raise PolicyError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"policy file {p} must be a JSON object, got {type(parsed).__name__}"
        raise PolicyError(msg)
    return _validate_policy_dict(parsed)


def _reject_constant(name: str) -> Any:
    """Hook for :func:`json.loads` ``parse_constant``: reject NaN/Infinity.

    The JSON grammar admits no constant tokens. Python's decoder accepts
    ``NaN`` / ``Infinity`` / ``-Infinity`` by default; we treat them as
    malformed input so a policy file never carries a non-finite number.
    """
    msg = f"canonical JSON must not contain the constant {name!r}"
    raise PolicyError(msg)


def _within(estimate: ResourceEstimate, envelope: _Envelope) -> bool:
    """Return True iff ``estimate`` fits within ``envelope`` on all four axes.

    A pure field-wise ``<=`` comparison. The estimate is a
    :class:`~srl.execution.estimate.ResourceEstimate` (validated at
    construction), so the attributes are trusted non-negative ints here.
    """
    return (
        estimate.cpu_cores <= envelope.cpu_cores
        and estimate.rss_bytes <= envelope.rss_bytes
        and estimate.scratch_bytes <= envelope.scratch_bytes
        and estimate.wall_seconds <= envelope.wall_seconds
    )


def admit(
    estimate: ResourceEstimate, policy: ResourcePolicy, *, use_exception: bool = False
) -> AdmissionDecision:
    """Admit ``estimate`` against ``policy``; return the decision.

    A pure function with no side effects and no silent downgrade:

    - within the default envelope -> :pyattr:`AdmissionDecision.ADMITTED_DEFAULT`;
    - over the default envelope but within the exception envelope, AND
      ``use_exception=True`` -> :pyattr:`AdmissionDecision.ADMITTED_EXCEPTION`;
    - otherwise -> :pyattr:`AdmissionDecision.WAIT_REMOTE_EXECUTOR`.

    The exception envelope is opt-in: an estimate over the default caps with
    ``use_exception=False`` is ``WAIT_REMOTE_EXECUTOR`` (never silently admitted
    to the exception envelope). An estimate over the exception caps is
    ``WAIT_REMOTE_EXECUTOR`` regardless of the flag.

    Parameters
    ----------
    estimate:
        A :class:`~srl.execution.estimate.ResourceEstimate` (validated at
        construction).
    policy:
        The loaded :class:`ResourcePolicy`.
    use_exception:
        Whether the caller is authorized to use the exception envelope. Defaults
        to ``False`` so the default path is the strict one.

    Returns
    -------
    AdmissionDecision
        One of the three admission outcomes.
    """
    if _within(estimate, policy.default):
        return AdmissionDecision.ADMITTED_DEFAULT
    if use_exception and _within(estimate, policy.exception):
        return AdmissionDecision.ADMITTED_EXCEPTION
    return AdmissionDecision.WAIT_REMOTE_EXECUTOR


__all__ = [
    "OVERFLOW_ACTION",
    "POLICY_FAIL_REASON",
    "RESOURCE_POLICY_SCHEMA_VERSION",
    "AdmissionDecision",
    "PolicyError",
    "ResourcePolicy",
    "admit",
    "load_policy",
]
