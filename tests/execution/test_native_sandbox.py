"""Tests for the V3.7 native T2/T3 sandbox evidence evaluator."""

from __future__ import annotations

import pytest

from srl.execution.native_sandbox import (
    NativeSandboxEvidence,
    NativeSandboxKind,
    NativeSandboxStatus,
    evaluate_native_sandbox,
    local_native_sandbox_evidence,
)


def _complete_evidence(
    kind: NativeSandboxKind = NativeSandboxKind.MICROVM,
) -> NativeSandboxEvidence:
    return NativeSandboxEvidence(
        target_id="fixture-linux-target",
        platform_name="linux-x86_64",
        kind=kind,
        rootless=True,
        network_denied=True,
        read_only_pack_image=True,
        no_inherited_credentials=True,
        cas_writer_external=True,
        scratch_limit_enforced=True,
        output_limit_enforced=True,
        adversarial_escape_suite_passed=True,
        taint_tracking_verified=kind is NativeSandboxKind.MICROVM,
    )


def test_local_host_waits_for_t2_t3_native_target() -> None:
    """Current host evidence is fail-closed for T2/T3."""
    evidence = local_native_sandbox_evidence("fixture-local")
    t2 = evaluate_native_sandbox(evidence, trust_class="T2")
    t3 = evaluate_native_sandbox(evidence, trust_class="T3")

    assert t2.status is NativeSandboxStatus.WAIT_COMPUTE_TARGET
    assert t3.status is NativeSandboxStatus.WAIT_COMPUTE_TARGET
    assert "container_or_microvm" in t2.missing_requirements
    assert "microvm" in t3.missing_requirements


def test_complete_rootless_container_evidence_admits_t2_only() -> None:
    """T2 can use container evidence; T3 cannot downgrade to it."""
    evidence = _complete_evidence(NativeSandboxKind.ROOTLESS_CONTAINER)

    t2 = evaluate_native_sandbox(evidence, trust_class="T2")
    t3 = evaluate_native_sandbox(evidence, trust_class="T3")

    assert t2.status is NativeSandboxStatus.ACTIVE
    assert t3.status is NativeSandboxStatus.WAIT_COMPUTE_TARGET
    assert "microvm" in t3.missing_requirements
    assert "taint_tracking_verified" in t3.missing_requirements


def test_complete_microvm_evidence_admits_t2_and_t3() -> None:
    """Full microVM evidence satisfies both T2 and T3 requirements."""
    evidence = _complete_evidence()

    assert evaluate_native_sandbox(evidence, trust_class="T2").status is NativeSandboxStatus.ACTIVE
    assert evaluate_native_sandbox(evidence, trust_class="T3").status is NativeSandboxStatus.ACTIVE


def test_native_evidence_rejects_authority_claims() -> None:
    """A native sandbox evidence manifest never grants authority by itself."""
    with pytest.raises(ValueError, match="grants_authority"):
        NativeSandboxEvidence(
            target_id="bad",
            platform_name="linux",
            kind=NativeSandboxKind.MICROVM,
            grants_authority=True,
        )


def test_unknown_trust_class_rejected() -> None:
    """Only T2/T3 are evaluated by the native sandbox gate."""
    with pytest.raises(ValueError, match="trust_class"):
        evaluate_native_sandbox(_complete_evidence(), trust_class="T1")
