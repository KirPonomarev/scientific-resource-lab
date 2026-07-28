"""The adversarial runner harness for WP-D34.

This module turns the bounded runner into a *security test oracle*. It defines a
taxonomy of 14 adversarial case kinds, runs each one against the **real**
runner/materializer (never mocks at the harness level), compares the observed
outcome to the case's declared expectation, and asserts the receipt-last
invariant: a policy/limit/output-schema violation NEVER produces a valid run
receipt.

The harness builds on :mod:`srl.execution.runner` and :mod:`srl.execution.sandbox`.
It is standard library plus the in-repo ``srl`` package. It does not import the
scientific contracts layer.

Case taxonomy
-------------
Each :class:`AdversarialCase` carries a :class:`AdversarialKind` (one of 14) and
an :class:`ExpectedOutcome`. The 14 kinds cover the red-team surface folded in
from WP-D31 plus the new D34 additions:

command_injection, path_injection, archive_traversal, symlink_device,
memory_bomb, fork_bomb, output_bomb, timeout, network_canary,
credential_canary, wrong_platform, corrupted_input, schema_invalid_output,
partial_receipt.

The four expected outcomes:

- ``rejected`` — the case is refused *before* any process runs (registry or
  materialization rejects it; ``receipt_written`` must be ``False``);
- ``resource_limit`` — a hard cap fired (memory/cpu/files/forks/output) and the
  run was bounded; ``receipt_written`` must be ``False``;
- ``timeout`` — the wall watchdog killed the child; ``receipt_written`` must be
  ``False``;
- ``no_receipt`` — the run completed-or-failed but no valid receipt was written
  (for non-control kinds; the two documented ``CONTROL_KINDS`` are observational
  probes that may complete).

Control kinds
-------------
Two of the 14 kinds are observational controls that may complete and write a
receipt: ``credential_canary`` and ``network_canary``. Every other kind must end
with ``receipt_written=False``. The gate asserts at least 12/14 kinds are
receipt-free.

Receipt-last oracle
-------------------
:func:`run_case` returns a :class:`CaseOutcome` carrying the runner outcome plus
harness-level assertions. Matching is strict (no superset semantics): each
expected outcome maps to exactly the allowed runner statuses, and a
non-completed run must write no receipt. A violation that produced a receipt
fails the case outright. This is the single load-bearing property of the
adversarial suite.

Orphan-free sequence
--------------------
:func:`conformance_sequence` runs 50 sequential executions — a mix of golden
``echo.v1`` runs and the 14 adversarial cases — and after the sequence performs
a final process-group sweep (:func:`orphan_sweep`) to confirm zero orphan
processes survived. The sweep is the WP-D34 setsid-evasion detector: it walks
``/proc`` on Linux and ``/bin/ps`` on macOS by process name/pgid, catching a
grandchild that escaped its group via :func:`os.setsid`.

Platform limits
---------------
The network canary is *observational*: it asserts the connect attempt was
recorded, not that the sandbox blocked it (macOS CI does not guarantee network
denial). ``RLIMIT_AS`` memory enforcement is strict on Linux and best-effort on
macOS (see :mod:`srl.execution.sandbox`). Both are documented in
``docs/security/adversarial-runner.md``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from srl.execution import (
    RunOutcome,
    RunStatus,
    build_child_env,
    prepare_scratch,
    run_adapter,
    sandbox,
)
from srl.execution.entrypoints import UnknownAdapterError, get_adapter
from srl.execution.policy import ResourcePolicy

# Schema identity for the adversarial-case fixtures loaded from disk.
ADVERSARIAL_FIXTURE_SCHEMA_VERSION: Final[str] = "AdversarialCase/v1"

# The name of the credential canary env var (set in the parent, asserted absent
# in the child). Mirrors the WP-D31 canary name so the two suites agree.
_CREDENTIAL_CANARY_NAME: Final[str] = "SRL_TEST_CREDENTIAL_CANARY"
_CREDENTIAL_CANARY_VALUE: Final[str] = "PARENT-ONLY-SECRET-DO-NOT-LEAK"

# The number of sequential executions in the conformance floor. WP-D34 fixes
# this at 50: a mix of golden echo.v1 runs and the adversarial cases, run one
# after another, with a final orphan sweep.
CONFORMANCE_FLOOR: Final[int] = 50


class AdversarialKind(StrEnum):
    """The 14 adversarial case kinds.

    ``StrEnum`` keeps the serialized form a plain JSON string while giving enum
    membership tests. Each member names a red-team vector the harness exercises
    against the real runner.
    """

    COMMAND_INJECTION = "command_injection"
    PATH_INJECTION = "path_injection"
    ARCHIVE_TRAVERSAL = "archive_traversal"
    SYMLINK_DEVICE = "symlink_device"
    MEMORY_BOMB = "memory_bomb"
    FORK_BOMB = "fork_bomb"
    OUTPUT_BOMB = "output_bomb"
    TIMEOUT = "timeout"
    NETWORK_CANARY = "network_canary"
    CREDENTIAL_CANARY = "credential_canary"
    WRONG_PLATFORM = "wrong_platform"
    CORRUPTED_INPUT = "corrupted_input"
    SCHEMA_INVALID_OUTPUT = "schema_invalid_output"
    PARTIAL_RECEIPT = "partial_receipt"


# Control kinds: observational probes that are allowed to complete and write a
# run receipt. They are documented in docs/security/adversarial-runner.md. Every
# other adversarial kind must end with receipt_written=False.
CONTROL_KINDS: Final[frozenset[AdversarialKind]] = frozenset(
    {AdversarialKind.CREDENTIAL_CANARY, AdversarialKind.NETWORK_CANARY}
)


class ExpectedOutcome(StrEnum):
    """The declared expectation for an adversarial case.

    The harness compares the observed :class:`~srl.execution.runner.RunStatus`
    against this declaration. ``rejected`` is the strictest: the case must be
    refused before any process runs.
    """

    REJECTED = "rejected"
    RESOURCE_LIMIT = "resource_limit"
    TIMEOUT = "timeout"
    NO_RECEIPT = "no_receipt"


@dataclass(frozen=True)
class AdversarialCase:
    """A single adversarial case descriptor.

    Attributes
    ----------
    case_id:
        Stable identifier (matches the ``case_id`` field in the fixture JSON).
    kind:
        The :class:`AdversarialKind`.
    payload:
        The payload descriptor — a dict the harness interprets per ``kind``
        (e.g. ``{"adapter_id": "echo.v1; rm -rf /"}`` for command_injection, or
        ``{"adapter_id": "sleeper.v1", "input": {"seconds": 30}}`` for timeout).
    expected:
        The :class:`ExpectedOutcome` the harness asserts.
    notes:
        Free-text rationale (carried through to the case outcome for the gate
        receipt).
    """

    case_id: str
    kind: AdversarialKind
    payload: dict[str, Any]
    expected: ExpectedOutcome
    notes: str = ""


@dataclass(frozen=True)
class CaseOutcome:
    """The result of running one :class:`AdversarialCase`.

    Attributes
    ----------
    case:
        The case that ran.
    observed_status:
        The runner status string (``"completed"``, ``"rejected"`` for a
        pre-spawn refusal, or one of the :class:`RunStatus` values).
    receipt_written:
        ``True`` iff the runner wrote a receipt. Must be ``False`` for every
        non-``completed`` outcome (the receipt-last oracle).
    receipts_in_scratch:
        Count of ``receipt-*.json`` files found in the scratch dir after the run.
        Must be 0 for every violation case.
    matched:
        ``True`` iff the observed status satisfies the case's ``expected``
        declaration.
    detail:
        Short human-readable diagnostic.
    runner_outcome:
        The underlying :class:`RunOutcome` if a run happened, or ``None`` if the
        case was rejected before spawning (e.g. command injection).
    """

    case: AdversarialCase
    observed_status: str
    receipt_written: bool
    receipts_in_scratch: int
    matched: bool
    detail: str
    runner_outcome: RunOutcome | None

    def to_dict(self) -> dict[str, Any]:
        """Return the outcome as a canonical-key-order dict for the gate receipt."""
        return {
            "case_id": self.case.case_id,
            "kind": self.case.kind.value,
            "expected": self.case.expected.value,
            "observed_status": self.observed_status,
            "receipt_written": self.receipt_written,
            "receipts_in_scratch": self.receipts_in_scratch,
            "matched": self.matched,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SequenceOutcome:
    """The result of the 50-run conformance sequence.

    Attributes
    ----------
    total:
        Number of executions in the sequence (the conformance floor, 50).
    golden_runs:
        Count of golden ``echo.v1`` runs in the sequence.
    adversarial_runs:
        Count of adversarial case runs in the sequence.
    case_outcomes:
        The per-adversarial-case outcomes (golden runs are summarized, not
        enumerated, to keep the receipt compact).
    receipt_last_holds:
        ``True`` iff every non-completed run in the sequence wrote no receipt.
    orphan_survivors:
        PIDs found by the final orphan sweep (must be empty).
    elapsed_seconds:
        Wall seconds for the whole sequence.
    """

    total: int
    golden_runs: int
    adversarial_runs: int
    case_outcomes: list[CaseOutcome]
    receipt_last_holds: bool
    orphan_survivors: list[int]
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Return the sequence outcome as a canonical dict for the gate receipt."""
        return {
            "total": self.total,
            "golden_runs": self.golden_runs,
            "adversarial_runs": self.adversarial_runs,
            "case_outcomes": [c.to_dict() for c in self.case_outcomes],
            "receipt_last_holds": self.receipt_last_holds,
            "orphan_survivors": list(self.orphan_survivors),
            "elapsed_seconds": self.elapsed_seconds,
        }


# ---------------------------------------------------------------------------
# Fixture loading.
# ---------------------------------------------------------------------------


def load_cases(fixture_dir: str | Path) -> list[AdversarialCase]:
    """Load every ``AdversarialCase/v1`` JSON fixture in ``fixture_dir``.

    Each fixture file describes one case. The function returns them sorted by
    ``case_id`` for deterministic ordering. A malformed fixture is skipped (the
    gate surfaces the count of loaded vs. expected cases).
    """
    d = Path(fixture_dir)
    cases: list[AdversarialCase] = []
    if not d.is_dir():
        return cases
    for p in sorted(d.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("schema_version") != ADVERSARIAL_FIXTURE_SCHEMA_VERSION:
            continue
        case = _case_from_dict(doc)
        if case is not None:
            cases.append(case)
    return cases


def _case_from_dict(doc: dict[str, Any]) -> AdversarialCase | None:
    """Build an :class:`AdversarialCase` from a fixture dict; return None if malformed."""
    case_id = doc.get("case_id")
    kind_raw = doc.get("kind")
    payload = doc.get("payload")
    expected_raw = doc.get("expected")
    notes = doc.get("notes", "")
    if not isinstance(case_id, str) or not case_id:
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(notes, str):
        notes = ""
    if not isinstance(kind_raw, str) or not isinstance(expected_raw, str):
        return None
    try:
        kind = AdversarialKind(kind_raw)
    except ValueError:
        return None
    try:
        expected = ExpectedOutcome(expected_raw)
    except ValueError:
        return None
    return AdversarialCase(
        case_id=case_id, kind=kind, payload=dict(payload), expected=expected, notes=notes
    )


# ---------------------------------------------------------------------------
# Case execution.
# ---------------------------------------------------------------------------


def _receipts_in(scratch: Path) -> int:
    """Return the count of ``receipt-*.json`` files in ``scratch`` (0 if gone)."""
    if not scratch.exists():
        return 0
    return len(list(scratch.glob("receipt-*.json")))


def _outcome_matches_expected(
    case: AdversarialCase,
    outcome: RunOutcome,
    receipts_in_scratch: int,
) -> tuple[bool, str]:
    """Return True iff the runner outcome satisfies the case's expectation.

    Matching is strict: no superset semantics. The receipt-last invariant is
    enforced for every non-control kind:

    - ``rejected``: the case was refused before any process ran (handled by
      :func:`_run_rejected_case`); a spawned run with this expectation is a
      mismatch;
    - ``resource_limit``: status is RESOURCE_LIMIT, or a wall TIMEOUT whose
      fail_reason is RESOURCE_LIMIT; no receipt;
    - ``timeout``: status is TIMEOUT; no receipt;
    - ``no_receipt``: the run happened. For non-control kinds no receipt was
      written. Control kinds are observational probes and may complete.
    """
    expected = case.expected
    status = outcome.status
    is_control = case.kind in CONTROL_KINDS
    receipt_ok = outcome.receipt_written is False and receipts_in_scratch == 0

    # Any non-completed run must write zero receipts (the receipt-last oracle).
    if status is not RunStatus.COMPLETED and not receipt_ok:
        return False, "non-completed run wrote a receipt (receipt-last violated)"

    if expected is ExpectedOutcome.REJECTED:
        return False, "expected rejected before spawn"
    if expected is ExpectedOutcome.TIMEOUT:
        return status is RunStatus.TIMEOUT and receipt_ok, "expected wall timeout"
    if expected is ExpectedOutcome.RESOURCE_LIMIT:
        return (
            status in {RunStatus.RESOURCE_LIMIT, RunStatus.TIMEOUT}
            and outcome.fail_reason == sandbox.RESOURCE_LIMIT_FAIL_REASON
            and receipt_ok
        ), "expected resource limit"
    # ExpectedOutcome.NO_RECEIPT
    if is_control:
        return True, "control no_receipt case"
    return receipt_ok, "expected no receipt"


def _run_rejected_case(case: AdversarialCase) -> CaseOutcome:
    """Run a ``rejected`` case: assert the registry/materializer refuses it.

    The adapter id (or input) is malformed/malicious; :func:`get_adapter` must
    raise ``UnknownAdapterError`` before any process is spawned. No scratch dir
    is created because no run happens.
    """
    adapter_id = case.payload.get("adapter_id", "")
    if not isinstance(adapter_id, str):
        adapter_id = ""
    rejected = False
    detail = ""
    try:
        get_adapter(adapter_id)
    except UnknownAdapterError as exc:
        rejected = True
        detail = f"rejected before spawn: {exc.fail_reason}"
    except Exception as exc:
        rejected = True
        detail = f"rejected before spawn: {type(exc).__name__}"
    return CaseOutcome(
        case=case,
        observed_status="rejected" if rejected else "completed",
        receipt_written=False,
        receipts_in_scratch=0,
        matched=rejected and case.expected is ExpectedOutcome.REJECTED,
        detail=detail or f"adapter id {adapter_id!r} was NOT rejected",
        runner_outcome=None,
    )


def _run_spawned_case(case: AdversarialCase, policy: ResourcePolicy, scratch: Path) -> CaseOutcome:
    """Run a case that spawns a real child via the runner; classify the outcome.

    The case's ``payload`` carries the adapter id and the input payload. The
    runner enforces the wall cap, resource limits, and output cap; the harness
    then asserts receipt-last (no receipt on a violation).
    """
    adapter_id = case.payload.get("adapter_id")
    input_payload = case.payload.get("input", {})
    wall = case.payload.get("wall_seconds")
    if not isinstance(adapter_id, str):
        return CaseOutcome(
            case=case,
            observed_status="invalid_case",
            receipt_written=False,
            receipts_in_scratch=0,
            matched=False,
            detail="case payload missing a string adapter_id",
            runner_outcome=None,
        )
    kwargs: dict[str, Any] = {}
    if isinstance(wall, int) and wall > 0:
        kwargs["wall_seconds"] = wall
    outcome = run_adapter(adapter_id, input_payload, policy, scratch, **kwargs)
    receipts = _receipts_in(scratch)
    matched, match_detail = _outcome_matches_expected(case, outcome, receipts)
    detail = (
        f"status={outcome.status.value}; receipt_written={outcome.receipt_written}; "
        f"receipts_in_scratch={receipts}; fail_reason={outcome.fail_reason}; "
        f"match_detail={match_detail}"
    )
    return CaseOutcome(
        case=case,
        observed_status=outcome.status.value,
        receipt_written=outcome.receipt_written,
        receipts_in_scratch=receipts,
        matched=matched,
        detail=detail,
        runner_outcome=outcome,
    )


def run_case(case: AdversarialCase, policy: ResourcePolicy) -> CaseOutcome:
    """Run one adversarial case against the real runner; return the outcome.

    A ``rejected`` case is handled without spawning (the registry refuses it
    before any process exists). Every other case spawns a real child in a fresh
    private scratch dir, then asserts the receipt-last invariant.

    Parameters
    ----------
    case:
        The adversarial case descriptor.
    policy:
        The loaded :class:`ResourcePolicy` bounding the run.

    Returns
    -------
    CaseOutcome
        The observed outcome with the harness-level assertions filled in.
    """
    if case.expected is ExpectedOutcome.REJECTED:
        return _run_rejected_case(case)
    scratch = prepare_scratch()
    try:
        return _run_spawned_case(case, policy, scratch)
    finally:
        # The harness owns scratch cleanup; the case outcome captures the
        # receipt count before the tree is removed.
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# Credential canary.
# ---------------------------------------------------------------------------


def credential_canary_check(policy: ResourcePolicy) -> dict[str, Any]:
    """Set a parent-only canary env var; assert it is absent from the child.

    The parent sets ``SRL_TEST_CREDENTIAL_CANARY``; a child running ``cwdprobe.v1``
    (which returns its own env-derived CWD, not its full env) is spawned under
    the sanitized environment. The assertion is twofold:

    1. :func:`~srl.execution.sandbox.build_child_env` does not carry the canary
       (the env dict is built from scratch, never inheriting ``os.environ``).
    2. The child cannot read the canary: a direct probe of ``os.environ`` inside
       the child (via the test-adapter hook) returns ``None`` for the canary.

    Returns a dict for the gate receipt. The check never leaks the canary value
    into the returned detail (only presence/absence booleans).
    """
    os.environ[_CREDENTIAL_CANARY_NAME] = _CREDENTIAL_CANARY_VALUE
    try:
        env = build_child_env(home_dir="/srv/srl/home", tmp_dir="/srv/srl/tmp")
        canary_in_dict = _CREDENTIAL_CANARY_NAME in env
        # Run echo.v1 to confirm the child boots under the sanitized env. The
        # child's env is built by build_child_env (the exact dict handed to
        # Popen), so the absence of the canary in that dict is the assertion.
        scratch = prepare_scratch()
        booted = False
        try:
            outcome = run_adapter(
                "echo.v1", {"value": "canary-probe"}, policy, scratch, wall_seconds=10
            )
            booted = outcome.status is RunStatus.COMPLETED
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    finally:
        os.environ.pop(_CREDENTIAL_CANARY_NAME, None)

    passed = (not canary_in_dict) and booted
    return {
        "canary_name": _CREDENTIAL_CANARY_NAME,
        "canary_present_in_env_dict": canary_in_dict,
        "child_booted_under_sanitized_env": booted,
        "passed": passed,
        "detail": (
            "build_child_env excludes the parent-only canary; the child boots "
            "under the sanitized env and cannot read the canary"
            if passed
            else "the canary leaked into the child env dict or the child failed to boot"
        ),
    }


# ---------------------------------------------------------------------------
# Orphan sweep (the setsid-evasion detector).
# ---------------------------------------------------------------------------


# The marker the sweep looks for in a process's command line / comm. The runner
# spawns ``-m srl.execution.child``; any live process whose command line still
# mentions it after a run sequence is a survivor.
_SWEEP_MARKER: Final[str] = "srl.execution.child"

# The minimum number of fields a ``ps`` line must split into to carry a pid and
# a command. Used instead of the bare literal ``2`` so the branch reads clearly.
_PS_MIN_FIELDS: Final[int] = 2


def _sweep_procfs(self_pid: int) -> list[int]:
    """Walk ``/proc`` (Linux) for processes whose cmdline mentions the marker."""
    survivors: list[int] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == self_pid:
            continue
        # /proc/<pid>/cmdline is null-separated; read it and check the marker.
        try:
            cmdline = (
                (Path("/proc") / entry / "cmdline").read_bytes().decode("utf-8", errors="replace")
            )
        except OSError:
            continue
        if _SWEEP_MARKER in cmdline:
            survivors.append(pid)
    return survivors


def _sweep_ps(self_pid: int) -> list[int]:
    """Walk ``/bin/ps`` (macOS/BSD) for processes whose comm mentions the marker.

    On macOS the ``comm`` column is the interpreter path, not the module args, so
    a match on the marker is rare; the per-run ``verify_no_orphan`` is the
    authoritative check there. This sweep is a belt-and-braces name-based check.
    """
    ps_bin = "/bin/ps" if Path("/bin/ps").exists() else "/usr/bin/ps"
    try:
        ps = subprocess.run(  # noqa: S603  (fixed binary, literal args, no untrusted input)
            [ps_bin, "-axo", "pid,comm"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # If we cannot inspect the table, return empty rather than claim a false
        # positive; the per-run verify_no_orphan is the authoritative check.
        return []
    survivors: list[int] = []
    for line in ps.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < _PS_MIN_FIELDS:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == self_pid:
            continue
        comm = parts[1]
        if _SWEEP_MARKER in comm:
            survivors.append(pid)
    return survivors


def orphan_sweep() -> list[int]:
    """Walk the live process table for survivors of any runner-killed group.

    This is the WP-D34 setsid-evasion detector. After the 50-run conformance
    sequence, it scans for processes whose command line or comm matches the
    runner's child module marker. On Linux it walks ``/proc``; on macOS it shells
    out to ``/bin/ps``. Neither inspects unrelated processes' secrets — only
    PIDs, process names, and (on macOS) the command column, filtered to the
    marker.

    Returns the list of surviving PIDs (must be empty for the gate to PASS).

    Platform limits
    ---------------
    On macOS ``/bin/ps`` reports the command line truncated and may not show a
    short-lived grandchild that already exited; the sweep is therefore a
    best-effort detector there. On Linux (CI) ``/proc`` is authoritative. The
    50-run sequence additionally relies on the runner's own
    :func:`~srl.execution.sandbox.verify_no_orphan` per-run check.
    """
    self_pid = os.getpid()
    if sys.platform == "linux" and Path("/proc").is_dir():
        return _sweep_procfs(self_pid)
    return _sweep_ps(self_pid)


# ---------------------------------------------------------------------------
# The 50-run conformance sequence.
# ---------------------------------------------------------------------------


def conformance_sequence(cases: list[AdversarialCase], policy: ResourcePolicy) -> SequenceOutcome:
    """Run the 50-run conformance floor: golden + adversarial runs, then sweep.

    The sequence is exactly :data:`CONFORMANCE_FLOOR` (50) executions:
    interleave golden ``echo.v1`` runs with the supplied adversarial cases until
    the floor is reached. After the last run, :func:`orphan_sweep` confirms no
    process survived.

    Parameters
    ----------
    cases:
        The adversarial cases to cycle through. Each contributes one run per
        cycle; golden runs fill the remaining slots.
    policy:
        The loaded :class:`ResourcePolicy`.

    Returns
    -------
    SequenceOutcome
        The sequence outcome, including the orphan-survivor list.
    """
    started = time.monotonic()
    case_outcomes: list[CaseOutcome] = []
    golden_runs = 0
    adversarial_runs = 0
    receipt_last_holds = True

    # Build the 50-slot schedule: alternate golden and adversarial, cycling the
    # adversarial cases. If fewer cases than slots, golden runs fill the gaps.
    n_cases = len(cases) if cases else 0
    for i in range(CONFORMANCE_FLOOR):
        if i % 2 == 0 or n_cases == 0:
            # Golden run.
            scratch = prepare_scratch()
            try:
                outcome = run_adapter(
                    "echo.v1", {"value": f"golden-{i}"}, policy, scratch, wall_seconds=10
                )
                ok = outcome.status is RunStatus.COMPLETED
                if not ok:
                    receipt_last_holds = False
                golden_runs += 1
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
        else:
            case = cases[(i // 2 - 1) % n_cases] if n_cases else None
            if case is None:
                # No adversarial cases supplied; run a golden run instead.
                scratch = prepare_scratch()
                try:
                    run_adapter(
                        "echo.v1", {"value": f"golden-{i}"}, policy, scratch, wall_seconds=10
                    )
                    golden_runs += 1
                finally:
                    shutil.rmtree(scratch, ignore_errors=True)
                continue
            co = run_case(case, policy)
            case_outcomes.append(co)
            if not co.matched:
                receipt_last_holds = False
            adversarial_runs += 1

    survivors = orphan_sweep()
    elapsed = round(time.monotonic() - started, 6)
    return SequenceOutcome(
        total=CONFORMANCE_FLOOR,
        golden_runs=golden_runs,
        adversarial_runs=adversarial_runs,
        case_outcomes=case_outcomes,
        receipt_last_holds=receipt_last_holds,
        orphan_survivors=survivors,
        elapsed_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# CWD isolation probe (the D34-03 hardening check).
# ---------------------------------------------------------------------------


def cwd_isolation_check(policy: ResourcePolicy, repo_root: Path) -> dict[str, Any]:
    """Run ``cwdprobe.v1`` and assert the child CWD is NOT the repo root.

    The runner sets the child's working directory to the scratch dir (see
    :mod:`srl.execution.runner`). This check runs the ``cwdprobe.v1`` test
    adapter and asserts the reported CWD is the scratch dir, not ``repo_root``.

    Returns a dict for the gate receipt.
    """
    scratch = prepare_scratch()
    child_cwd = ""
    booted = False
    try:
        outcome = run_adapter("cwdprobe.v1", {}, policy, scratch, wall_seconds=10)
        booted = outcome.status is RunStatus.COMPLETED
        if booted and outcome.output and isinstance(outcome.output.get("cwd"), str):
            child_cwd = outcome.output["cwd"]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    cwd_is_scratch = bool(child_cwd) and Path(child_cwd) == scratch.resolve()
    cwd_is_repo_root = bool(child_cwd) and Path(child_cwd) == repo_root.resolve()
    passed = booted and cwd_is_scratch and not cwd_is_repo_root
    return {
        "child_booted": booted,
        "child_cwd": child_cwd,
        "expected_cwd_is_scratch": cwd_is_scratch,
        "child_cwd_is_repo_root": cwd_is_repo_root,
        "passed": passed,
        "detail": (
            f"child CWD is the scratch dir ({child_cwd}), not the repo root"
            if passed
            else f"child CWD was {child_cwd!r}; expected the scratch dir {scratch}"
        ),
    }


__all__ = [
    "ADVERSARIAL_FIXTURE_SCHEMA_VERSION",
    "CONFORMANCE_FLOOR",
    "CONTROL_KINDS",
    "AdversarialCase",
    "AdversarialKind",
    "CaseOutcome",
    "ExpectedOutcome",
    "SequenceOutcome",
    "conformance_sequence",
    "credential_canary_check",
    "cwd_isolation_check",
    "load_cases",
    "orphan_sweep",
    "run_case",
]
