#!/usr/bin/env python3
"""V3.7 A09 Lean/mathlib and mathematical-corpus activation gate."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402
from srl.packs.formal.lean import (  # noqa: E402
    LeanCorpusStatus,
    LeanProofStatus,
    check_lean_source,
    default_corpus_pins,
    default_corpus_statements,
    traverse_pinned_corpus_statements,
    validate_mathlib_project,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A09"
EXPECTED_A09: Final[tuple[str, ...]] = (
    "lean",
    "lake",
    "mathlib",
    "cslib-index",
    "erdos-problems-metadata",
    "formal-conjectures",
)


def _check_candidate_receipt_projection(*, direct_checks_passed: bool) -> dict[str, Any]:
    failures = [] if direct_checks_passed else ["direct A09 probe checks did not all pass"]
    return {
        "check_id": "A09-01-receipt-projects-truth-ledger-active",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "A09 probe receipt is hash-bound to Lean/mathlib pins, mathlib smoke "
            "and corpus traversal; build_truth_ledger consumes the committed receipt offline"
        ),
        "a09_active_inventory_projected": list(EXPECTED_A09),
    }


def _check_kernel_accept_reject() -> dict[str, Any]:
    valid = check_lean_source(
        "theorem srl_a09_valid_gate : True := by trivial\n#print axioms srl_a09_valid_gate\n",
        theorem_name="srl_a09_valid_gate",
        expect_axioms=True,
    )
    invalid = check_lean_source(
        "theorem srl_a09_invalid_gate : False := by trivial\n",
        theorem_name="srl_a09_invalid_gate",
    )
    failures = []
    if valid["status"] != LeanProofStatus.CHECKED.value:
        failures.append(f"valid theorem status={valid['status']}")
    if invalid["status"] != LeanProofStatus.REJECTED.value:
        failures.append(f"invalid theorem status={invalid['status']}")
    if valid.get("axioms") is None:
        failures.append("valid theorem receipt missing axiom inventory")
    return {
        "check_id": "A09-02-lean-kernel-accept-reject",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "Lean kernel accepted a valid theorem, rejected an invalid theorem and emitted axioms",
        "valid_receipt": valid,
        "invalid_receipt": invalid,
    }


def _check_mathlib_import(project_dir: Path) -> dict[str, Any]:
    source = "\n".join(
        (
            "import Mathlib.Data.Nat.Basic",
            "",
            "theorem srl_a09_mathlib_gate : Nat.succ 1 = 2 := rfl",
            "#print axioms srl_a09_mathlib_gate",
            "",
        )
    )
    receipt = check_lean_source(
        source,
        theorem_name="srl_a09_mathlib_gate",
        project_dir=project_dir,
        expect_axioms=True,
        uses_mathlib=True,
        timeout_seconds=120.0,
    )
    failures = []
    if receipt["status"] != LeanProofStatus.CHECKED.value:
        failures.append(f"mathlib theorem status={receipt['status']}")
    if receipt.get("uses_mathlib") is not True:
        failures.append("mathlib receipt missing uses_mathlib=true")
    if receipt.get("axioms") is None:
        failures.append("mathlib receipt missing axiom inventory")
    return {
        "check_id": "A09-03-mathlib-import",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "pinned mathlib module import worked outside fixture mocks",
        "mathlib_receipt": receipt,
    }


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: float = 60.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - command vectors are fixed by this gate.
        command,
        cwd=cwd,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )


def _verify_remote_statement(
    *,
    repository_url: str,
    revision: str,
    source_path: str,
    expected_sha256: str,
    markers: list[str],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="srl-a09-corpus-") as tmp:
        root = Path(tmp)
        commands = [
            ["git", "init", "-q"],
            ["git", "remote", "add", "origin", repository_url],
            ["git", "fetch", "--depth", "1", "origin", revision],
        ]
        command_results = []
        for command in commands:
            proc = _run(command, cwd=root, timeout_seconds=180.0)
            command_results.append(
                {
                    "command": command,
                    "returncode": proc.returncode,
                    "stderr_preview": proc.stderr.decode("utf-8", errors="replace")[:1000],
                }
            )
            if proc.returncode != 0:
                return {
                    "status": "FAIL",
                    "detail": "remote fetch failed",
                    "commands": command_results,
                }
        proc = _run(["git", "show", f"FETCH_HEAD:{source_path}"], cwd=root, timeout_seconds=60.0)
        if proc.returncode != 0:
            return {
                "status": "FAIL",
                "detail": "remote source path missing",
                "commands": command_results,
                "stderr_preview": proc.stderr.decode("utf-8", errors="replace")[:1000],
            }
        text = proc.stdout.decode("utf-8", errors="replace")
        actual_sha256 = hashlib.sha256(proc.stdout).hexdigest()
        missing = [marker for marker in markers if marker not in text]
        status = "PASS" if actual_sha256 == expected_sha256 and not missing else "FAIL"
        return {
            "status": status,
            "detail": "remote pinned corpus blob matched and parser markers were present"
            if status == "PASS"
            else "remote pinned corpus verification failed",
            "actual_sha256": actual_sha256,
            "expected_sha256": expected_sha256,
            "missing_markers": missing,
            "commands": command_results,
        }


def _check_corpus_traversal() -> dict[str, Any]:
    receipt = traverse_pinned_corpus_statements()
    pins = {pin.corpus_id: pin for pin in default_corpus_pins()}
    remote_results = []
    for statement in default_corpus_statements():
        pin = pins[statement.corpus_id]
        remote_results.append(
            {
                "statement_id": statement.statement_id,
                "remote": _verify_remote_statement(
                    repository_url=pin.repository_url,
                    revision=pin.repository_revision,
                    source_path=statement.source_path,
                    expected_sha256=statement.source_sha256,
                    markers=list(statement.parser_markers),
                ),
            }
        )
    failures = []
    if receipt["status"] != LeanCorpusStatus.TRAVERSED.value:
        failures.append(f"local traversal status={receipt['status']}")
    failures.extend(
        item["statement_id"] for item in remote_results if item["remote"]["status"] != "PASS"
    )
    return {
        "check_id": "A09-04-pinned-corpus-traversal",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "Erdos/Formal Conjectures statement traversed local pipeline and matched remote pin",
        "corpus_receipt": receipt,
        "remote_results": remote_results,
    }


def main() -> int:
    if shutil.which("lean") is None or shutil.which("lake") is None:
        sys.stderr.write("lean and lake must be installed and on PATH for A09\n")
        return 1
    configured_project = os.environ.get("SRL_A09_MATHLIB_PROJECT_DIR")
    if not configured_project:
        sys.stderr.write(
            "SRL_A09_MATHLIB_PROJECT_DIR must point at a prepared pinned mathlib project; "
            "run scripts/ci/prepare_a09_mathlib.py first\n"
        )
        return 1

    project_dir = Path(configured_project)
    mathlib_project = validate_mathlib_project(project_dir)
    direct_checks = [
        _check_kernel_accept_reject(),
        {
            "check_id": "A09-00-pinned-mathlib-project",
            "status": mathlib_project["status"],
            "detail": "pinned mathlib Lake project validated without provisioning"
            if mathlib_project["status"] == "PASS"
            else "pinned mathlib Lake project validation failed",
            "mathlib_project": mathlib_project,
        },
        _check_mathlib_import(project_dir),
        _check_corpus_traversal(),
    ]
    direct_status = all(item["status"] == "PASS" for item in direct_checks)
    checks = [_check_candidate_receipt_projection(direct_checks_passed=direct_status)]
    checks.extend(direct_checks)
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "stage_closure": "A09_ACTIVE" if status == "PASS" else "A09_WAIT_TOOLCHAIN",
        "active_packs": list(EXPECTED_A09) if status == "PASS" else [],
        "parked_packs": [] if status == "PASS" else list(EXPECTED_A09),
        "remaining_internal_waits": []
        if status == "PASS"
        else [f"WAIT_TOOLCHAIN:{component_id}" for component_id in EXPECTED_A09],
        "remaining_external_waits": ["WAIT_AUTHORITY:A09_BIND_PINNED_LEAN_MATHLIB_PROJECT_TO_T7"],
        "checks": checks,
        "canonical_writes": 0,
        "grants_authority": False,
        "live_actions": 0,
    }
    receipt["receipt_id"] = object_id(
        {key: value for key, value in receipt.items() if key != "receipt_id"}
    )
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
