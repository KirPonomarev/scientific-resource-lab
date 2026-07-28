"""Resource policy, admission, and the fixed-entrypoint bounded runner (M1).

This package encodes the machine-checkable contracts that govern local
scientific execution: a :class:`~srl.execution.policy.ResourcePolicy` with a
default envelope and a bounded exception envelope, a pure
:func:`~srl.execution.policy.admit` decision with no silent downgrade, a
hermetic :mod:`~srl.execution.platform_probe` preflight that enforces the
free-disk floor, a content-addressed :class:`~srl.execution.estimate.ResourceEstimate`,
the static adapter registry (:mod:`~srl.execution.entrypoints`), the subprocess
sandbox (:mod:`~srl.execution.sandbox`), and the bounded runner itself
(:func:`~srl.execution.runner.run_adapter`).

It is intentionally standard library only, mirroring the autonomy primitives in
:mod:`srl.autonomy`, so it runs in any environment without coupling to the
scientific contracts layer (and its ``jsonschema`` dependency). The runner calls
:func:`~srl.execution.policy.admit` and
:func:`~srl.execution.platform_probe.preflight` before launching a step, and
launches it only through the fixed ``-m srl.execution.child`` entrypoint.

The contracts here are *admission* contracts, not scientific ones. A green
admission means a step fit the resource envelope; it never means a scientific
claim is supported (see ``GOVERNANCE.md`` for the evidence rules).
"""

from __future__ import annotations

from srl.execution.entrypoints import (
    IR_UNSUPPORTED_REASON,
    UNKNOWN_ADAPTER_FAIL_REASON,
    AdapterDescriptor,
    UnknownAdapterError,
    get_adapter,
    list_adapters,
    run_handler,
    validate_input,
    validate_output,
)
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
from srl.execution.runner import (
    POLICY_VIOLATION_FAIL_REASON,
    RUN_RECEIPT_SCHEMA_VERSION,
    RunOutcome,
    RunStatus,
    RunUsage,
    run_adapter,
)
from srl.execution.sandbox import (
    DEFAULT_OUTPUT_CAP_BYTES,
    ORPHAN_FAIL_REASON,
    CapturedOutput,
    LimitSetupError,
    OrphanDetectedError,
    OutputLimitError,
    ResourceLimits,
    SandboxError,
    build_child_env,
    make_preexec,
    prepare_scratch,
)

__all__ = [
    "DEFAULT_OUTPUT_CAP_BYTES",
    "ESTIMATE_FAIL_REASON",
    "IR_UNSUPPORTED_REASON",
    "ORPHAN_FAIL_REASON",
    "OVERFLOW_ACTION",
    "POLICY_FAIL_REASON",
    "POLICY_VIOLATION_FAIL_REASON",
    "PREFLIGHT_SCHEMA_VERSION",
    "RESOURCE_LIMIT_FAIL_REASON",
    "RESOURCE_POLICY_SCHEMA_VERSION",
    "RUN_RECEIPT_SCHEMA_VERSION",
    "UNKNOWN_ADAPTER_FAIL_REASON",
    "AdapterDescriptor",
    "AdmissionDecision",
    "CapturedOutput",
    "DiskProbe",
    "LimitSetupError",
    "OrphanDetectedError",
    "OutputLimitError",
    "PolicyError",
    "PreflightProvider",
    "PreflightReceipt",
    "ResourceEstimate",
    "ResourceEstimateError",
    "ResourceLimitError",
    "ResourceLimits",
    "ResourcePolicy",
    "RunOutcome",
    "RunStatus",
    "RunUsage",
    "SandboxError",
    "StaticPreflightProvider",
    "UnknownAdapterError",
    "admit",
    "build_child_env",
    "get_adapter",
    "list_adapters",
    "load_policy",
    "make_preexec",
    "preflight",
    "prepare_scratch",
    "run_adapter",
    "run_handler",
    "validate_input",
    "validate_output",
]
