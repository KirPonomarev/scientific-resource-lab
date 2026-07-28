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
    "Decision",
    "IdempotencyInputs",
    "LeakViolation",
    "PolicyError",
    "ResumeDecision",
    "ScopeViolation",
    "check_write",
    "idempotency_key",
    "load_policy",
    "reconcile",
    "scan_bytes",
    "scan_diff",
]
