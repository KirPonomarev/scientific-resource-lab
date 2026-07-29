"""Hermetic tests for the WP-D34 adversarial runner suite.

Pins:

1. The 14 :class:`~srl.execution.adversarial.AdversarialKind` members are all
   represented in the fixtures and each produces its expected outcome when run
   against the REAL runner (no harness-level mocks).
2. The receipt-last oracle: a policy/limit/output-schema violation NEVER
   produces a valid run receipt (asserted per case).
3. The 50-run conformance sequence completes with zero orphan survivors and the
   receipt-last invariant intact throughout (the orphan-free floor).
4. The credential canary: a parent-only env var never reaches the child.
5. The cwd isolation: the child's working directory is the scratch dir, not the
   parent repo root.

These tests spawn real child processes under short wall caps. The test-only
adapter hook (``SRL_RUNNER_TEST_ADAPTERS=1``) is enabled for the cases that
exercise the sandbox enforcement paths (timeout, output cap, fork, network
canary, cwd probe). The full gate script
(``scripts/checks/wp34-gate.py``) is the CI authority; these unit tests give
fast, focused coverage.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from srl.execution import RunStatus, load_policy, prepare_scratch, run_adapter
from srl.execution.adversarial import (
    CONFORMANCE_FLOOR,
    AdversarialKind,
    ExpectedOutcome,
    conformance_sequence,
    credential_canary_check,
    cwd_isolation_check,
    load_cases,
    orphan_sweep,
    run_case,
)

_POLICY_PATH = Path("policies/resource-policy-m1.json")
_FIXTURES = Path("fixtures/conformance/adversarial")
_GATE = "SRL_RUNNER_TEST_ADAPTERS"


@pytest.fixture
def policy() -> Any:
    """The shipped M1 policy."""
    return load_policy(_POLICY_PATH)


@pytest.fixture(autouse=True)
def _enable_test_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the gated test-adapter hook for every test in this module."""
    monkeypatch.setenv(_GATE, "1")


# ---------------------------------------------------------------------------
# Case taxonomy + fixture loading.
# ---------------------------------------------------------------------------


def test_adversarial_kind_has_fourteen_members() -> None:
    """The taxonomy covers exactly the 14 documented red-team vectors."""
    members = {k.value for k in AdversarialKind}
    assert members == {
        "archive_traversal",
        "command_injection",
        "corrupted_input",
        "credential_canary",
        "fork_bomb",
        "memory_bomb",
        "network_canary",
        "output_bomb",
        "partial_receipt",
        "path_injection",
        "schema_invalid_output",
        "symlink_device",
        "timeout",
        "wrong_platform",
    }


def test_fixtures_load_fourteen_cases_one_per_kind() -> None:
    """The fixture dir yields 14 cases covering each kind exactly once."""
    cases = load_cases(_FIXTURES)
    assert len(cases) == 14
    kinds = [c.kind for c in cases]
    assert sorted(k.value for k in kinds) == sorted(k.value for k in AdversarialKind)
    assert len({k.value for k in kinds}) == 14  # no duplicates


# ---------------------------------------------------------------------------
# Per-case outcomes (the receipt-last oracle).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("match_kind", sorted(k.value for k in AdversarialKind))
def test_each_case_matches_expectation_and_receipt_last(policy: Any, match_kind: str) -> None:
    """Every adversarial case matches its declared expectation.

    The receipt-last oracle: for any case whose observed status is not
    'completed', no receipt was written and the scratch dir held zero
    receipt files. A violation that produced a receipt fails here.
    """
    cases = load_cases(_FIXTURES)
    case = next(c for c in cases if c.kind.value == match_kind)
    outcome = run_case(case, policy)
    assert outcome.matched, f"{case.case_id}: {outcome.detail}"
    # The receipt-last invariant: a non-completed run must write no receipt.
    if outcome.observed_status != RunStatus.COMPLETED.value:
        assert not outcome.receipt_written, f"{case.case_id} wrote a receipt on a violation"
        assert outcome.receipts_in_scratch == 0, (
            f"{case.case_id} left {outcome.receipts_in_scratch} receipt(s) in scratch"
        )


def test_rejected_cases_never_spawn(policy: Any) -> None:
    """The rejected injection cases (command/path/symlink/archive/platform) spawn nothing."""
    cases = load_cases(_FIXTURES)
    rejected = [c for c in cases if c.expected is ExpectedOutcome.REJECTED]
    assert len(rejected) == 5
    for case in rejected:
        outcome = run_case(case, policy)
        assert outcome.runner_outcome is None
        assert outcome.observed_status == "rejected"
        assert outcome.receipt_written is False


# ---------------------------------------------------------------------------
# The 50-run conformance floor (orphan-free sequence).
# ---------------------------------------------------------------------------


def test_fifty_run_conformance_sequence_is_orphan_free(policy: Any) -> None:
    """50 sequential golden+adversarial executions leave zero orphan survivors.

    This is the WP-D34 conformance floor: the receipt-last invariant holds
    across all 50 runs, and a final process-group sweep finds no survivor. The
    sweep is the setsid-evasion detector. The sequence runs in ~35-50s on a warm
    machine (well under the 120s gate ceiling); it is the longest test in the
    security suite and is always run by CI.
    """
    cases = load_cases(_FIXTURES)
    seq = conformance_sequence(cases, policy)
    assert seq.total == CONFORMANCE_FLOOR
    assert seq.receipt_last_holds
    # The golden + adversarial counts sum to the floor.
    assert seq.golden_runs + seq.adversarial_runs == CONFORMANCE_FLOOR
    assert seq.adversarial_runs > 0
    # The final orphan sweep finds no survivor.
    assert seq.orphan_survivors == []
    # An independent sweep right after also finds nothing.
    assert orphan_sweep() == []


# ---------------------------------------------------------------------------
# Credential canary + cwd isolation.
# ---------------------------------------------------------------------------


def test_credential_canary_absent_from_child(policy: Any) -> None:
    """A parent-only canary env var never reaches the child."""
    result = credential_canary_check(policy)
    assert result["passed"], result["detail"]
    assert result["canary_present_in_env_dict"] is False
    assert result["child_booted_under_sanitized_env"] is True
    assert result["child_observed_canary"] is False


def test_child_cwd_is_scratch_not_repo_root(policy: Any) -> None:
    """The child's working directory is the scratch dir, not the repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    result = cwd_isolation_check(policy, repo_root)
    assert result["passed"], result["detail"]
    assert result["child_cwd_is_repo_root"] is False


# ---------------------------------------------------------------------------
# Network canary is observational.
# ---------------------------------------------------------------------------


def test_network_canary_records_attempt(policy: Any) -> None:
    """netcanary.v1 records the connect attempt (observational, not blocking).

    The assertion is that the attempt was recorded in the child output, NOT that
    the sandbox blocked it. The target is RFC 5737 TEST-NET-1 (192.0.2.1) which
    must never be reachable.
    """
    scratch = prepare_scratch()
    try:
        outcome = run_adapter("netcanary.v1", {}, policy, scratch, wall_seconds=8)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.output is not None
    assert outcome.output.get("attempted") is True
    target = outcome.output.get("target", "")
    assert "192.0.2.1" in target, f"canary targeted an unexpected host: {target}"
    # The outcome is recorded (connected/timeout/oserror:*); we do NOT assert
    # which, because macOS CI network denial is not guaranteed.
    assert isinstance(outcome.output.get("outcome"), str)
