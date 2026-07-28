"""Tests for :mod:`srl.catalog.registry`.

Hermetic: runs against the packaged seed registry and in-memory synthetic
entries built with ``build_entry``.
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

from srl.catalog.registry import (
    ADMISSION_STAGES,
    NOT_ADMITTED_STAGE,
    CapabilityRegistryEntry,
    CatalogError,
    MeasuredResources,
    PlatformSpec,
    Provenance,
    _build_entry_from_raw,
    build_default_registry,
    build_entry,
    load_registry_seed,
)
from srl.planning.profiles import SCIENCE_LAB_PROFILES
from tests.catalog._helpers import make_admitted_entry, make_entry


def test_seed_loads_15_entries_sorted() -> None:
    """The packaged seed loads exactly 15 entries, sorted by capability_id."""
    entries = load_registry_seed()
    assert len(entries) == len(SCIENCE_LAB_PROFILES)
    ids = [e.capability_id for e in entries]
    assert ids == sorted(ids)
    # Every B14 profile is represented exactly once.
    profiles = {e.profile for e in entries}
    assert profiles == set(SCIENCE_LAB_PROFILES)


def test_build_default_registry_matches_seed() -> None:
    """build_default_registry returns the seed entries."""
    assert build_default_registry() == load_registry_seed()


def test_seed_entries_are_honestly_not_admitted() -> None:
    """Every seed entry is not_admitted with NOASSERTION license (honesty)."""
    for entry in load_registry_seed():
        assert entry.admission_stage == NOT_ADMITTED_STAGE
        assert entry.pack_manifest_digest is None
        assert entry.measured_resources is None
        assert entry.license_spdx == "NOASSERTION"
        assert entry.provenance.source_url is None
        assert entry.provenance.source_sha256 is None


def test_seed_entries_match_b14_catalog_data() -> None:
    """The seed capability_ids and adapter_ids mirror B14 catalog_data.json."""
    b14_raw = (
        resources.files("srl.planning").joinpath("catalog_data.json").read_text(encoding="utf-8")
    )
    b14 = json.loads(b14_raw)
    b14_by_profile = {c["profile"]: c for c in b14["capabilities"]}
    for entry in load_registry_seed():
        b14_entry = b14_by_profile[entry.profile]
        assert entry.capability_id == b14_entry["capability_id"]
        assert entry.adapter_id == b14_entry["adapter_id"]


def test_build_entry_valid_admitted_entry() -> None:
    """build_entry accepts a fully-populated EXPERIMENTAL_ACCEPTED entry."""
    entry = make_admitted_entry()
    assert entry.admission_stage == "EXPERIMENTAL_ACCEPTED"
    assert entry.adapter_id == "ripser"
    assert entry.measured_resources is not None
    assert entry.measured_resources.wall_seconds == 3.5
    assert entry.license_spdx == "MIT"


@pytest.mark.parametrize(
    ("field", "bad_value", "reason_substring"),
    [
        ("capability_id", "", "capability_id"),
        ("capability_id", 123, "capability_id"),
        ("profile", "not_a_profile", "profile"),
        ("profile", "", "profile"),
        ("adapter_id", "", "adapter_id"),
        ("pack_manifest_digest", "not-a-digest", "pack_manifest_digest"),
        ("license_spdx", "", "license_spdx"),
        ("admission_stage", "BOGUS_STAGE", "admission_stage"),
    ],
)
def test_build_entry_rejects_invalid_scalars(
    field: str, bad_value: object, reason_substring: str
) -> None:
    """build_entry raises CatalogError (CONTRACT_INVALID) on invalid scalars."""
    kwargs = dict(
        capability_id="cap.x",
        profile="algebra_exact",
        adapter_id=None,
        pack_manifest_digest=None,
        platforms=(),
        measured_resources=None,
        license_spdx="NOASSERTION",
        provenance=Provenance(source_url=None, source_sha256=None),
        admission_stage="not_admitted",
    )
    kwargs[field] = bad_value
    with pytest.raises(CatalogError) as exc_info:
        build_entry(**kwargs)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"
    assert reason_substring in str(exc_info.value)


def test_build_entry_rejects_bad_platform() -> None:
    """A platform with an unknown os is rejected."""
    with pytest.raises(CatalogError, match=r"platforms\[0\]\.os"):
        build_entry(
            capability_id="cap.x",
            profile="algebra_exact",
            adapter_id=None,
            pack_manifest_digest=None,
            platforms=(PlatformSpec(os="windows", arch="x86_64", abi=None),),
            measured_resources=None,
            license_spdx="NOASSERTION",
            provenance=Provenance(source_url=None, source_sha256=None),
            admission_stage="not_admitted",
        )


def test_build_entry_rejects_negative_measured_resources() -> None:
    """Negative measured resource fields are rejected."""
    with pytest.raises(CatalogError, match="expanded_bytes must be non-negative"):
        build_entry(
            capability_id="cap.x",
            profile="algebra_exact",
            adapter_id=None,
            pack_manifest_digest=None,
            platforms=(),
            measured_resources=MeasuredResources(expanded_bytes=-1, rss_bytes=10, wall_seconds=1.0),
            license_spdx="NOASSERTION",
            provenance=Provenance(source_url=None, source_sha256=None),
            admission_stage="not_admitted",
        )


@pytest.mark.parametrize("stage", [*ADMISSION_STAGES, NOT_ADMITTED_STAGE])
def test_build_entry_accepts_all_admission_stages(stage: str) -> None:
    """Every C23 admission stage plus not_admitted is a valid admission_stage."""
    entry = make_entry(admission_stage=stage)
    assert entry.admission_stage == stage


def test_entry_is_frozen() -> None:
    """A registry entry is immutable."""
    entry = make_entry()
    with pytest.raises((AttributeError, Exception)):
        entry.capability_id = "cap.other"  # type: ignore[misc]


def test_entry_to_dict_roundtrips_through_build_entry() -> None:
    """to_dict -> build_entry_from_raw reconstructs an equal entry."""
    original = make_admitted_entry()
    rebuilt = _build_entry_from_raw(original.to_dict())
    assert rebuilt == original


def test_packaged_seed_file_is_valid_json() -> None:
    """The packaged seed_entries.json is valid JSON with the right schema."""
    raw = resources.files("srl.catalog").joinpath("seed_entries.json").read_text("utf-8")
    doc = json.loads(raw)
    assert doc["schema_version"] == "CapabilityRegistrySeed/v1"
    assert isinstance(doc["entries"], list)
    assert len(doc["entries"]) == len(SCIENCE_LAB_PROFILES)


def test_registry_entry_equality_is_by_value() -> None:
    """Two structurally equal entries compare equal (frozen dataclass)."""
    a: CapabilityRegistryEntry = make_entry()
    b: CapabilityRegistryEntry = make_entry()
    assert a == b
    assert hash(a) == hash(b)
