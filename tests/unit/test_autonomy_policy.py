"""Unit tests for the autonomy policy loader (``srl.autonomy.policy``).

The policy loader is the gate between the on-disk ``automation/policy.json``
and the in-memory expectations the rest of the automation trusts. These tests
pin three things:

1. The committed ``automation/policy.json`` loads and validates (all 19 keys,
   correct types, correct enum values, ``AutonomyPolicy/v1``).
2. Each individual deviation the loader must catch is caught: a missing key,
   an extra key, a wrong type, a bad value, a wrong schema version.
3. Structural failures (missing file, bad JSON, non-object) raise
   :class:`PolicyError` with a usable reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from srl.autonomy.policy import POLICY_SCHEMA_VERSION, PolicyError, load_policy

# Path to the committed policy, resolved from the repo root (tests run with
# cwd = repo root under pytest).
_POLICY_PATH = Path("automation/policy.json")


def _load_canonical_policy_dict() -> dict[str, object]:
    """Read the committed policy and return it as a plain dict for mutation."""
    return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))


def test_committed_policy_loads_and_validates() -> None:
    """The committed ``automation/policy.json`` loads with no error."""
    policy = load_policy(_POLICY_PATH)
    assert isinstance(policy, dict)
    assert policy["schema_version"] == POLICY_SCHEMA_VERSION
    # All 19 keys present.
    assert len(policy) == 19


def test_committed_policy_is_canonical_json() -> None:
    """The committed policy is canonical: sorted keys, compact, ASCII, newline."""
    raw = _POLICY_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert raw == canonical + "\n"


def test_missing_key_is_rejected(tmp_path: Path) -> None:
    """A policy missing one required key raises PolicyError."""
    policy = _load_canonical_policy_dict()
    # Remove one key that is not the schema_version anchor.
    del policy["auto_commit"]
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "missing_key"


def test_extra_key_is_rejected(tmp_path: Path) -> None:
    """A policy with an unexpected key raises PolicyError."""
    policy = _load_canonical_policy_dict()
    policy["unexpected_extra_key"] = True
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "extra_key"


def test_wrong_type_is_rejected(tmp_path: Path) -> None:
    """A key with the wrong JSON type raises PolicyError."""
    policy = _load_canonical_policy_dict()
    # public_repo is bool; make it a string.
    policy["public_repo"] = "true"
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "wrong_type"
    assert exc_info.value.key == "public_repo"


def test_bad_value_is_rejected(tmp_path: Path) -> None:
    """A key with a disallowed enum value raises PolicyError."""
    policy = _load_canonical_policy_dict()
    # merge_method must be "squash"; set a different value.
    policy["merge_method"] = "merge"
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "bad_value"
    assert exc_info.value.key == "merge_method"


def test_int_value_out_of_allowed_set_is_rejected(tmp_path: Path) -> None:
    """An int key with a value outside its allowed set raises PolicyError."""
    policy = _load_canonical_policy_dict()
    # max_parallel_implementation_lanes must stay within the allowed set.
    policy["max_parallel_implementation_lanes"] = 9
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "bad_value"
    assert exc_info.value.key == "max_parallel_implementation_lanes"


def test_wrong_schema_version_is_rejected(tmp_path: Path) -> None:
    """A policy with an unknown schema version raises PolicyError."""
    policy = _load_canonical_policy_dict()
    policy["schema_version"] = "AutonomyPolicy/v0"
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert "AutonomyPolicy/v1" in str(exc_info.value)


def test_v1_policy_with_nonfour_lanes_is_rejected(tmp_path: Path) -> None:
    """AutonomyPolicy/v1 fixes lanes at exactly 4 (cross-field constraint)."""
    policy = _load_canonical_policy_dict()
    policy["schema_version"] = "AutonomyPolicy/v1"
    policy["max_parallel_implementation_lanes"] = 6
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "version_constraint"
    assert exc_info.value.key == "max_parallel_implementation_lanes"


def test_v1_policy_with_four_lanes_is_accepted(tmp_path: Path) -> None:
    """AutonomyPolicy/v1 with lanes=4 remains valid after the v2 bump."""
    policy = _load_canonical_policy_dict()
    policy["schema_version"] = "AutonomyPolicy/v1"
    policy["max_parallel_implementation_lanes"] = 4
    good = tmp_path / "policy.json"
    good.write_text(json.dumps(policy), encoding="utf-8")
    loaded = load_policy(good)
    assert loaded["schema_version"] == "AutonomyPolicy/v1"


def test_v2_policy_with_six_lanes_is_accepted(tmp_path: Path) -> None:
    """AutonomyPolicy/v2 with lanes=6 remains valid after the v3 bump."""
    policy = _load_canonical_policy_dict()
    policy["schema_version"] = "AutonomyPolicy/v2"
    policy["max_parallel_implementation_lanes"] = 6
    good = tmp_path / "policy.json"
    good.write_text(json.dumps(policy), encoding="utf-8")
    loaded = load_policy(good)
    assert loaded["schema_version"] == "AutonomyPolicy/v2"


def test_v3_policy_with_eight_lanes_is_accepted() -> None:
    """The committed AutonomyPolicy/v3 (lanes=8) validates."""
    policy = load_policy(_POLICY_PATH)
    assert policy["schema_version"] == "AutonomyPolicy/v3"
    assert policy["max_parallel_implementation_lanes"] == 8


def test_lanes_above_eight_are_rejected(tmp_path: Path) -> None:
    """A lanes value outside the allowed set raises PolicyError."""
    policy = _load_canonical_policy_dict()
    policy["max_parallel_implementation_lanes"] = 9
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "bad_value"


def test_bool_is_not_treated_as_int(tmp_path: Path) -> None:
    """A bool value where an int is expected is rejected (bool is not int here).

    Python's ``bool`` subclasses ``int``, so a naive isinstance check would
    accept ``True`` for an int field. The loader must distinguish them.
    """
    policy = _load_canonical_policy_dict()
    # max_scientific_execution_wip is int(1); replace with True (a bool).
    policy["max_scientific_execution_wip"] = True
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "wrong_type"
    assert exc_info.value.key == "max_scientific_execution_wip"


def test_missing_file_raises(tmp_path: Path) -> None:
    """A nonexistent policy path raises PolicyError."""
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(PolicyError) as exc_info:
        load_policy(missing)
    assert exc_info.value.reason == "missing_file"


def test_bad_json_raises(tmp_path: Path) -> None:
    """A policy file that is not valid JSON raises PolicyError."""
    bad = tmp_path / "policy.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "bad_json"


def test_non_object_json_raises(tmp_path: Path) -> None:
    """A policy file that is valid JSON but not an object raises PolicyError."""
    bad = tmp_path / "policy.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(bad)
    assert exc_info.value.reason == "not_object"
