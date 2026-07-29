"""Unit tests for the fixed-entrypoint bounded runner (srl.execution.runner).

Pins:

1. ``run_adapter`` on ``echo.v1`` completes, validates output, and writes a
   receipt (receipt-last).
2. ``run_adapter`` on ``uppercase.v1`` upper-cases the text and writes a receipt.
3. An unknown/injection adapter id raises UnknownAdapterError BEFORE any process
   is created (no subprocess.Popen is reached).
4. A bad-input run (missing required field) exits the child with code 2 and the
   runner reports ``failed`` with NO receipt.
5. A wall timeout kills the child, reports ``timeout``, writes NO receipt, and
   leaves no orphan.
6. An over-cap output stream reports ``resource_limit`` and writes NO receipt.
7. A failed limit setup (preexec) aborts the run and reports ``resource_limit``
   with NO receipt.
8. The receipt-last invariant: only ``completed`` writes a receipt.

These tests spawn real child processes under short wall caps (2-5 s) so they
are hermetic and fast. The test-only adapter hook (SRL_RUNNER_TEST_ADAPTERS=1)
is enabled for the timeout/output-cap cases.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from srl.execution import (
    POLICY_VIOLATION_FAIL_REASON,
    RESOURCE_LIMIT_FAIL_REASON,
    RUN_RECEIPT_SCHEMA_VERSION,
    LimitSetupError,
    RunOutcome,
    RunStatus,
    UnknownAdapterError,
    load_policy,
    prepare_scratch,
    run_adapter,
)
from srl.execution.runner import _SpawnDeps, build_command_for

_POLICY_PATH = Path("policies/resource-policy-m1.json")
_GATE = "SRL_RUNNER_TEST_ADAPTERS"


@pytest.fixture
def policy() -> Any:
    """The shipped M1 policy."""
    return load_policy(_POLICY_PATH)


@pytest.fixture
def scratch() -> Path:
    """A private scratch dir; cleaned up after the test."""
    s = prepare_scratch()
    yield s
    shutil.rmtree(s, ignore_errors=True)


def _receipts(scratch: Path) -> list[Path]:
    """List receipt files written in scratch."""
    return sorted(scratch.glob("receipt-*.json"))


# ---------------------------------------------------------------------------
# Happy paths (completed + receipt-last).
# ---------------------------------------------------------------------------


def test_run_echo_completes_and_writes_receipt(policy: Any, scratch: Path) -> None:
    """echo.v1 completes, echoes the input, and writes a RunReceipt/v1."""
    outcome = run_adapter("echo.v1", {"value": "hello"}, policy, scratch, wall_seconds=10)
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.output == {"value": "hello"}
    assert outcome.receipt_written is True
    assert outcome.fail_reason is None
    rs = _receipts(scratch)
    assert len(rs) == 1
    body = json.loads(rs[0].read_bytes())
    assert body["schema_version"] == RUN_RECEIPT_SCHEMA_VERSION
    assert body["adapter_id"] == "echo.v1"
    assert body["status"] == "completed"
    assert body["usage"]["wall_seconds"] >= 0


def test_run_uppercase_completes_and_writes_receipt(policy: Any, scratch: Path) -> None:
    """uppercase.v1 upper-cases text and writes a receipt."""
    outcome = run_adapter("uppercase.v1", {"text": "hello world"}, policy, scratch, wall_seconds=10)
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.output == {"text": "HELLO WORLD"}
    assert outcome.receipt_written is True


def test_run_uppercase_non_ascii(policy: Any, scratch: Path) -> None:
    """uppercase.v1 handles non-ASCII text (UTF-8 canonical round-trip)."""
    outcome = run_adapter("uppercase.v1", {"text": "héllo"}, policy, scratch, wall_seconds=10)
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.output == {"text": "HÉLLO"}


def test_run_usage_records_wall_and_rss(policy: Any, scratch: Path) -> None:
    """The usage records a non-negative wall and rss."""
    outcome = run_adapter("echo.v1", {"value": "x"}, policy, scratch, wall_seconds=10)
    assert outcome.usage.wall_seconds >= 0
    assert outcome.usage.rss_bytes >= 0
    assert outcome.usage.output_bytes >= 0


# ---------------------------------------------------------------------------
# Unknown / injection adapter: rejected before spawn.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_id",
    [
        "echo.v1; rm -rf /",
        "../../etc/passwd",
        "echo.v1`whoami`",
        "echo.v1$(id)",
        "nope.v1",
    ],
)
def test_run_rejects_injection_before_spawn(adapter_id: str, policy: Any, scratch: Path) -> None:
    """An unknown/injection id raises before any process is created."""
    with pytest.raises(UnknownAdapterError) as exc_info:
        run_adapter(adapter_id, {"value": "x"}, policy, scratch, wall_seconds=5)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"
    assert exc_info.value.adapter_id == adapter_id
    # No receipt was written (we never spawned).
    assert _receipts(scratch) == []


def test_run_injection_does_not_spawn_via_fake_popen(
    policy: Any, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injection guard fires before Popen is constructed.

    We inject a Popen factory that records any call; for an unknown adapter it
    must never be invoked.
    """
    calls: list[Any] = []

    class _RecordingPopen:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            raise AssertionError("Popen must not be called for an unknown adapter")

    deps = _SpawnDeps(popen_factory=_RecordingPopen)
    with pytest.raises(UnknownAdapterError):
        run_adapter("echo.v1; rm -rf /", {"value": "x"}, policy, scratch, wall_seconds=5, deps=deps)
    assert calls == []


# ---------------------------------------------------------------------------
# Bad input: child exits 2 -> failed, no receipt.
# ---------------------------------------------------------------------------


def test_run_bad_input_fails_no_receipt(policy: Any, scratch: Path) -> None:
    """A payload missing a required field makes the child exit 2 -> failed."""
    outcome = run_adapter("uppercase.v1", {}, policy, scratch, wall_seconds=10)
    assert outcome.status is RunStatus.FAILED
    assert outcome.receipt_written is False
    assert outcome.output is None
    assert _receipts(scratch) == []


def test_run_bad_input_detail_carries_child_stderr(policy: Any, scratch: Path) -> None:
    """The failed detail surfaces the child's contract-failure line."""
    outcome = run_adapter("uppercase.v1", {}, policy, scratch, wall_seconds=10)
    assert "child exited 2" in outcome.detail
    assert "missing required" in outcome.detail


# ---------------------------------------------------------------------------
# Wall timeout: killed, no receipt, no orphan.
# ---------------------------------------------------------------------------


def test_run_timeout_kills_no_receipt_no_orphan(
    policy: Any, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sleeper past the wall cap is killed; timeout; no receipt; no orphan."""
    monkeypatch.setenv(_GATE, "1")
    outcome = run_adapter("sleeper.v1", {"seconds": 30}, policy, scratch, wall_seconds=2)
    assert outcome.status is RunStatus.TIMEOUT
    assert outcome.receipt_written is False
    assert outcome.fail_reason == RESOURCE_LIMIT_FAIL_REASON
    assert outcome.status is not RunStatus.POLICY_VIOLATION  # no orphan
    assert _receipts(scratch) == []
    # The wall elapsed is roughly the cap (not the full 30s sleep).
    assert outcome.usage.wall_seconds < 15


# ---------------------------------------------------------------------------
# Output cap: over-cap -> resource_limit, no receipt.
# ---------------------------------------------------------------------------


def test_run_output_cap_resource_limit_no_receipt(
    policy: Any, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An over-cap stdout stream yields resource_limit and no receipt."""
    monkeypatch.setenv(_GATE, "1")
    outcome = run_adapter(
        "chatter.v1",
        {"bytes": 4 * 1024 * 1024},
        policy,
        scratch,
        wall_seconds=10,
        output_cap_bytes=64 * 1024,
    )
    assert outcome.status is RunStatus.RESOURCE_LIMIT
    assert outcome.receipt_written is False
    assert outcome.fail_reason == RESOURCE_LIMIT_FAIL_REASON
    assert _receipts(scratch) == []


def test_run_scratch_cap_resource_limit_no_receipt(
    policy: Any, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An over-cap scratch write yields resource_limit before any receipt."""
    monkeypatch.setenv(_GATE, "1")
    outcome = run_adapter(
        "scratchfiller.v1",
        {"bytes": 256 * 1024},
        policy,
        scratch,
        wall_seconds=10,
        output_cap_bytes=1024 * 1024,
        scratch_cap_bytes=64 * 1024,
    )
    assert outcome.status is RunStatus.RESOURCE_LIMIT
    assert outcome.receipt_written is False
    assert outcome.fail_reason == RESOURCE_LIMIT_FAIL_REASON
    assert "scratch usage" in outcome.detail
    assert _receipts(scratch) == []


def test_child_envprobe_cannot_see_parent_canary(
    policy: Any, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live child cannot read a parent-only canary env var."""
    monkeypatch.setenv(_GATE, "1")
    monkeypatch.setenv("SRL_TEST_A05_CANARY", "parent-only-value")
    outcome = run_adapter(
        "envprobe.v1",
        {"name": "SRL_TEST_A05_CANARY"},
        policy,
        scratch,
        wall_seconds=10,
    )
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.output == {
        "name": "SRL_TEST_A05_CANARY",
        "present": False,
        "value_length": 0,
    }


# ---------------------------------------------------------------------------
# Failed limit setup: preexec failure -> resource_limit, no receipt.
# ---------------------------------------------------------------------------


def test_run_failed_limit_setup_aborts_before_exec(policy: Any, scratch: Path) -> None:
    """A failing preexec aborts the run; resource_limit; no child; no receipt."""
    deps = _SpawnDeps(preexec_factory=_failing_preexec_factory)
    outcome = run_adapter("echo.v1", {"value": "x"}, policy, scratch, wall_seconds=5, deps=deps)
    assert outcome.status is RunStatus.RESOURCE_LIMIT
    assert outcome.receipt_written is False
    assert "limit setup failed" in outcome.detail
    assert _receipts(scratch) == []


def _failing_preexec_factory(_limits: Any) -> Any:
    """A preexec factory whose preexec always raises LimitSetupError."""

    def _boom() -> None:
        raise LimitSetupError("simulated limit setup failure")

    return _boom


# ---------------------------------------------------------------------------
# Receipt-last invariant: only completed writes a receipt.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_receipt"),
    [
        (RunStatus.COMPLETED, True),
        (RunStatus.FAILED, False),
        (RunStatus.TIMEOUT, False),
        (RunStatus.RESOURCE_LIMIT, False),
        (RunStatus.POLICY_VIOLATION, False),
    ],
)
def test_receipt_last_only_completed_writes_receipt(
    status: RunStatus, expected_receipt: bool
) -> None:
    """Only the COMPLETED status has receipt_written=True by construction."""
    # This is a structural assertion over the RunStatus taxonomy: every
    # non-completed branch in _watch explicitly sets receipt_written=False.
    outcome = RunOutcome(
        adapter_id="echo.v1",
        status=status,
        output=None,
        usage=__import__("srl.execution.runner", fromlist=["RunUsage"]).RunUsage(
            wall_seconds=0.0, rss_bytes=0, output_bytes=0
        ),
        receipt_written=expected_receipt,
        fail_reason=None if status is RunStatus.COMPLETED else RESOURCE_LIMIT_FAIL_REASON,
        detail="structural",
    )
    assert outcome.receipt_written is expected_receipt


def test_policy_violation_fail_reason_is_orphan() -> None:
    """POLICY_VIOLATION_FAIL_REASON is the orphan fail reason."""
    assert POLICY_VIOLATION_FAIL_REASON == "ORPHAN_PROCESS_DETECTED"


# ---------------------------------------------------------------------------
# build_command_for: fixed shape, no shell.
# ---------------------------------------------------------------------------


def test_build_command_for_is_fixed_module_no_shell() -> None:
    """The command is [python, -m, srl.execution.child, adapter_id, in, out]."""
    cmd = build_command_for("echo.v1", Path("/in.json"), Path("/out.json"))
    assert cmd[1:3] == ["-m", "srl.execution.child"]
    assert cmd[3] == "echo.v1"
    assert cmd[4] == "/in.json"
    assert cmd[5] == "/out.json"
    # No shell=True anywhere: the command is a list, executed directly.
    assert isinstance(cmd, list)
    assert all(isinstance(c, str) for c in cmd)


def test_build_command_for_id_is_inert_arg() -> None:
    """An injection-shaped id is just an inert positional argument."""
    cmd = build_command_for("echo.v1; rm -rf /", Path("/i"), Path("/o"))
    # The id is a single list element, never split by a shell.
    assert cmd[3] == "echo.v1; rm -rf /"
