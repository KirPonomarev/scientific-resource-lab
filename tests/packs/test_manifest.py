"""Tests for :mod:`srl.packs.manifest`.

All tests are hermetic: they run against a temporary fixture directory or
inline manifest dicts so they never depend on committed binary files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.packs import (
    LICENSE_INCOMPATIBLE_REASON,
    LICENSE_UNKNOWN_REASON,
    LicenseError,
    PackManifestError,
    ResourcePackManifest,
    build_manifest,
    compute_tree_sha256,
)
from srl.planning.profiles import SCIENCE_LAB_PROFILES


def _minimal_manifest(tree_sha256: str) -> dict[str, Any]:
    """Return a minimal valid manifest dict for testing."""
    return {
        "schema_version": "ResourcePackManifest/v1",
        "pack_id": "test.pack",
        "name": "Test Pack",
        "version": "1.0.0",
        "capability_profiles": ["algebra_exact"],
        "platforms": [{"os": "linux", "arch": "x86_64", "abi": None}],
        "source": {
            "url": None,
            "commit": None,
            "source_sha256": "sha256:" + "a" * 64,
        },
        "lock_sha256": "sha256:" + "b" * 64,
        "tree_sha256": tree_sha256,
        "license": {
            "spdx": "MIT",
            "texts_sha256": ["sha256:" + "c" * 64],
        },
        "sbom_sha256": None,
        "entrypoints": [
            {"entrypoint_id": "runtime", "kind": "python_module", "ref": "run.py"},
        ],
        "probes": {"runtime_probe": "runtime", "actual_compute_probe": "runtime"},
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def test_build_valid_manifest() -> None:
    """A minimal valid manifest dict builds without error."""
    manifest = build_manifest(_minimal_manifest("sha256:" + "d" * 64))
    assert isinstance(manifest, ResourcePackManifest)
    assert manifest.schema_version == "ResourcePackManifest/v1"
    assert manifest.pack_id == "test.pack"
    assert manifest.canonical_writes == 0
    assert manifest.grants_authority is False


def test_manifest_to_dict_roundtrip() -> None:
    """``to_dict`` is JSON-serializable and carries the expected fields."""
    manifest = build_manifest(_minimal_manifest("sha256:" + "d" * 64))
    raw = manifest.to_dict()
    serialized = json.dumps(raw)
    parsed = json.loads(serialized)
    assert parsed["pack_id"] == raw["pack_id"]
    assert parsed["capability_profiles"] == list(raw["capability_profiles"])


def test_manifest_canonical_dumps_sorted_keys() -> None:
    """Canonical dumps uses sorted keys and a trailing newline."""
    manifest = build_manifest(_minimal_manifest("sha256:" + "d" * 64))
    data = manifest.canonical_dumps()
    assert data.endswith(b"\n")
    parsed = json.loads(data)
    assert list(parsed.keys()) == sorted(parsed.keys())


def test_capability_profiles_subset_of_b14() -> None:
    """All valid capability profiles must be known B14 profile names."""
    valid = _minimal_manifest("sha256:" + "d" * 64)
    valid["capability_profiles"] = list(SCIENCE_LAB_PROFILES)
    manifest = build_manifest(valid)
    assert set(manifest.capability_profiles) == set(SCIENCE_LAB_PROFILES)


def test_unknown_capability_profile_rejected() -> None:
    """An unknown profile name raises a contract error."""
    invalid = _minimal_manifest("sha256:" + "d" * 64)
    invalid["capability_profiles"] = ["not_a_profile"]
    with pytest.raises(PackManifestError) as exc_info:
        build_manifest(invalid)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_missing_required_key_rejected() -> None:
    """A manifest missing a required top-level key is rejected."""
    invalid = _minimal_manifest("sha256:" + "d" * 64)
    del invalid["pack_id"]
    with pytest.raises(PackManifestError) as exc_info:
        build_manifest(invalid)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_extra_top_level_key_rejected() -> None:
    """A manifest with an extra top-level key is rejected."""
    invalid = _minimal_manifest("sha256:" + "d" * 64)
    invalid["extra"] = "value"
    with pytest.raises(PackManifestError) as exc_info:
        build_manifest(invalid)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_bad_schema_version_rejected() -> None:
    """A manifest with a wrong schema_version is rejected."""
    invalid = _minimal_manifest("sha256:" + "d" * 64)
    invalid["schema_version"] = "ResourcePackManifest/v2"
    with pytest.raises(PackManifestError) as exc_info:
        build_manifest(invalid)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


@pytest.mark.parametrize(
    "spdx, expected_reason",
    [
        ("MIT", None),
        ("Apache-2.0", None),
        ("GPL-3.0", LICENSE_INCOMPATIBLE_REASON),
        ("GPL-2.0-only", LICENSE_INCOMPATIBLE_REASON),
        ("LGPL-3.0-or-later", LICENSE_INCOMPATIBLE_REASON),
        ("AGPL-1.0", LICENSE_INCOMPATIBLE_REASON),
        ("SSPL-1.0", LICENSE_INCOMPATIBLE_REASON),
        ("BUSL-1.1", LICENSE_INCOMPATIBLE_REASON),
        ("Proprietary", LICENSE_UNKNOWN_REASON),
    ],
)
def test_license_policy(spdx: str, expected_reason: str | None) -> None:
    """License allowlist, incompatible prefixes, and unknown licenses are enforced."""
    doc = _minimal_manifest("sha256:" + "d" * 64)
    doc["license"]["spdx"] = spdx
    if expected_reason is None:
        manifest = build_manifest(doc)
        assert manifest.license.spdx == spdx
    else:
        with pytest.raises(LicenseError) as exc_info:
            build_manifest(doc)
        assert exc_info.value.fail_reason == expected_reason


def test_canonical_writes_must_be_zero() -> None:
    """canonical_writes is enforced to be exactly 0."""
    invalid = _minimal_manifest("sha256:" + "d" * 64)
    invalid["canonical_writes"] = 1
    with pytest.raises(PackManifestError) as exc_info:
        build_manifest(invalid)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_grants_authority_must_be_false() -> None:
    """grants_authority is enforced to be False."""
    invalid = _minimal_manifest("sha256:" + "d" * 64)
    invalid["grants_authority"] = True
    with pytest.raises(PackManifestError) as exc_info:
        build_manifest(invalid)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_probe_must_point_at_declared_entrypoint() -> None:
    """Probe ids must reference declared entrypoints."""
    invalid = _minimal_manifest("sha256:" + "d" * 64)
    invalid["probes"]["actual_compute_probe"] = "missing"
    with pytest.raises(PackManifestError) as exc_info:
        build_manifest(invalid)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"


def test_compute_tree_sha256_deterministic(tmp_path: Path) -> None:
    """The same tree produces the same tree_sha256 across calls."""
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.txt").write_text("alpha", encoding="utf-8")
    (root / "b").mkdir()
    (root / "b" / "c.txt").write_text("gamma", encoding="utf-8")
    first = compute_tree_sha256(root)
    second = compute_tree_sha256(root)
    assert first == second
    assert first.startswith("sha256:")


def test_compute_tree_sha256_changes_with_content(tmp_path: Path) -> None:
    """Changing file content changes the tree hash."""
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.txt").write_text("alpha", encoding="utf-8")
    first = compute_tree_sha256(root)
    (root / "a.txt").write_text("beta", encoding="utf-8")
    second = compute_tree_sha256(root)
    assert first != second


def test_build_manifest_from_fixture(make_fixtures: Any, tmp_path: Path) -> None:
    """The generated valid fixture manifest builds and validates."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    raw = json.loads(fixtures.manifest_valid.read_text(encoding="utf-8"))
    manifest = build_manifest(raw)
    assert manifest.pack_id == "srl.pack.test"
    assert manifest.license.spdx == "MIT"
