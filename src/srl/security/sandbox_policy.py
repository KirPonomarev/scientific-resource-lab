"""Trust-class sandbox admission policy.

This module is the fail-closed bridge between pack trust classes (T0-T4) and
the bounded runner. It does not launch containers, microVMs, remote providers,
or paid APIs. It only answers one question: does the supplied host capability
manifest prove enough isolation for the requested trust class?

If the answer is no, the decision parks the run as ``WAIT_COMPUTE_NODE`` or
``WAIT_AUTHORITY``. It never downgrades T2/T3 work into the weaker local
subprocess sandbox.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

SANDBOX_POLICY_SCHEMA_VERSION: Final[str] = "SandboxPolicy/v1"
HOST_CAPABILITY_MANIFEST_SCHEMA_VERSION: Final[str] = "HostCapabilityManifest/v1"


class TrustClass(StrEnum):
    """SRF trust classes."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class IsolationCapability(StrEnum):
    """Capabilities a host can prove to the sandbox admission layer."""

    PROCESS_LIMITS = "process_limits"
    SANITIZED_ENV = "sanitized_env"
    PRIVATE_SCRATCH = "private_scratch"
    READ_ONLY_INPUT = "read_only_input"
    OUTPUT_CAP = "output_cap"
    NO_SECRETS = "no_secrets"
    NETWORK_DENY = "network_deny"
    CONTAINER = "container"
    MICROVM = "microvm"
    TAINT_TRACKING = "taint_tracking"
    EGRESS_ALLOWLIST = "egress_allowlist"
    BUDGET_RECEIPT = "budget_receipt"
    REDACTION = "redaction"
    PROVIDER_RECEIPT = "provider_receipt"


class SandboxAdmissionStatus(StrEnum):
    """Sandbox admission outcomes."""

    ADMITTED_LOCAL = "ADMITTED_LOCAL"
    ADMITTED_REMOTE = "ADMITTED_REMOTE"
    WAIT_COMPUTE_NODE = "WAIT_COMPUTE_NODE"
    WAIT_AUTHORITY = "WAIT_AUTHORITY"


@dataclass(frozen=True)
class HostCapabilityManifest:
    """A host's declared sandbox capability set."""

    host_id: str
    platform_name: str
    capabilities: frozenset[IsolationCapability]
    schema_version: str = HOST_CAPABILITY_MANIFEST_SCHEMA_VERSION
    canonical_writes: int = 0
    grants_authority: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != HOST_CAPABILITY_MANIFEST_SCHEMA_VERSION:
            msg = (
                f"schema_version must be {HOST_CAPABILITY_MANIFEST_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )
            raise ValueError(msg)
        if not self.host_id:
            msg = "host_id must be non-empty"
            raise ValueError(msg)
        if not self.platform_name:
            msg = "platform_name must be non-empty"
            raise ValueError(msg)
        if self.canonical_writes != 0:
            msg = "canonical_writes must be 0"
            raise ValueError(msg)
        if self.grants_authority:
            msg = "grants_authority must be false"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible manifest."""
        return {
            "schema_version": self.schema_version,
            "host_id": self.host_id,
            "platform_name": self.platform_name,
            "capabilities": sorted(cap.value for cap in self.capabilities),
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }


@dataclass(frozen=True)
class SandboxAdmission:
    """The result of admitting one trust class against one host manifest."""

    schema_version: str
    trust_class: TrustClass
    status: SandboxAdmissionStatus
    required_capabilities: tuple[str, ...]
    observed_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    reason: str
    canonical_writes: int = 0
    grants_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible admission receipt."""
        return {
            "schema_version": self.schema_version,
            "trust_class": self.trust_class.value,
            "status": self.status.value,
            "required_capabilities": list(self.required_capabilities),
            "observed_capabilities": list(self.observed_capabilities),
            "missing_capabilities": list(self.missing_capabilities),
            "reason": self.reason,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }


_T0_REQUIRED: Final[frozenset[IsolationCapability]] = frozenset(
    {
        IsolationCapability.PROCESS_LIMITS,
        IsolationCapability.SANITIZED_ENV,
        IsolationCapability.PRIVATE_SCRATCH,
        IsolationCapability.OUTPUT_CAP,
    }
)
_T1_REQUIRED: Final[frozenset[IsolationCapability]] = _T0_REQUIRED | frozenset(
    {
        IsolationCapability.READ_ONLY_INPUT,
        IsolationCapability.NO_SECRETS,
    }
)
_T2_REQUIRED: Final[frozenset[IsolationCapability]] = _T1_REQUIRED | frozenset(
    {
        IsolationCapability.NETWORK_DENY,
        IsolationCapability.CONTAINER,
    }
)
_T3_REQUIRED: Final[frozenset[IsolationCapability]] = _T1_REQUIRED | frozenset(
    {
        IsolationCapability.NETWORK_DENY,
        IsolationCapability.MICROVM,
        IsolationCapability.TAINT_TRACKING,
    }
)
_T4_REQUIRED: Final[frozenset[IsolationCapability]] = frozenset(
    {
        IsolationCapability.NO_SECRETS,
        IsolationCapability.EGRESS_ALLOWLIST,
        IsolationCapability.BUDGET_RECEIPT,
        IsolationCapability.REDACTION,
        IsolationCapability.PROVIDER_RECEIPT,
    }
)

_REQUIRED_BY_CLASS: Final[dict[TrustClass, frozenset[IsolationCapability]]] = {
    TrustClass.T0: _T0_REQUIRED,
    TrustClass.T1: _T1_REQUIRED,
    TrustClass.T2: _T2_REQUIRED,
    TrustClass.T3: _T3_REQUIRED,
    TrustClass.T4: _T4_REQUIRED,
}


def current_host_capability_manifest(
    host_id: str = "local-operator-host",
) -> HostCapabilityManifest:
    """Return the capabilities the current Python host can prove locally.

    The local runner can prove the subprocess sandbox properties it implements:
    sanitized environment, private scratch, read-only input, output caps, no
    inherited secrets, and POSIX process limits where available. It does not
    claim network namespaces, containers, microVMs, taint tracking, egress
    allowlists, budgets, or provider receipts.
    """
    capabilities = {
        IsolationCapability.SANITIZED_ENV,
        IsolationCapability.PRIVATE_SCRATCH,
        IsolationCapability.READ_ONLY_INPUT,
        IsolationCapability.OUTPUT_CAP,
        IsolationCapability.NO_SECRETS,
    }
    if os.name == "posix":
        capabilities.add(IsolationCapability.PROCESS_LIMITS)
    return HostCapabilityManifest(
        host_id=host_id,
        platform_name=platform.platform(),
        capabilities=frozenset(capabilities),
    )


def admit_sandbox(
    trust_class: TrustClass,
    manifest: HostCapabilityManifest,
) -> SandboxAdmission:
    """Admit or park a trust class against ``manifest``."""
    required = _REQUIRED_BY_CLASS[trust_class]
    observed = manifest.capabilities
    missing = tuple(sorted((required - observed), key=lambda cap: cap.value))
    required_values = tuple(sorted(cap.value for cap in required))
    observed_values = tuple(sorted(cap.value for cap in observed))
    missing_values = tuple(cap.value for cap in missing)
    if not missing:
        status = _admitted_status_for(trust_class)
        reason = f"{trust_class.value} isolation requirements are satisfied by host manifest"
    elif trust_class is TrustClass.T4 and _authority_missing(missing):
        status = SandboxAdmissionStatus.WAIT_AUTHORITY
        reason = "remote or paid provider lane lacks budget/provider authority receipt"
    else:
        status = SandboxAdmissionStatus.WAIT_COMPUTE_NODE
        reason = (
            f"{trust_class.value} requires stronger isolation; missing {', '.join(missing_values)}"
        )
    return SandboxAdmission(
        schema_version=SANDBOX_POLICY_SCHEMA_VERSION,
        trust_class=trust_class,
        status=status,
        required_capabilities=required_values,
        observed_capabilities=observed_values,
        missing_capabilities=missing_values,
        reason=reason,
    )


def _admitted_status_for(trust_class: TrustClass) -> SandboxAdmissionStatus:
    if trust_class is TrustClass.T4:
        return SandboxAdmissionStatus.ADMITTED_REMOTE
    return SandboxAdmissionStatus.ADMITTED_LOCAL


def _authority_missing(missing: tuple[IsolationCapability, ...]) -> bool:
    return any(
        cap
        in {
            IsolationCapability.BUDGET_RECEIPT,
            IsolationCapability.PROVIDER_RECEIPT,
        }
        for cap in missing
    )


__all__ = [
    "HOST_CAPABILITY_MANIFEST_SCHEMA_VERSION",
    "SANDBOX_POLICY_SCHEMA_VERSION",
    "HostCapabilityManifest",
    "IsolationCapability",
    "SandboxAdmission",
    "SandboxAdmissionStatus",
    "TrustClass",
    "admit_sandbox",
    "current_host_capability_manifest",
]
