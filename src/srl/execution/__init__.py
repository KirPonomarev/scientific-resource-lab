"""Resource policy and admission semantics for bounded execution (M1, WP-D30).

This package encodes the machine-checkable contracts that govern local
scientific execution: a :class:`~srl.execution.policy.ResourcePolicy` with a
default envelope and a bounded exception envelope, a pure
:func:`~srl.execution.policy.admit` decision with no silent downgrade, a
hermetic :mod:`~srl.execution.platform_probe` preflight that enforces the
free-disk floor, and a content-addressed
:class:`~srl.execution.estimate.ResourceEstimate`.

It is intentionally standard library only, mirroring the autonomy primitives in
:mod:`srl.autonomy`, so it runs in any environment without coupling to the
scientific contracts layer (and its ``jsonschema`` dependency). The runner
(WP-D31) will call :func:`~srl.execution.policy.admit` and
:func:`~srl.execution.platform_probe.preflight` before launching a step.

The contracts here are *admission* contracts, not scientific ones. A green
admission means a step fit the resource envelope; it never means a scientific
claim is supported (see ``GOVERNANCE.md`` for the evidence rules).
"""

from __future__ import annotations

from srl.execution.estimate import (
    ESTIMATE_FAIL_REASON,
    ResourceEstimate,
    ResourceEstimateError,
)
from srl.execution.platform_probe import (
    PREFLIGHT_SCHEMA_VERSION,
    RESOURCE_LIMIT_FAIL_REASON,
    DiskProbe,
    PreflightProvider,
    PreflightReceipt,
    ResourceLimitError,
    StaticPreflightProvider,
    preflight,
)
from srl.execution.policy import (
    OVERFLOW_ACTION,
    POLICY_FAIL_REASON,
    RESOURCE_POLICY_SCHEMA_VERSION,
    AdmissionDecision,
    PolicyError,
    ResourcePolicy,
    admit,
    load_policy,
)

__all__ = [
    "ESTIMATE_FAIL_REASON",
    "OVERFLOW_ACTION",
    "POLICY_FAIL_REASON",
    "PREFLIGHT_SCHEMA_VERSION",
    "RESOURCE_LIMIT_FAIL_REASON",
    "RESOURCE_POLICY_SCHEMA_VERSION",
    "AdmissionDecision",
    "DiskProbe",
    "PolicyError",
    "PreflightProvider",
    "PreflightReceipt",
    "ResourceEstimate",
    "ResourceEstimateError",
    "ResourceLimitError",
    "ResourcePolicy",
    "StaticPreflightProvider",
    "admit",
    "load_policy",
    "preflight",
]
