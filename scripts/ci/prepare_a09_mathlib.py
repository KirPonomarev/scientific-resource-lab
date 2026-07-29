#!/usr/bin/env python3
"""Prepare one session-scoped pinned A09 Lean/mathlib project.

This script is the only CI/local verify provisioning entrypoint for the A09
mathlib smoke project. Truth-ledger projection and stage gates consume the
prepared project or the committed A09 receipt; they do not call Lake update.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.packs.formal.lean import (  # noqa: E402
    a09_mathlib_cache_key,
    default_lean_pins,
    prepare_mathlib_project,
    validate_mathlib_project,
)

SCHEMA_VERSION: Final[str] = "A09MathlibPrepareReport/v1"


def _default_cache_root() -> Path:
    tmpdir = os.environ.get("TMPDIR") or tempfile.gettempdir()
    return Path(tmpdir) / "srl-a09-mathlib-session-cache"


def _installer_hash() -> str:
    hasher = hashlib.sha256()
    for path in (
        REPO_ROOT / "scripts" / "ci" / "install-lean-toolchain.sh",
        Path(__file__).resolve(),
    ):
        hasher.update(path.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def prepare_session_project(
    *,
    cache_root: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    pins = default_lean_pins()
    installer_hash = _installer_hash()
    cache_key = a09_mathlib_cache_key(pins=pins, installer_hash=installer_hash)
    cache_root.mkdir(parents=True, exist_ok=True)
    lock_path = cache_root / ".a09-mathlib.lock"
    target = cache_root / cache_key
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "cache_key": cache_key,
        "installer_sha256": installer_hash,
        "pins": pins.to_dict(),
        "prepare_count": 0,
        "fetch_count": 0,
        "cache_status": "uninitialized",
        "project_dir": str(target),
        "project_dir_role": "session_cache_not_published",
        "canonical_writes": 0,
        "grants_authority": False,
    }

    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        existing_validation = validate_mathlib_project(target, pins=pins)
        if existing_validation["status"] == "PASS":
            report.update(
                {
                    "status": "PASS",
                    "cache_status": "reused",
                    "validation": existing_validation,
                }
            )
            return report

        if target.exists():
            shutil.rmtree(target)
        staging = cache_root / f".{cache_key}.staging-{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging)
        try:
            provision = prepare_mathlib_project(
                staging,
                pins=pins,
                timeout_seconds=timeout_seconds,
            )
            report["prepare_count"] = 1
            report["fetch_count"] = 1 if provision.get("commands") else 0
            validation = validate_mathlib_project(staging, pins=pins)
            report["provision"] = provision
            report["validation"] = validation
            if provision["status"] != "PASS" or validation["status"] != "PASS":
                report["cache_status"] = "prepare_failed"
                return report
            staging.rename(target)
            report.update({"status": "PASS", "cache_status": "prepared"})
            return report
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(os.environ["SRL_A09_CACHE_ROOT"])
        if "SRL_A09_CACHE_ROOT" in os.environ
        else _default_cache_root(),
    )
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    report = prepare_session_project(
        cache_root=args.cache_root,
        timeout_seconds=args.timeout_seconds,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
