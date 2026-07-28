"""Unit tests for the subprocess sandbox primitives (srl.execution.sandbox).

Pins:

1. ``build_child_env`` never inherits the parent environ: a parent-only canary
   is absent from the built dict.
2. ``prepare_scratch`` creates a 0o700 directory under tempfile.mkdtemp.
3. The mandatory resource limits (CPU, FSIZE, NOFILE, NPROC) are applied by the
   preexec; a failing ``setrlimit`` for a mandatory limit raises
   ``LimitSetupError`` before exec.
4. ``RLIMIT_AS`` is best-effort (does not raise on platforms that refuse it).
5. Output capture caps each stream; an over-cap stream sets ``truncated``.
6. ``verify_no_orphan`` does not raise for a clean, reaped process.
"""

from __future__ import annotations

import resource
import stat
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from srl.execution.sandbox import (
    DEFAULT_OUTPUT_CAP_BYTES,
    RESOURCE_LIMIT_FAIL_REASON,
    CapturedOutput,
    LimitSetupError,
    ResourceLimits,
    _apply_limits_preexec,
    _CappedReader,
    build_child_env,
    make_preexec,
    prepare_scratch,
    verify_no_orphan,
)

_CANARY = "SRL_TEST_CANARY_UNITTEST"


# ---------------------------------------------------------------------------
# build_child_env: no parent-environ inheritance.
# ---------------------------------------------------------------------------


def test_build_child_env_excludes_canary(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parent-only env var never appears in the built child env dict."""
    monkeypatch.setenv(_CANARY, "secret")
    env = build_child_env(home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp")
    assert _CANARY not in env
    # The fixed five keys are always present.
    for key in ("PATH", "HOME", "TMPDIR", "LANG", "PYTHONHASHSEED"):
        assert key in env
    assert env["LANG"] == "C.UTF-8"
    assert env["PYTHONHASHSEED"] == "0"


def test_build_child_env_does_not_copy_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Many parent-only vars are all excluded."""
    for i in range(8):
        monkeypatch.setenv(f"SRL_PARENT_ONLY_{i}", str(i))
    env = build_child_env(home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp")
    for i in range(8):
        assert f"SRL_PARENT_ONLY_{i}" not in env


def test_build_child_env_pythonpath_optional() -> None:
    """PYTHONPATH is included only when provided."""
    env_none = build_child_env(home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp")
    assert "PYTHONPATH" not in env_none
    env_pp = build_child_env(
        home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp", pythonpath="/opt/src"
    )
    assert env_pp["PYTHONPATH"] == "/opt/src"


def test_build_child_env_home_and_tmpdir_point_at_args() -> None:
    """HOME and TMPDIR are set to the provided sandbox-local paths."""
    env = build_child_env(home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp")
    assert env["HOME"] == "/srv/srl/home"
    assert env["TMPDIR"] == "/srv/srl/tmp"


def test_build_child_env_forwards_test_gate_only_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The test-gate env var is forwarded only when set to '1' and requested."""
    monkeypatch.setenv("SRL_RUNNER_TEST_ADAPTERS", "1")
    env = build_child_env(home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp", forward_test_gate=True)
    assert env.get("SRL_RUNNER_TEST_ADAPTERS") == "1"
    # Without the parent var set, nothing is forwarded.
    monkeypatch.delenv("SRL_RUNNER_TEST_ADAPTERS", raising=False)
    env2 = build_child_env(home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp", forward_test_gate=True)
    assert "SRL_RUNNER_TEST_ADAPTERS" not in env2


# ---------------------------------------------------------------------------
# prepare_scratch: 0o700 dir under mkdtemp.
# ---------------------------------------------------------------------------


def test_prepare_scratch_creates_0700_dir(tmp_path: Path) -> None:
    """prepare_scratch creates a directory with mode 0o700."""
    scratch = prepare_scratch(parent=tmp_path)
    assert scratch.is_dir()
    mode = stat.S_IMODE(scratch.stat().st_mode)
    assert mode == 0o700


def test_prepare_scratch_under_parent(tmp_path: Path) -> None:
    """The scratch dir is created under the given parent."""
    scratch = prepare_scratch(parent=tmp_path)
    assert scratch.parent == tmp_path
    scratch.rmdir()


# ---------------------------------------------------------------------------
# Resource limits: mandatory caps raise on failure; AS is best-effort.
# ---------------------------------------------------------------------------


def test_apply_limits_mandatory_failure_raises() -> None:
    """A failing setrlimit for a mandatory limit raises LimitSetupError."""
    original = resource.setrlimit

    def _failing(_which: int, _limits: tuple[int, int]) -> None:
        raise OSError("simulated kernel refusal")

    with patch("srl.execution.sandbox.resource.setrlimit", _failing):
        with pytest.raises(LimitSetupError) as exc_info:
            _apply_limits_preexec(ResourceLimits(rss_bytes=1024, cpu_seconds=1))
    assert exc_info.value.fail_reason == RESOURCE_LIMIT_FAIL_REASON
    # The original is restored by the context manager exit; sanity check.
    assert resource.setrlimit is original


def test_apply_limits_as_best_effort_no_raise() -> None:
    """RLIMIT_AS failure (hard_required=False) does not raise.

    On macOS arm64 the kernel refuses to lower the AS hard limit; the applier
    treats that as best-effort and the other limits still apply. We simulate
    every setrlimit (so no real limits touch the test process) and make only
    the AS call fail.
    """
    call_log: list[int] = []

    def _fake_setrlimit(which: int, limits: tuple[int, int]) -> None:
        call_log.append(which)
        if which == resource.RLIMIT_AS:
            raise ValueError("current limit exceeds maximum limit")
        # All other limits "succeed" without touching the real test process.

    limits = ResourceLimits(rss_bytes=1024 * 1024 * 256, cpu_seconds=2)
    with patch("srl.execution.sandbox.resource.setrlimit", _fake_setrlimit):
        _apply_limits_preexec(limits)  # must not raise
    # AS was attempted (best-effort) and the mandatory limits were too.
    assert resource.RLIMIT_AS in call_log
    assert resource.RLIMIT_CPU in call_log
    assert resource.RLIMIT_FSIZE in call_log


def test_make_preexec_returns_callable() -> None:
    """make_preexec returns a no-arg callable suitable for preexec_fn."""
    preexec = make_preexec(ResourceLimits(rss_bytes=1024 * 1024 * 64, cpu_seconds=5))
    assert callable(preexec)
    # We do NOT invoke preexec() here: it is meant to run in the forked child
    # (via subprocess preexec_fn), not in the test process. Calling it in the
    # current process would lower this process's rlimits and break the suite.
    # The end-to-end invocation is covered by the runner tests (real children).


# ---------------------------------------------------------------------------
# Output capture: capped reader.
# ---------------------------------------------------------------------------


def test_capped_reader_under_cap() -> None:
    """A stream under the cap is read fully; not truncated."""
    stream = BytesIO(b"hello world")
    reader = _CappedReader(stream, cap_bytes=1024)
    reader.run()
    assert reader.bytes == b"hello world"
    assert reader.truncated is False


def test_capped_reader_over_cap_truncates() -> None:
    """A stream over the cap is truncated at the cap and flagged."""
    data = b"x" * 4096
    stream = BytesIO(data)
    reader = _CappedReader(stream, cap_bytes=100)
    reader.run()
    assert len(reader.bytes) == 100
    assert reader.truncated is True


def test_captured_output_dataclass() -> None:
    """CapturedOutput holds stdout/stderr/truncated."""
    cap = CapturedOutput(stdout=b"out", stderr=b"err", truncated=False)
    assert cap.stdout == b"out"
    assert cap.stderr == b"err"
    assert cap.truncated is False


def test_default_output_cap_is_one_mib() -> None:
    """The default per-stream output cap is 1 MiB."""
    assert DEFAULT_OUTPUT_CAP_BYTES == 1024 * 1024


# ---------------------------------------------------------------------------
# verify_no_orphan: clean process does not raise.
# ---------------------------------------------------------------------------


class _FakeProc:
    """A minimal subprocess.Popen stand-in for orphan-check tests."""

    def __init__(self, pid: int, returncode: int | None = 0) -> None:
        self.pid = pid
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


def test_verify_no_orphan_clean_process(tmp_path: Path) -> None:
    """A clean, reaped process (no surviving group members) does not raise."""
    # Spawn a trivial child that exits immediately, then check its (now empty)
    # process group. This is the realistic clean case.
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    proc.wait()
    # After wait, the group should have no live members.
    verify_no_orphan(proc)
