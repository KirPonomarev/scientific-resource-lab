"""Subprocess sandbox primitives for the bounded runner (WP-D31).

The runner executes adapters in a child process so a runaway handler cannot
take down the orchestrator. This module assembles the *cage* around that child:

- a **sanitized environment** built from scratch (the parent ``environ`` is
  never inherited — only a fixed minimal ``PATH`` / ``HOME`` / ``TMPDIR`` /
  ``LANG`` / ``PYTHONHASHSEED`` are passed);
- a **private scratch directory** under a fresh ``tempfile.mkdtemp`` with mode
  ``0o700``;
- **POSIX resource limits** applied via ``preexec_fn`` (``RLIMIT_AS`` from the
  policy ``rss_bytes``, ``RLIMIT_CPU``, ``RLIMIT_NPROC`` bounded at 256,
  ``RLIMIT_FSIZE`` from the output cap, ``RLIMIT_NOFILE`` 256) — a failed limit
  setup aborts the run *before* exec;
- a **process group** (``start_new_session=True``) with a watchdog that
  ``terminate``\\ s -> grace -> ``kill``\\ s the whole group, then verifies no
  orphan survives;
- **output capture** with byte caps (default 1 MiB per stream) — an over-cap
  stream is treated as a resource limit and the child is killed.

Portability note
----------------
On macOS arm64 ``RLIMIT_AS`` cannot be lowered below the current hard limit
(the kernel rejects it with ``current limit exceeds maximum limit``). This
module applies ``RLIMIT_AS`` *best-effort*: if the platform refuses to lower
it, the other limits (``CPU``, ``FSIZE``, ``NOFILE``, ``NPROC``) are still
applied and the wall timeout plus the output cap act as the memory backstop.
Full address-space enforcement is realised on Linux (CI). The sandbox is
therefore conservative everywhere and strict on Linux.

This module is standard library only (``subprocess``, ``resource``, ``os``,
``signal``, ``tempfile``), mirroring the rest of :mod:`srl.execution`.
"""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# The typed fail reasons surfaced by the sandbox. ``RESOURCE_LIMIT`` for a hard
# resource cap (memory/cpu/files/time) and ``ORPHAN_PROCESS_DETECTED`` for a
# survivor after the watchdog kills the group. Both mirror
# automation/fail-reasons.json (class ``ci``).
RESOURCE_LIMIT_FAIL_REASON: Final[str] = "RESOURCE_LIMIT"
ORPHAN_FAIL_REASON: Final[str] = "ORPHAN_PROCESS_DETECTED"

# The fixed, minimal environment keys passed to the child. The parent environ
# is never inherited: only these keys are set, and their values are fixed or
# sandbox-local (HOME/TMPDIR point at the scratch temp tree). The child thus
# never sees a parent-only secret.
_PATH_DEFAULT: Final[str] = "/usr/local/bin:/usr/bin:/bin"
_LANG: Final[str] = "C.UTF-8"
_PYTHONHASHSEED: Final[str] = "0"

# Bounded resource caps independent of the policy. NOFILE and NPROC are fixed
# small ceilings so a child cannot exhaust file descriptors or fork a fan-out.
# FSIZE is derived from the output cap (see ResourceLimits).
_NOFILE_LIMIT: Final[int] = 256
_NPROC_LIMIT: Final[int] = 256

# Output byte caps. Each of stdout/stderr is capped independently; the default
# (1 MiB each) keeps a runaway logger from filling memory/disk.
_MIB: Final[int] = 1024 * 1024
DEFAULT_OUTPUT_CAP_BYTES: Final[int] = _MIB

# Watchdog grace period: after SIGTERM the child has this many seconds to exit
# before it receives SIGKILL.
_GRACE_SECONDS: Final[float] = 5.0

# The exit code the child uses to signal a contract/handler failure (input
# validation, unknown adapter, handler exception). Distinct from 1 (generic
# error) and 0 (success) so the runner can classify the outcome.
_CHILD_EXIT_CONTRACT: Final[int] = 2

# The env-var gate for the test-only adapter hook. Forwarded to the child only
# when the caller opts in (see build_child_env forward_test_gate). Production
# runs never set it.
_TEST_GATE_ENV: Final[str] = "SRL_RUNNER_TEST_ADAPTERS"


class SandboxError(ValueError):
    """Base class for sandbox failures. Carries a typed ``fail_reason``.

    A :class:`ValueError` (not :class:`Exception`) so a caller handling the
    failure via ``except ValueError`` still catches the sandbox family,
    mirroring :class:`srl.execution.policy.PolicyError`.
    """

    def __init__(self, message: str, *, fail_reason: str) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


class LimitSetupError(SandboxError):
    """Raised when a POSIX resource limit cannot be applied before exec.

    ``fail_reason`` is ``RESOURCE_LIMIT``. A failed limit setup aborts the run
    *before* the child execs, so a misconfigured sandbox never silently runs
    with unbounded resources.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=RESOURCE_LIMIT_FAIL_REASON)


class OutputLimitError(SandboxError):
    """Raised when a child stream exceeds its byte cap.

    ``fail_reason`` is ``RESOURCE_LIMIT``. The child is killed when this fires.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=RESOURCE_LIMIT_FAIL_REASON)


class OrphanDetectedError(SandboxError):
    """Raised when a process survives the watchdog kill of its group.

    ``fail_reason`` is ``ORPHAN_PROCESS_DETECTED``. This is a hard stop
    (``hard_stop=true`` in the fail-reason registry): a survivor means the cage
    leaked and the run must not be trusted.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=ORPHAN_FAIL_REASON)


# ---------------------------------------------------------------------------
# Environment + scratch.
# ---------------------------------------------------------------------------


def build_child_env(
    *,
    home_dir: str | Path,
    tmp_dir: str | Path,
    pythonpath: str | None = None,
    forward_test_gate: bool = False,
) -> dict[str, str]:
    """Return a sanitized environment dict for the child process.

    The parent :data:`os.environ` is **never** inherited. Only fixed/sandbox-local
    keys are set: a minimal ``PATH``, ``HOME`` and ``TMPDIR`` pointing at the
    sandbox-local temp tree, ``LANG=C.UTF-8`` for deterministic decoding,
    ``PYTHONHASHSEED=0`` for deterministic hash ordering, and (when provided)
    ``PYTHONPATH`` pointing at the in-repo ``srl`` package root so the fixed
    ``-m srl.execution.child`` entrypoint is importable. A parent-only env var
    (e.g. a secret token) therefore never reaches the child.

    ``PYTHONPATH`` is not a leak: it points at the same package the orchestrator
    is running from, never at parent secrets. In an installed environment
    (``uv run`` / venv) the package is already importable and ``pythonpath`` may
    be ``None``; in a dev checkout the runner derives it from the ``srl``
    package location so the child can import the fixed module.

    When ``forward_test_gate`` is ``True`` and the parent has set the
    ``SRL_RUNNER_TEST_ADAPTERS`` env var to ``"1"``, that single env var is
    forwarded so the child can load the fixed test-only adapter module. This is
    a test signal, not a secret: it enables the in-repo test adapter hook (a
    fixed module, not caller data). In production it is never set, so nothing is
    forwarded.

    Notes
    -----
    On macOS the CFoundation layer injects ``__CF_USER_TEXT_ENCODING``
    automatically into the child regardless of the dict passed to
    :func:`subprocess.Popen`; that value is derived from the UID, not from the
    parent environ, so it is not a leak of a parent secret. The canary test
    asserts our specific canary is absent, not that the child env is exactly
    this dict.
    """
    home = str(home_dir)
    tmp = str(tmp_dir)
    env: dict[str, str] = {
        "PATH": _PATH_DEFAULT,
        "HOME": home,
        "TMPDIR": tmp,
        "LANG": _LANG,
        "PYTHONHASHSEED": _PYTHONHASHSEED,
    }
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    if forward_test_gate:
        gate = os.environ.get(_TEST_GATE_ENV, "")
        if gate == "1":
            env[_TEST_GATE_ENV] = "1"
    return env


def prepare_scratch(*, parent: str | Path | None = None) -> Path:
    """Create a private scratch directory with mode ``0o700`` and return it.

    A fresh :func:`tempfile.mkdtemp` under ``parent`` (default the system temp
    dir) is created and chmod-ed to ``0o700`` so only the owning UID can read
    or write it. The caller (runner) owns cleanup.

    Parameters
    ----------
    parent:
        Optional parent directory for the scratch tree. Defaults to the system
        temp directory via :func:`tempfile.gettempdir`.
    """
    base = str(parent) if parent is not None else None
    scratch = Path(tempfile.mkdtemp(prefix="srl-runner-", dir=base))
    os.chmod(scratch, 0o700)
    return scratch


# ---------------------------------------------------------------------------
# Resource limits.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceLimits:
    """The POSIX resource caps applied to the child via ``preexec_fn``.

    Attributes
    ----------
    rss_bytes:
        The address-space cap (``RLIMIT_AS``) derived from the policy
        ``rss_bytes``. Best-effort on macOS (see module docstring).
    cpu_seconds:
        The CPU-time cap (``RLIMIT_CPU``) for the child. Kept >= the wall cap
        so a CPU spike is bounded independently of the wall watchdog.
    nproc:
        The max processes / threads cap (``RLIMIT_NPROC``). Fixed at 256.
    fsize_bytes:
        The max file-write size (``RLIMIT_FSIZE``) derived from the output cap.
    nofile:
        The max open file descriptors (``RLIMIT_NOFILE``). Fixed at 256.
    """

    rss_bytes: int
    cpu_seconds: int
    nproc: int = _NPROC_LIMIT
    fsize_bytes: int = DEFAULT_OUTPUT_CAP_BYTES
    nofile: int = _NOFILE_LIMIT


def _try_setrlimit(
    which: int, soft: int, hard: int, *, label: str, hard_required: bool = True
) -> None:
    """Apply one ``RLIMIT_*`` cap; raise :class:`LimitSetupError` on failure.

    ``resource.setrlimit`` is called with ``(soft, hard)``. On platforms where
    the requested hard limit exceeds the current hard limit (e.g. ``RLIMIT_AS``
    on macOS arm64), the call raises :class:`ValueError`; for limits flagged
    ``hard_required`` that aborts the run, and for best-effort limits (``AS``)
    the caller passes ``hard_required=False`` and the error is swallowed.

    A *soft*-limit failure (genuinely cannot lower the cap) always raises: that
    means the sandbox cannot enforce a mandatory cap and the run must not start.
    """
    try:
        resource.setrlimit(which, (soft, hard))
    except (ValueError, OSError) as exc:
        if hard_required:
            msg = f"failed to set {label} to ({soft}, {hard}): {exc}"
            raise LimitSetupError(msg) from exc


def _apply_limits_preexec(limits: ResourceLimits) -> None:
    """``preexec_fn`` body: apply every resource cap before exec.

    Called in the child after :func:`os.fork` but before :func:`os.execv`. Every
    mandatory cap (``CPU``, ``FSIZE``, ``NOFILE``, ``NPROC``) must succeed or
    the run aborts. ``RLIMIT_AS`` is best-effort: on platforms that refuse to
    lower it (macOS arm64) the remaining caps still apply and the wall timeout
    plus output cap backstop memory.

    ``RLIMIT_CPU`` is set to ``cpu_seconds`` so a compute-bound child is killed
    by ``SIGXCPU`` after its CPU budget even if the wall watchdog is slow.
    """
    # Mandatory caps: a failure to set any of these aborts before exec.
    _try_setrlimit(resource.RLIMIT_CPU, limits.cpu_seconds, limits.cpu_seconds, label="RLIMIT_CPU")
    _try_setrlimit(
        resource.RLIMIT_FSIZE,
        limits.fsize_bytes,
        limits.fsize_bytes,
        label="RLIMIT_FSIZE",
    )
    _try_setrlimit(resource.RLIMIT_NOFILE, limits.nofile, limits.nofile, label="RLIMIT_NOFILE")
    _try_setrlimit(resource.RLIMIT_NPROC, limits.nproc, limits.nproc, label="RLIMIT_NPROC")
    # Best-effort address-space cap. On macOS arm64 the kernel refuses to lower
    # the hard limit below the current value, so this is a no-op there; on Linux
    # (CI) it is enforced and kills an over-budget child with SIGSEGV/MemoryError.
    _try_setrlimit(
        resource.RLIMIT_AS,
        limits.rss_bytes,
        limits.rss_bytes,
        label="RLIMIT_AS",
        hard_required=False,
    )


def make_preexec(limits: ResourceLimits) -> Any:
    """Return a ``preexec_fn`` callable that applies ``limits`` in the child.

    Wrapping :func:`_apply_limits_preexec` in a closure lets the runner hand a
    single callable to :class:`subprocess.Popen` and lets tests monkeypatch the
    limit applier. The returned callable takes no arguments (the
    ``preexec_fn`` contract).
    """

    # Capture limits in the default-arg so the closure is robust to rebinding.
    def _preexec(_limits: ResourceLimits = limits) -> None:
        _apply_limits_preexec(_limits)

    return _preexec


# ---------------------------------------------------------------------------
# Output capture with byte caps.
# ---------------------------------------------------------------------------


@dataclass
class CapturedOutput:
    """The captured stdout/stderr of a child, each capped at ``cap_bytes``.

    ``truncated`` is ``True`` iff either stream hit its cap (the run is then
    classified as ``resource_limit`` by the runner). The bytes are the prefix
    up to the cap; nothing beyond the cap is retained.

    Attributes
    ----------
    stdout:
        Raw captured stdout bytes (``<= cap_bytes``).
    stderr:
        Raw captured stderr bytes (``<= cap_bytes``).
    truncated:
        ``True`` iff a stream was over cap.
    """

    stdout: bytes
    stderr: bytes
    truncated: bool


class _CappedReader:
    """A thread that drains one child pipe into a capped buffer.

    Reads chunks from ``stream`` until EOF or until ``cap_bytes`` is reached.
    If the cap is hit, sets ``self.truncated = True`` and the caller (the
    watcher) is expected to kill the child. Keeping one reader per stream means
    an over-cap stdout cannot block stderr (and vice versa).
    """

    def __init__(self, stream: Any, cap_bytes: int) -> None:
        self._stream = stream
        self._cap = cap_bytes
        self._buf = bytearray()
        self.truncated = False

    def run(self) -> None:
        """Drain the stream into the buffer until EOF or the cap is hit."""
        cap = self._cap
        while True:
            try:
                chunk = self._stream.read(4096)
            except (OSError, ValueError):
                # Pipe closed or read after Popen cleanup; stop cleanly.
                break
            if not chunk:
                break
            remaining = cap - len(self._buf)
            if remaining <= 0:
                self.truncated = True
                break
            if len(chunk) > remaining:
                self._buf.extend(chunk[:remaining])
                self.truncated = True
                break
            self._buf.extend(chunk)

    @property
    def bytes(self) -> bytes:
        """The captured prefix (``<= cap_bytes``)."""
        return bytes(self._buf)


# ---------------------------------------------------------------------------
# Process group watchdog.
# ---------------------------------------------------------------------------


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    """SIGTERM the process group, wait the grace, then SIGKILL it.

    ``proc`` was started with ``start_new_session=True``, so its PID is the
    process-group leader and ``os.killpg`` reaches every descendant. The grace
    window lets a well-behaved child flush and exit; after it, SIGKILL is
    unconditional. Errors from killing an already-dead group are swallowed: the
    point of this routine is to make the group gone.
    """
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        # Already gone, or not ours to signal: nothing more to do for SIGTERM.
        pass
    try:
        proc.wait(timeout=_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        # Reap to avoid a zombie; ignore further timeout (SIGKILL is fatal).
        try:
            proc.wait(timeout=_GRACE_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover  (extreme edge)
            pass


# /proc/<pid>/stat is parsed from the right (comm may contain spaces); we split
# off the trailing 7 fields and need at least this many to reach pgrp (field 5,
# which lands at parts[-4] after the rsplit). Kept as a named constant so the
# minimum-parts guard is not a magic literal.
_PROC_STAT_MIN_PARTS: Final[int] = 5


def _proc_pgrp(pid: int) -> int | None:
    """Return the process-group id of ``pid`` from ``/proc/<pid>/stat`` (Linux).

    ``/proc/<pid>/stat`` field 5 is ``pgrp``. The comm field (field 2) may
    contain spaces and parens, so the line is parsed from the right. Returns
    ``None`` if the entry is gone or unreadable.
    """
    try:
        text = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    parts = text.rsplit(" ", 7)
    if len(parts) < _PROC_STAT_MIN_PARTS:
        return None
    try:
        return int(parts[-4])
    except ValueError:
        return None


def _survivors_linux(pgid: int) -> list[int]:
    """Return PIDs in ``/proc`` whose pgrp matches ``pgid`` (Linux walker)."""
    out: list[int] = []
    self_pid = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == self_pid:
            continue
        if _proc_pgrp(pid) == pgid:
            out.append(pid)
    return out


def _survivors_ps(pgid: int) -> list[int]:
    """Return pgids reported by ``ps`` that match ``pgid`` (macOS/BSD walker).

    Uses the absolute ``/bin/ps`` path to avoid the S607 partial-path warning;
    we only read the pgid column, never environment or argument data.
    """
    ps_bin = "/bin/ps" if Path("/bin/ps").exists() else "/usr/bin/ps"
    try:
        ps = subprocess.run(  # noqa: S603  (fixed binary path, literal args, no untrusted input)
            [ps_bin, "-axo", "pgid"],
            capture_output=True,
            text=True,
            timeout=_GRACE_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # If we cannot inspect the table, do not claim all-clear; raise so the
        # run is not trusted on a host we cannot reason about.
        msg = f"cannot verify no orphan: process table inspection failed for pgid={pgid}"
        raise OrphanDetectedError(msg) from exc
    out: list[int] = []
    for line in ps.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        try:
            pgrp = int(line)
        except ValueError:
            continue
        if pgrp == pgid:
            out.append(pgrp)
    return out


def verify_no_orphan(proc: subprocess.Popen[bytes]) -> None:
    """After kill, verify no process in the child group survived; raise if any do.

    Walks the live process table for any process whose process-group id still
    matches ``proc.pid``. On POSIX a killed leader leaves no live member; if one
    survives, that is an ``ORPHAN_PROCESS_DETECTED`` hard stop.

    The check uses only stdlib: it samples :func:`os.listdir` of ``/proc`` on
    Linux and ``/bin/ps`` on macOS/BSD. Neither inspects unrelated processes'
    secrets — only PIDs and their group ids.
    """
    pgid = proc.pid
    if pgid <= 0:
        return
    if sys.platform == "linux" and Path("/proc").is_dir():
        survivors = _survivors_linux(pgid)
    else:
        survivors = _survivors_ps(pgid)
    if survivors:
        msg = f"orphan process(es) survived watchdog kill for pgid={pgid}: {survivors[:8]}"
        raise OrphanDetectedError(msg)


def reap_group(proc: subprocess.Popen[bytes]) -> None:
    """Best-effort: kill the group and verify no orphan, swallowing nothing.

    Called by the runner after a timeout/resource-limit to guarantee the cage
    is empty before returning. :func:`verify_no_orphan` raises on a survivor;
    the caller decides whether that is a hard failure or a recorded outcome.
    """
    _kill_group(proc)
    verify_no_orphan(proc)


__all__ = [
    "DEFAULT_OUTPUT_CAP_BYTES",
    "ORPHAN_FAIL_REASON",
    "RESOURCE_LIMIT_FAIL_REASON",
    "CapturedOutput",
    "LimitSetupError",
    "OrphanDetectedError",
    "OutputLimitError",
    "ResourceLimits",
    "SandboxError",
    "build_child_env",
    "make_preexec",
    "prepare_scratch",
    "reap_group",
    "verify_no_orphan",
]
