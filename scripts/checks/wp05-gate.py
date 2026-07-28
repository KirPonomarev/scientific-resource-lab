#!/usr/bin/env python3
"""WP-A05 acceptance gate for the public synthetic fixture corpus.

Runs the four WP-A05 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and a future ``make
gate-wp05`` target.

The checks
----------
A05-01 byte-deterministic regeneration
    Running ``fixtures/public/generate.py all`` twice into separate temp dirs
    produces identical SHA-256 entries in each ``MANIFEST.json``.

A05-02 manifest coverage and integrity
    Every generated fixture file in ``fixtures/public/`` has a matching
    ``MANIFEST.json`` entry with the correct sha256 and byte_size.

A05-03 size bounds
    The entire corpus is under 25 MiB and every individual fixture file is
    under 5 MiB.

A05-04 no real-data markers
    The fixture JSON files contain no absolute paths (``/Users/``, ``/Volumes/``,
    ``/home/``, Windows drive letters) and no obvious credential tokens
    (``api_key``, ``password``, ``secret``, ``token``, ``private_key``, etc.).

The script is standard library only so it can be run without installing uv or
the project dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Receipt identity.
# ---------------------------------------------------------------------------
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-A05"

# Repository layout constants.
_FIXTURES_DIR: Final[str] = "fixtures/public"
_GENERATOR: Final[str] = "fixtures/public/generate.py"
_MANIFEST_NAME: Final[str] = "MANIFEST.json"
_README_NAME: Final[str] = "README.md"

# Size bounds.
_MAX_TOTAL_BYTES: Final[int] = 25 * 1024 * 1024
_MAX_FILE_BYTES: Final[int] = 5 * 1024 * 1024

# Argument count for the single-check CLI form: "--check <id>".
_SINGLE_CHECK_ARGC: Final[int] = 2

# Real-data marker patterns. Keep them explicit and documented; these are
# heuristic scans, not a full secret-detection engine.
_PATH_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("unix_users", re.compile(r"/Users/[^/\s]+")),
    ("unix_volumes", re.compile(r"/Volumes/[^/\s]+")),
    ("unix_home", re.compile(r"/home/[^/\s]+")),
    ("windows_users", re.compile(r"C:\\\\Users\\\\[^\\\s]+")),
)
_CREDENTIAL_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("api_key", re.compile(r"api[_-]?key", re.IGNORECASE)),
    ("password", re.compile(r"password", re.IGNORECASE)),
    ("private_key", re.compile(r"private[_-]?key", re.IGNORECASE)),
    ("secret", re.compile(r"secret", re.IGNORECASE)),
    ("token", re.compile(r"token", re.IGNORECASE)),
)


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact) to stdout."""
    line = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _repo_root() -> Path:
    """Return the repository root from the script location."""
    return Path(__file__).resolve().parents[2]


def _run_generator(output_dir: Path) -> dict[str, Any]:
    """Run the fixture generator into a temp directory and return its manifest."""
    repo_root = _repo_root()
    generator = repo_root / _GENERATOR
    cmd = [sys.executable, str(generator), "--output-dir", str(output_dir), "all"]
    proc = subprocess.run(  # noqa: S603
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "error": f"generator exited {proc.returncode}",
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    manifest_path = output_dir / _MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {"error": f"could not read manifest: {exc}"}
    return {"manifest": manifest}


def _manifest_sha256_entries(manifest: dict[str, Any]) -> dict[str, str]:
    """Return filename -> sha256 from a manifest's entries."""
    entries = manifest.get("entries", {})
    return {name: entry.get("sha256", "") for name, entry in entries.items()}


def _check_a05_01() -> dict[str, Any]:
    """A05-01: regeneration is byte-deterministic by manifest sha256."""
    with tempfile.TemporaryDirectory(prefix="wp05-a05-01-a-") as dir_a:
        with tempfile.TemporaryDirectory(prefix="wp05-a05-01-b-") as dir_b:
            result_a = _run_generator(Path(dir_a))
            result_b = _run_generator(Path(dir_b))

    if "error" in result_a:
        return {"status": "FAIL", "detail": f"run 1 failed: {result_a['error']}"}
    if "error" in result_b:
        return {"status": "FAIL", "detail": f"run 2 failed: {result_b['error']}"}

    entries_a = _manifest_sha256_entries(result_a["manifest"])
    entries_b = _manifest_sha256_entries(result_b["manifest"])

    if entries_a != entries_b:
        only_a = sorted(set(entries_a) - set(entries_b))
        only_b = sorted(set(entries_b) - set(entries_a))
        mismatched = sorted(
            name for name in entries_a if name in entries_b and entries_a[name] != entries_b[name]
        )
        return {
            "status": "FAIL",
            "detail": "two generator runs produced different MANIFEST sha256 entries",
            "only_in_run_1": only_a,
            "only_in_run_2": only_b,
            "mismatched_sha256": mismatched,
        }
    return {
        "status": "PASS",
        "detail": "two generator runs produced identical MANIFEST sha256 entries",
        "files": sorted(entries_a.keys()),
    }


def _is_fixture_file(path: Path) -> bool:
    """True for generated JSON corpus artifacts that must appear in MANIFEST."""
    return (
        path.is_file()
        and path.suffix == ".json"
        and path.name not in {_MANIFEST_NAME, _README_NAME}
    )


def _check_a05_02() -> dict[str, Any]:
    """A05-02: every fixture file has a MANIFEST entry with matching sha256 and size."""
    fixtures_dir = _repo_root() / _FIXTURES_DIR
    manifest_path = fixtures_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        return {"status": "FAIL", "detail": "MANIFEST.json is missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "FAIL", "detail": f"MANIFEST.json is not valid JSON: {exc}"}

    entries = manifest.get("entries", {})
    missing: list[str] = []
    bad_sha256: list[str] = []
    bad_size: list[str] = []

    for fixture_path in sorted(fixtures_dir.iterdir()):
        if not _is_fixture_file(fixture_path):
            continue
        name = fixture_path.name
        entry = entries.get(name)
        if entry is None:
            missing.append(name)
            continue
        actual_size = fixture_path.stat().st_size
        expected_size = entry.get("byte_size")
        if actual_size != expected_size:
            bad_size.append(f"{name}: expected {expected_size}, got {actual_size}")
        actual_sha256 = _sha256_file(fixture_path)
        expected_sha256 = entry.get("sha256")
        if actual_sha256 != expected_sha256:
            bad_sha256.append(f"{name}: sha256 mismatch")

    failures = missing + bad_size + bad_sha256
    if failures:
        return {
            "status": "FAIL",
            "detail": "fixture files missing or inconsistent with MANIFEST",
            "missing": missing,
            "bad_size": bad_size,
            "bad_sha256": bad_sha256,
        }
    return {
        "status": "PASS",
        "detail": "all fixture files have consistent MANIFEST entries",
        "files": sorted(entries.keys()),
    }


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's contents."""
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of a byte string."""
    return hashlib.sha256(data).hexdigest()


def _check_a05_03() -> dict[str, Any]:
    """A05-03: corpus total < 25 MiB and every fixture file < 5 MiB."""
    fixtures_dir = _repo_root() / _FIXTURES_DIR
    total = 0
    oversized: list[str] = []
    for fixture_path in fixtures_dir.iterdir():
        if not fixture_path.is_file():
            continue
        size = fixture_path.stat().st_size
        total += size
        if size > _MAX_FILE_BYTES:
            oversized.append(f"{fixture_path.name}: {size} bytes")

    total_too_large = total > _MAX_TOTAL_BYTES
    if oversized or total_too_large:
        return {
            "status": "FAIL",
            "detail": "size limits exceeded",
            "total_bytes": total,
            "total_limit_bytes": _MAX_TOTAL_BYTES,
            "oversized_files": oversized,
        }
    return {
        "status": "PASS",
        "detail": "corpus and every fixture file are within size limits",
        "total_bytes": total,
        "total_limit_bytes": _MAX_TOTAL_BYTES,
        "max_file_bytes": _MAX_FILE_BYTES,
        "files": sum(1 for _ in fixtures_dir.iterdir() if _.is_file()),
    }


def _check_a05_04() -> dict[str, Any]:
    """A05-04: no absolute paths or real-data markers in fixture JSON files."""
    fixtures_dir = _repo_root() / _FIXTURES_DIR
    findings: list[dict[str, Any]] = []

    for fixture_path in sorted(fixtures_dir.iterdir()):
        if not _is_fixture_file(fixture_path):
            continue
        text = fixture_path.read_text(encoding="utf-8")
        for label, pattern in _PATH_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "file": fixture_path.name,
                        "pattern": label,
                        "match": match.group(0),
                        "position": match.start(),
                    }
                )
        for label, pattern in _CREDENTIAL_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "file": fixture_path.name,
                        "pattern": label,
                        "match": match.group(0),
                        "position": match.start(),
                    }
                )

    if findings:
        return {
            "status": "FAIL",
            "detail": "real-data markers found in fixture files",
            "findings": findings[:50],  # cap to keep the receipt readable
            "finding_count": len(findings),
        }
    return {
        "status": "PASS",
        "detail": "no absolute paths or credential markers found in fixture files",
        "patterns_checked": [label for label, _ in _PATH_PATTERNS + _CREDENTIAL_PATTERNS],
    }


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "A05-01": _check_a05_01(),
        "A05-02": _check_a05_02(),
        "A05-03": _check_a05_03(),
        "A05-04": _check_a05_04(),
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
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for future checks.json invocations.
    if args and args[0] == "--check" and len(args) == _SINGLE_CHECK_ARGC:
        cid = args[1]
        runners = {
            "A05-01": _check_a05_01,
            "A05-02": _check_a05_02,
            "A05-03": _check_a05_03,
            "A05-04": _check_a05_04,
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
    # Stable CWD-independent behavior: run from repo root so relative paths
    # resolve predictably.
    try:
        os.chdir(_repo_root())
    except OSError:
        pass
    raise SystemExit(main())
