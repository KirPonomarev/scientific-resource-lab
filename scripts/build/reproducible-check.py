#!/usr/bin/env python3
"""Reproducible-wheel check for SRL.

Builds the wheel twice into two independent clean output directories with a
fixed ``SOURCE_DATE_EPOCH``, normalizes both wheels as zip archives (sorted
entries, zeroed timestamps), and compares them per-entry by SHA-256.

On success it prints a one-line canonical JSON manifest to stdout and exits 0:

    {"entries": <int>, "content_manifest_sha256": "<hex>"}

On any mismatch it prints a JSON error object and exits non-zero so the check
can be wired into CI and ``make repro-check``.

Design notes
------------
- Two independent build directories isolate the build outputs so a stale
  artifact cannot make the comparison trivially pass.
- ``SOURCE_DATE_EPOCH`` is the conventional environment variable (PEP 558 /
  SOURCE_DATE_EPOCH spec) tools consult for reproducible timestamps. The fixed
  value (2024-01-01T00:00:00Z) is documented in the manifest.
- Normalization zeroes every entry's timestamp and sorts entries by name before
  hashing, so non-determinism in zip packing order or mtimes does not produce
  false negatives. A genuine content difference shows up as a per-entry sha256
  mismatch, which we report.
- Standard library only: no dependency on the project's environment beyond
  ``uv`` itself being on PATH.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

# Fixed reproducibility anchor. Documented in the manifest. Do not change
# without bumping the manifest schema version.
SOURCE_DATE_EPOCH: str = "1704067200"  # 2024-01-01T00:00:00Z

MANIFEST_SCHEMA: str = "ReproducibleWheelManifest/v1"
ERROR_SCHEMA: str = "ReproducibleWheelCheckError/v1"


class EntryHash(NamedTuple):
    """A normalized zip entry identified by archive path and content hash."""

    name: str
    sha256: str


class CheckError(Exception):
    """Raised when the reproducible-wheel check fails.

    Carries an optional ``detail`` string for diagnostics. Constructed with
    positional args (``CheckError(message, detail)``) so it never relies on
    ``Exception`` accepting keyword arguments.
    """

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail: str = detail

    @property
    def message(self) -> str:
        """The primary error message (first positional arg)."""
        return str(self.args[0]) if self.args else ""


def _emit(manifest: dict[str, Any]) -> None:
    """Write one canonical JSON line to stdout (sorted keys, compact)."""
    line = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _emit_error(message: str, detail: str = "") -> None:
    """Emit a canonical JSON error object."""
    payload: dict[str, Any] = {
        "schema_version": ERROR_SCHEMA,
        "error": message,
    }
    if detail:
        payload["detail"] = detail
    _emit(payload)


def _find_wheel(directory: Path) -> Path:
    """Return the single wheel produced in ``directory``."""
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1:
        msg = (
            f"expected exactly one wheel in {directory}, found {len(wheels)}: "
            f"{[w.name for w in wheels]}"
        )
        raise CheckError(msg)
    return wheels[0]


def _build_wheel(out_dir: Path) -> Path:
    """Build the wheel into ``out_dir`` with SOURCE_DATE_EPOCH pinned.

    Builds run in an isolated, clean directory so output isolation does not
    depend on the caller's working tree state.
    """
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    # ``--wheel`` restricts output to the wheel; ``--out-dir`` sets the target.
    result = subprocess.run(  # noqa: S603 - argv is fully controlled
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CheckError(
            f"uv build failed (rc={result.returncode})",
            detail=(result.stderr or result.stdout).strip()[-2000:],
        )
    return _find_wheel(out_dir)


def _normalize_wheel(wheel: Path) -> list[EntryHash]:
    """Return per-entry hashes for ``wheel`` under a normalized zip view.

    Normalization: sort entries by name, zero their timestamps. The hash is
    over entry content only. This makes the comparison insensitive to zip
    packing order and mtime, while still detecting any real content change.
    """
    if not zipfile.is_zipfile(wheel):
        msg = f"not a zip/wheel: {wheel}"
        raise CheckError(msg)
    entries: list[EntryHash] = []
    with zipfile.ZipFile(wheel) as zf:
        names = sorted(zf.namelist())
        for name in names:
            info = zf.getinfo(name)
            data = zf.read(info)
            digest = hashlib.sha256(data).hexdigest()
            entries.append(EntryHash(name=name, sha256=digest))
    return entries


def _content_manifest_sha256(entries: list[EntryHash]) -> str:
    """Hash the sorted (name, sha256) entry list into one manifest digest.

    The manifest is canonical JSON over the entry list, hashed with SHA-256.
    Equal wheels produce equal manifests produce equal digests.
    """
    payload = [
        {"name": e.name, "sha256": e.sha256}
        for e in sorted(entries, key=lambda x: x.name)
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _diff_entries(left: list[EntryHash], right: list[EntryHash]) -> str | None:
    """Return a human-readable difference string, or ``None`` if equal."""
    left_map = {e.name: e.sha256 for e in left}
    right_map = {e.name: e.sha256 for e in right}
    diffs: list[str] = []
    for name in sorted(set(left_map) | set(right_map)):
        l = left_map.get(name, "<missing>")
        r = right_map.get(name, "<missing>")
        if l != r:
            diffs.append(f"{name}: {l} != {r}")
    return "; ".join(diffs) if diffs else None


def run_check(repo_root: Path) -> dict[str, Any]:
    """Run the reproducible-wheel check and return the success manifest.

    Raises :class:`CheckError` on any failure.
    """
    with tempfile.TemporaryDirectory(prefix="srl-repro-") as tmp:
        tmp_path = Path(tmp)
        # Build each wheel in its own subdir so outputs cannot collide.
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        # ``uv build`` reads the project from the current working directory.
        # Run it from repo_root so the build sees the real pyproject.toml.
        wheel_a = _run_from(repo_root, _build_wheel, dir_a)
        wheel_b = _run_from(repo_root, _build_wheel, dir_b)

        if wheel_a.name != wheel_b.name:
            raise CheckError(
                "wheel names differ",
                detail=f"{wheel_a.name} != {wheel_b.name}",
            )

        entries_a = _normalize_wheel(wheel_a)
        entries_b = _normalize_wheel(wheel_b)

        diff = _diff_entries(entries_a, entries_b)
        if diff is not None:
            raise CheckError("wheel content differs between builds", detail=diff)

        manifest_sha = _content_manifest_sha256(entries_a)
        return {
            "schema_version": MANIFEST_SCHEMA,
            "wheel": wheel_a.name,
            "entries": len(entries_a),
            "content_manifest_sha256": manifest_sha,
            "source_date_epoch": SOURCE_DATE_EPOCH,
        }


def _run_from(
    repo_root: Path, fn: Callable[[Path], Path], out_dir: Path
) -> Path:
    """Run ``fn(out_dir)`` with the current working directory set to repo_root.

    A small wrapper so ``uv build`` always runs from the project root without
    sprinkling ``cwd=`` through the build helper.
    """
    prev = Path.cwd()
    try:
        os.chdir(repo_root)
        return fn(out_dir)
    finally:
        os.chdir(prev)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, non-zero on failure."""
    args = sys.argv[1:] if argv is None else argv
    repo_root = Path(args[0]).resolve() if args else Path.cwd().resolve()

    if not (repo_root / "pyproject.toml").is_file():
        _emit_error(
            "no pyproject.toml found",
            detail=str(repo_root),
        )
        return 2
    if shutil.which("uv") is None:
        _emit_error("uv not found on PATH")
        return 2

    try:
        manifest = run_check(repo_root)
    except CheckError as exc:
        _emit_error(exc.message, detail=exc.detail)
        return 1
    except subprocess.CalledProcessError as exc:
        _emit_error("uv build failed", detail=str(exc))
        return 1

    _emit(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
