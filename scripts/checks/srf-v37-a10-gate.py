#!/usr/bin/env python3
"""V3.7 A10 independent prover activation gate."""

from __future__ import annotations

import hashlib
import os
import re
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
from srl.packs.formal import (  # noqa: E402
    SHARED_A10_THEOREM_LABEL,
    FormalContour,
    FormalContourStatus,
    build_a10_translation_manifests,
    build_cross_prover_admission_bundle,
    independent_prover_pin_manifest_hash,
    load_independent_prover_pins,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A10"
EXPECTED_A10: Final[tuple[str, ...]] = ("rocq", "isabelle", "hol4")


def _tmp_root() -> Path:
    root = Path(os.environ.get("SRL_A10_TMPDIR", REPO_ROOT / ".tmp" / "a10-proof-work"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: float = 180.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - command vectors are fixed by this gate.
        command,
        cwd=cwd,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )


def _preview(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")[:1000]


def _sanitize_receipt_text(value: str) -> str:
    replacements = (
        (os.environ.get("SRL_A10_HOL4_HOME", ""), "$SRL_A10_HOL4_HOME"),
        (str(_tmp_root()), "$SRL_A10_TMPDIR"),
        (str(REPO_ROOT), "$REPO_ROOT"),
    )
    sanitized = value
    for raw, replacement in replacements:
        if raw:
            sanitized = sanitized.replace(raw, replacement)
    return re.sub(
        r"\$SRL_A10_TMPDIR/srl-a10-[^:\s]+",
        "$SRL_A10_PROOF_DIR",
        sanitized,
    )


def _sanitize_command(command: list[str]) -> list[str]:
    return [_sanitize_receipt_text(item) for item in command]


def _command_receipt(
    command: list[str],
    proc: subprocess.CompletedProcess[bytes],
) -> dict[str, Any]:
    return {
        "command": _sanitize_command(command),
        "returncode": proc.returncode,
        "stdout_sha256": _sha256_bytes(proc.stdout),
        "stderr_sha256": _sha256_bytes(proc.stderr),
        "stdout_preview": _sanitize_receipt_text(_preview(proc.stdout)),
        "stderr_preview": _sanitize_receipt_text(_preview(proc.stderr)),
    }


def _docker_command(
    image: str,
    inner: list[str],
    *,
    workdir: Path | None = None,
    set_workdir: bool = True,
) -> list[str]:
    command = ["docker", "run", "--rm"]
    platform_name = os.environ.get("SRL_A10_DOCKER_PLATFORM")
    if platform_name:
        command.extend(["--platform", platform_name])
    if workdir is not None:
        command.extend(["-v", f"{workdir.resolve()}:/work"])
        if set_workdir:
            command.extend(["-w", "/work"])
    command.append(image)
    command.extend(inner)
    return command


def _check_rocq() -> dict[str, Any]:
    image = os.environ.get("SRL_A10_ROCQ_DOCKER_IMAGE")
    with tempfile.TemporaryDirectory(prefix="srl-a10-rocq-", dir=_tmp_root()) as tmp:
        root = Path(tmp)
        source = "\n".join(
            (
                "Theorem srl_a10_zero_add : forall n : nat, 0 + n = n.",
                "Proof.",
                "  intros n.",
                "  reflexivity.",
                "Qed.",
                "",
            )
        )
        source_path = root / "SRL_A10_ROCQ.v"
        source_path.write_text(source, encoding="utf-8")
        if image:
            version_command = _docker_command(
                image,
                ["sh", "-lc", "rocq -v || coqc -v"],
            )
            proof_command = _docker_command(
                image,
                [
                    "sh",
                    "-lc",
                    (
                        "if command -v rocq >/dev/null; then "
                        "rocq compile SRL_A10_ROCQ.v; else coqc SRL_A10_ROCQ.v; fi"
                    ),
                ],
                workdir=root,
            )
        else:
            executable = shutil.which("rocq") or shutil.which("coqc")
            if executable is None:
                return _missing("A10-02-rocq-proof", "rocq", "rocq/coqc executable missing")
            version_command = [executable, "-v"]
            proof_command = (
                [executable, "compile", str(source_path)]
                if executable.endswith("rocq")
                else [executable, str(source_path)]
            )
        version = _run(version_command, cwd=root)
        proof = _run(proof_command, cwd=root)
        failures = []
        if version.returncode != 0:
            failures.append("version probe failed")
        if proof.returncode != 0:
            failures.append("proof compilation failed")
        return _proof_check(
            check_id="A10-02-rocq-proof",
            prover_id="rocq",
            contour_id="rocq.primary",
            status="FAIL" if failures else "PASS",
            detail="; ".join(failures)
            if failures
            else "Rocq/Coq compiled shared nat zero-add theorem",
            version_command=version_command,
            version_proc=version,
            proof_command=proof_command,
            proof_proc=proof,
            source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        )


def _check_isabelle() -> dict[str, Any]:
    image = os.environ.get("SRL_A10_ISABELLE_DOCKER_IMAGE")
    with tempfile.TemporaryDirectory(prefix="srl-a10-isabelle-", dir=_tmp_root()) as tmp:
        root = Path(tmp)
        (root / "ROOT").write_text(
            "session SRL_A10 = HOL +\n  theories SRL_A10\n",
            encoding="utf-8",
        )
        theory = "\n".join(
            (
                "theory SRL_A10",
                "  imports Main",
                "begin",
                "",
                'theorem srl_a10_zero_add: "0 + (n::nat) = n"',
                "  by simp",
                "",
                "end",
                "",
            )
        )
        (root / "SRL_A10.thy").write_text(theory, encoding="utf-8")
        if image:
            version_command = _docker_command(image, ["version"])
            proof_command = _docker_command(
                image,
                ["build", "-D", "/work"],
                workdir=root,
                set_workdir=False,
            )
        else:
            executable = shutil.which("isabelle")
            if executable is None:
                return _missing("A10-03-isabelle-proof", "isabelle", "isabelle executable missing")
            version_command = [executable, "version"]
            proof_command = [executable, "build", "-D", str(root)]
        version = _run(version_command, cwd=root)
        proof = _run(proof_command, cwd=root, timeout_seconds=600.0)
        failures = []
        if version.returncode != 0:
            failures.append("version probe failed")
        if proof.returncode != 0:
            failures.append("session build failed")
        return _proof_check(
            check_id="A10-03-isabelle-proof",
            prover_id="isabelle",
            contour_id="isabelle.hol",
            status="FAIL" if failures else "PASS",
            detail="; ".join(failures)
            if failures
            else "Isabelle/HOL built shared nat zero-add theory",
            version_command=version_command,
            version_proc=version,
            proof_command=proof_command,
            proof_proc=proof,
            source_sha256=hashlib.sha256(theory.encode("utf-8")).hexdigest(),
        )


def _check_hol4() -> dict[str, Any]:
    hol4_home = os.environ.get("SRL_A10_HOL4_HOME")
    if not hol4_home:
        return _missing("A10-04-hol4-proof", "hol4", "SRL_A10_HOL4_HOME missing")
    home = Path(hol4_home)
    holmake = home / "bin" / "Holmake"
    hol = home / "bin" / "hol"
    if not holmake.exists() or not hol.exists():
        return _missing("A10-04-hol4-proof", "hol4", "Holmake/hol missing in SRL_A10_HOL4_HOME")
    with tempfile.TemporaryDirectory(prefix="srl-a10-hol4-", dir=_tmp_root()) as tmp:
        root = Path(tmp)
        script = "\n".join(
            (
                "open HolKernel boolLib bossLib;",
                'val _ = new_theory "srl_a10";',
                "val srl_a10_zero_add = store_thm(",
                '  "srl_a10_zero_add",',
                "  ``!n:num. 0 + n = n``,",
                "  simp[]);",
                "val _ = export_theory();",
                "",
            )
        )
        (root / "srl_a10Script.sml").write_text(script, encoding="utf-8")
        version_command = [str(hol), "--noconfig"]
        version = subprocess.run(  # noqa: S603 - fixed HOL executable.
            version_command,
            cwd=root,
            input=b"val _ = OS.Process.exit OS.Process.success;\n",
            capture_output=True,
            check=False,
            timeout=120.0,
        )
        proof_command = [str(holmake), "srl_a10Theory.uo"]
        proof = _run(proof_command, cwd=root, timeout_seconds=600.0)
        failures = []
        if version.returncode != 0:
            failures.append("hol executable probe failed")
        if proof.returncode != 0:
            failures.append("Holmake proof build failed")
        return _proof_check(
            check_id="A10-04-hol4-proof",
            prover_id="hol4",
            contour_id="hol4.primary",
            status="FAIL" if failures else "PASS",
            detail="; ".join(failures) if failures else "HOL4 built shared nat zero-add theory",
            version_command=version_command,
            version_proc=version,
            proof_command=proof_command,
            proof_proc=proof,
            source_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest(),
        )


def _missing(check_id: str, prover_id: str, reason: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "FAIL",
        "detail": reason,
        "prover_id": prover_id,
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _proof_check(  # noqa: PLR0913 - receipt fields stay explicit.
    *,
    check_id: str,
    prover_id: str,
    contour_id: str,
    status: str,
    detail: str,
    version_command: list[str],
    version_proc: subprocess.CompletedProcess[bytes],
    proof_command: list[str],
    proof_proc: subprocess.CompletedProcess[bytes],
    source_sha256: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "detail": detail,
        "proof_receipt": {
            "schema_version": "IndependentProverProofReceipt/v1",
            "prover_id": prover_id,
            "contour_id": contour_id,
            "theorem_label": SHARED_A10_THEOREM_LABEL,
            "source_sha256": source_sha256,
            "version_probe": _command_receipt(version_command, version_proc),
            "proof_probe": _command_receipt(proof_command, proof_proc),
            "formal_check": "checked" if status == "PASS" else "unchecked",
            "formal_scope": "declared_statement_only",
            "canonical_writes": 0,
            "grants_authority": False,
        },
    }


def _check_semantic_manifests(proof_checks: list[dict[str, Any]]) -> dict[str, Any]:
    by_prover = {
        item.get("proof_receipt", {}).get("prover_id"): item.get("proof_receipt")
        for item in proof_checks
        if isinstance(item.get("proof_receipt"), dict)
    }
    contours = (
        FormalContour(
            contour_id="lean.primary",
            prover_name="Lean/mathlib",
            logic="dependent_type_theory_calculus_of_inductive_constructions_family",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("lean", "lake"),
            version_output="A09 StageCompletionReceipt/v1",
            semantic_scope="declared_statement_only",
            assumptions=("formalization_correctness_not_implied",),
            reason="A09_lean_primary_proven",
        ),
        FormalContour(
            contour_id="rocq.primary",
            prover_name="Rocq/Coq",
            logic="calculus_of_inductive_constructions",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("rocq", "coqc"),
            version_output=str(by_prover["rocq"]["version_probe"]["stdout_preview"]),
            semantic_scope="constructive_type_theory_with_universe_constraints",
            assumptions=("kernel_acceptance_is_per_statement",),
            reason="A10_stage_receipt",
        ),
        FormalContour(
            contour_id="isabelle.hol",
            prover_name="Isabelle/HOL",
            logic="classical_higher_order_logic",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("isabelle",),
            version_output=str(by_prover["isabelle"]["version_probe"]["stdout_preview"]),
            semantic_scope="object_logic_hol_inside_isabelle_framework",
            assumptions=("session_image_and_theory_imports_are_part_of_the_statement",),
            reason="A10_stage_receipt",
        ),
        FormalContour(
            contour_id="hol4.primary",
            prover_name="HOL4",
            logic="classical_higher_order_logic",
            status=FormalContourStatus.ACTIVE,
            executable_candidates=("hol", "Holmake"),
            version_output="HOL4 executable accepted batch command",
            semantic_scope="hol4_kernel_theory_graph",
            assumptions=("theory_load_order_is_part_of_the_statement",),
            reason="A10_stage_receipt",
        ),
    )
    manifests = build_a10_translation_manifests(contours=contours)
    bundle = build_cross_prover_admission_bundle(
        contours=contours,
        translation_manifests=manifests,
    )
    failures = []
    if bundle["wait_contour_ids"] != []:
        failures.append("bundle contains WAIT contours")
    if bundle["automatic_equivalence_claims"] != 0:
        failures.append("bundle claims automatic equivalence")
    if any(manifest["equivalence_claimed"] is not False for manifest in manifests):
        failures.append("translation manifest claimed equivalence")
    return {
        "check_id": "A10-05-semantic-gap-manifests",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "shared claim represented per logic with explicit semantic gaps "
            "and no equivalence claim"
        ),
        "admission_bundle": bundle,
    }


def _check_pin_manifest() -> dict[str, Any]:
    pins = load_independent_prover_pins()
    return {
        "check_id": "A10-01-independent-prover-pins",
        "status": "PASS",
        "detail": "A10 independent prover pins are authority-negative and hash-bound",
        "pin_manifest_sha256": independent_prover_pin_manifest_hash(),
        "shared_claim": pins["shared_claim"],
    }


def _check_candidate_receipt_projection(*, direct_checks_passed: bool) -> dict[str, Any]:
    failures = [] if direct_checks_passed else ["direct A10 prover checks did not all pass"]
    return {
        "check_id": "A10-00-receipt-projects-truth-ledger-active",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "A10 probe receipt is hash-bound to real Rocq/Coq, Isabelle/HOL "
            "and HOL4 proofs; build_truth_ledger consumes the committed receipt offline"
        ),
        "a10_active_inventory_projected": list(EXPECTED_A10),
    }


def main() -> int:
    proof_checks = [_check_rocq(), _check_isabelle(), _check_hol4()]
    direct_status = all(item["status"] == "PASS" for item in proof_checks)
    semantic = (
        _check_semantic_manifests(proof_checks)
        if direct_status
        else {
            "check_id": "A10-05-semantic-gap-manifests",
            "status": "FAIL",
            "detail": "proof checks must pass before semantic manifests can close A10",
        }
    )
    direct_checks = [_check_pin_manifest(), *proof_checks, semantic]
    status = "PASS" if all(item["status"] == "PASS" for item in direct_checks) else "FAIL"
    checks = [_check_candidate_receipt_projection(direct_checks_passed=status == "PASS")]
    checks.extend(direct_checks)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "stage_closure": "A10_ACTIVE" if status == "PASS" else "A10_WAIT_TOOLCHAIN",
        "active_packs": list(EXPECTED_A10) if status == "PASS" else [],
        "parked_packs": [] if status == "PASS" else list(EXPECTED_A10),
        "remaining_internal_waits": []
        if status == "PASS"
        else [f"WAIT_TOOLCHAIN:{component_id}" for component_id in EXPECTED_A10],
        "remaining_external_waits": [],
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
