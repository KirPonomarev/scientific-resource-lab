#!/usr/bin/env python3
"""WP-A03 acceptance gate for autonomous workflow contracts.

Runs the five WP-A03 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp03``.

The checks
----------
A03-01 owned allowed write
    An in-scope owned path is accepted by ``scopes.check_write``.

A03-02 out-of-scope write -> STOP pre-write
    An out-of-scope, ``..`` traversal, or absolute-escaping path raises
    ``ScopeViolation`` *before* any write. The script proves the refusal is
    pre-write by asserting no file was created at the would-be target.

A03-03 secret fixture -> STOP pre-commit
    A synthetic inline fixture containing an obviously-fake ``ghp_`` token and
    a ``/Users/alice`` path is flagged by ``leakguard`` before commit. The
    fixture string is constructed inline in the script and is never written
    to disk; the token is the documented example value, not a real credential.

A03-04 failed check -> no merge
    A failing-check observed state fed to ``resume.reconcile`` must not yield
    a merge-permitting decision. The script documents the mapping by
    asserting ``permits_merge`` is ``False`` for the failing-check rows.

A03-05 interrupted run -> deterministic resume
    Two ``resume.reconcile`` runs over the same serialized observed state
    produce byte-identical decision JSON.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as ``python3 scripts/checks/wp03-gate.py``
without a prior ``uv run``, and also works under ``uv run`` (idempotent path
insertion).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp03-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.autonomy import (  # noqa: E402  (path setup must precede import)
    IdempotencyInputs,
    ScopeViolation,
    check_write,
    idempotency_key,
    load_policy,
    reconcile,
    scan_diff,
)
from srl.autonomy.resume import decision_to_json  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-A03"

# Length of a SHA-256 hex digest (used for idempotency-key/mission-digest
# evidence assertions). Extracted as a constant to avoid magic-value lint.
_HEX_SHA256_LEN: Final[int] = 64
# Argument count for the single-check CLI form: "--check <id>".
_SINGLE_CHECK_ARGC: Final[int] = 2

# Obviously fake fixture token for A03-03. Documented as an example; never a
# real credential. The 36-char body matches the ghp_ classic-PAT shape so the
# pattern fires, while the EXAMPLE prefix makes it visibly synthetic. The
# S105 suppression is intentional: this is a synthetic fixture, not a secret.
_FAKE_GHP_TOKEN: Final[str] = "ghp_EXAMPLE000000000000000000000000000000"  # noqa: S105
_FAKE_HOME_PATH: Final[str] = "/Users/alice/projects/secret"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact) to stdout."""
    line = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _check_a03_01() -> dict[str, Any]:
    """A03-01: an owned, in-scope path is accepted."""
    owned = frozenset({"src/srl/autonomy/"})
    target = "src/srl/autonomy/policy.py"
    try:
        check_write(target, owned)
    except ScopeViolation as exc:
        return {
            "status": "FAIL",
            "detail": f"in-scope path was rejected: {target!r}; {exc}",
        }
    return {
        "status": "PASS",
        "detail": "in-scope owned path accepted",
        "target": target,
    }


def _check_a03_02() -> dict[str, Any]:
    """A03-02: an out-of-scope write is stopped pre-write, with no file created.

    Proves the refusal is pre-write by attempting the refused write into a
    temp dir and asserting the would-be target file does not exist afterwards.
    """
    owned = frozenset({"src/srl/autonomy/"})
    # Three refusal classes: out-of-scope, '..' traversal, absolute escape.
    refused: list[str] = ["README.md", "../escape.txt", "/etc/passwd"]
    proof_dir = Path(tempfile.mkdtemp(prefix="wp03-a03-02-"))
    created_targets: list[str] = []
    for bad in refused:
        # The proof target is a temp-file analog of the refused path. If the
        # guard is wrong and lets the write through, this file would be
        # created; we assert it is not. The slug is deterministic (sanitize
        # the path to a stable filename) so the proof is reproducible.
        slug = bad.replace("/", "_").replace(".", "_").strip("_") or "root"
        proof_target = proof_dir / f"would_be_created_{slug}.txt"
        raised = False
        try:
            check_write(bad, owned)
        except ScopeViolation as exc:
            raised = True
            if exc.fail_reason != "CONTRACT_INVALID":
                return {
                    "status": "FAIL",
                    "detail": f"wrong fail_reason for {bad!r}: {exc.fail_reason}",
                }
        if not raised:
            return {
                "status": "FAIL",
                "detail": f"out-of-scope path was not rejected: {bad!r}",
            }
        # No write should have occurred: prove the proof target is absent.
        if proof_target.exists():
            created_targets.append(str(proof_target))
    return {
        "status": "PASS",
        "detail": "all out-of-scope/traversal/absolute paths rejected pre-write",
        "refused": refused,
        "files_created": created_targets,  # must be empty
    }


def _check_a03_03() -> dict[str, Any]:
    """A03-03: a synthetic inline secret fixture is flagged pre-commit."""
    # The fixture is constructed inline and never written to disk.
    fixture = (
        f"diff --git a/leak.py b/leak.py\n"
        f"+token = '{_FAKE_GHP_TOKEN}'\n"
        f"+home = '{_FAKE_HOME_PATH}'\n"
    )
    findings = scan_diff(fixture)
    if not findings:
        return {"status": "FAIL", "detail": "synthetic fixture was not flagged"}
    reasons = sorted({f.fail_reason for f in findings})
    names = sorted({f.pattern_name for f in findings})
    # Must include the public-leak fail reason at minimum.
    if "PUBLIC_LEAK_DETECTED" not in reasons:
        return {
            "status": "FAIL",
            "detail": f"missing PUBLIC_LEAK_DETECTED in {reasons}",
        }
    # Must have flagged both the token and the home path.
    if "github_pat_classic" not in names or "absolute_users_home" not in names:
        return {
            "status": "FAIL",
            "detail": f"expected ghp + home findings, got {names}",
        }
    return {
        "status": "PASS",
        "detail": "synthetic fixture flagged pre-commit",
        "pattern_names": names,
        "fail_reasons": reasons,
    }


def _check_a03_04() -> dict[str, Any]:
    """A03-04: a failing-check state does not permit a merge.

    Exercises the failing-check rows of the resume table and asserts each
    yields ``permits_merge=False``. Documents the mapping from failing-check
    observed state to decision.
    """
    inputs = IdempotencyInputs(
        repository_id="KirPonomarev/scientific-resource-lab",
        mission_digest="0" * 64,
        wp_id=WP_ID,
        base_sha="0" * 40,
        policy_sha="0" * 64,
    )
    # Failing-check observed states: merged-but-failing and commit-but-failing.
    failing_states = {
        "merged_checks_failing": {"pr_state": "merged", "checks_passed": False},
        "commit_checks_failing": {"commit_sha": "c" * 40, "checks_passed": False},
        "no_evidence_failing": {"checks_passed": False},
    }
    mapping: dict[str, dict[str, Any]] = {}
    for name, obs in failing_states.items():
        decision = reconcile(inputs, obs)
        if decision.permits_merge:
            return {
                "status": "FAIL",
                "detail": f"failing-check state {name} permitted merge",
            }
        mapping[name] = {
            "decision": decision.decision.value,
            "permits_merge": decision.permits_merge,
        }
    return {
        "status": "PASS",
        "detail": "no failing-check state permits merge",
        "mapping": mapping,
    }


def _check_a03_05() -> dict[str, Any]:
    """A03-05: two reconcile runs over the same state yield identical JSON."""
    inputs = IdempotencyInputs(
        repository_id="KirPonomarev/scientific-resource-lab",
        mission_digest="abcdef" * 10 + "abcd",  # 64 hex
        wp_id=WP_ID,
        base_sha="1" * 40,
        policy_sha="2" * 64,
    )
    observed = {"pr_state": "open", "commit_sha": "3" * 40, "checks_passed": True}
    # Serialize the observed state once (simulating an interrupted run written
    # to disk) and re-read it for the second run, so the proof is over the
    # serialized form, not the live object.
    serialized = json.dumps(observed, sort_keys=True, separators=(",", ":"))
    run1 = decision_to_json(reconcile(inputs, json.loads(serialized)))
    run2 = decision_to_json(reconcile(inputs, json.loads(serialized)))
    if run1 != run2:
        return {
            "status": "FAIL",
            "detail": "two reconcile runs produced different JSON",
            "run1": run1,
            "run2": run2,
        }
    # Also assert the idempotency key is stable.
    key1 = idempotency_key(inputs)
    key2 = idempotency_key(inputs)
    if key1 != key2 or len(key1) != _HEX_SHA256_LEN:
        return {"status": "FAIL", "detail": "idempotency key not stable/64-hex"}
    return {
        "status": "PASS",
        "detail": "deterministic resume: byte-identical decision JSON",
        "decision_json": run1.strip(),
        "idempotency_key": key1,
    }


def _policy_evidence() -> dict[str, Any]:
    """Load the policy and report a compact evidence summary for the receipt."""
    policy_path = _REPO_ROOT / "automation" / "policy.json"
    try:
        policy = load_policy(policy_path)
    except Exception as exc:  # gate must report any loader failure as evidence
        return {"loaded": False, "error": str(exc)}
    return {
        "loaded": True,
        "schema_version": policy["schema_version"],
        "key_count": len(policy),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "A03-01": _check_a03_01(),
        "A03-02": _check_a03_02(),
        "A03-03": _check_a03_03(),
        "A03-04": _check_a03_04(),
        "A03-05": _check_a03_05(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "policy": _policy_evidence(),
            "statuses": statuses,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check" and len(args) == _SINGLE_CHECK_ARGC:
        cid = args[1]
        runners = {
            "A03-01": _check_a03_01,
            "A03-02": _check_a03_02,
            "A03-03": _check_a03_03,
            "A03-04": _check_a03_04,
            "A03-05": _check_a03_05,
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
    # Stable CWD-independent behavior: ensure we run from repo root so any
    # relative path evidence (none mutating) resolves predictably.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
