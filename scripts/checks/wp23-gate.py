#!/usr/bin/env python3
"""WP-C23 acceptance gate for the pack admission pipeline.

Runs the six WP-C23 checks, prints a single canonical ``GateReceipt/v1`` JSON
line to stdout, and exits 0 only if every check PASSes. The gate exercises the
linear nine-stage admission machine and its typed terminal rejections using
synthetic evidence dicts.

Checks
------
C23-01 full linear admission
    Advancing a pack through all eight transitions from ``DISCOVERED`` to
    ``EXPERIMENTAL_ACCEPTED`` with valid evidence succeeds and produces a correct
    receipt chain.

C23-02 stage skip rejected
    Skipping a mandatory stage (e.g., ``DISCOVERED`` -> ``BUILT``) raises
    ``AdmissionError`` with ``CONTRACT_INVALID``.

C23-03 source verification failure
    Failing source verification raises ``AdmissionError`` with
    ``UPSTREAM_SOURCE_UNVERIFIED``.

C23-04 license policy
    An unknown license raises ``LICENSE_UNKNOWN``; an incompatible license raises
    ``LICENSE_INCOMPATIBLE``.

C23-05 lock drift
    Lock drift raises ``DEPENDENCY_LOCK_DRIFT``.

C23-06 build, byte, and probe integrity
    An invalid manifest build and a byte-tree mismatch raise
    ``PACK_INTEGRITY_FAILURE``; failed runtime and actual-compute probes raise
    ``ACTUAL_COMPUTE_FAILED``; accepting from ``RUNTIME_PROBED`` without the
    actual-compute probe stage raises ``PACK_PROBE_ONLY``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp23-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON  # noqa: E402
from srl.packs import (  # noqa: E402
    ACTUAL_COMPUTE_FAILED_REASON,
    DEPENDENCY_LOCK_DRIFT_REASON,
    LICENSE_INCOMPATIBLE_REASON,
    LICENSE_UNKNOWN_REASON,
    PACK_INTEGRITY_FAILURE_REASON,
    PACK_PROBE_ONLY_REASON,
    UPSTREAM_SOURCE_UNVERIFIED_REASON,
    AdmissionError,
    advance,
    initial_state,
)
from srl.packs.receipts import STAGES  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-C23"

# Short aliases for the fail reasons used in assertions below.
CONTRACT_INVALID: Final[str] = CONTRACT_INVALID_FAIL_REASON
UPSTREAM_SOURCE_UNVERIFIED: Final[str] = UPSTREAM_SOURCE_UNVERIFIED_REASON
LICENSE_UNKNOWN: Final[str] = LICENSE_UNKNOWN_REASON
LICENSE_INCOMPATIBLE: Final[str] = LICENSE_INCOMPATIBLE_REASON
DEPENDENCY_LOCK_DRIFT: Final[str] = DEPENDENCY_LOCK_DRIFT_REASON
PACK_INTEGRITY_FAILURE: Final[str] = PACK_INTEGRITY_FAILURE_REASON
ACTUAL_COMPUTE_FAILED: Final[str] = ACTUAL_COMPUTE_FAILED_REASON
PACK_PROBE_ONLY: Final[str] = PACK_PROBE_ONLY_REASON


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _valid_evidence(stage: str) -> dict[str, Any]:
    """Return evidence that passes the gate for ``stage``."""
    evidence_by_stage: dict[str, dict[str, Any]] = {
        "SOURCE_VERIFIED": {"kind": "source_verification", "verified": True},
        "LICENSE_CLEARED": {"kind": "license_clearance", "status": "allowed", "spdx": "MIT"},
        "LOCKED": {"kind": "lock_digest", "drift": False},
        "BUILT": {"kind": "build_manifest", "valid": True},
        "BYTE_VERIFIED": {"kind": "tree_hash", "matched": True},
        "RUNTIME_PROBED": {"kind": "runtime_probe", "passed": True},
        "ACTUAL_COMPUTE_PROBED": {"kind": "actual_compute_probe", "passed": True},
        "EXPERIMENTAL_ACCEPTED": {"kind": "experimental_accept", "detail": "admitted"},
    }
    return evidence_by_stage[stage]


def _advance_to(stage: str, pack_id: str = "wp23.pack") -> Any:
    """Advance ``pack_id`` to ``stage`` inclusive and return the state."""
    state = initial_state(pack_id)
    for s in STAGES[1:]:
        state, _ = advance(state, s, _valid_evidence(s))
        if s == stage:
            return state
    return state


# ---------------------------------------------------------------------------
# C23-01: full linear admission.
# ---------------------------------------------------------------------------


def _check_c23_01() -> dict[str, Any]:
    """C23-01: all eight transitions succeed and chain correctly."""
    state = initial_state("wp23.c23-01.pack")
    receipts: list[Any] = []
    for stage in STAGES[1:]:
        state, receipt = advance(state, stage, _valid_evidence(stage))
        receipts.append(receipt)

    errors: list[str] = []
    if state.current_stage != "EXPERIMENTAL_ACCEPTED":
        errors.append(f"final stage is {state.current_stage!r}")
    if len(receipts) != len(STAGES) - 1:
        errors.append(f"expected {len(STAGES) - 1} receipts, got {len(receipts)}")
    for i, receipt in enumerate(receipts):
        expected_stage = STAGES[i + 1]
        if receipt.stage != expected_stage:
            errors.append(f"receipt[{i}].stage={receipt.stage!r} != {expected_stage!r}")
        expected_from = STAGES[i]
        if receipt.from_stage != expected_from:
            errors.append(f"receipt[{i}].from_stage={receipt.from_stage!r} != {expected_from!r}")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": "full linear admission produced 8 valid receipts",
    }


# ---------------------------------------------------------------------------
# C23-02: stage skip rejected.
# ---------------------------------------------------------------------------


def _check_c23_02() -> dict[str, Any]:
    """C23-02: skipping a mandatory stage is a structural contract error."""
    state = initial_state("wp23.c23-02.pack")
    try:
        advance(state, "BUILT", _valid_evidence("BUILT"))
        return {"status": "FAIL", "detail": "DISCOVERED -> BUILT skip was accepted"}
    except AdmissionError as exc:
        if exc.fail_reason == CONTRACT_INVALID:
            return {
                "status": "PASS",
                "detail": "DISCOVERED -> BUILT skip rejected with CONTRACT_INVALID",
            }
        return {
            "status": "FAIL",
            "detail": f"skip rejected with wrong fail_reason: {exc.fail_reason!r}",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# C23-03: source verification failure.
# ---------------------------------------------------------------------------


def _check_c23_03() -> dict[str, Any]:
    """C23-03: failed source verification raises UPSTREAM_SOURCE_UNVERIFIED."""
    state = initial_state("wp23.c23-03.pack")
    try:
        advance(state, "SOURCE_VERIFIED", {"kind": "source_verification", "verified": False})
        return {
            "status": "FAIL",
            "detail": "failed source verification was accepted",
        }
    except AdmissionError as exc:
        if exc.fail_reason == UPSTREAM_SOURCE_UNVERIFIED:
            return {
                "status": "PASS",
                "detail": "source verification failure rejected with UPSTREAM_SOURCE_UNVERIFIED",
            }
        return {
            "status": "FAIL",
            "detail": (
                f"source verification failure rejected with wrong fail_reason: {exc.fail_reason!r}"
            ),
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# C23-04: license policy.
# ---------------------------------------------------------------------------


def _check_c23_04() -> dict[str, Any]:
    """C23-04: unknown and incompatible licenses are rejected."""
    state = initial_state("wp23.c23-04.pack")
    state, _ = advance(state, "SOURCE_VERIFIED", _valid_evidence("SOURCE_VERIFIED"))
    cases: list[dict[str, Any]] = []
    for name, evidence, expected in (
        (
            "unknown",
            {"kind": "license_clearance", "status": "unknown", "spdx": "Weird-License"},
            LICENSE_UNKNOWN,
        ),
        (
            "incompatible",
            {"kind": "license_clearance", "status": "incompatible", "spdx": "GPL-3.0"},
            LICENSE_INCOMPATIBLE,
        ),
    ):
        try:
            advance(state, "LICENSE_CLEARED", evidence)
            cases.append({"case": name, "pass": False, "reason": "no exception raised"})
        except AdmissionError as exc:
            cases.append(
                {
                    "case": name,
                    "pass": exc.fail_reason == expected,
                    "reason": exc.fail_reason,
                }
            )
        except Exception as exc:
            cases.append(
                {
                    "case": name,
                    "pass": False,
                    "reason": f"unexpected {type(exc).__name__}: {exc}",
                }
            )

    failures = [c["case"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"license policy checks failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "unknown license rejected as LICENSE_UNKNOWN, incompatible as LICENSE_INCOMPATIBLE"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C23-05: lock drift.
# ---------------------------------------------------------------------------


def _check_c23_05() -> dict[str, Any]:
    """C23-05: dependency lock drift raises DEPENDENCY_LOCK_DRIFT."""
    state = _advance_to("LICENSE_CLEARED", pack_id="wp23.c23-05.pack")
    try:
        advance(state, "LOCKED", {"kind": "lock_digest", "drift": True})
        return {"status": "FAIL", "detail": "lock drift was accepted"}
    except AdmissionError as exc:
        if exc.fail_reason == DEPENDENCY_LOCK_DRIFT:
            return {
                "status": "PASS",
                "detail": "lock drift rejected with DEPENDENCY_LOCK_DRIFT",
            }
        return {
            "status": "FAIL",
            "detail": f"lock drift rejected with wrong fail_reason: {exc.fail_reason!r}",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# C23-06: build, byte, and probe integrity.
# ---------------------------------------------------------------------------


def _run_subcase(
    advance_to: str,
    target_stage: str,
    evidence: dict[str, Any],
    expected_reason: str,
    case: str,
) -> dict[str, Any]:
    """Advance to ``advance_to`` and assert the transition fails as expected."""
    state = _advance_to(advance_to, pack_id="wp23.c23-06.pack")
    try:
        advance(state, target_stage, evidence)
    except AdmissionError as exc:
        return {
            "case": case,
            "pass": exc.fail_reason == expected_reason,
            "reason": exc.fail_reason,
        }
    except Exception as exc:
        return {
            "case": case,
            "pass": False,
            "reason": f"unexpected {type(exc).__name__}: {exc}",
        }
    return {"case": case, "pass": False, "reason": "no exception raised"}


def _check_c23_06() -> dict[str, Any]:
    """C23-06: integrity and probe failures return the typed fail reasons."""
    cases = [
        _run_subcase(
            "LOCKED",
            "BUILT",
            {"kind": "build_manifest", "valid": False},
            PACK_INTEGRITY_FAILURE,
            "build_manifest_invalid",
        ),
        _run_subcase(
            "BUILT",
            "BYTE_VERIFIED",
            {"kind": "tree_hash", "matched": False},
            PACK_INTEGRITY_FAILURE,
            "byte_tree_mismatch",
        ),
        _run_subcase(
            "BYTE_VERIFIED",
            "RUNTIME_PROBED",
            {"kind": "runtime_probe", "passed": False},
            ACTUAL_COMPUTE_FAILED,
            "runtime_probe_failure",
        ),
        _run_subcase(
            "RUNTIME_PROBED",
            "ACTUAL_COMPUTE_PROBED",
            {"kind": "actual_compute_probe", "passed": False},
            ACTUAL_COMPUTE_FAILED,
            "actual_compute_probe_failure",
        ),
        _run_subcase(
            "RUNTIME_PROBED",
            "EXPERIMENTAL_ACCEPTED",
            _valid_evidence("EXPERIMENTAL_ACCEPTED"),
            PACK_PROBE_ONLY,
            "probe_only_skip",
        ),
    ]

    failures = [c["case"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"integrity/probe checks failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "build/byte integrity failures returned PACK_INTEGRITY_FAILURE, "
            "probe failures returned ACTUAL_COMPUTE_FAILED, "
            "and probe-only skip returned PACK_PROBE_ONLY"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all six checks and assemble the gate receipt."""
    checks = {
        "C23-01": _check_c23_01(),
        "C23-02": _check_c23_02(),
        "C23-03": _check_c23_03(),
        "C23-04": _check_c23_04(),
        "C23-05": _check_c23_05(),
        "C23-06": _check_c23_06(),
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
            "stages": list(STAGES),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    if args and args[0] == "--check":
        # Single-check mode is not implemented for C23; re-run the whole receipt.
        receipt = _build_receipt()
        _emit(receipt)
        return 0 if receipt["overall"] == "PASS" else 1

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
