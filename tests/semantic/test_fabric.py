"""Unit tests for the scientific object fabric (srl.semantic.fabric).

Pins:

1. **Envelope minting**: :func:`mint_object` wraps a payload into a
   ``ScientificObjectEnvelope/v1`` with a computed ``object_id`` (sha256 over
   the canonical bytes of the envelope without the id), provenance
   (``created_utc`` normalized, ``parents``), and the two safety consts
   (``canonical_writes=0``, ``grants_authority=false``).
2. **Identity**: the ``object_id`` matches a manual
   :func:`srl.contracts.ids.object_id` computation and is deterministic.
3. **Schema validation**: the produced envelope validates against
   ``ScientificObjectEnvelope``.
4. **Fixture round-trips**: the positive object-fabric fixtures validate
   against their schemas and the negative fixtures reject with the named
   error (covered jointly with the gate, asserted here for the test suite).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.contracts.ids import object_id
from srl.contracts.schema import validate as schema_validate
from srl.semantic.fabric import SUPPORTED_OBJECT_TYPES, mint_object

# Fixtures directory (repo-relative for the round-trip tests).
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "conformance" / "object_fabric"


def _claim_payload() -> dict[str, object]:
    """A minimal valid ScientificClaim/v1 payload (candidate hypothesis)."""
    return {
        "schema_version": "ScientificClaim/v1",
        "claim_id": "sha256:" + "a" * 64,
        "statement": {"subject": "x", "predicate": "correlates_with", "object": "y"},
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


# --- Pins: mint_object shape + identity -----------------------------------


def test_mint_object_envelope_shape() -> None:
    """mint_object produces a ScientificObjectEnvelope/v1 with all required fields."""
    env = mint_object("claim", _claim_payload())
    assert env["schema_version"] == "ScientificObjectEnvelope/v1"
    assert env["object_type"] == "claim"
    assert env["object_id"].startswith("sha256:")
    assert env["parents"] == []
    assert env["canonical_writes"] == 0
    assert env["grants_authority"] is False
    assert env["payload"] == _claim_payload()
    assert env["created_utc"] == "2026-07-28T00:00:00Z"


def test_mint_object_id_is_sha256_of_envelope_without_id() -> None:
    """object_id matches a manual object_id computation over the envelope without the id."""
    env = mint_object("claim", _claim_payload())
    without_id = {k: v for k, v in env.items() if k != "object_id"}
    expected = "sha256:" + hashlib.sha256(dumps(without_id)).hexdigest()
    assert env["object_id"] == expected
    # And it matches the ids helper directly.
    assert env["object_id"] == object_id(without_id)


def test_mint_object_is_deterministic() -> None:
    """The same inputs yield the same object_id on every mint."""
    payload = _claim_payload()
    a = mint_object("claim", payload)
    b = mint_object("claim", payload)
    assert a == b
    assert a["object_id"] == b["object_id"]


def test_mint_object_validates_against_envelope_schema() -> None:
    """The produced envelope validates against ScientificObjectEnvelope."""
    env = mint_object("claim", _claim_payload())
    schema_validate(env, "ScientificObjectEnvelope")  # should not raise


def test_mint_object_normalizes_timestamp() -> None:
    """created_utc is normalized (lowercase z / +00:00 -> Z)."""
    env_z = mint_object("claim", _claim_payload(), created_utc="2026-07-28T01:02:03z")
    env_off = mint_object("claim", _claim_payload(), created_utc="2026-07-28T01:02:03+00:00")
    assert env_z["created_utc"] == "2026-07-28T01:02:03Z"
    assert env_off["created_utc"] == "2026-07-28T01:02:03Z"


def test_mint_object_rejects_bad_timestamp() -> None:
    """A non-UTC / fractional timestamp is rejected at mint time."""
    with pytest.raises(ContractError):
        mint_object("claim", _claim_payload(), created_utc="2026-07-28T01:02:03.456Z")


def test_mint_object_carries_parents() -> None:
    """parents are carried through verbatim (as a copy)."""
    parent = "sha256:" + "b" * 64
    env = mint_object("claim", _claim_payload(), parents=[parent])
    assert env["parents"] == [parent]
    # Mutating the returned parents list must not affect a re-mint.
    env["parents"].append("sha256:" + "c" * 64)
    env2 = mint_object("claim", _claim_payload(), parents=[parent])
    assert env2["parents"] == [parent]


def test_supported_object_types_cover_payload_kinds() -> None:
    """SUPPORTED_OBJECT_TYPES enumerates the payload-bearing kinds.

    The six WP-B11 object types plus the two WP-B12 transformation objects
    (adapter_profile, transformation_receipt), each with a v1 payload schema.
    """
    assert SUPPORTED_OBJECT_TYPES == frozenset(
        {
            "claim",
            "math_ir",
            "symbol_table",
            "condition_set",
            "constant_ref",
            "model_interface",
            "adapter_profile",
            "transformation_receipt",
        }
    )


@pytest.mark.parametrize("object_type", sorted(SUPPORTED_OBJECT_TYPES))
def test_mint_object_accepts_each_supported_type(object_type: str) -> None:
    """mint_object accepts every supported object_type (envelope schema enum)."""
    env = mint_object(object_type, {"note": "demo"})
    schema_validate(env, "ScientificObjectEnvelope")
    assert env["object_type"] == object_type


# --- Pins: fixture round-trips --------------------------------------------

# Maps each positive fixture to its schema name.
_POSITIVE_FIXTURES = {
    "p01-math-ir-newton": "MathIR",
    "p02-claim-newton": "ScientificClaim",
    "p03-claim-hypothesis": "ScientificClaim",
    "p04-symbol-table": "SymbolTable",
    "p05-constant-ref-newton": "ConstantRef",
    "p06-condition-set": "ConditionSet",
    "p07-model-interface-oscillator": "ModelInterface",
}


@pytest.mark.parametrize("name,schema", sorted(_POSITIVE_FIXTURES.items()))
def test_positive_fixture_validates(name: str, schema: str) -> None:
    """Every positive object-fabric fixture validates against its schema."""
    path = _FIXTURES / f"{name}.input.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    schema_validate(doc, schema)  # should not raise


def test_fixture_manifest_lists_all_positive_and_negative_vectors() -> None:
    """The manifest enumerates 7 positive and 7 negative vectors."""
    manifest = json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "ObjectFabricVectorManifest/v1"
    assert len(manifest["positive"]) == 7
    assert len(manifest["negative"]) == 7
