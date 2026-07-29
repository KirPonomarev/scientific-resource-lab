"""Native T2/T3 sandbox target evidence evaluator for V3.7 A05.

The local subprocess runner proves T0/T1 isolation. T2/T3 require a compatible
Linux target with a rootless container or microVM boundary, denied network by
default, read-only pack image, no inherited credentials, external CAS writer,
and enforced output/scratch caps. This module validates that evidence and
returns ``WAIT_COMPUTE_TARGET`` unless every required axis is present.

It does not start a container, microVM, daemon, remote executor, paid resource,
or protected target. It is the fail-closed software contract that a native
target receipt must satisfy before later stages may claim enforced T2/T3.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

NATIVE_SANDBOX_EVIDENCE_SCHEMA_VERSION: Final[str] = "NativeSandboxEvidence/v1"
NATIVE_SANDBOX_RECEIPT_SCHEMA_VERSION: Final[str] = "NativeSandboxReceipt/v1"


class NativeSandboxKind(StrEnum):
    """Native isolation implementations A05 can reason about."""

    NONE = "none"
    ROOTLESS_CONTAINER = "rootless_container"
    MICROVM = "microvm"


class NativeSandboxStatus(StrEnum):
    """Native T2/T3 target evaluation outcome."""

    ACTIVE = "ACTIVE"
    WAIT_COMPUTE_TARGET = "WAIT_COMPUTE_TARGET"


@dataclass(frozen=True)
class NativeSandboxEvidence:
    """Evidence supplied by a native Linux sandbox target probe."""

    target_id: str
    platform_name: str
    kind: NativeSandboxKind
    rootless: bool = False
    network_denied: bool = False
    read_only_pack_image: bool = False
    no_inherited_credentials: bool = False
    cas_writer_external: bool = False
    scratch_limit_enforced: bool = False
    output_limit_enforced: bool = False
    adversarial_escape_suite_passed: bool = False
    taint_tracking_verified: bool = False
    schema_version: str = NATIVE_SANDBOX_EVIDENCE_SCHEMA_VERSION
    canonical_writes: int = 0
    grants_authority: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != NATIVE_SANDBOX_EVIDENCE_SCHEMA_VERSION:
            msg = (
                f"schema_version must be {NATIVE_SANDBOX_EVIDENCE_SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )
            raise ValueError(msg)
        if not self.target_id:
            msg = "target_id must be non-empty"
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
        """Return stable JSON-compatible evidence."""
        return {
            "schema_version": self.schema_version,
            "target_id": self.target_id,
            "platform_name": self.platform_name,
            "kind": self.kind.value,
            "rootless": self.rootless,
            "network_denied": self.network_denied,
            "read_only_pack_image": self.read_only_pack_image,
            "no_inherited_credentials": self.no_inherited_credentials,
            "cas_writer_external": self.cas_writer_external,
            "scratch_limit_enforced": self.scratch_limit_enforced,
            "output_limit_enforced": self.output_limit_enforced,
            "adversarial_escape_suite_passed": self.adversarial_escape_suite_passed,
            "taint_tracking_verified": self.taint_tracking_verified,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }


@dataclass(frozen=True)
class NativeSandboxReceipt:
    """Result of evaluating native target evidence for T2 or T3."""

    trust_class: str
    status: NativeSandboxStatus
    required_requirements: tuple[str, ...]
    observed_requirements: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    reason: str
    evidence: NativeSandboxEvidence
    schema_version: str = NATIVE_SANDBOX_RECEIPT_SCHEMA_VERSION
    canonical_writes: int = 0
    grants_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible receipt."""
        return {
            "schema_version": self.schema_version,
            "trust_class": self.trust_class,
            "status": self.status.value,
            "required_requirements": list(self.required_requirements),
            "observed_requirements": list(self.observed_requirements),
            "missing_requirements": list(self.missing_requirements),
            "reason": self.reason,
            "evidence": self.evidence.to_dict(),
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }


_COMMON_REQUIREMENTS: Final[tuple[str, ...]] = (
    "linux_platform",
    "rootless",
    "network_denied",
    "read_only_pack_image",
    "no_inherited_credentials",
    "cas_writer_external",
    "scratch_limit_enforced",
    "output_limit_enforced",
    "adversarial_escape_suite_passed",
)

_T2_REQUIREMENTS: Final[tuple[str, ...]] = (*_COMMON_REQUIREMENTS, "container_or_microvm")
_T3_REQUIREMENTS: Final[tuple[str, ...]] = (
    *_COMMON_REQUIREMENTS,
    "microvm",
    "taint_tracking_verified",
)


def local_native_sandbox_evidence(target_id: str = "local-operator-host") -> NativeSandboxEvidence:
    """Return the current host's native T2/T3 evidence, fail-closed."""
    return NativeSandboxEvidence(
        target_id=target_id,
        platform_name=f"{sys.platform}:{platform.platform()}",
        kind=NativeSandboxKind.NONE,
    )


def evaluate_native_sandbox(
    evidence: NativeSandboxEvidence,
    *,
    trust_class: str,
) -> NativeSandboxReceipt:
    """Evaluate native target evidence for ``T2`` or ``T3``."""
    normalized = trust_class.upper()
    if normalized not in {"T2", "T3"}:
        msg = f"trust_class must be 'T2' or 'T3', got {trust_class!r}"
        raise ValueError(msg)
    required = _T3_REQUIREMENTS if normalized == "T3" else _T2_REQUIREMENTS
    observed = _observed_requirements(evidence)
    missing = tuple(req for req in required if req not in observed)
    if missing:
        status = NativeSandboxStatus.WAIT_COMPUTE_TARGET
        reason = f"{normalized} native sandbox missing {', '.join(missing)}"
    else:
        status = NativeSandboxStatus.ACTIVE
        reason = f"{normalized} native sandbox evidence satisfies every requirement"
    return NativeSandboxReceipt(
        trust_class=normalized,
        status=status,
        required_requirements=required,
        observed_requirements=tuple(sorted(observed)),
        missing_requirements=missing,
        reason=reason,
        evidence=evidence,
    )


def _observed_requirements(evidence: NativeSandboxEvidence) -> frozenset[str]:
    observed: set[str] = set()
    if evidence.platform_name.lower().startswith("linux"):
        observed.add("linux_platform")
    boolean_requirements = (
        ("rootless", evidence.rootless),
        ("network_denied", evidence.network_denied),
        ("read_only_pack_image", evidence.read_only_pack_image),
        ("no_inherited_credentials", evidence.no_inherited_credentials),
        ("cas_writer_external", evidence.cas_writer_external),
        ("scratch_limit_enforced", evidence.scratch_limit_enforced),
        ("output_limit_enforced", evidence.output_limit_enforced),
        ("adversarial_escape_suite_passed", evidence.adversarial_escape_suite_passed),
        ("taint_tracking_verified", evidence.taint_tracking_verified),
    )
    observed.update(name for name, present in boolean_requirements if present)
    if evidence.kind in {NativeSandboxKind.ROOTLESS_CONTAINER, NativeSandboxKind.MICROVM}:
        observed.add("container_or_microvm")
    if evidence.kind is NativeSandboxKind.MICROVM:
        observed.add("microvm")
    return frozenset(observed)


__all__ = [
    "NATIVE_SANDBOX_EVIDENCE_SCHEMA_VERSION",
    "NATIVE_SANDBOX_RECEIPT_SCHEMA_VERSION",
    "NativeSandboxEvidence",
    "NativeSandboxKind",
    "NativeSandboxReceipt",
    "NativeSandboxStatus",
    "evaluate_native_sandbox",
    "local_native_sandbox_evidence",
]
