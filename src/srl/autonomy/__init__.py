"""Autonomy contract primitives for SRL.

This package encodes the machine-checkable contracts that govern autonomous
work under ``AutonomyPolicy/v1``. It is intentionally pure standard library:
the policy loader, scope guard, public-leak guard and deterministic resume
reconciler are all dependency-free so they can run in any environment,
including a minimal CI runner, without coupling to the scientific stack.

The contracts here are *admission* contracts, not scientific ones. A green
return from any function in this package means the operation satisfied the
automation contract; it never means a scientific claim is supported (see
``GOVERNANCE.md`` for the evidence rules).
"""

from __future__ import annotations

from srl.autonomy.lanes import (
    DEFAULT_LEASE_TTL_SECONDS,
    LEDGER_SCHEMA_VERSION,
    Executor,
    LaneEntry,
    LaneError,
    LaneLedger,
    LaneStatus,
    PathOwnershipError,
    acquire_lane,
    expire_leases,
    heartbeat,
    load_ledger,
    policy_lane_cap,
    release_lane,
    save_ledger,
)
from srl.autonomy.leakguard import LeakViolation, scan_bytes, scan_diff
from srl.autonomy.policy import PolicyError, load_policy
from srl.autonomy.resume import (
    Decision,
    IdempotencyInputs,
    ResumeDecision,
    idempotency_key,
    reconcile,
)
from srl.autonomy.scopes import ScopeViolation, check_write

__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "LEDGER_SCHEMA_VERSION",
    "Decision",
    "Executor",
    "IdempotencyInputs",
    "LaneEntry",
    "LaneError",
    "LaneLedger",
    "LaneStatus",
    "LeakViolation",
    "PathOwnershipError",
    "PolicyError",
    "ResumeDecision",
    "ScopeViolation",
    "acquire_lane",
    "check_write",
    "expire_leases",
    "heartbeat",
    "idempotency_key",
    "load_ledger",
    "load_policy",
    "policy_lane_cap",
    "reconcile",
    "release_lane",
    "save_ledger",
    "scan_bytes",
    "scan_diff",
]
