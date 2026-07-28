#!/usr/bin/env python3
"""Generate WP-C22 conformance fixtures at gate/test time.

No binary fixtures are committed; this script creates them on demand in a
scratch directory. All archives are produced with the standard library tarfile
module and exercise the safe-extraction rules in :mod:`srl.packs.extract`.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Make the in-repo srl package importable when the script is run directly.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[3]  # fixtures/conformance/packs/make_fixtures.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.packs.manifest import compute_tree_sha256  # noqa: E402

# A stable 64-hex sha256 digest used for non-content fixture fields.
_FAKE_SHA256: str = "sha256:" + "a" * 64

# Sample file contents for the valid pack.
_RUN_PY: bytes = b"def runtime_probe(): return {'ready': True}\n"
_COMPUTE_PY: bytes = b"def actual_compute_probe(): return {'result': 42}\n"
_PARAMETERS_JSON: bytes = b'{"tolerance": 1e-9}\n'
_LICENSE_TXT: bytes = b"MIT License\nCopyright (c) Example\n"


@dataclass(frozen=True, slots=True)
class PackFixtures:
    """Paths to all generated WP-C22 fixtures."""

    valid_dir: Path
    valid_tar: Path
    traversal_tar: Path
    symlink_tar: Path
    hardlink_tar: Path
    device_tar: Path
    setuid_tar: Path
    stray_exec_tar: Path
    manifest_valid: Path
    manifest_gpl: Path
    manifest_unknown: Path
    manifest_wrong_platform: Path
    manifest_bad_tree: Path


def _sha256_bytes(data: bytes) -> str:
    """Return the sha256 digest of ``data`` with the SRL prefix."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _license_text_sha256() -> str:
    """Return the content-addressed digest of the sample license text."""
    return _sha256_bytes(_LICENSE_TXT)


def _build_valid_pack_dir(base: Path) -> Path:
    """Create a tiny valid pack directory and return its path."""
    pack_dir = base / "valid_pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "run.py").write_bytes(_RUN_PY)
    (pack_dir / "compute.py").write_bytes(_COMPUTE_PY)
    data_dir = pack_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "parameters.json").write_bytes(_PARAMETERS_JSON)
    (pack_dir / "LICENSE.txt").write_bytes(_LICENSE_TXT)
    return pack_dir


def _create_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    """Create a tar archive from a list of (TarInfo, content) pairs."""
    with tarfile.open(path, "w") as tar:
        for info, content in members:
            tar.addfile(info, io.BytesIO(content))


def _make_valid_tar(fixtures_dir: Path, valid_dir: Path) -> Path:
    """Create a benign tar archive of the valid pack."""
    tar_path = fixtures_dir / "valid.tar"
    with tarfile.open(tar_path, "w") as tar:
        for dirpath, _dirnames, filenames in os.walk(valid_dir):
            for filename in filenames:
                full = Path(dirpath) / filename
                rel = full.relative_to(valid_dir).as_posix()
                info = tarfile.TarInfo(name=rel)
                data = full.read_bytes()
                info.size = len(data)
                info.mtime = 0
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    return tar_path


def _make_traversal_tar(fixtures_dir: Path) -> Path:
    """Create a tar whose member escapes via '..' segments."""
    tar_path = fixtures_dir / "traversal.tar"
    info = tarfile.TarInfo(name="data/../../evil.txt")
    info.size = 0
    info.mtime = 0
    info.mode = 0o644
    _create_tar(tar_path, [(info, b"")])
    return tar_path


def _make_symlink_tar(fixtures_dir: Path) -> Path:
    """Create a tar containing a symlink pointing outside the destination."""
    tar_path = fixtures_dir / "symlink.tar"
    info = tarfile.TarInfo(name="link")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    info.mtime = 0
    info.mode = 0o777
    _create_tar(tar_path, [(info, b"")])
    return tar_path


def _make_hardlink_tar(fixtures_dir: Path) -> Path:
    """Create a tar containing a hard link."""
    tar_path = fixtures_dir / "hardlink.tar"
    info = tarfile.TarInfo(name="hardlink")
    info.type = tarfile.LNKTYPE
    info.linkname = "target"
    info.mtime = 0
    info.size = 0
    info.mode = 0o644
    _create_tar(tar_path, [(info, b"")])
    return tar_path


def _make_device_tar(fixtures_dir: Path) -> Path:
    """Create a tar containing a character device node."""
    tar_path = fixtures_dir / "device.tar"
    info = tarfile.TarInfo(name="null")
    info.type = tarfile.CHRTYPE
    info.devmajor = 1
    info.devminor = 3
    info.mtime = 0
    info.mode = 0o666
    _create_tar(tar_path, [(info, b"")])
    return tar_path


def _make_setuid_tar(fixtures_dir: Path) -> Path:
    """Create a tar containing a regular file with setuid bit set."""
    tar_path = fixtures_dir / "setuid.tar"
    info = tarfile.TarInfo(name="setuid_bin")
    info.size = 2
    info.mtime = 0
    info.mode = 0o4755  # setuid + executable
    _create_tar(tar_path, [(info, b"hi")])
    return tar_path


def _make_stray_exec_tar(fixtures_dir: Path) -> Path:
    """Create a tar containing a non-entrypoint file with executable bits."""
    tar_path = fixtures_dir / "stray_exec.tar"
    info = tarfile.TarInfo(name="not_an_entrypoint.sh")
    info.size = 2
    info.mtime = 0
    info.mode = 0o755  # executable but not declared as an entrypoint
    _create_tar(tar_path, [(info, b"hi")])
    return tar_path


def _base_manifest(tree_sha256: str, platform_arch: str = "arm64") -> dict[str, Any]:
    """Return a base manifest dict that can be specialized for each fixture."""
    return {
        "schema_version": "ResourcePackManifest/v1",
        "pack_id": "srl.pack.test",
        "name": "Test Pack",
        "version": "1.0.0",
        "capability_profiles": ["algebra_exact"],
        "platforms": [
            {"os": "linux", "arch": "x86_64", "abi": None},
            {"os": "macos", "arch": platform_arch, "abi": None},
        ],
        "source": {"url": None, "commit": None, "source_sha256": _FAKE_SHA256},
        "lock_sha256": _FAKE_SHA256,
        "tree_sha256": tree_sha256,
        "license": {"spdx": "MIT", "texts_sha256": [_license_text_sha256()]},
        "sbom_sha256": None,
        "entrypoints": [
            {"entrypoint_id": "runtime", "kind": "python_module", "ref": "run.py"},
            {"entrypoint_id": "compute", "kind": "python_module", "ref": "compute.py"},
        ],
        "probes": {"runtime_probe": "runtime", "actual_compute_probe": "compute"},
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Write compact JSON to ``path``."""
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def make_all_fixtures(base_dir: str | Path) -> PackFixtures:
    """Generate all WP-C22 conformance fixtures under ``base_dir``.

    Parameters
    ----------
    base_dir:
        Scratch directory where the fixtures are created. It is created if it
        does not exist.

    Returns
    -------
    PackFixtures
        Paths to every generated fixture.
    """
    fixtures_dir = Path(base_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    valid_dir = _build_valid_pack_dir(fixtures_dir)
    valid_tree = compute_tree_sha256(valid_dir)
    valid_tar = _make_valid_tar(fixtures_dir, valid_dir)

    traversal_tar = _make_traversal_tar(fixtures_dir)
    symlink_tar = _make_symlink_tar(fixtures_dir)
    hardlink_tar = _make_hardlink_tar(fixtures_dir)
    device_tar = _make_device_tar(fixtures_dir)
    setuid_tar = _make_setuid_tar(fixtures_dir)
    stray_exec_tar = _make_stray_exec_tar(fixtures_dir)

    manifest_valid = fixtures_dir / "manifest_valid.json"
    _write_json(manifest_valid, _base_manifest(valid_tree))

    manifest_gpl = fixtures_dir / "manifest_gpl.json"
    gpl_doc = _base_manifest(valid_tree)
    gpl_doc["license"] = {"spdx": "GPL-3.0", "texts_sha256": [_FAKE_SHA256]}
    _write_json(manifest_gpl, gpl_doc)

    manifest_unknown = fixtures_dir / "manifest_unknown.json"
    unknown_doc = _base_manifest(valid_tree)
    unknown_doc["license"] = {"spdx": "Unknown-License", "texts_sha256": [_FAKE_SHA256]}
    _write_json(manifest_unknown, unknown_doc)

    manifest_wrong_platform = fixtures_dir / "manifest_wrong_platform.json"
    wrong_doc = _base_manifest(valid_tree)
    wrong_doc["platforms"] = [{"os": "macos", "arch": "x86_64", "abi": None}]
    _write_json(manifest_wrong_platform, wrong_doc)

    manifest_bad_tree = fixtures_dir / "manifest_bad_tree.json"
    bad_tree_doc = _base_manifest(valid_tree)
    bad_tree_doc["tree_sha256"] = _FAKE_SHA256
    _write_json(manifest_bad_tree, bad_tree_doc)

    return PackFixtures(
        valid_dir=valid_dir,
        valid_tar=valid_tar,
        traversal_tar=traversal_tar,
        symlink_tar=symlink_tar,
        hardlink_tar=hardlink_tar,
        device_tar=device_tar,
        setuid_tar=setuid_tar,
        stray_exec_tar=stray_exec_tar,
        manifest_valid=manifest_valid,
        manifest_gpl=manifest_gpl,
        manifest_unknown=manifest_unknown,
        manifest_wrong_platform=manifest_wrong_platform,
        manifest_bad_tree=manifest_bad_tree,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: generate fixtures into a default tmp directory."""
    parser = argparse.ArgumentParser(description="Generate WP-C22 conformance fixtures")
    parser.add_argument(
        "--out",
        default=str(_REPO_ROOT / ".tmp" / "wp22-fixtures"),
        help="Output directory for generated fixtures",
    )
    args = parser.parse_args(argv)

    fixtures = make_all_fixtures(args.out)
    print(json.dumps({k: str(v) for k, v in asdict(fixtures).items()}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
