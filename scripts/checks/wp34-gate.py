#!/usr/bin/env python3
"""WP-D34 acceptance gate for the adversarial runner suite.

Runs the three WP-D34 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI.

The checks
----------
D34-01 all 14 adversarial kinds produce their expected outcome
    Every :class:`~srl.execution.adversarial.AdversarialKind` (command_injection,
    path_injection, archive_traversal, symlink_device, memory_bomb, fork_bomb,
    output_bomb, timeout, network_canary, credential_canary, wrong_platform,
    corrupted_input, schema_invalid_output, partial_receipt) is loaded from
    ``fixtures/conformance/adversarial/`` and run against the REAL runner. Each
    case's observed status must match its declared expectation, and — the
    load-bearing invariant — a policy/limit/output-schema violation must NEVER
    produce a valid run receipt (asserted per case by scanning the scratch dir).

D34-02 50 sequential golden+adversarial executions leave zero orphans
    A sequence of 50 executions (golden ``echo.v1`` runs interleaved with the
    adversarial cases) completes with the receipt-last invariant intact, and a
    final process-group sweep (:func:`~srl.execution.adversarial.orphan_sweep`)
    finds zero surviving processes. The sweep is the setsid-evasion detector.

D34-03 hardening: child cwd is the scratch dir; setsid-evasion detector exists
    The child's working directory is NOT the parent repo root (the runner sets
    ``cwd`` to the scratch dir — verified via the ``cwdprobe.v1`` adapter), and
    the orphan sweep walks ``/proc`` on Linux and ``/bin/ps`` on macOS by
    process name/pgid (the setsid-evasion detector; platform limits documented).

The gate enables the test-only adapter hook via ``SRL_RUNNER_TEST_ADAPTERS=1``
so ``sleeper.v1`` / ``bomb.v1`` / ``forker.v1`` / ``chatter.v1`` /
``netcanary.v1`` / ``cwdprobe.v1`` / ``setsiddler.v1`` are importable. This env
var is a test signal (it loads a fixed in-repo module, not caller data) and is
never set in production.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as ``python3 scripts/checks/wp34-gate.py``
without a prior ``uv run``, and also works under ``uv run``. Total runtime is
kept under 120s.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp34-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Enable the test-only adapter hook for the duration of this gate. The hook
# loads a fixed in-repo module (srl.execution._test_adapters); it never reads
# caller data. The shipped production registry (without this var) is exactly
# {echo.v1, uppercase.v1}.
os.environ["SRL_RUNNER_TEST_ADAPTERS"] = "1"

from srl.execution import (  # noqa: E402
    load_policy,
    prepare_scratch,
    run_adapter,
)
from srl.execution.adversarial import (  # noqa: E402
    CONFORMANCE_FLOOR,
    AdversarialKind,
    conformance_sequence,
    cwd_isolation_check,
    load_cases,
    orphan_sweep,
    run_case,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-D34"

# The canonical M1 policy path.
_POLICY_PATH: Final[Path] = _REPO_ROOT / "policies" / "resource-policy-m1.json"

# The fixture directory for the adversarial case descriptors.
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "adversarial"

# The expected number of distinct adversarial kinds (one fixture per kind).
_EXPECTED_KINDS: Final[int] = 14

# The gate runtime ceiling (seconds). The 50-run sequence dominates; on a warm
# machine it completes well under this. Documented for CI timeout budgeting.
_GATE_RUNTIME_CEILING_SECONDS: Final[int] = 120


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout.

    Local canonical encoder (same form as ``srl.contracts.canonical.dumps`` and
    the runner's internal encoder) so the gate stays standard-library-only and
    does not pull the contracts package (and its ``jsonschema`` dependency).
    """
    text = json.dumps(
        receipt,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# D34-01 all 14 adversarial kinds produce their expected outcome.
# ---------------------------------------------------------------------------


def _check_d34_01() -> dict[str, Any]:
    """D34-01: every adversarial kind matches its expectation; no receipt on violation.

    Loads the 14 fixtures, runs each against the real runner, and asserts:
    (a) the observed status matches the declared expectation; and
    (b) a policy/limit violation never produces a valid run receipt — for every
    non-completed run, ``receipt_written`` is False AND the scratch dir has
    zero ``receipt-*.json`` files.
    """
    policy = load_policy(_POLICY_PATH)
    cases = load_cases(_FIXTURES)
    case_outcomes = [run_case(c, policy) for c in cases]

    # (a) every kind is represented exactly once.
    kinds_seen = sorted({c.kind.value for c in cases})
    all_kinds = sorted(k.value for k in AdversarialKind)
    kinds_complete = kinds_seen == all_kinds and len(cases) == _EXPECTED_KINDS

    # (b) every case matched its expectation.
    unmatched = [co.to_dict() for co in case_outcomes if not co.matched]

    # (c) the receipt-last oracle: for every case whose observed status is not
    # 'completed' (i.e. a violation / bounded outcome), no receipt was written
    # and the scratch dir held zero receipts. A violation that produced a
    # receipt is a hard failure of this check.
    receipt_violations = [
        co.to_dict()
        for co in case_outcomes
        if co.observed_status != "completed" and (co.receipt_written or co.receipts_in_scratch != 0)
    ]

    failures: list[str] = []
    if not kinds_complete:
        failures.append(
            f"expected {_EXPECTED_KINDS} kinds ({all_kinds}); saw {len(cases)} ({kinds_seen})"
        )
    if unmatched:
        failures.append(f"{len(unmatched)} case(s) did not match their expectation")
    if receipt_violations:
        failures.append(
            f"{len(receipt_violations)} violation case(s) produced a receipt (receipt-last broken)"
        )

    if failures:
        return {
            "status": "FAIL",
            "detail": "; ".join(failures),
            "kinds_seen": kinds_seen,
            "all_kinds": all_kinds,
            "unmatched": unmatched,
            "receipt_violations": receipt_violations,
            "cases": [co.to_dict() for co in case_outcomes],
        }
    return {
        "status": "PASS",
        "detail": (
            f"all {_EXPECTED_KINDS} adversarial kinds produced their expected outcome; "
            "every policy/limit violation wrote zero receipts (receipt-last holds)"
        ),
        "kinds_seen": kinds_seen,
        "cases": [co.to_dict() for co in case_outcomes],
    }


# ---------------------------------------------------------------------------
# D34-02 50 sequential golden+adversarial executions leave zero orphans.
# ---------------------------------------------------------------------------


def _check_d34_02() -> dict[str, Any]:
    """D34-02: the 50-run conformance floor completes with zero orphan survivors.

    Runs the conformance sequence (golden echo.v1 runs interleaved with the
    adversarial cases), then performs the final orphan sweep. The receipt-last
    invariant must hold across all 50 runs, and the sweep must find zero
    surviving processes.
    """
    policy = load_policy(_POLICY_PATH)
    cases = load_cases(_FIXTURES)
    started = time.monotonic()
    seq = conformance_sequence(cases, policy)
    elapsed = round(time.monotonic() - started, 6)

    # An independent sweep right after the sequence's own sweep, to be sure.
    extra_survivors = orphan_sweep()

    failures: list[str] = []
    if seq.total != CONFORMANCE_FLOOR:
        failures.append(f"sequence ran {seq.total} executions, expected {CONFORMANCE_FLOOR}")
    if not seq.receipt_last_holds:
        failures.append("the receipt-last invariant did not hold across the 50 runs")
    if seq.orphan_survivors:
        failures.append(
            f"the sequence's orphan sweep found {len(seq.orphan_survivors)} survivor(s): "
            f"{seq.orphan_survivors[:8]}"
        )
    if extra_survivors:
        failures.append(
            f"an independent post-sequence sweep found {len(extra_survivors)} survivor(s): "
            f"{extra_survivors[:8]}"
        )

    seq_dict = seq.to_dict()
    seq_dict["elapsed_seconds"] = elapsed
    seq_dict["extra_sweep_survivors"] = extra_survivors

    if failures:
        return {
            "status": "FAIL",
            "detail": "; ".join(failures),
            "sequence": seq_dict,
        }
    return {
        "status": "PASS",
        "detail": (
            f"{CONFORMANCE_FLOOR} sequential golden+adversarial executions completed in "
            f"{elapsed:.1f}s with zero orphan survivors; receipt-last held throughout"
        ),
        "sequence": seq_dict,
    }


# ---------------------------------------------------------------------------
# D34-03 hardening: child cwd + setsid-evasion detector.
# ---------------------------------------------------------------------------


def _check_d34_03() -> dict[str, Any]:
    """D34-03: child cwd is the scratch dir; the setsid-evasion detector exists.

    Two assertions:
    1. The child's working directory is the scratch dir, NOT the repo root
       (verified via the ``cwdprobe.v1`` adapter which returns ``os.getcwd()``).
    2. The orphan sweep (:func:`orphan_sweep`) is present and walks the live
       process table by name/pgid (the setsid-evasion detector). It is exercised
       against a ``setsiddler.v1`` grandchild that escapes the group; the sweep
       must run without error and the grandchild must not survive the run.
    """
    policy = load_policy(_POLICY_PATH)

    # Assertion 1: cwd isolation.
    cwd_check = cwd_isolation_check(policy, _REPO_ROOT)

    # Assertion 2: the setsid-evasion detector exists and runs. We run the
    # setsiddler adapter (which forks a setsid grandchild that lingers briefly),
    # then immediately sweep. The grandchild is reaped by the handler before it
    # returns, so the sweep should find nothing — but the point is that the
    # sweep *ran* and *could* find a survivor if one existed.
    scratch = prepare_scratch()
    sweep_ran = False
    sweep_after_setsiddler: list[int] = []
    setsiddler_detail = ""
    try:
        outcome = run_adapter("setsiddler.v1", {"linger": 1}, policy, scratch, wall_seconds=8)
        setsiddler_detail = (
            f"setsiddler.v1 status={outcome.status.value}; "
            f"output={outcome.output}; receipt_written={outcome.receipt_written}"
        )
        survivors = orphan_sweep()
        sweep_ran = True
        sweep_after_setsiddler = survivors
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    failures: list[str] = []
    if not cwd_check["passed"]:
        failures.append(f"child cwd was not the scratch dir: {cwd_check['detail']}")
    if not sweep_ran:
        failures.append("the orphan sweep did not run")
    if sweep_after_setsiddler:
        failures.append(
            f"the sweep found {len(sweep_after_setsiddler)} survivor(s) after setsiddler: "
            f"{sweep_after_setsiddler[:8]}"
        )

    if failures:
        return {
            "status": "FAIL",
            "detail": "; ".join(failures),
            "cwd_check": cwd_check,
            "sweep_ran": sweep_ran,
            "sweep_after_setsiddler": sweep_after_setsiddler,
            "setsiddler_detail": setsiddler_detail,
            "platform": sys.platform,
        }
    return {
        "status": "PASS",
        "detail": (
            f"child cwd is the scratch dir (not the repo root); the orphan sweep "
            f"runs on {sys.platform} and found no survivor after a setsid-evading "
            f"grandchild. Platform limits documented in docs/security/adversarial-runner.md."
        ),
        "cwd_check": cwd_check,
        "sweep_ran": sweep_ran,
        "sweep_after_setsiddler": sweep_after_setsiddler,
        "setsiddler_detail": setsiddler_detail,
        "platform": sys.platform,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: fixtures, policy, platform, conformance floor."""
    return {
        "policy_path": str(_POLICY_PATH.relative_to(_REPO_ROOT)),
        "fixtures_path": str(_FIXTURES.relative_to(_REPO_ROOT)),
        "platform": sys.platform,
        "conformance_floor": CONFORMANCE_FLOOR,
        "expected_kinds": _EXPECTED_KINDS,
        "gate_runtime_ceiling_seconds": _GATE_RUNTIME_CEILING_SECONDS,
    }


def _build_receipt() -> dict[str, Any]:
    """Run all three checks and assemble the GateReceipt/v1 dict."""
    gate_started = time.monotonic()
    checks = {
        "D34-01": _check_d34_01(),
        "D34-02": _check_d34_02(),
        "D34-03": _check_d34_03(),
    }
    gate_elapsed = round(time.monotonic() - gate_started, 6)
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "gate_elapsed_seconds": gate_elapsed,
        "within_runtime_ceiling": gate_elapsed <= _GATE_RUNTIME_CEILING_SECONDS,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            **_evidence(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "D34-01": _check_d34_01,
            "D34-02": _check_d34_02,
            "D34-03": _check_d34_03,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "error": f"unknown check {cid}"})
            return 2
        result = runner()
        _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "check": cid, **result})
        return 0 if result["status"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
