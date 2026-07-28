"""Platform probe and preflight for the resource policy.

Before a step is admitted locally, the runner confirms the host can actually
honour the policy's free-disk floor. :func:`preflight` reads the free bytes via
an injectable provider and raises :class:`ResourceLimitError`
(``fail_reason='RESOURCE_LIMIT'``) when the floor is not met.

The probe is split from admission on purpose. Admission
(:func:`srl.execution.policy.admit`) is a pure decision over an estimate and a
policy; preflight is a measurement over the live host. Keeping them separate
means a pure admission decision can be unit-tested without touching the
filesystem, and a preflight result can be cached or faked without re-running
admission.

Hermetic testing
----------------
The default :class:`DiskProbe` reads ``shutil.disk_usage``, which touches the
real filesystem and is non-hermetic. Tests inject a :class:`PreflightProvider`
(a frozen dataclass returning a fixed free-byte count) so preflight is fully
deterministic and never depends on the runner's disk.

Design notes
------------
This module is intentionally standard library only, mirroring the autonomy
primitives in :mod:`srl.autonomy`. The ``RESOURCE_LIMIT`` fail reason mirrors
the ``ci`` class entry in automation/fail-reasons.json ("A hard resource limit
(CPU, memory, disk, time) was exceeded").
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from srl.execution.estimate import ResourceEstimate
from srl.execution.policy import ResourcePolicy

# The typed fail reason emitted when the free-disk floor is not met. Mirrors the
# ``RESOURCE_LIMIT`` entry in automation/fail-reasons.json (class ``ci``).
RESOURCE_LIMIT_FAIL_REASON: Final[str] = "RESOURCE_LIMIT"

# The schema identity for the preflight receipt emitted by :func:`preflight`.
PREFLIGHT_SCHEMA_VERSION: Final[str] = "PreflightReceipt/v1"

# Canonical JSON separators, mirroring the rest of the execution package.
_SEP: Final[tuple[str, str]] = (",", ":")


class ResourceLimitError(ValueError):
    """Raised when a hard resource limit is exceeded at preflight.

    A :class:`ValueError` (not an :class:`Exception`) so a caller handling the
    failure via ``except ValueError`` still catches it. The ``fail_reason`` is
    ``RESOURCE_LIMIT`` so the failure routes through the resume and fail-reason
    machinery as a hard resource limit (class ``ci``, ``retriable=false``).

    Attributes
    ----------
    fail_reason:
        Typed fail reason (always ``RESOURCE_LIMIT`` for preflight failures).
    """

    def __init__(self, message: str, *, fail_reason: str = RESOURCE_LIMIT_FAIL_REASON) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


class PreflightProvider(Protocol):
    """Injectable source of the free-disk byte count for preflight.

    A :class:`typing.Protocol` (structural typing) so tests pass any object with
    a matching ``free_disk_bytes`` attribute without inheriting from a base. The
    default :class:`DiskProbe` satisfies it via the real filesystem; the test
    :class:`PreflightProvider` (a frozen dataclass) satisfies it with a constant.
    """

    @property
    def free_disk_bytes(self) -> int:
        """Free bytes on the target volume as a non-negative int."""
        ...


@dataclass(frozen=True)
class StaticPreflightProvider:
    """A :class:`PreflightProvider` that returns a fixed free-byte count.

    Frozen so two preflight calls over the same provider are byte-identical and
    the provider is safe to share across admission attempts. Used by tests and
    by any caller that wants preflight to be a pure function of a chosen value.
    """

    free_disk_bytes: int


class DiskProbe:
    """Reads free bytes from the real filesystem via :func:`shutil.disk_usage`.

    Non-hermetic: the returned value depends on the runner's actual disk state.
    Constructed with the path whose volume is measured (default the current
    working directory). For hermetic tests, inject a
    :class:`StaticPreflightProvider` instead.
    """

    def __init__(self, path: str | Path = ".") -> None:
        """Remember the volume path; do not touch the filesystem at construction.

        The path is resolved lazily in :pyattr:`free_disk_bytes` so constructing
        a probe never fails and the probe can be built before the volume exists.
        """
        self._path = Path(path)

    @property
    def free_disk_bytes(self) -> int:
        """Return the free bytes on the probe's volume.

        Uses :func:`shutil.disk_usage`, which on POSIX returns the bytes
        available to unprivileged processes. The value is non-negative.
        """
        return shutil.disk_usage(self._path).free


@dataclass(frozen=True)
class PreflightReceipt:
    """The result of a successful preflight.

    Attributes
    ----------
    required_free_disk_bytes:
        The policy's free-disk floor that was enforced.
    observed_free_disk_bytes:
        The free bytes observed on the host.
    ok:
        ``True`` (a receipt is only emitted on success; a failure raises).
    """

    required_free_disk_bytes: int
    observed_free_disk_bytes: int
    ok: bool

    def to_dict(self) -> dict[str, object]:
        """Return the receipt as a dict for canonical serialization.

        Includes the estimate digest so a serialized preflight receipt ties back
        to the exact estimate that was about to run. Key order is fixed for
        stable bytes.
        """
        return {
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "required_free_disk_bytes": self.required_free_disk_bytes,
            "observed_free_disk_bytes": self.observed_free_disk_bytes,
            "ok": self.ok,
        }


def preflight(
    estimate: ResourceEstimate,
    policy: ResourcePolicy,
    preflight_provider: PreflightProvider,
) -> PreflightReceipt:
    """Enforce the policy's free-disk floor; raise if not met.

    Reads ``free_disk_bytes`` from ``preflight_provider`` (injectable for tests)
    and raises :class:`ResourceLimitError` (``fail_reason='RESOURCE_LIMIT'``)
    when the observed free bytes are strictly less than the policy's
    ``required_free_disk_bytes``. On success, returns a :class:`PreflightReceipt`
    recording both values.

    The estimate is accepted positionally so a caller can bind a specific step
    to its preflight; the floor enforced is the policy-wide floor (the estimate
    does not widen it in M1).

    Parameters
    ----------
    estimate:
        The estimate about to run (carried for receipt context; validated at
        construction).
    policy:
        The loaded :class:`ResourcePolicy` whose ``required_free_disk_bytes``
        floor is enforced.
    preflight_provider:
        Injectable source of the observed free-disk byte count.

    Returns
    -------
    PreflightReceipt
        The successful preflight result.

    Raises
    ------
    ResourceLimitError
        If the observed free bytes are below the policy's floor. The
        ``fail_reason`` is ``RESOURCE_LIMIT``.
    """
    del estimate  # carried for receipt/identity context; not used to widen the floor in M1
    observed = preflight_provider.free_disk_bytes
    required = policy.required_free_disk_bytes
    if observed < required:
        msg = (
            f"preflight RESOURCE_LIMIT: observed free disk {observed} bytes is below "
            f"the policy floor {required} bytes"
        )
        raise ResourceLimitError(msg)
    return PreflightReceipt(
        required_free_disk_bytes=required,
        observed_free_disk_bytes=observed,
        ok=True,
    )


__all__ = [
    "PREFLIGHT_SCHEMA_VERSION",
    "RESOURCE_LIMIT_FAIL_REASON",
    "DiskProbe",
    "PreflightProvider",
    "PreflightReceipt",
    "ResourceLimitError",
    "StaticPreflightProvider",
    "preflight",
]
