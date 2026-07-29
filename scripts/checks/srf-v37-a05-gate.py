#!/usr/bin/env python3
"""V3.7 A05 enforced sandbox gate.

This gate proves the software side of A05 without touching a protected compute
target. It runs the existing adversarial runner suite against the real local
subprocess runner, verifies direct credential canary absence inside a child,
checks output and scratch limit enforcement, and proves T2/T3 native isolation
remains fail-closed at ``WAIT_COMPUTE_TARGET`` until a compatible Linux
container/microVM target supplies native evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Test-only adapters are fixed in-repo code and are required for the adversarial
# suite. Production runs without this env var see only the shipped registry.
os.environ["SRL_RUNNER_TEST_ADAPTERS"] = "1"

from srl.contracts import dumps, object_id  # noqa: E402
from srl.execution import (  # noqa: E402
    RESOURCE_LIMIT_FAIL_REASON,
    RunStatus,
    evaluate_native_sandbox,
    load_policy,
    local_native_sandbox_evidence,
    prepare_scratch,
    run_adapter,
)
from srl.execution.adversarial import (  # noqa: E402
    CONFORMANCE_FLOOR,
    credential_canary_check,
    cwd_isolation_check,
    load_cases,
    orphan_sweep,
    run_case,
)
from srl.security import (  # noqa: E402
    SandboxAdmissionStatus,
    TrustClass,
    admit_sandbox,
    current_host_capability_manifest,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A05"
POLICY_PATH: Final[Path] = REPO_ROOT / "policies" / "resource-policy-m1.json"
FIXTURES: Final[Path] = REPO_ROOT / "fixtures" / "conformance" / "adversarial"
OPERATOR_ACTION: Final[Path] = (
    REPO_ROOT / "docs" / "target-binding" / "native-sandbox-compute-operator-action.json"
)
EXPECTED_ADVERSARIAL_KINDS: Final[int] = 14


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt_count(path: Path) -> int:
    return len(list(path.glob("receipt-*.json"))) if path.exists() else 0


def _check_adversarial_escape_suite() -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    cases = load_cases(FIXTURES)
    outcomes = [run_case(case, policy) for case in cases]
    survivors = orphan_sweep()

    failures: list[str] = []
    if len(cases) != EXPECTED_ADVERSARIAL_KINDS:
        failures.append(f"expected {EXPECTED_ADVERSARIAL_KINDS} cases, saw {len(cases)}")
    unmatched = [outcome.to_dict() for outcome in outcomes if not outcome.matched]
    if unmatched:
        failures.append(f"{len(unmatched)} adversarial case(s) did not match expectation")
    receipt_violations = [
        outcome.to_dict()
        for outcome in outcomes
        if outcome.observed_status != "completed"
        and (outcome.receipt_written or outcome.receipts_in_scratch != 0)
    ]
    if receipt_violations:
        failures.append(f"{len(receipt_violations)} violation case(s) wrote receipts")
    if survivors:
        failures.append(f"orphan sweep found survivor(s): {survivors[:8]}")
    return {
        "check_id": "A05-01-adversarial-escape-suite",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "14 adversarial cases matched expectations with receipt-last and zero orphans",
        "case_count": len(cases),
        "unmatched": unmatched,
        "receipt_violations": receipt_violations,
        "orphan_survivors": survivors,
    }


def _check_secret_canary_and_cwd() -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    canary = credential_canary_check(policy)
    cwd = cwd_isolation_check(policy, REPO_ROOT)
    failures: list[str] = []
    if not canary["passed"]:
        failures.append(str(canary["detail"]))
    if canary.get("child_observed_canary") is not False:
        failures.append("child envprobe observed the parent-only credential canary")
    if not cwd["passed"]:
        failures.append(str(cwd["detail"]))
    return {
        "check_id": "A05-02-secret-canary-and-cwd",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "parent credential canary is absent inside child and cwd is private scratch",
        "credential_canary": canary,
        "cwd_check": {
            "child_booted": cwd["child_booted"],
            "child_cwd_is_repo_root": cwd["child_cwd_is_repo_root"],
            "expected_cwd_is_scratch": cwd["expected_cwd_is_scratch"],
            "passed": cwd["passed"],
        },
    }


def _check_output_and_scratch_limits() -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    failures: list[str] = []

    output_scratch = prepare_scratch()
    try:
        output_outcome = run_adapter(
            "chatter.v1",
            {"bytes": 2 * 1024 * 1024},
            policy,
            output_scratch,
            wall_seconds=10,
            output_cap_bytes=64 * 1024,
        )
        output_receipts = _receipt_count(output_scratch)
    finally:
        shutil.rmtree(output_scratch, ignore_errors=True)

    scratch = prepare_scratch()
    try:
        scratch_outcome = run_adapter(
            "scratchfiller.v1",
            {"bytes": 256 * 1024},
            policy,
            scratch,
            wall_seconds=10,
            output_cap_bytes=1024 * 1024,
            scratch_cap_bytes=64 * 1024,
        )
        scratch_receipts = _receipt_count(scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if output_outcome.status is not RunStatus.RESOURCE_LIMIT:
        failures.append(f"output bomb yielded {output_outcome.status.value}")
    if output_outcome.fail_reason != RESOURCE_LIMIT_FAIL_REASON or output_receipts != 0:
        failures.append("output bomb produced wrong fail_reason or receipt")
    if scratch_outcome.status is not RunStatus.RESOURCE_LIMIT:
        failures.append(f"scratch flood yielded {scratch_outcome.status.value}")
    if scratch_outcome.fail_reason != RESOURCE_LIMIT_FAIL_REASON or scratch_receipts != 0:
        failures.append("scratch flood produced wrong fail_reason or receipt")
    return {
        "check_id": "A05-03-output-and-scratch-limits",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "output cap and aggregate scratch cap both enforce RESOURCE_LIMIT with no receipt",
        "output_status": output_outcome.status.value,
        "output_fail_reason": output_outcome.fail_reason,
        "output_receipts": output_receipts,
        "scratch_status": scratch_outcome.status.value,
        "scratch_fail_reason": scratch_outcome.fail_reason,
        "scratch_receipts": scratch_receipts,
    }


def _check_t2_t3_fail_closed() -> dict[str, Any]:
    host_manifest = current_host_capability_manifest("a05-local-host")
    policy_t2 = admit_sandbox(TrustClass.T2, host_manifest)
    policy_t3 = admit_sandbox(TrustClass.T3, host_manifest)
    native_evidence = local_native_sandbox_evidence("a05-local-host")
    native_t2 = evaluate_native_sandbox(native_evidence, trust_class="T2")
    native_t3 = evaluate_native_sandbox(native_evidence, trust_class="T3")

    failures: list[str] = []
    for label, policy_receipt in (("policy_t2", policy_t2), ("policy_t3", policy_t3)):
        if policy_receipt.status is not SandboxAdmissionStatus.WAIT_COMPUTE_NODE:
            failures.append(f"{label} did not return WAIT_COMPUTE_NODE")
    for label, native_receipt in (("native_t2", native_t2), ("native_t3", native_t3)):
        if native_receipt.status.value != "WAIT_COMPUTE_TARGET":
            failures.append(f"{label} did not return WAIT_COMPUTE_TARGET")
    return {
        "check_id": "A05-04-t2-t3-fail-closed",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "local host cannot claim T2/T3; native evaluator returns WAIT_COMPUTE_TARGET",
        "host_manifest": host_manifest.to_dict(),
        "policy_t2": policy_t2.to_dict(),
        "policy_t3": policy_t3.to_dict(),
        "native_t2": native_t2.to_dict(),
        "native_t3": native_t3.to_dict(),
    }


def _check_operator_action() -> dict[str, Any]:
    failures: list[str] = []
    try:
        action = json.loads(OPERATOR_ACTION.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "check_id": "A05-05-native-target-operator-action",
            "status": "FAIL",
            "detail": f"operator action unreadable: {exc}",
        }
    action_hash = _file_sha256(OPERATOR_ACTION)
    if action.get("action_id") != "A05_BIND_NATIVE_SANDBOX_COMPUTE_TARGET":
        failures.append("operator action id drifted")
    if action.get("authority_required") is not True:
        failures.append("operator action must require authority")
    if action.get("grants_authority") is not False:
        failures.append("operator action must not grant authority")
    if action.get("expected_receipt_schema") != "NativeSandboxReceipt/v1":
        failures.append("operator action expected receipt schema drifted")
    return {
        "check_id": "A05-05-native-target-operator-action",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "native sandbox target action is exact and non-authorizing",
        "operator_action_hash": action_hash,
    }


def _check_conformance_floor() -> dict[str, Any]:
    policy = load_policy(POLICY_PATH)
    cases = load_cases(FIXTURES)
    from srl.execution.adversarial import conformance_sequence  # noqa: PLC0415

    seq = conformance_sequence(cases, policy)
    failures: list[str] = []
    if seq.total != CONFORMANCE_FLOOR:
        failures.append(f"sequence total {seq.total} != {CONFORMANCE_FLOOR}")
    if not seq.receipt_last_holds:
        failures.append("receipt-last did not hold through conformance sequence")
    if seq.orphan_survivors:
        failures.append(f"sequence orphan survivors: {seq.orphan_survivors[:8]}")
    return {
        "check_id": "A05-06-fifty-run-conformance-floor",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else f"{CONFORMANCE_FLOOR} sequential runs completed with receipt-last and zero orphans",
        "sequence": _stable_sequence(seq.to_dict()),
    }


def _stable_sequence(sequence: dict[str, Any]) -> dict[str, Any]:
    """Return sequence evidence without dynamic elapsed time."""
    stable = dict(sequence)
    stable.pop("elapsed_seconds", None)
    return stable


def build_gate_receipt() -> dict[str, Any]:
    checks = (
        _check_adversarial_escape_suite(),
        _check_secret_canary_and_cwd(),
        _check_output_and_scratch_limits(),
        _check_t2_t3_fail_closed(),
        _check_operator_action(),
        _check_conformance_floor(),
    )
    failures = [check for check in checks if check["status"] != "PASS"]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "status": "FAIL" if failures else "PASS",
        "terminal_state": "A05_ACCEPTED_WAIT_NATIVE_T2_T3_TARGET"
        if not failures
        else "A05_BLOCKED",
        "stage_closure": "SOFTWARE_T0_T1_ENFORCED_T2_T3_WAIT_COMPUTE_TARGET"
        if not failures
        else "BLOCKED",
        "checks": list(checks),
        "protected_compute_binding": "WAIT_COMPUTE_TARGET:A05_BIND_NATIVE_SANDBOX_COMPUTE_TARGET",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    payload["receipt_id"] = object_id(payload)
    return payload


def main() -> int:
    receipt = build_gate_receipt()
    sys.stdout.write(dumps(receipt).decode("utf-8") + "\n")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
