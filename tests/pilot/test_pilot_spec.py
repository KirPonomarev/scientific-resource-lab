"""Hermetic tests for PilotSpec/v1 loading, freezing, and honesty guards.

Pins the schema registration, the analog fixture, the const-false invariants,
the holdout guard, and the freeze / pilot_id content-addressing.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from srl.contracts.schema import (
    ContractValidationError,
    list_schemas,
    load_schema,
    schema_file_map,
)
from srl.pilot.spec import (
    CONST_FALSE_INVARIANT,
    HOLDOUT_INVARIANT,
    PILOT_FAIL_REASON,
    PILOT_SPEC_SCHEMA_VERSION,
    PilotSpecError,
    _validate_const_false,
    freeze_spec,
    load_pilot_spec,
    pilot_id,
    validate_holdout_free,
)

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO / "fixtures" / "conformance" / "pilot"
_POSITIVE = _FIXTURES / "p01-analog-retrospective.input.json"


def _synth(seed: str) -> str:
    """Return a synthetic sha256-shaped digest over a deterministic seed."""
    return "sha256:" + hashlib.sha256(("srl-pilot-synthetic-" + seed).encode()).hexdigest()


def _base_spec(**overrides: object) -> dict[str, object]:
    """Return a schema-valid PilotSpec body (no pilot_id) with overrides."""
    body: dict[str, object] = {
        "schema_version": PILOT_SPEC_SCHEMA_VERSION,
        "source_artifact_digests": [_synth("s1")],
        "retrospective_window": {
            "start_utc": "2026-01-01T00:00:00Z",
            "end_utc": "2026-06-30T00:00:00Z",
            "split_rule": "chronological_80_20",
        },
        "preprocessing_scope": "demean",
        "features": ["mean"],
        "metrics": [{"name": "effect_size", "tolerance_decimal": "0.01"}],
        "null_generators": [{"kind": "phase_randomized", "seed": 17}],
        "seed_policy": {"seed": 42, "threads": 2},
        "pack_digests": [_synth("p1")],
        "catalog_digest": _synth("c"),
        "policy_digest": _synth("po"),
        "output_schemas": ["EvidenceAssessment"],
        "status_promotion_allowed": False,
        "prospective_holdout_materialization_allowed": False,
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body.update(overrides)
    return body


def _valid_spec(**overrides: object) -> dict[str, object]:
    """Return a fully valid PilotSpec (with a correct pilot_id) + overrides."""
    body = _base_spec(**overrides)
    spec_no_id = {k: v for k, v in body.items() if k != "pilot_id"}
    body["pilot_id"] = pilot_id(spec_no_id)  # type: ignore[arg-type]
    return body


# ---------------------------------------------------------------------------
# Schema registration
# ---------------------------------------------------------------------------


def test_pilot_spec_registered_and_loads() -> None:
    """PilotSpec is in the loader registry and loads + meta-validates."""
    assert "PilotSpec" in list_schemas()
    schema = load_schema("PilotSpec")
    assert schema["title"] == PILOT_SPEC_SCHEMA_VERSION
    assert schema["$id"] == "https://schemas.srlab.dev/v1/PilotSpec.json"
    assert schema["additionalProperties"] is False


def test_no_orphan_schema_files() -> None:
    """Every on-disk schema file maps to a registry name (no orphans)."""
    schema_dir = _REPO / "src" / "srl" / "contracts" / "schemas" / "v1"
    disk = {p.name for p in schema_dir.glob("*.json")}
    known = set(schema_file_map().values())
    assert disk == known, f"orphan/missing: {disk.symmetric_difference(known)}"


def test_pilot_spec_carries_safety_consts() -> None:
    """PilotSpec pins all four safety consts as const."""
    schema = load_schema("PilotSpec")
    props = schema["properties"]
    for field, expected in [
        ("canonical_writes", 0),
        ("grants_authority", False),
        ("status_promotion_allowed", False),
        ("prospective_holdout_materialization_allowed", False),
    ]:
        assert props[field]["const"] == expected, f"{field} not pinned to {expected}"


# ---------------------------------------------------------------------------
# Analog fixture
# ---------------------------------------------------------------------------


def test_analog_fixture_loads_and_freezes() -> None:
    """The positive fixture validates, freezes deterministically, and its
    stored pilot_id recomputes from the body."""
    spec = load_pilot_spec(_POSITIVE)
    frozen_a = freeze_spec(spec)
    frozen_b = freeze_spec(spec)
    assert frozen_a == frozen_b, "freeze_spec is not deterministic"
    recomputed = pilot_id(spec)
    assert recomputed == spec["pilot_id"], "stored pilot_id does not recompute"


def test_analog_fixture_uses_only_synthetic_digests() -> None:
    """Every digest in the analog fixture is sha256-shaped (no paths)."""
    spec = json.loads(_POSITIVE.read_text(encoding="utf-8"))
    assert spec["catalog_digest"] == _synth("catalog-v0.2.0")
    for d in spec["source_artifact_digests"]:
        assert d.startswith("sha256:") and len(d) == 71
    # No digest may carry a path separator.
    for d in spec["pack_digests"]:
        assert "/" not in d and "\\" not in d


# ---------------------------------------------------------------------------
# Const-false invariants
# ---------------------------------------------------------------------------


def test_status_promotion_true_rejected_schema_and_python() -> None:
    """status_promotion_allowed=true is rejected at schema + python layers."""
    spec = _valid_spec(status_promotion_allowed=True)
    # Schema layer: const:false fires.
    with pytest.raises(ContractValidationError):
        load_pilot_spec(json.dumps(spec))
    # Python const layer (bypassing schema): invariant pilot_safety_const.
    with pytest.raises(PilotSpecError) as exc_info:
        _validate_const_false(spec)  # type: ignore[arg-type]
    assert exc_info.value.invariant == CONST_FALSE_INVARIANT
    assert exc_info.value.fail_reason == PILOT_FAIL_REASON


def test_prospective_holdout_true_rejected_schema() -> None:
    """prospective_holdout_materialization_allowed=true is rejected (const:false)."""
    spec = _valid_spec(prospective_holdout_materialization_allowed=True)
    with pytest.raises(ContractValidationError):
        load_pilot_spec(json.dumps(spec))


def test_grants_authority_true_rejected() -> None:
    """grants_authority=true is rejected (const:false)."""
    spec = _valid_spec(grants_authority=True)
    with pytest.raises(ContractValidationError):
        load_pilot_spec(json.dumps(spec))


# ---------------------------------------------------------------------------
# Holdout guard
# ---------------------------------------------------------------------------


def test_holdout_field_marker_rejected() -> None:
    """An affirmative holdout field name is rejected by the holdout guard."""
    spec = _valid_spec()
    spec["holdout_materialized"] = True  # type: ignore[call-overload]
    with pytest.raises(PilotSpecError) as exc_info:
        validate_holdout_free(spec)  # type: ignore[arg-type]
    assert exc_info.value.invariant == HOLDOUT_INVARIANT


def test_holdout_value_marker_rejected() -> None:
    """A holdout materialization value string is rejected by the guard."""
    spec = _valid_spec(preprocessing_scope="materialize a prospective holdout")
    with pytest.raises(PilotSpecError) as exc_info:
        validate_holdout_free(spec)  # type: ignore[arg-type]
    assert exc_info.value.invariant == HOLDOUT_INVARIANT


def test_legitimate_holdout_const_not_flagged() -> None:
    """The legitimate prospective_holdout_materialization_allowed const is NOT
    a holdout marker (regression guard against false positives)."""
    spec = _valid_spec()
    validate_holdout_free(spec)  # type: ignore[arg-type]  # must not raise


def test_negative_fixtures_reject_as_expected() -> None:
    """Both negative conformance vectors reject with the expected error."""
    neg = _FIXTURES / "negative"
    for name in (
        "n01-status-promotion-allowed-true",
        "n02-holdout-materialization-marker",
    ):
        input_path = neg / f"{name}.input.json"
        expected_path = neg / f"{name}.expected_error.json"
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        with pytest.raises((PilotSpecError, ContractValidationError)) as exc_info:
            load_pilot_spec(input_path)
        assert exc_info.value.fail_reason == expected["fail_reason"]


# ---------------------------------------------------------------------------
# Freeze / pilot_id
# ---------------------------------------------------------------------------


def test_freeze_spec_stable_across_reorder() -> None:
    """freeze_spec produces identical bytes regardless of dict insertion order."""
    spec = _valid_spec()
    reordered = dict(reversed(list(spec.items())))
    assert freeze_spec(spec) == freeze_spec(reordered)  # type: ignore[arg-type]


def test_pilot_id_excludes_itself() -> None:
    """pilot_id is computed over the body WITHOUT pilot_id (self-hash-free)."""
    spec = _valid_spec()
    body_no_id = {k: v for k, v in spec.items() if k != "pilot_id"}
    expected = pilot_id(body_no_id)  # type: ignore[arg-type]
    assert pilot_id(spec) == expected  # type: ignore[arg-type]
    other = _valid_spec(features=["different"])
    assert pilot_id(other) != pilot_id(spec)  # type: ignore[arg-type]


def test_load_pilot_spec_accepts_path_string_handle() -> None:
    """load_pilot_spec accepts a Path, a JSON string, and a text handle."""
    text = _POSITIVE.read_text(encoding="utf-8")
    expected_id = json.loads(text)["pilot_id"]
    assert load_pilot_spec(_POSITIVE)["pilot_id"] == expected_id
    assert load_pilot_spec(text)["pilot_id"] == expected_id
    with _POSITIVE.open(encoding="utf-8") as fh:
        assert load_pilot_spec(fh)["pilot_id"] == expected_id


def test_load_pilot_spec_rejects_non_object() -> None:
    """A non-object JSON value is rejected."""
    with pytest.raises(PilotSpecError):
        load_pilot_spec("[1, 2, 3]")


def test_load_pilot_spec_rejects_malformed_json() -> None:
    """Malformed JSON is rejected."""
    with pytest.raises(PilotSpecError):
        load_pilot_spec("{not json")


# ---------------------------------------------------------------------------
# No private path in pilot artifacts
# ---------------------------------------------------------------------------


_LOCAL_PATH_RE = re.compile(
    r"(?:/Users/[A-Za-z0-9][A-Za-z0-9._-]*|/home/[A-Za-z0-9][A-Za-z0-9._-]*"
    r"|/Volumes/[A-Za-z0-9][A-Za-z0-9._-]*)"
)


def test_no_private_path_in_fixtures_or_schema() -> None:
    """No /Users/ /home/ /Volumes/ marker appears in any pilot artifact."""
    files = [p for p in _FIXTURES.rglob("*") if p.is_file()]
    files.append(_REPO / "src" / "srl" / "contracts" / "schemas" / "v1" / "pilot-spec.json")
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not _LOCAL_PATH_RE.search(text), f"private path in {path}"
