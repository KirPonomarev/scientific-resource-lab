"""Hermetic tests for the LabExportPacket/v1 schema and conformance fixtures.

Pins:

1. The ``lab-export-packet.json`` schema is registered, meta-validates, and has
   the canonical ``$id`` and the four safety-const constraints.
2. The canonical valid fixture (``packets.valid.v1.json``) round-trips through
   ``build_packet`` for every case, yielding schema-valid packets under the cap.
3. The adversarial fixture (``adversarial.inputs.v1.json``) reconstructs every
   forbidden string at runtime from safe placeholders and each case is rejected
   typed.
4. The schema rejects a packet tampered on any safety const.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.bridge import LAB_EXPORT_PACKET_SCHEMA_VERSION, PACKET_MAX_BYTES
from srl.bridge.exporter import (
    DisclosurePolicy,
    ExportObject,
    build_packet,
)
from srl.bridge.sanitizer import SanitizerRefusalError
from srl.contracts import dumps
from srl.contracts.errors import ContractError
from srl.contracts.schema import (
    SchemaError,
    list_schemas,
    load_schema,
    schema_file_map,
)
from srl.contracts.schema import (
    validate as schema_validate,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VALID_FIXTURE = _REPO_ROOT / "fixtures" / "conformance" / "bridge" / "packets.valid.v1.json"
_ADVERSARIAL_FIXTURE = (
    _REPO_ROOT / "fixtures" / "conformance" / "bridge" / "adversarial.inputs.v1.json"
)
_SCHEMA_FILE = (
    _REPO_ROOT / "src" / "srl" / "contracts" / "schemas" / "v1" / "lab-export-packet.json"
)

# A synthetic valid object digest reused in tamper tests.
_VALID_DIGEST = "sha256:" + "a" * 64


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Schema registration + meta-validation.
# ---------------------------------------------------------------------------


def test_schema_registered_in_loader() -> None:
    """LabExportPacket is a known schema name with the canonical file."""
    assert "LabExportPacket" in list_schemas()
    assert schema_file_map()["LabExportPacket"] == "lab-export-packet.json"


def test_schema_loads_and_meta_validates() -> None:
    """The schema loads (which meta-validates) and carries the right $id."""
    schema = load_schema("LabExportPacket")
    assert schema["$id"] == "https://schemas.srlab.dev/v1/LabExportPacket.json"
    assert schema["title"] == LAB_EXPORT_PACKET_SCHEMA_VERSION
    assert schema["additionalProperties"] is False


def test_schema_file_exists_on_disk() -> None:
    """The schema source file exists (no drift between tree and loader)."""
    assert _SCHEMA_FILE.is_file()


def test_schema_pins_safety_consts() -> None:
    """The schema const-pins the four safety fields."""
    schema = load_schema("LabExportPacket")
    props = schema["properties"]
    assert props["review_only"]["const"] is True
    assert props["canonical_effect"]["const"] == "none"
    assert props["grants_authority"]["const"] is False
    assert props["canonical_writes"]["const"] == 0


def test_schema_requires_all_fields() -> None:
    """The required list covers every top-level field."""
    schema = load_schema("LabExportPacket")
    required = set(schema["required"])
    expected = {
        "schema_version",
        "packet_id",
        "created_utc",
        "source_snapshot_digest",
        "objects",
        "disclosure_policy",
        "review_only",
        "canonical_effect",
        "grants_authority",
        "canonical_writes",
    }
    assert required == expected


# ---------------------------------------------------------------------------
# Valid fixture round-trip.
# ---------------------------------------------------------------------------


def _objects_from_case(case: dict[str, Any]) -> list[ExportObject]:
    return [
        ExportObject(
            object_digest=o["object_digest"],
            object_type=o["object_type"],
            sanitized_summary=o["sanitized_summary"],
            provenance_refs=tuple(o.get("provenance_refs", [])),
        )
        for o in case["objects"]
    ]


def _policy_from_case(case: dict[str, Any]) -> DisclosurePolicy:
    p = case["policy"]
    return DisclosurePolicy(
        private_identities=p["private_identities"],
        summary_max_bytes=p["summary_max_bytes"],
    )


def test_valid_fixture_round_trips() -> None:
    """Every valid fixture case builds, validates, and is under 1 MiB."""
    doc = _load(_VALID_FIXTURE)
    cases = doc["cases"]
    assert len(cases) >= 2
    for case in cases:
        objects = _objects_from_case(case)
        policy = _policy_from_case(case)
        packet = build_packet(
            objects,
            policy,
            created_utc=case.get("created_utc", "2026-07-28T00:00:00Z"),
            source_snapshot_digest=case.get("source_snapshot_digest"),
        )
        schema_validate(packet, "LabExportPacket")
        assert len(dumps(packet)) <= PACKET_MAX_BYTES
        assert packet["review_only"] is True


def test_valid_fixture_has_two_cases() -> None:
    """The valid fixture carries exactly the two documented build cases."""
    doc = _load(_VALID_FIXTURE)
    ids = [c["case_id"] for c in doc["cases"]]
    assert ids == ["valid-single-claim", "valid-mixed-types"]


# ---------------------------------------------------------------------------
# Adversarial fixture round-trip.
# ---------------------------------------------------------------------------


# Credential-shaped opaque labels the fixture templates use. The literal
# expansion lives here (split across concatenation so no contiguous forbidden
# literal appears in this tracked .py file under the public-boundary scanner).
_CRED_TOKEN_MAP = {
    "{GH}": "gh" + "p",
    "{SK}": "s" + "k",
    "{AK}": "AK" + "IA",
    "{PEM}": "BEGI" + "N RSA PRIVATE K" + "EY",
}


def _substitute(template: str, placeholder_map: dict[str, str]) -> str:
    merged = {**placeholder_map, **_CRED_TOKEN_MAP}
    out = template
    for token, literal in merged.items():
        out = out.replace(token, literal)
    return out


def _build_adversarial(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """Build a packet for one adversarial case (must raise)."""
    fc = case["forbidden_class"]
    if fc == "unknown_object_type":
        ExportObject(
            object_digest=_VALID_DIGEST,
            object_type=case.get("object_type", "bogus"),
            sanitized_summary="valid summary",
        )
        return
    if fc == "unknown_schema_version":
        summary = _substitute(case.get("prefix", ""), placeholder_map)
        packet = build_packet(
            [ExportObject(_VALID_DIGEST, "claim", summary)],
            DisclosurePolicy(private_identities="digest_replaced"),
        )
        packet["schema_version"] = "LabExportPacket/vBogus"
        schema_validate(packet, "LabExportPacket")
        return
    if fc == "self_referential_hash":
        summary = _substitute(case.get("prefix", ""), placeholder_map)
        packet = build_packet(
            [ExportObject(_VALID_DIGEST, "claim", summary)],
            DisclosurePolicy(private_identities="digest_replaced"),
        )
        # A structurally-invalid object_digest must fail schema validation.
        bad = {
            **packet,
            "objects": [{**packet["objects"][0], "object_digest": "not-a-sha256"}],
        }
        schema_validate(bad, "LabExportPacket")
        return
    prefix = _substitute(case.get("prefix", ""), placeholder_map)
    token = _substitute(case.get("token_template", ""), placeholder_map)
    summary = (prefix + " " + token).strip() if token else prefix
    build_packet(
        [ExportObject(_VALID_DIGEST, "claim", summary)],
        DisclosurePolicy(private_identities="digest_replaced"),
    )


def test_adversarial_fixture_every_case_rejected() -> None:
    """Every adversarial case is rejected with its expected fail_reason."""
    doc = _load(_ADVERSARIAL_FIXTURE)
    placeholder_map = doc["placeholder_map"]
    cases = doc["cases"]
    assert len(cases) >= 15  # every forbidden class + structural failures
    for case in cases:
        expected = case["expected_fail_reason"]
        with pytest.raises((SanitizerRefusalError, ContractError, SchemaError)) as exc_info:
            _build_adversarial(case, placeholder_map)
        assert exc_info.value.fail_reason == expected, (
            f"{case['case_id']}: expected {expected}, got {exc_info.value.fail_reason}"
        )


def test_adversarial_fixture_covers_every_forbidden_class() -> None:
    """The adversarial fixture exercises every detector class."""
    doc = _load(_ADVERSARIAL_FIXTURE)
    classes = {c["forbidden_class"] for c in doc["cases"]}
    expected_classes = {
        "local_path",
        "unix_path",
        "windows_path",
        "argv_flag",
        "shell_command",
        "env_assignment",
        "env_reference",
        "credential_pattern",
        "raw_dataset_marker",
        "t7_uuidv7",
        "vps_topology_marker",
        "private_key_marker",
        "promotion_flag",
        "unknown_object_type",
        "unknown_schema_version",
        "self_referential_hash",
    }
    assert expected_classes <= classes


def test_adversarial_fixture_is_scanner_clean() -> None:
    """The adversarial fixture file contains no literal forbidden markers.

    This is the key property: the fixture carries only safe placeholder tokens,
    so it never trips the public-boundary scanner EVEN WHEN TRACKED. The literal
    forbidden strings exist only at runtime, after substitution. This test
    checks the ACTUAL scanner regex shapes (not naive substrings), matching what
    ``scripts/checks/public_boundary.py`` would flag.
    """
    import re  # local: only this assertion needs it  # noqa: PLC0415

    text = _ADVERSARIAL_FIXTURE.read_text(encoding="utf-8")
    # The exact scanner regex shapes for credentials + private-key headers.
    scanner_regexes = {
        "ghp": re.compile(r"ghp_[A-Za-z0-9]{16,}"),
        "gho": re.compile(r"gho_[A-Za-z0-9]{16,}"),
        "github_pat": re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
        "sk": re.compile(r"sk-[A-Za-z0-9]{16,}"),
        "AKIA": re.compile(r"AKIA[0-9A-Z]{16}"),
        "pem": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    }
    for name, pattern in scanner_regexes.items():
        assert pattern.search(text) is None, f"scanner shape {name!r} present in fixture"
    # No literal slash-prefixed local paths.
    for marker in ("/Users/", "/home/", "/Volumes/"):
        assert marker not in text
    # No literal private keys (the sensitive JSON-key shapes).
    for marker in ("organism_pulse", "unified_snapshot", "operator_context"):
        assert marker not in text
    # No literal UUIDv7 shapes (8-4-4-4-12 hex with version 7).
    uuidv7 = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    )
    assert uuidv7.search(text) is None
    # Every credential/path marker IS reconstructable from a placeholder label.
    for token in ("{S}", "{H}", "{U}", "{E}", "{B}", "{GH}", "{SK}", "{AK}", "{PEM}"):
        assert token in text
    # The fixture's placeholder_map must NOT carry the credential literal
    # expansions (those live in the gate/test Python source, split).
    doc = json.loads(text)
    for key in ("{GH}", "{SK}", "{AK}", "{PEM}"):
        assert key not in doc["placeholder_map"]
