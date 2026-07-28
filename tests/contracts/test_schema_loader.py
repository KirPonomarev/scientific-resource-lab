"""Unit tests for the schema loader/validator (srl.contracts.schema).

Pins:

1. Every shipped schema loads and meta-validates against the 2020-12
   meta-schema; ``meta_validate_all`` returns the name -> ``$id`` map.
2. ``validate`` accepts a valid envelope and rejects a ``grants_authority=true``
   envelope and an envelope with an unknown additional property.
3. An unknown schema name raises :class:`SchemaError`.
"""

from __future__ import annotations

import pytest

from srl.contracts.schema import (
    SCHEMA_FAIL_REASON,
    ContractValidationError,
    SchemaError,
    list_schemas,
    load_schema,
    meta_validate_all,
    schema_file_map,
    validate,
)

# A canonical 64-hex digest used across fixture envelopes.
_DIGEST = "sha256:" + "a" * 64


def _good_envelope() -> dict[str, object]:
    """Return a minimal valid ScientificObjectEnvelope/v1 instance."""
    return {
        "schema_version": "ScientificObjectEnvelope/v1",
        "object_id": _DIGEST,
        "object_type": "claim",
        "created_utc": "2026-07-28T01:02:03Z",
        "parents": [],
        "payload": {"note": "demo"},
        "canonical_writes": 0,
        "grants_authority": False,
    }


def test_list_schemas_returns_known_set() -> None:
    """list_schemas returns the three shipped schema names."""
    names = list_schemas()
    assert "ArtifactRef" in names
    assert "ScientificObjectEnvelope" in names
    assert "GateReceipt" in names


def test_schema_file_map_covers_known_names() -> None:
    """schema_file_map has an entry for every known schema name."""
    file_map = schema_file_map()
    assert set(file_map) == set(list_schemas())
    for filename in file_map.values():
        assert filename.endswith(".json")


def test_meta_validate_all_passes() -> None:
    """Every shipped schema meta-validates; the name->$id map is returned."""
    name_to_id = meta_validate_all()
    assert name_to_id["ArtifactRef"] == "https://schemas.srlab.dev/v1/ArtifactRef.json"
    assert name_to_id["ScientificObjectEnvelope"] == (
        "https://schemas.srlab.dev/v1/ScientificObjectEnvelope.json"
    )
    assert name_to_id["GateReceipt"] == "https://schemas.srlab.dev/v1/GateReceipt.json"


def test_meta_validate_all_ids_are_unique() -> None:
    """No two schemas share an $id (enforced by meta_validate_all)."""
    name_to_id = meta_validate_all()
    ids = list(name_to_id.values())
    assert len(ids) == len(set(ids))


def test_load_schema_returns_dict_with_dialect() -> None:
    """load_schema returns the parsed dict declaring the 2020-12 dialect."""
    schema = load_schema("ArtifactRef")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "ArtifactRef/v1"
    assert schema["additionalProperties"] is False


def test_load_schema_is_cached() -> None:
    """load_schema returns the same cached object for repeated calls."""
    a = load_schema("ArtifactRef")
    b = load_schema("ArtifactRef")
    assert a is b


def test_load_schema_rejects_unknown_name() -> None:
    """An unknown schema name raises SchemaError."""
    with pytest.raises(SchemaError) as exc_info:
        load_schema("DoesNotExist")
    assert "unknown schema name" in str(exc_info.value).lower()


def test_validate_accepts_valid_envelope() -> None:
    """validate accepts a well-formed envelope."""
    validate(_good_envelope(), "ScientificObjectEnvelope")  # should not raise


@pytest.mark.parametrize(
    "object_type",
    [
        "claim",
        "math_ir",
        "model_interface",
        "transformation_receipt",
        "run_receipt",
        "catalog_snapshot",
        "plan",
        "request",
    ],
)
def test_validate_accepts_each_object_type(object_type: str) -> None:
    """Every enumerated object_type is accepted by the envelope schema."""
    env = _good_envelope()
    env["object_type"] = object_type
    validate(env, "ScientificObjectEnvelope")


def test_validate_rejects_grants_authority_true() -> None:
    """grants_authority=true is rejected (safety const)."""
    env = _good_envelope()
    env["grants_authority"] = True
    with pytest.raises(ContractValidationError) as exc_info:
        validate(env, "ScientificObjectEnvelope")
    assert exc_info.value.fail_reason == SCHEMA_FAIL_REASON
    assert "grants_authority" in exc_info.value.json_path


def test_validate_rejects_nonzero_canonical_writes() -> None:
    """canonical_writes != 0 is rejected (safety const)."""
    env = _good_envelope()
    env["canonical_writes"] = 1
    with pytest.raises(ContractValidationError):
        validate(env, "ScientificObjectEnvelope")


def test_validate_rejects_unknown_additional_property() -> None:
    """An unknown additional property is rejected (additionalProperties=false)."""
    env = _good_envelope()
    env["unexpected_extra"] = "x"
    with pytest.raises(ContractValidationError) as exc_info:
        validate(env, "ScientificObjectEnvelope")
    assert exc_info.value.validator == "additionalProperties"


def test_validate_rejects_bad_object_type() -> None:
    """An object_type outside the enum is rejected."""
    env = _good_envelope()
    env["object_type"] = "not_a_real_type"
    with pytest.raises(ContractValidationError) as exc_info:
        validate(env, "ScientificObjectEnvelope")
    assert exc_info.value.validator == "enum"


def test_validate_rejects_bad_object_id_shape() -> None:
    """A malformed object_id is rejected by the pattern."""
    env = _good_envelope()
    env["object_id"] = "not-a-sha256"
    with pytest.raises(ContractValidationError):
        validate(env, "ScientificObjectEnvelope")


def test_validate_carries_json_path() -> None:
    """ContractValidationError carries the failing JSON path."""
    env = _good_envelope()
    env["created_utc"] = "not-a-timestamp"
    with pytest.raises(ContractValidationError) as exc_info:
        validate(env, "ScientificObjectEnvelope")
    assert "created_utc" in exc_info.value.json_path


def test_validate_artifact_ref_schema_accepts_valid() -> None:
    """The ArtifactRef schema accepts a valid reference."""
    ref = {
        "schema_version": "ArtifactRef/v1",
        "media_type": "application/json",
        "digest": _DIGEST,
        "size_bytes": 0,
    }
    validate(ref, "ArtifactRef")  # should not raise
