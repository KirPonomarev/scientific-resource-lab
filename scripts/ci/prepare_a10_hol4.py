#!/usr/bin/env python3
"""Prepare a pinned HOL4 tree for the V3.7 A10 gate."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.packs.formal import (  # noqa: E402
    independent_prover_pin_manifest_hash,
    load_independent_prover_pins,
)

DEFAULT_CACHE_ROOT: Final[Path] = (
    Path(os.environ.get("TMPDIR", tempfile.gettempdir())) / "srl-a10-hol4-session-cache"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _installer_hash() -> str:
    return _sha256_file(Path(__file__))


def _cache_key(pins: dict[str, Any]) -> str:
    hol4 = pins["hol4"]
    payload = {
        "schema_version": "A10HOL4CacheKey/v1",
        "os": platform.system().lower(),
        "machine": platform.machine().lower(),
        "release_tag": hol4["release_tag"],
        "release_tar_sha256": hol4["release_tar_sha256"],
        "pin_manifest_sha256": independent_prover_pin_manifest_hash(),
        "installer_sha256": _installer_hash(),
    }
    digest = hashlib.sha256(dumps(payload)).hexdigest()
    return f"srl-a10-hol4-{payload['os']}-{payload['machine']}-{hol4['release_tag']}-{digest}"


def _validate_generated_script_bindings(path: Path) -> list[str]:
    failures: list[str] = []
    for rel in ("bin/hol", "bin/Holmake"):
        script = path / rel
        if not script.exists():
            continue
        rendered = script.read_text(encoding="utf-8", errors="replace")
        if ".staging-" in rendered:
            failures.append(f"{rel} contains embedded staging path")
        if str(path) not in rendered:
            failures.append(f"{rel} is not bound to final cache directory")
    return failures


def _polyml_lib_dir_candidates() -> tuple[Path, ...]:
    """Return bounded candidate directories that may contain ``libpolymain.a``."""
    candidates: list[Path] = []
    env_dir = os.environ.get("SRL_A10_POLYML_LIB_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    poly_executable = shutil.which("poly")
    if poly_executable:
        poly_path = Path(poly_executable).resolve()
        candidates.extend(
            (
                poly_path.parent.parent / "lib",
                poly_path.parent.parent / "lib64",
            )
        )
    machine = platform.machine().lower()
    multiarch = {
        "x86_64": "x86_64-linux-gnu",
        "amd64": "x86_64-linux-gnu",
        "aarch64": "aarch64-linux-gnu",
        "arm64": "aarch64-linux-gnu",
    }.get(machine)
    if multiarch:
        candidates.append(Path("/usr/lib") / multiarch)
    candidates.extend(
        (
            Path("/usr/lib"),
            Path("/usr/local/lib"),
            Path("/opt/homebrew/lib"),
            Path("/opt/local/lib"),
        )
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return tuple(deduped)


def _polyml_search_roots() -> tuple[Path, ...]:
    """Return bounded roots for fallback ``libpolymain.a`` discovery."""
    return (
        Path("/usr/lib"),
        Path("/usr/local/lib"),
        Path("/opt/homebrew/lib"),
        Path("/opt/local/lib"),
    )


def _find_polyml_lib_dir() -> Path | None:
    """Return the directory containing ``libpolymain.a`` if it is discoverable."""
    for candidate in _polyml_lib_dir_candidates():
        if (candidate / "libpolymain.a").exists():
            return candidate
    for root in _polyml_search_roots():
        if not root.exists():
            continue
        for path in root.rglob("libpolymain.a"):
            return path.parent
    return None


def _write_polyml_includes_if_found(hol4_home: Path) -> str | None:
    """Write HOL4's Poly/ML include override when the static library is present."""
    lib_dir = _find_polyml_lib_dir()
    if lib_dir is None:
        return None
    includes_dir = hol4_home / "tools-poly"
    includes_dir.mkdir(parents=True, exist_ok=True)
    (includes_dir / "poly-includes.ML").write_text(
        f'val polymllibdir = "{lib_dir}";\n',
        encoding="utf-8",
    )
    return str(lib_dir)


def _validate_hol4_home(path: Path, pins: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not path.exists():
        return False, ["HOL4 home does not exist"]
    for rel in ("bin/Holmake", "bin/hol", "tools/smart-configure.sml"):
        if not (path / rel).exists():
            failures.append(f"missing {rel}")
    marker = path / ".srl-a10-hol4.json"
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"marker JSON invalid: {exc}")
        else:
            if data.get("release_tag") != pins["hol4"]["release_tag"]:
                failures.append("release tag mismatch")
            if data.get("release_tar_sha256") != pins["hol4"]["release_tar_sha256"]:
                failures.append("tarball hash mismatch")
            if data.get("pin_manifest_sha256") != independent_prover_pin_manifest_hash():
                failures.append("pin manifest hash mismatch")
    else:
        failures.append("marker missing")
    failures.extend(_validate_generated_script_bindings(path))
    return not failures, failures


def _run(command: list[str], *, cwd: Path, input_bytes: bytes | None = None) -> None:
    proc = subprocess.run(  # noqa: S603 - command vectors are fixed by this helper.
        command,
        cwd=cwd,
        input=input_bytes,
        capture_output=True,
        check=False,
        timeout=1800.0,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[:4000]
        stdout = proc.stdout.decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(
            f"{command!r} failed with {proc.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )


def _download(url: str, target: Path, expected_sha256: str) -> None:
    with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310 - URL is pinned.
        with target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    actual = _sha256_file(target)
    if actual != expected_sha256:
        raise RuntimeError(
            f"HOL4 tarball sha256 mismatch: expected {expected_sha256}, got {actual}"
        )


def prepare_hol4(cache_root: Path = DEFAULT_CACHE_ROOT) -> dict[str, Any]:
    pins = load_independent_prover_pins()
    cache_key = _cache_key(pins)
    cache_root.mkdir(parents=True, exist_ok=True)
    final_dir = cache_root / cache_key
    lock_path = cache_root / ".a10-hol4.lock"
    prepare_count = 0
    fetch_count = 0
    polyml_lib_dir: str | None = None

    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        ok, failures = _validate_hol4_home(final_dir, pins)
        if not ok:
            shutil.rmtree(final_dir, ignore_errors=True)
            prepare_count = 1
            fetch_count = 1
            staging = Path(tempfile.mkdtemp(prefix=f"{cache_key}.staging-", dir=cache_root))
            try:
                archive = staging / pins["hol4"]["release_asset"]
                _download(
                    str(pins["hol4"]["release_url"]),
                    archive,
                    str(pins["hol4"]["release_tar_sha256"]),
                )
                with tarfile.open(archive, "r:gz") as tar:
                    tar.extractall(staging, filter="data")
                candidates = [item for item in staging.iterdir() if item.is_dir()]
                source_dirs = [
                    item for item in candidates if (item / "tools/smart-configure.sml").exists()
                ]
                if len(source_dirs) != 1:
                    raise RuntimeError("HOL4 tarball did not contain exactly one source root")
                source = source_dirs[0]
                source.rename(final_dir)
                polyml_lib_dir = _write_polyml_includes_if_found(final_dir)
                configure = (final_dir / "tools" / "smart-configure.sml").read_bytes()
                _run(["poly"], cwd=final_dir, input_bytes=configure)
                _run(["bin/build"], cwd=final_dir)
                marker = {
                    "schema_version": "PreparedHOL4/v1",
                    "release_tag": pins["hol4"]["release_tag"],
                    "release_tar_sha256": pins["hol4"]["release_tar_sha256"],
                    "pin_manifest_sha256": independent_prover_pin_manifest_hash(),
                    "polyml_lib_dir": polyml_lib_dir,
                    "canonical_writes": 0,
                    "grants_authority": False,
                }
                (final_dir / ".srl-a10-hol4.json").write_text(
                    json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
            except Exception:
                shutil.rmtree(final_dir, ignore_errors=True)
                raise
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            ok, failures = _validate_hol4_home(final_dir, pins)
            if not ok:
                raise RuntimeError(f"prepared HOL4 cache did not validate: {failures}")
            cache_status = "prepared"
        else:
            cache_status = "reused"

    return {
        "schema_version": "A10HOL4PrepareReport/v1",
        "cache_key": cache_key,
        "cache_status": cache_status,
        "prepare_count": prepare_count,
        "fetch_count": fetch_count,
        "hol4_home": str(final_dir),
        "polyml_lib_dir": polyml_lib_dir,
        "pin_manifest_sha256": independent_prover_pin_manifest_hash(),
        "installer_sha256": _installer_hash(),
        "canonical_writes": 0,
        "grants_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = prepare_hol4(args.cache_root)
    rendered = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
