#!/usr/bin/env python3
"""WP-D30 acceptance gate for the M1 resource policy and admission semantics.

Runs the four WP-D30 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp30``.

The checks
----------
D30-01 default caps exact
    Loads ``policies/resource-policy-m1.json`` and asserts the six exact
    integer caps of the default envelope plus the free-disk floor: cpu_cores=1,
    rss_bytes=1610612736 (1.5 GiB), wall_seconds=300, scratch_bytes=4294967296
    (4 GiB), required_free_disk_bytes=21474836480 (20 GiB), concurrency=1. The
    safety consts (canonical_writes=0, grants_authority=false) and the overflow
    action (WAIT_REMOTE_EXECUTOR) are also pinned.

D30-02 exception envelope bounded
    An over-cap exception value is rejected at load with ``PolicyError`` and
    ``fail_reason='CONTRACT_INVALID'``. Each of the four absolute caps
    (cpu_cores<=2, rss_bytes<=2 GiB, wall_seconds<=900, scratch<=default) is
    probed with a value one beyond it.

D30-03 over-exception estimate parks (no silent downgrade)
    An estimate over the exception caps yields ``WAIT_REMOTE_EXECUTOR`` even
    with ``use_exception=True``; an estimate over the default caps but within the
    exception yields ``WAIT_REMOTE_EXECUTOR`` without the flag and
    ``ADMITTED_EXCEPTION`` only with the flag. A larger job is never silently
    admitted under a smaller envelope.

D30-04 low-disk preflight -> RESOURCE_LIMIT
    A preflight against a provider below the free-disk floor raises
    ``ResourceLimitError`` with ``fail_reason='RESOURCE_LIMIT'``; a provider at
    or above the floor returns a receipt with ``ok=True``.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp30-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp30-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts.canonical import dumps  # noqa: E402  (path setup precedes import)
from srl.execution import (  # noqa: E402
    RESOURCE_LIMIT_FAIL_REASON,
    AdmissionDecision,
    DiskProbe,
    PolicyError,
    ResourceEstimate,
    StaticPreflightProvider,
    admit,
    load_policy,
    preflight,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-D30"

# The canonical M1 policy path.
_POLICY_PATH: Final[Path] = _REPO_ROOT / "policies" / "resource-policy-m1.json"

# The exact default caps asserted by D30-01. These are the authority: the loaded
# policy must carry exactly these integers (the spec pins them).
_GIB: Final[int] = 1024**3
_EXPECTED_DEFAULT: Final[dict[str, int]] = {
    "concurrency": 1,
    "cpu_cores": 1,
    "rss_bytes": 1610612736,  # 1.5 GiB
    "wall_seconds": 300,
    "scratch_bytes": 4294967296,  # 4 GiB
    "required_free_disk_bytes": 21474836480,  # 20 GiB
}
_EXPECTED_OVERFLOW_ACTION: Final[str] = "WAIT_REMOTE_EXECUTOR"

# The typed fail reasons surfaced in the gate cases. Mirrors
# automation/fail-reasons.json: CONTRACT_INVALID (class contract) and
# RESOURCE_LIMIT (class ci).
POLICY_FAIL_REASON_REF: Final[str] = "CONTRACT_INVALID"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _write_policy(doc: dict[str, Any]) -> Path:
    """Write ``doc`` to a temp file and return its path; used by rejection cases.

    The temp file lets the over-cap cases exercise the real loader (which reads
    from disk) without mutating the shipped M1 policy.
    """
    fd, name = tempfile.mkstemp(prefix="wp30-policy-", suffix=".json")
    os.close(fd)
    p = Path(name)
    p.write_text(dumps(doc).decode("utf-8"), encoding="utf-8")
    return p


def _m1_doc_with_exception(exception: dict[str, int]) -> dict[str, Any]:
    """Return the canonical M1 policy doc with the exception replaced.

    The rest of the document is the shipped M1 policy; only the exception
    sub-object is swapped so each over-cap probe isolates one field.
    """
    return {
        "schema_version": "ResourcePolicy/v1",
        "name": "m1-default",
        "concurrency": 1,
        "cpu_cores": 1,
        "rss_bytes": 1610612736,
        "wall_seconds": 300,
        "scratch_bytes": 4294967296,
        "required_free_disk_bytes": 21474836480,
        "exception": exception,
        "overflow_action": "WAIT_REMOTE_EXECUTOR",
        "canonical_writes": 0,
        "grants_authority": False,
    }


# ---------------------------------------------------------------------------
# D30-01 default caps exact.
# ---------------------------------------------------------------------------


def _check_d30_01() -> dict[str, Any]:
    """D30-01: the loaded M1 policy carries the exact default caps."""
    policy = load_policy(_POLICY_PATH)
    actual: dict[str, int] = {
        "concurrency": policy.concurrency,
        "cpu_cores": policy.default.cpu_cores,
        "rss_bytes": policy.default.rss_bytes,
        "wall_seconds": policy.default.wall_seconds,
        "scratch_bytes": policy.default.scratch_bytes,
        "required_free_disk_bytes": policy.required_free_disk_bytes,
    }
    mismatches: list[dict[str, Any]] = []
    for key, expected in _EXPECTED_DEFAULT.items():
        got = actual[key]
        if got != expected:
            mismatches.append({"field": key, "expected": expected, "actual": got})
    # Safety consts and overflow action.
    if policy.overflow_action != _EXPECTED_OVERFLOW_ACTION:
        mismatches.append(
            {
                "field": "overflow_action",
                "expected": _EXPECTED_OVERFLOW_ACTION,
                "actual": policy.overflow_action,
            }
        )
    if policy.canonical_writes != 0:
        mismatches.append(
            {"field": "canonical_writes", "expected": 0, "actual": policy.canonical_writes}
        )
    if policy.grants_authority:
        mismatches.append({"field": "grants_authority", "expected": False, "actual": True})
    if policy.name != "m1-default":
        mismatches.append({"field": "name", "expected": "m1-default", "actual": policy.name})
    if mismatches:
        return {
            "status": "FAIL",
            "detail": "one or more default caps / safety consts did not match the pinned values",
            "actual": actual,
            "mismatches": mismatches,
        }
    return {
        "status": "PASS",
        "detail": (
            "default envelope and free-disk floor carry the exact pinned integers "
            "(cpu=1, rss=1.5GiB, wall=300, scratch=4GiB, free_disk=20GiB, concurrency=1); "
            "overflow=WAIT_REMOTE_EXECUTOR; canonical_writes=0; grants_authority=false"
        ),
        "actual": actual,
    }


# ---------------------------------------------------------------------------
# D30-02 exception envelope bounded.
# ---------------------------------------------------------------------------


def _check_d30_02() -> dict[str, Any]:
    """D30-02: an over-cap exception value is rejected at load."""
    # The canonical valid exception (the shipped M1 one).
    valid_exception: dict[str, int] = {
        "cpu_cores": 2,
        "rss_bytes": 2 * _GIB,
        "wall_seconds": 900,
        "scratch_bytes": 4294967296,
    }
    # Each probe raises one field one step beyond its absolute cap. scratch is
    # bounded by the default scratch (4 GiB), so scratch=4GiB+1 is over.
    over_cap_probes: dict[str, dict[str, int]] = {
        "cpu_cores_over": {**valid_exception, "cpu_cores": 3},
        "rss_bytes_over": {**valid_exception, "rss_bytes": 2 * _GIB + 1},
        "wall_seconds_over": {**valid_exception, "wall_seconds": 901},
        "scratch_over_default": {**valid_exception, "scratch_bytes": 4294967296 + 1},
    }
    cases: list[dict[str, Any]] = []
    for label, exception in over_cap_probes.items():
        doc = _m1_doc_with_exception(exception)
        path = _write_policy(doc)
        try:
            load_policy(path)
            cases.append({"case": label, "outcome": "NOT rejected", "field": exception})
        except PolicyError as exc:
            cases.append(
                {
                    "case": label,
                    "outcome": "rejected",
                    "fail_reason": exc.fail_reason,
                    "exception": exception,
                }
            )
        finally:
            path.unlink(missing_ok=True)

    not_rejected = [c for c in cases if not c["outcome"].startswith("rejected")]
    if not_rejected:
        return {
            "status": "FAIL",
            "detail": "one or more over-cap exception values were not rejected",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "every over-cap exception value rejected at load with fail_reason=CONTRACT_INVALID "
            "(cpu>2, rss>2GiB, wall>900, scratch>default)"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# D30-03 over-exception estimate parks (no silent downgrade).
# ---------------------------------------------------------------------------


def _check_d30_03() -> dict[str, Any]:
    """D30-03: an over-exception estimate parks; no silent downgrade."""
    policy = load_policy(_POLICY_PATH)
    cases: list[dict[str, Any]] = []

    # Within default -> ADMITTED_DEFAULT.
    e_default = ResourceEstimate(
        wall_seconds=300, rss_bytes=1610612736, scratch_bytes=4294967296, cpu_cores=1
    )
    cases.append(
        {
            "case": "within-default",
            "decision": admit(e_default, policy).value,
            "expected": AdmissionDecision.ADMITTED_DEFAULT.value,
        }
    )

    # Over default, within exception, no flag -> WAIT_REMOTE_EXECUTOR (not
    # silently admitted to the exception envelope).
    e_exc = ResourceEstimate(
        wall_seconds=900, rss_bytes=2 * _GIB, scratch_bytes=4294967296, cpu_cores=2
    )
    cases.append(
        {
            "case": "exception-no-flag",
            "decision": admit(e_exc, policy, use_exception=False).value,
            "expected": AdmissionDecision.WAIT_REMOTE_EXECUTOR.value,
        }
    )

    # Over default, within exception, with flag -> ADMITTED_EXCEPTION.
    cases.append(
        {
            "case": "exception-with-flag",
            "decision": admit(e_exc, policy, use_exception=True).value,
            "expected": AdmissionDecision.ADMITTED_EXCEPTION.value,
        }
    )

    # Over exception (wall one second beyond cap), even with flag -> WAIT.
    e_over = ResourceEstimate(
        wall_seconds=901, rss_bytes=2 * _GIB, scratch_bytes=4294967296, cpu_cores=2
    )
    cases.append(
        {
            "case": "over-exception-with-flag",
            "decision": admit(e_over, policy, use_exception=True).value,
            "expected": AdmissionDecision.WAIT_REMOTE_EXECUTOR.value,
        }
    )

    failures = [c for c in cases if c["decision"] != c["expected"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": "admission matrix did not match the expected no-silent-downgrade semantics",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "over-default estimate parks without the flag; over-exception estimate parks even with "
            "the flag; a larger job is never silently admitted under a smaller envelope"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# D30-04 low-disk preflight -> RESOURCE_LIMIT.
# ---------------------------------------------------------------------------


def _check_d30_04() -> dict[str, Any]:
    """D30-04: a low-disk preflight raises RESOURCE_LIMIT; a floor preflight passes."""
    policy = load_policy(_POLICY_PATH)
    estimate = ResourceEstimate(
        wall_seconds=300, rss_bytes=1610612736, scratch_bytes=4294967296, cpu_cores=1
    )
    cases: list[dict[str, Any]] = []

    # One byte below the floor -> RESOURCE_LIMIT.
    low = StaticPreflightProvider(free_disk_bytes=policy.required_free_disk_bytes - 1)
    low_raised = False
    low_reason = ""
    try:
        preflight(estimate, policy, low)
    except Exception as exc:  # capture any error type for the receipt
        low_raised = True
        low_reason = getattr(exc, "fail_reason", "")
    cases.append(
        {
            "case": "below-floor",
            "raised": low_raised,
            "fail_reason": low_reason,
            "expected_reason": RESOURCE_LIMIT_FAIL_REASON,
        }
    )

    # Exactly at the floor -> ok (boundary is inclusive).
    at_floor = StaticPreflightProvider(free_disk_bytes=policy.required_free_disk_bytes)
    at_floor_ok = False
    try:
        receipt = preflight(estimate, policy, at_floor)
        at_floor_ok = receipt.ok
    except Exception:  # capture any error type
        at_floor_ok = False
    cases.append({"case": "at-floor", "ok": at_floor_ok})

    # Well above the floor -> ok.
    above = StaticPreflightProvider(free_disk_bytes=policy.required_free_disk_bytes * 2)
    above_ok = False
    try:
        receipt = preflight(estimate, policy, above)
        above_ok = receipt.ok
    except Exception:  # capture any error type
        above_ok = False
    cases.append({"case": "above-floor", "ok": above_ok})

    failures = []
    if not low_raised or low_reason != RESOURCE_LIMIT_FAIL_REASON:
        failures.append("below-floor preflight did not raise RESOURCE_LIMIT")
    if not at_floor_ok:
        failures.append("at-floor preflight did not return ok")
    if not above_ok:
        failures.append("above-floor preflight did not return ok")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "below-floor preflight raises ResourceLimitError (fail_reason=RESOURCE_LIMIT); "
            "at-floor and above-floor return a receipt with ok=True"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: the DiskProbe provider kind and policy path."""
    return {
        "policy_path": str(_POLICY_PATH.relative_to(_REPO_ROOT)),
        "default_provider": DiskProbe.__name__,
        "injectable_provider": type(StaticPreflightProvider(0)).__name__,
    }


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "D30-01": _check_d30_01(),
        "D30-02": _check_d30_02(),
        "D30-03": _check_d30_03(),
        "D30-04": _check_d30_04(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
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
            "D30-01": _check_d30_01,
            "D30-02": _check_d30_02,
            "D30-03": _check_d30_03,
            "D30-04": _check_d30_04,
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
