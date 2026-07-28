#!/usr/bin/env python3
"""Weekly deterministic replay check.

Re-runs the canonical conformance vectors, verifies the autonomy policy still
loads, and recomputes a MANIFEST-style digest of the shipped v1 schemas.

All external work is invoked through ``subprocess`` so this script stays a
thin orchestrator and never imports the package under test directly.  The
script uses only the Python standard library and makes no network calls.

Exits non-zero if any step fails.  On success, prints a single canonical JSON
receipt line (``WeeklyReplayReceipt/v1``) to stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Paths (relative to the repository root).
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/weekly_replay.py -> repo root
_SCHEMAS_DIR: Final[Path] = _REPO_ROOT / "src" / "srl" / "contracts" / "schemas" / "v1"
_POLICY_PATH: Final[Path] = _REPO_ROOT / "automation" / "policy.json"
_VECTORS_SCRIPT: Final[Path] = _REPO_ROOT / "scripts" / "checks" / "canonical-vectors.py"

RECEIPT_SCHEMA: Final[str] = "WeeklyReplayReceipt/v1"


def _run(
    cmd: list[str],
    *,
    cwd: Path = _REPO_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return its completed process, capturing stdout/stderr."""
    # Commands are hardcoded literals inside this script; no user input is
    # interpolated.  S603 fires on any subprocess.run use and is not actionable.
    return subprocess.run(  # noqa: S603
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_vectors() -> dict[str, Any]:
    """Run the canonical-vectors script and return a summary."""
    empty = {
        "status": "FAIL",
        "positive_passed": 0,
        "positive_total": 0,
        "negative_passed": 0,
        "negative_total": 0,
    }
    proc = _run([sys.executable, str(_VECTORS_SCRIPT)])
    if proc.returncode != 0:
        empty["detail"] = proc.stderr or proc.stdout
        return empty

    try:
        receipt = json.loads(proc.stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError) as exc:
        empty["detail"] = f"could not parse vector receipt: {exc}"
        return empty

    overall = receipt.get("overall", "FAIL")
    positive = receipt.get("positive", {})
    negative = receipt.get("negative", {})
    return {
        "status": overall,
        "positive_passed": positive.get("passed", 0),
        "positive_total": positive.get("total", 0),
        "negative_passed": negative.get("passed", 0),
        "negative_total": negative.get("total", 0),
    }


def _run_policy_check() -> dict[str, Any]:
    """Verify that the autonomy policy loads through the package loader."""
    code = (
        "from srl.autonomy.policy import load_policy; "
        f"load_policy({str(_POLICY_PATH)!r}); "
        'print("policy-load-ok")'
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    proc = _run(["python3", "-c", code], env=env)
    if proc.returncode != 0 or "policy-load-ok" not in proc.stdout:
        return {"status": "FAIL", "detail": proc.stderr or proc.stdout}
    return {"status": "PASS"}


def _manifest_digest(root: Path) -> str:
    """Compute a deterministic MANIFEST-style sha256 digest of all files under root.

    For each file (sorted by relative path), compute the sha256 of its raw bytes.
    Then compute the sha256 of the concatenated manifest lines
    ``<hexdigest>  <relative_path>\n`` in sorted order.  This is stable across
    platforms and insensitive to mtimes or git modes.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"schema directory not found: {root}")

    entries: list[tuple[str, str]] = []  # (hexdigest, relpath)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append((file_hash, rel))

    if not entries:
        raise ValueError(f"no files found in schema directory: {root}")

    manifest = "".join(f"{digest}  {rel}\n" for digest, rel in sorted(entries))
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def _emit_receipt(receipt: dict[str, Any]) -> None:
    """Write one compact canonical JSON line to stdout."""
    print(json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def main() -> int:
    """Run all weekly replay checks and emit the receipt."""
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass

    vectors = _run_vectors()
    policy = _run_policy_check()
    try:
        schemas_digest = _manifest_digest(_SCHEMAS_DIR)
    except (OSError, ValueError) as exc:
        schemas_digest = ""
        schema_error = f"schema digest failed: {exc}"
    else:
        schema_error = ""

    overall = "PASS"
    if vectors["status"] != "PASS":
        overall = "FAIL"
    if policy["status"] != "PASS":
        overall = "FAIL"
    if not schemas_digest:
        overall = "FAIL"

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "overall": overall,
        "vectors": {
            "status": vectors["status"],
            "positive_passed": vectors["positive_passed"],
            "positive_total": vectors["positive_total"],
            "negative_passed": vectors["negative_passed"],
            "negative_total": vectors["negative_total"],
        },
        "policy": policy["status"],
        "schemas_digest": schemas_digest,
        "created_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if schema_error:
        receipt["schema_error"] = schema_error
    if vectors.get("detail"):
        receipt["vectors_detail"] = vectors["detail"]
    if policy.get("detail"):
        receipt["policy_detail"] = policy["detail"]

    _emit_receipt(receipt)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
