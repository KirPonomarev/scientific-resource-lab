"""Tests for :mod:`srl.packs.materialize`.

Tests verify tree-hash verification, post-copy integrity checks, and the
immutable-store refusal before any execution is staged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.packs import (
    LICENSE_INCOMPATIBLE_REASON,
    PACK_INTEGRITY_FAILURE_REASON,
    PLATFORM_UNSUPPORTED_REASON,
    LicenseError,
    MaterializationError,
    MaterializationReceipt,
    PlatformError,
    build_manifest,
    check_manifest_platform,
    compute_tree_sha256,
    current_platform,
    extract_pack,
    materialize,
)


def _extract_valid_pack(make_fixtures: Any, tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Generate fixtures, extract the valid pack, and return its root + manifest."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    pack_root = tmp_path / "pack_root"
    entrypoints = {"run.py", "compute.py"}
    extract_pack(fixtures.valid_tar, pack_root, entrypoints=entrypoints)
    manifest = json.loads(fixtures.manifest_valid.read_text(encoding="utf-8"))
    manifest["tree_sha256"] = compute_tree_sha256(pack_root)
    return pack_root, manifest


def test_materialize_valid_pack_emits_receipt(make_fixtures: Any, tmp_path: Path) -> None:
    """Materializing a valid pack copies content and emits a verified receipt."""
    pack_root, manifest = _extract_valid_pack(make_fixtures, tmp_path)
    staging = tmp_path / "staging"
    receipt = materialize(manifest, pack_root, staging)
    assert isinstance(receipt, MaterializationReceipt)
    assert receipt.verified is True
    assert receipt.from_tree_sha256 == receipt.to_tree_sha256
    assert receipt.schema_version == "MaterializationReceipt/v1"
    assert receipt.grants_authority is False
    assert receipt.canonical_writes == 0
    assert staging.is_dir()


def test_materialize_refuses_immutable_store(make_fixtures: Any, tmp_path: Path) -> None:
    """A pack root inside an immutable store is refused."""
    pack_root, manifest = _extract_valid_pack(make_fixtures, tmp_path)
    immutable_root = tmp_path / "store"
    immutable_root.mkdir()
    (immutable_root / ".srl_immutable").write_text("", encoding="utf-8")
    moved_root = immutable_root / "packs" / "test"
    moved_root.parent.mkdir(parents=True)
    pack_root.rename(moved_root)

    staging = tmp_path / "staging"
    with pytest.raises(MaterializationError) as exc_info:
        materialize(manifest, moved_root, staging)
    assert exc_info.value.fail_reason == PACK_INTEGRITY_FAILURE_REASON
    assert "mutable T7 execution forbidden" in str(exc_info.value)


def test_materialize_tree_hash_mismatch(make_fixtures: Any, tmp_path: Path) -> None:
    """A manifest tree_sha256 that does not match the pack root is rejected."""
    pack_root, manifest = _extract_valid_pack(make_fixtures, tmp_path)
    manifest["tree_sha256"] = "sha256:" + "f" * 64
    staging = tmp_path / "staging"
    with pytest.raises(MaterializationError) as exc_info:
        materialize(manifest, pack_root, staging)
    assert exc_info.value.fail_reason == PACK_INTEGRITY_FAILURE_REASON


def test_materialize_post_copy_tree_hash_mismatch(make_fixtures: Any, tmp_path: Path) -> None:
    """A pack whose post-copy tree differs from the manifest is rejected."""
    pack_root, _manifest = _extract_valid_pack(make_fixtures, tmp_path)
    # Add a symlink that the pre-copy tree hash ignores but the copy materializes.
    (pack_root / "link.txt").symlink_to(pack_root / "run.py")
    manifest = dict(_manifest)
    manifest["tree_sha256"] = compute_tree_sha256(pack_root)

    staging = tmp_path / "staging"
    with pytest.raises(MaterializationError) as exc_info:
        materialize(manifest, pack_root, staging)
    assert exc_info.value.fail_reason == PACK_INTEGRITY_FAILURE_REASON


def test_check_manifest_platform_accepts_current(make_fixtures: Any, tmp_path: Path) -> None:
    """The valid fixture manifest supports the current platform."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    manifest = json.loads(fixtures.manifest_valid.read_text(encoding="utf-8"))
    check_manifest_platform(manifest, current_platform())


def test_check_manifest_platform_rejects_wrong_platform(make_fixtures: Any, tmp_path: Path) -> None:
    """The wrong-platform fixture manifest raises PLATFORM_UNSUPPORTED."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    manifest = json.loads(fixtures.manifest_wrong_platform.read_text(encoding="utf-8"))
    with pytest.raises(PlatformError) as exc_info:
        check_manifest_platform(manifest, current_platform())
    assert exc_info.value.fail_reason == PLATFORM_UNSUPPORTED_REASON


def test_build_manifest_from_gpl_fixture(make_fixtures: Any, tmp_path: Path) -> None:
    """The GPL fixture manifest raises LICENSE_INCOMPATIBLE."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    manifest = json.loads(fixtures.manifest_gpl.read_text(encoding="utf-8"))
    with pytest.raises(LicenseError) as exc_info:
        build_manifest(manifest)
    assert exc_info.value.fail_reason == LICENSE_INCOMPATIBLE_REASON
