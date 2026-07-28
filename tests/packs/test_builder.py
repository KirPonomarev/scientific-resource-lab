"""Tests for :mod:`srl.packs.builder`.

All tests are hermetic: they build packs inside temporary directories with
synthetic files and specs, never touching the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from srl.packs import (
    BuilderError,
    LicenseError,
    ResourcePackManifest,
    build_pack,
)


def _valid_spec(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid spec, with optional overrides."""
    spec: dict[str, Any] = {
        "name": "Test Pack",
        "version": "1.0.0",
        "capability_profiles": ["algebra_exact"],
        "entrypoints": [
            {"entrypoint_id": "runtime", "kind": "python_module", "ref": "run.py"},
            {"entrypoint_id": "compute", "kind": "python_module", "ref": "compute.py"},
        ],
        "source": {"url": None, "commit": None},
        "license": {"spdx": "MIT"},
    }
    spec.update(overrides)
    return spec


def _write_tree(workdir: Path, **files: str) -> None:
    """Write text files into ``workdir`` (keys are POSIX-style relative paths)."""
    for rel_path, content in files.items():
        path = workdir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_build_pack_emits_valid_manifest(tmp_path: Path) -> None:
    """A minimal valid spec and tree produce a validated manifest."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(
        workdir,
        **{
            "run.py": "def runtime(): pass\n",
            "compute.py": "def compute(): pass\n",
        },
    )

    manifest, tree = build_pack(_valid_spec(), workdir)
    assert isinstance(manifest, ResourcePackManifest)
    assert tree == workdir.resolve()
    assert manifest.schema_version == "ResourcePackManifest/v1"
    assert manifest.pack_id == "test_pack.1.0.0"
    assert manifest.name == "Test Pack"
    assert manifest.version == "1.0.0"
    assert manifest.capability_profiles == ("algebra_exact",)
    assert manifest.license.spdx == "MIT"
    assert manifest.canonical_writes == 0
    assert manifest.grants_authority is False


def test_build_pack_is_deterministic_for_same_inputs(tmp_path: Path) -> None:
    """The same spec and tree produce byte-identical canonical manifests."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(
        workdir,
        **{
            "run.py": "def runtime(): pass\n",
            "compute.py": "def compute(): pass\n",
        },
    )
    spec = _valid_spec()

    manifest1, _ = build_pack(spec, workdir)
    manifest2, _ = build_pack(spec, workdir)
    assert manifest1.canonical_dumps() == manifest2.canonical_dumps()
    assert manifest1.tree_sha256 == manifest2.tree_sha256


def test_build_pack_tree_hash_changes_with_content(tmp_path: Path) -> None:
    """Changing the tree content changes the manifest tree hash."""
    workdir1 = tmp_path / "pack1"
    workdir1.mkdir()
    _write_tree(workdir1, **{"run.py": "alpha\n"})

    workdir2 = tmp_path / "pack2"
    workdir2.mkdir()
    _write_tree(workdir2, **{"run.py": "beta\n"})

    manifest1, _ = build_pack(_valid_spec(), workdir1)
    manifest2, _ = build_pack(_valid_spec(), workdir2)
    assert manifest1.tree_sha256 != manifest2.tree_sha256


def test_build_pack_uses_provided_pack_id(tmp_path: Path) -> None:
    """An explicit spec pack_id overrides the derived one."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    manifest, _ = build_pack(_valid_spec(pack_id="custom.pack.id"), workdir)
    assert manifest.pack_id == "custom.pack.id"


def test_build_pack_unknown_license_rejected(tmp_path: Path) -> None:
    """An unknown SPDX license raises LicenseError with LICENSE_UNKNOWN."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    with pytest.raises(LicenseError) as exc_info:
        build_pack(_valid_spec(license={"spdx": "Weird-License"}), workdir)
    assert exc_info.value.fail_reason == "LICENSE_UNKNOWN"


def test_build_pack_incompatible_license_rejected(tmp_path: Path) -> None:
    """A GPL license raises LicenseError with LICENSE_INCOMPATIBLE."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    with pytest.raises(LicenseError) as exc_info:
        build_pack(_valid_spec(license={"spdx": "GPL-3.0"}), workdir)
    assert exc_info.value.fail_reason == "LICENSE_INCOMPATIBLE"


def test_build_pack_uses_license_text_file(tmp_path: Path) -> None:
    """A LICENSE.txt file in the tree is hashed into the manifest."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(
        workdir,
        **{
            "run.py": "# runtime\n",
            "LICENSE.txt": "Custom MIT License Text\n",
        },
    )
    manifest1, _ = build_pack(_valid_spec(), workdir)
    manifest2, _ = build_pack(_valid_spec(), workdir)
    assert manifest1.license.texts_sha256 == manifest2.license.texts_sha256


def test_build_pack_lock_file_hash(tmp_path: Path) -> None:
    """A lock.json file is hashed into lock_sha256."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n", "lock.json": '{"deps": []}\n'})
    manifest, _ = build_pack(_valid_spec(), workdir)
    assert manifest.lock_sha256 != "sha256:" + "0" * 64


def test_build_pack_source_sha256_deterministic(tmp_path: Path) -> None:
    """The same source metadata produces the same source_sha256."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    spec = _valid_spec(
        source={
            "url": "https://example.com/repo",
            "commit": "abc123",
        },
    )
    manifest1, _ = build_pack(spec, workdir)
    manifest2, _ = build_pack(spec, workdir)
    assert manifest1.source.source_sha256 == manifest2.source.source_sha256
    assert manifest1.source.url == "https://example.com/repo"
    assert manifest1.source.commit == "abc123"


def test_build_pack_default_probes_from_entrypoints(tmp_path: Path) -> None:
    """Default probes point to the first (and second, if available) entrypoints."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n", "compute.py": "# compute\n"})
    manifest, _ = build_pack(_valid_spec(), workdir)
    assert manifest.probes.runtime_probe == "runtime"
    assert manifest.probes.actual_compute_probe == "compute"


def test_build_pack_single_entrypoint_defaults_both_probes(tmp_path: Path) -> None:
    """With only one entrypoint, both probes default to it."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    spec = _valid_spec(
        entrypoints=[{"entrypoint_id": "only", "kind": "python_module", "ref": "run.py"}],
    )
    manifest, _ = build_pack(spec, workdir)
    assert manifest.probes.runtime_probe == "only"
    assert manifest.probes.actual_compute_probe == "only"


def test_build_pack_custom_probes(tmp_path: Path) -> None:
    """An explicit probes block is preserved in the manifest."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n", "compute.py": "# compute\n"})
    spec = _valid_spec(
        probes={"runtime_probe": "compute", "actual_compute_probe": "runtime"},
    )
    manifest, _ = build_pack(spec, workdir)
    assert manifest.probes.runtime_probe == "compute"
    assert manifest.probes.actual_compute_probe == "runtime"


def test_build_pack_missing_workdir(tmp_path: Path) -> None:
    """A non-existent workdir raises BuilderError."""
    with pytest.raises(BuilderError):
        build_pack(_valid_spec(), tmp_path / "missing")


def test_build_pack_bad_capability_profile(tmp_path: Path) -> None:
    """An unknown capability profile raises BuilderError."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    with pytest.raises(BuilderError):
        build_pack(_valid_spec(capability_profiles=["not_a_profile"]), workdir)


def test_build_pack_bad_entrypoint_kind(tmp_path: Path) -> None:
    """An entrypoint kind other than python_module raises BuilderError."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    spec = _valid_spec(
        entrypoints=[{"entrypoint_id": "bad", "kind": "binary", "ref": "run.py"}],
    )
    with pytest.raises(BuilderError):
        build_pack(spec, workdir)


def test_build_pack_custom_created_utc(tmp_path: Path) -> None:
    """An explicit created_utc in the spec is preserved."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    spec = _valid_spec(created_utc="2026-07-28T00:00:00Z")
    manifest, _ = build_pack(spec, workdir)
    assert manifest.created_utc == "2026-07-28T00:00:00Z"


def test_build_pack_default_platforms(tmp_path: Path) -> None:
    """Default platforms cover all four supported os/arch combinations."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    manifest, _ = build_pack(_valid_spec(), workdir)
    platforms = {(p.os, p.arch) for p in manifest.platforms}
    expected = {
        ("linux", "x86_64"),
        ("linux", "arm64"),
        ("macos", "x86_64"),
        ("macos", "arm64"),
    }
    assert platforms == expected


def test_build_pack_canonical_writes_zero(tmp_path: Path) -> None:
    """The builder emits a manifest with canonical_writes=0."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    manifest, _ = build_pack(_valid_spec(), workdir)
    assert manifest.canonical_writes == 0
    assert manifest.grants_authority is False


def test_build_pack_uses_workdir_license_file_over_default(tmp_path: Path) -> None:
    """A LICENSE.txt file overrides the deterministic default license text."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(
        workdir,
        **{
            "run.py": "# runtime\n",
            "LICENSE.txt": "A\n",
        },
    )
    manifest_a, _ = build_pack(_valid_spec(), workdir)

    workdir_b = tmp_path / "pack_b"
    workdir_b.mkdir()
    _write_tree(
        workdir_b,
        **{
            "run.py": "# runtime\n",
            "LICENSE.txt": "B\n",
        },
    )
    manifest_b, _ = build_pack(_valid_spec(), workdir_b)
    assert manifest_a.license.texts_sha256 != manifest_b.license.texts_sha256


def test_build_pack_empty_spec_name_rejected(tmp_path: Path) -> None:
    """An empty pack name is rejected at build time."""
    workdir = tmp_path / "pack"
    workdir.mkdir()
    _write_tree(workdir, **{"run.py": "# runtime\n"})
    with pytest.raises(BuilderError):
        build_pack(_valid_spec(name=""), workdir)
