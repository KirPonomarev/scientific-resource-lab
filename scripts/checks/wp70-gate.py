#!/usr/bin/env python3
"""WP-H70 acceptance gate for the P1 admission framework.

Runs the four WP-H70 checks, prints a single canonical ``GateReceipt/v1`` JSON
line to stdout, and exits 0 only if every check PASSes. The gate exercises the
P1 admission evaluator in :mod:`srl.packs.p1` against the canonical policy at
``policies/p1-admission.json``.

Checks
------
H70-01 full-evidence candidate admitted
    A synthetic candidate carrying evidence for all eight requirements returns
    ``ADMIT_TO_PIPELINE`` with an empty ``missing`` list.

H70-02 each missing requirement yields its typed verdict
    Removing each requirement one at a time returns the typed verdict for that
    requirement (``WAIT_LICENSE`` for ``license_closure``, ``WAIT_RESOURCE`` for
    ``resource_measurement``, ``REJECT_CONTRACT`` for ``removal_rollback_path``,
    ``WAIT_CAPABILITY`` for the five capability-class requirements) and reports
    exactly that requirement id as missing.

H70-03 first-wave candidates produce typed WAIT verdicts
    The four first-wave candidate cards produce typed ``WAIT_*`` verdicts with
    explicit missing evidence. No card is faked into ``ADMIT_TO_PIPELINE``.

H70-04 license-unknown candidate held at WAIT_LICENSE
    A candidate with all capability/resource/rollback evidence present but no
    ``license_closure`` evidence returns ``WAIT_LICENSE``.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp70-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.packs.p1 import (  # noqa: E402
    FIRST_WAVE_CANDIDATES,
    P1_REQUIREMENTS,
    VERDICT_ADMIT_TO_PIPELINE,
    VERDICT_REJECT_CONTRACT,
    VERDICT_WAIT_CAPABILITY,
    VERDICT_WAIT_LICENSE,
    VERDICT_WAIT_RESOURCE,
    evaluate_p1_candidate,
    load_default_p1_policy,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-H70"

# Requirement id -> the verdict it must force when it is the sole missing
# requirement. Capability-class requirements default to WAIT_CAPABILITY.
_SOLO_VERDICT: Final[dict[str, str]] = {
    "license_closure": VERDICT_WAIT_LICENSE,
    "resource_measurement": VERDICT_WAIT_RESOURCE,
    "removal_rollback_path": VERDICT_REJECT_CONTRACT,
}


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _full_candidate(candidate_id: str = "h70.synthetic.full") -> dict[str, Any]:
    """Return a synthetic candidate carrying evidence for all eight requirements."""
    return {
        "candidate_id": candidate_id,
        "evidence": {rid: {"satisfied": True} for rid in P1_REQUIREMENTS},
    }


def _policy() -> dict[str, Any]:
    """Load the canonical P1 policy document as a raw dict for the evaluator."""
    policy_path = _REPO_ROOT / "policies" / "p1-admission.json"
    return json.loads(policy_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# H70-01: full-evidence candidate admitted.
# ---------------------------------------------------------------------------


def _check_h70_01() -> dict[str, Any]:
    """H70-01: a fully-evidenced synthetic candidate is ADMIT_TO_PIPELINE."""
    try:
        verdict = evaluate_p1_candidate(_full_candidate(), _policy())
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    errors: list[str] = []
    if verdict.verdict != VERDICT_ADMIT_TO_PIPELINE:
        errors.append(f"verdict={verdict.verdict!r}, expected {VERDICT_ADMIT_TO_PIPELINE!r}")
    if verdict.missing != ():
        errors.append(f"missing={list(verdict.missing)!r}, expected empty")
    if verdict.candidate_id != "h70.synthetic.full":
        errors.append(f"candidate_id={verdict.candidate_id!r}")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": "fully-evidenced synthetic candidate admitted with no missing requirements",
    }


# ---------------------------------------------------------------------------
# H70-02: each missing requirement yields its typed verdict.
# ---------------------------------------------------------------------------


def _check_h70_02() -> dict[str, Any]:
    """H70-02: each requirement, removed alone, yields its typed verdict."""
    base = _full_candidate(candidate_id="h70.solo")
    cases: list[dict[str, Any]] = []
    for rid in P1_REQUIREMENTS:
        candidate = copy.deepcopy(base)
        del candidate["evidence"][rid]
        try:
            verdict = evaluate_p1_candidate(candidate, _policy())
        except Exception as exc:  # gate must capture and report any failure.
            cases.append(
                {
                    "requirement": rid,
                    "pass": False,
                    "reason": f"unexpected {type(exc).__name__}: {exc}",
                }
            )
            continue
        expected = _SOLO_VERDICT.get(rid, VERDICT_WAIT_CAPABILITY)
        ok = verdict.verdict == expected and list(verdict.missing) == [rid]
        cases.append(
            {
                "requirement": rid,
                "verdict": verdict.verdict,
                "expected": expected,
                "missing": list(verdict.missing),
                "pass": ok,
            }
        )

    failures = [c["requirement"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"typed-verdict checks failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "each missing requirement yields its typed verdict with exactly that id missing"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# H70-03: first-wave candidates produce typed WAIT verdicts.
# ---------------------------------------------------------------------------


def _check_h70_03() -> dict[str, Any]:
    """H70-03: the four first-wave candidates produce typed WAIT verdicts."""
    cases: list[dict[str, Any]] = []
    for card in FIRST_WAVE_CANDIDATES:
        try:
            verdict = evaluate_p1_candidate(card, _policy())
        except Exception as exc:  # gate must capture and report any failure.
            cases.append(
                {
                    "candidate_id": card.get("candidate_id"),
                    "pass": False,
                    "reason": f"unexpected {type(exc).__name__}: {exc}",
                }
            )
            continue
        # No first-wave card may be faked into ADMIT; all must be typed WAIT_*.
        is_wait = verdict.verdict.startswith("WAIT_")
        ok = is_wait and verdict.candidate_id == card["candidate_id"] and len(verdict.missing) > 0
        cases.append(
            {
                "candidate_id": verdict.candidate_id,
                "verdict": verdict.verdict,
                "missing": list(verdict.missing),
                "pass": ok,
            }
        )

    failures = [c["candidate_id"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"first-wave candidate verdicts failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "the four first-wave candidates produce typed WAIT verdicts with explicit "
            "missing evidence; none faked into ADMIT"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# H70-04: license-unknown candidate held at WAIT_LICENSE.
# ---------------------------------------------------------------------------


def _check_h70_04() -> dict[str, Any]:
    """H70-04: a candidate with no license_closure evidence returns WAIT_LICENSE.

    The candidate carries evidence for every capability-class requirement, the
    resource measurement, and the rollback path, so the only missing requirement
    is ``license_closure``. The verdict must be ``WAIT_LICENSE`` (license gaps
    outrank capability/resource gaps), proving the license-unknown policy
    independently of the capability cards.
    """
    candidate = {"candidate_id": "h70.license-unknown", "evidence": {}}
    # Every requirement except license_closure carries evidence.
    for rid in P1_REQUIREMENTS:
        if rid != "license_closure":
            candidate["evidence"][rid] = {"satisfied": True}

    try:
        verdict = evaluate_p1_candidate(candidate, _policy())
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    errors: list[str] = []
    if verdict.verdict != VERDICT_WAIT_LICENSE:
        errors.append(f"verdict={verdict.verdict!r}, expected {VERDICT_WAIT_LICENSE!r}")
    if list(verdict.missing) != ["license_closure"]:
        errors.append(f"missing={list(verdict.missing)!r}, expected ['license_closure']")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": (
            "license-unknown candidate held at WAIT_LICENSE with only license_closure missing"
        ),
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the gate receipt."""
    checks = {
        "H70-01": _check_h70_01(),
        "H70-02": _check_h70_02(),
        "H70-03": _check_h70_03(),
        "H70-04": _check_h70_04(),
    }

    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    policy = load_default_p1_policy()
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            "policy_id": policy.policy_id,
            "policy_schema_version": policy.schema_version,
            "requirements": list(P1_REQUIREMENTS),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    if args and args[0] == "--check":
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
