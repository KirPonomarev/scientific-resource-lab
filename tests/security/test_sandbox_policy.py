from __future__ import annotations

import pytest

from srl.security import (
    HostCapabilityManifest,
    IsolationCapability,
    SandboxAdmissionStatus,
    TrustClass,
    admit_sandbox,
    current_host_capability_manifest,
)


def _manifest(*capabilities: IsolationCapability) -> HostCapabilityManifest:
    return HostCapabilityManifest(
        host_id="fixture-host",
        platform_name="fixture",
        capabilities=frozenset(capabilities),
    )


def test_current_host_admits_t0_t1_but_not_t2_t3_without_stronger_isolation() -> None:
    manifest = current_host_capability_manifest("fixture-current")

    assert admit_sandbox(TrustClass.T0, manifest).status is SandboxAdmissionStatus.ADMITTED_LOCAL
    assert admit_sandbox(TrustClass.T1, manifest).status is SandboxAdmissionStatus.ADMITTED_LOCAL

    t2 = admit_sandbox(TrustClass.T2, manifest)
    t3 = admit_sandbox(TrustClass.T3, manifest)

    assert t2.status is SandboxAdmissionStatus.WAIT_COMPUTE_NODE
    assert "container" in t2.missing_capabilities
    assert "network_deny" in t2.missing_capabilities
    assert t3.status is SandboxAdmissionStatus.WAIT_COMPUTE_NODE
    assert "microvm" in t3.missing_capabilities
    assert "taint_tracking" in t3.missing_capabilities


def test_t2_requires_container_and_network_deny() -> None:
    base = {
        IsolationCapability.PROCESS_LIMITS,
        IsolationCapability.SANITIZED_ENV,
        IsolationCapability.PRIVATE_SCRATCH,
        IsolationCapability.READ_ONLY_INPUT,
        IsolationCapability.OUTPUT_CAP,
        IsolationCapability.NO_SECRETS,
    }
    weak = _manifest(*base)
    strong = _manifest(
        *base,
        IsolationCapability.CONTAINER,
        IsolationCapability.NETWORK_DENY,
    )

    assert admit_sandbox(TrustClass.T2, weak).status is SandboxAdmissionStatus.WAIT_COMPUTE_NODE
    assert admit_sandbox(TrustClass.T2, strong).status is SandboxAdmissionStatus.ADMITTED_LOCAL


def test_t3_does_not_downgrade_to_t2_container_isolation() -> None:
    t2_only = _manifest(
        IsolationCapability.PROCESS_LIMITS,
        IsolationCapability.SANITIZED_ENV,
        IsolationCapability.PRIVATE_SCRATCH,
        IsolationCapability.READ_ONLY_INPUT,
        IsolationCapability.OUTPUT_CAP,
        IsolationCapability.NO_SECRETS,
        IsolationCapability.CONTAINER,
        IsolationCapability.NETWORK_DENY,
    )

    decision = admit_sandbox(TrustClass.T3, t2_only)

    assert decision.status is SandboxAdmissionStatus.WAIT_COMPUTE_NODE
    assert "microvm" in decision.missing_capabilities
    assert "taint_tracking" in decision.missing_capabilities


def test_t3_admits_only_with_microvm_network_deny_and_taint_tracking() -> None:
    manifest = _manifest(
        IsolationCapability.PROCESS_LIMITS,
        IsolationCapability.SANITIZED_ENV,
        IsolationCapability.PRIVATE_SCRATCH,
        IsolationCapability.READ_ONLY_INPUT,
        IsolationCapability.OUTPUT_CAP,
        IsolationCapability.NO_SECRETS,
        IsolationCapability.MICROVM,
        IsolationCapability.NETWORK_DENY,
        IsolationCapability.TAINT_TRACKING,
    )

    assert admit_sandbox(TrustClass.T3, manifest).status is SandboxAdmissionStatus.ADMITTED_LOCAL


def test_t4_requires_budget_and_provider_authority_receipts() -> None:
    no_budget = _manifest(
        IsolationCapability.NO_SECRETS,
        IsolationCapability.EGRESS_ALLOWLIST,
        IsolationCapability.REDACTION,
    )
    full_remote = _manifest(
        IsolationCapability.NO_SECRETS,
        IsolationCapability.EGRESS_ALLOWLIST,
        IsolationCapability.BUDGET_RECEIPT,
        IsolationCapability.REDACTION,
        IsolationCapability.PROVIDER_RECEIPT,
    )

    assert admit_sandbox(TrustClass.T4, no_budget).status is SandboxAdmissionStatus.WAIT_AUTHORITY
    assert (
        admit_sandbox(TrustClass.T4, full_remote).status is SandboxAdmissionStatus.ADMITTED_REMOTE
    )


def test_admission_receipt_never_grants_authority_or_canonical_writes() -> None:
    decision = admit_sandbox(TrustClass.T2, current_host_capability_manifest())
    payload = decision.to_dict()

    assert payload["canonical_writes"] == 0
    assert payload["grants_authority"] is False
    assert payload["schema_version"] == "SandboxPolicy/v1"


def test_manifest_rejects_authority_claims() -> None:
    with pytest.raises(ValueError, match="grants_authority"):
        HostCapabilityManifest(
            host_id="bad",
            platform_name="fixture",
            capabilities=frozenset(),
            grants_authority=True,
        )
