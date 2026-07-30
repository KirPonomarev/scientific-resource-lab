#!/usr/bin/env python3
"""Single-process V3.7 verification orchestration.

Make prerequisites run in separate shells, which is exactly how A09 ended up
with repeated mathlib provisioning. This orchestrator owns one environment and
injects the prepared A09 project only once, at the A09 probe boundary.
It also owns the A10 HOL4 session cache so independent prover verification does
not depend on Make prerequisite environment leakage.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scripts.ci.prepare_a09_mathlib import prepare_session_project  # noqa: E402
from scripts.ci.prepare_a10_hol4 import prepare_hol4  # noqa: E402

from srl.packs.formal import load_independent_prover_pins  # noqa: E402
from srl.products.sciml_domain import prepare_a14_julia_project  # noqa: E402

SUMMARY_PATH: Final[Path] = REPO_ROOT / ".tmp" / "verify-v37-summary.json"


def _default_isabelle_image() -> str:
    pins = load_independent_prover_pins()
    isabelle = pins["isabelle"]
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"} and isinstance(isabelle.get("docker_image_arm"), str):
        return str(isabelle["docker_image_arm"])
    return str(isabelle["docker_image"])


def _run(command: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(command, cwd=REPO_ROOT, env=env, check=False)  # noqa: S603
    elapsed = round(time.monotonic() - started, 3)
    result = {"command": command, "returncode": proc.returncode, "elapsed_seconds": elapsed}
    if proc.returncode != 0:
        raise SystemExit(json.dumps(result, indent=2, sort_keys=True))
    return result


def main() -> int:
    env = os.environ.copy()
    steps: list[dict[str, Any]] = []
    commands = [
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "ruff", "format", "--check", "."],
        ["uv", "run", "mypy"],
        ["uv", "run", "pytest"],
        [sys.executable, "scripts/checks/srf-v37-a01-gate.py"],
        [sys.executable, "scripts/checks/srf-v37-a02-gate.py"],
        [sys.executable, "scripts/checks/srf-v37-a03-gate.py"],
        [sys.executable, "scripts/checks/srf-v37-a04-gate.py"],
        [sys.executable, "scripts/checks/srf-v37-a05-gate.py"],
        [sys.executable, "scripts/checks/srf-v37-a06-gate.py"],
        [sys.executable, "scripts/checks/srf-v37-a07-gate.py"],
        [sys.executable, "scripts/checks/srf-v37-a08-gate.py"],
    ]
    for command in commands:
        steps.append(_run(command, env=env))

    cache_root = Path(env["SRL_A09_CACHE_ROOT"]) if "SRL_A09_CACHE_ROOT" in env else None
    prepare_report = prepare_session_project(
        cache_root=cache_root
        if cache_root is not None
        else Path(env.get("TMPDIR", tempfile.gettempdir())) / "srl-a09-mathlib-session-cache",
        timeout_seconds=float(env.get("SRL_A09_PREPARE_TIMEOUT_SECONDS", "900")),
    )
    if prepare_report["status"] != "PASS":
        raise SystemExit(json.dumps(prepare_report, indent=2, sort_keys=True))
    env["SRL_A09_MATHLIB_PROJECT_DIR"] = str(prepare_report["project_dir"])

    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a09-gate.py"], env=env))

    a10_cache_root = Path(env["SRL_A10_CACHE_ROOT"]) if "SRL_A10_CACHE_ROOT" in env else None
    a10_prepare_report = prepare_hol4(
        cache_root=a10_cache_root
        if a10_cache_root is not None
        else Path(env.get("TMPDIR", tempfile.gettempdir())) / "srl-a10-hol4-session-cache",
    )
    env["SRL_A10_HOL4_HOME"] = str(a10_prepare_report["hol4_home"])
    env.setdefault("SRL_A10_ROCQ_DOCKER_IMAGE", "rocq/rocq-prover:9.2.0")
    env.setdefault("SRL_A10_ISABELLE_DOCKER_IMAGE", _default_isabelle_image())

    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a10-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a11-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a12-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a13-gate.py"], env=env))

    a14_project = Path(
        env.get(
            "SRL_A14_JULIA_PROJECT_DIR",
            str(REPO_ROOT / ".cache" / "srl-a14-julia-project"),
        )
    )
    a14_depot = Path(env.get("JULIA_DEPOT_PATH", str(REPO_ROOT / ".cache" / "srl-a14-julia-depot")))
    a14_prepare_report = prepare_a14_julia_project(
        julia_project_dir=a14_project,
        julia_depot_path=str(a14_depot),
    )
    env["SRL_A14_JULIA_PROJECT_DIR"] = str(a14_project)
    env["JULIA_DEPOT_PATH"] = str(a14_depot)
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a14-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a15-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a16-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a17-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a18-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a19-gate.py"], env=env))
    steps.append(_run([sys.executable, "scripts/checks/srf-v37-a20-gate.py"], env=env))
    if (REPO_ROOT / "dist").exists():
        shutil.rmtree(REPO_ROOT / "dist")
    steps.append(_run(["uv", "build"], env=env))

    summary = {
        "schema_version": "V37VerifySummary/v1",
        "result": "PASS",
        "steps": steps,
        "a09_prepare": {
            key: prepare_report[key]
            for key in (
                "cache_key",
                "installer_sha256",
                "prepare_count",
                "fetch_count",
                "cache_status",
                "project_dir_role",
            )
        },
        "a10_hol4_prepare": {
            key: a10_prepare_report[key]
            for key in (
                "cache_key",
                "installer_sha256",
                "prepare_count",
                "fetch_count",
                "cache_status",
            )
        },
        "a14_julia_prepare": {
            key: a14_prepare_report[key]
            for key in (
                "julia_version",
                "julia_project_role",
                "julia_depot_role",
                "project_toml_sha256",
                "manifest_toml_sha256",
            )
        },
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
