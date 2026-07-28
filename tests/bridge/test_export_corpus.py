"""Hermetic tests for the WP-I81 export-adversarial corpus.

Drives the twelve-case valid corpus and the forty-plus-case adversarial corpus
under ``fixtures/conformance/bridge/corpus/`` through the REAL, merged exporter
(:func:`srl.bridge.exporter.build_packet`) and the refuse-not-strip sanitizer.
These tests are the pytest mirror of ``scripts/checks/wp81-corpus.py``: they
assert the same load-bearing properties (valid cases build; adversarial cases
are rejected typed; counts meet the plan floors; the corpus files exist and are
well-formed), but per-case, so a regression names the exact failing case.

The corpus VALIDATES AGAINST THE MERGED EXPORTER — it does not weaken it. The
tests do not import the gate script; they re-implement the minimal corpus
driver inline so a change to the gate cannot silently weaken what the test
suite checks.

Pins:

1. The corpus fixtures exist, parse as JSON, and carry the documented
   ``schema_version`` (``BridgeCorpusDoc/v1``).
2. Every valid case builds, schema-validates, and is under the 1 MiB cap; both
   disclosure policies (``digest_replaced`` and ``omitted``) are represented.
3. Every adversarial case is rejected with its expected typed ``fail_reason``
   (no wrong-reason passes). Forbidden classes, oversize packets, and smuggling
   hits use ``BRIDGE_CONTRACT_MISMATCH``; structural/schema/object-construction
   failures use ``CONTRACT_INVALID``.
4. The corpus meets the plan's floors: at least 12 valid and 40 adversarial
   cases.
5. The adversarial corpus covers every required forbidden class.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.bridge import (
    BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
    PACKET_MAX_BYTES,
)
from srl.bridge.exporter import (
    DisclosurePolicy,
    ExportObject,
    build_packet,
)
from srl.bridge.sanitizer import scan_payload
from srl.contracts import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate as schema_validate

# The corpus root, resolved relative to this test file (repo-root independent).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_DIR = _REPO_ROOT / "fixtures" / "conformance" / "bridge" / "corpus"
_VALID_FIXTURE = _CORPUS_DIR / "valid.v1.json"
_ADVERSARIAL_FIXTURE = _CORPUS_DIR / "adversarial.v1.json"

# The plan's minimum corpus floors.
_MIN_VALID_CASES = 12
_MIN_ADVERSARIAL_CASES = 40

# A synthetic valid digest reused across the adversarial build helpers.
_VALID_DIGEST = "sha256:" + "a" * 64
_VALID_PROV = "sha256:" + "c" * 64

# Credential label expansions, SPLIT so no contiguous forbidden literal appears
# in this tracked test file (the public-boundary scanner would otherwise flag
# it). Each reconstructs the credential prefix a sanitizer must refuse.
_CRED_TOKEN_MAP = {
    "{GH}": "gh" + "p",
    "{SK}": "s" + "k",
    "{AK}": "AK" + "IA",
    "{PEM}": "BEGI" + "N RSA PRIVATE K" + "EY",
}


def _load_corpus(path: Path) -> dict[str, object]:
    """Load and JSON-decode a corpus fixture."""
    return json.loads(path.read_text(encoding="utf-8"))


def _substitute(template: str, placeholder_map: dict[str, str]) -> str:
    """Reconstruct the literal forbidden string from placeholder pieces."""
    merged = {**placeholder_map, **_CRED_TOKEN_MAP}
    out = template
    for token, literal in merged.items():
        out = out.replace(token, literal)
    return out


def _objects_from_case(case: dict[str, object]) -> list[ExportObject]:
    """Rebuild ExportObject instances from a valid fixture case."""
    out: list[ExportObject] = []
    for obj in case["objects"]:  # type: ignore[index]
        out.append(
            ExportObject(
                object_digest=obj["object_digest"],  # type: ignore[index]
                object_type=obj["object_type"],  # type: ignore[index]
                sanitized_summary=obj["sanitized_summary"],  # type: ignore[index]
                provenance_refs=tuple(obj.get("provenance_refs", [])),  # type: ignore[union-attr]
            )
        )
    return out


def _policy_from_case(case: dict[str, object]) -> DisclosurePolicy:
    """Rebuild a DisclosurePolicy from a valid fixture case."""
    policy = case["policy"]  # type: ignore[index]
    return DisclosurePolicy(
        private_identities=policy["private_identities"],  # type: ignore[index]
        summary_max_bytes=policy["summary_max_bytes"],  # type: ignore[index]
    )


def _claim(summary: object) -> ExportObject:
    """Build a single claim-typed ExportObject with the given summary."""
    return ExportObject(  # type: ignore[arg-type]
        object_digest=_VALID_DIGEST,
        object_type="claim",
        sanitized_summary=summary,
    )


def _policy() -> DisclosurePolicy:
    """The default disclosure policy used by the corpus driver."""
    return DisclosurePolicy(private_identities="digest_replaced")


def _summary(case: dict[str, object], placeholder_map: dict[str, str]) -> str:
    """Reconstruct the literal forbidden summary from a case's prefix+token."""
    prefix = _substitute(case.get("prefix", ""), placeholder_map)  # type: ignore[arg-type]
    token = _substitute(case.get("token_template", ""), placeholder_map)  # type: ignore[arg-type]
    return (prefix + " " + token).strip() if token else prefix


def _build_unknown_object_type(case: dict[str, object], _pm: dict[str, str]) -> None:
    """ExportObject construction rejects a bad object_type (CONTRACT_INVALID)."""
    ExportObject(
        object_digest=_VALID_DIGEST,
        object_type=case.get("object_type", "bogus"),  # type: ignore[arg-type]
        sanitized_summary="valid summary",
    )


def _build_unknown_schema_version(case: dict[str, object], placeholder_map: dict[str, str]) -> None:
    """Build a valid packet then tamper schema_version and re-validate."""
    packet = build_packet([_claim(_summary(case, placeholder_map))], _policy())
    packet["schema_version"] = "LabExportPacket/vBogus"
    schema_validate(packet, "LabExportPacket")


def _build_unknown_license(case: dict[str, object], placeholder_map: dict[str, str]) -> None:
    """additionalProperties: false — a smuggled 'license' field is rejected."""
    packet = build_packet([_claim(_summary(case, placeholder_map))], _policy())
    schema_validate({**packet, "license": "unknown_license_v9"}, "LabExportPacket")


def _build_hash_guard(case: dict[str, object], placeholder_map: dict[str, str]) -> None:
    """Self-referential / stale hash guard: a non-sha256 digest is rejected."""
    packet = build_packet([_claim(_summary(case, placeholder_map))], _policy())
    packet_id = packet["packet_id"]
    for obj in packet["objects"]:
        if obj["object_digest"] == packet_id:
            msg = f"{case['class']}: object_digest equals packet_id (guard failed)"
            raise ContractError(msg)
    bad = {
        **packet,
        "objects": [{**packet["objects"][0], "object_digest": "not-a-sha256-digest"}],
    }
    schema_validate(bad, "LabExportPacket")


def _build_wrong_type(case: dict[str, object], _pm: dict[str, str]) -> None:
    """A wrong-typed field is rejected (CONTRACT_INVALID)."""
    kind = case.get("wrong_value_kind", "")
    if kind == "numeric_summary":
        from srl.bridge.sanitizer import normalize_summary  # noqa: PLC0415

        normalize_summary(123, max_bytes=1024)  # type: ignore[arg-type]
        return
    if kind == "integer_digest":
        ExportObject(12345, "claim", "A claim.")  # type: ignore[arg-type]
        return
    msg = f"wrong_type: unknown wrong_value_kind {kind!r}"
    raise ContractError(msg)


def _build_grants_authority_tamper(
    case: dict[str, object], placeholder_map: dict[str, str]
) -> None:
    """A safety const is pinned by the schema; tampering fails validation."""
    packet = build_packet([_claim(_summary(case, placeholder_map))], _policy())
    schema_validate(  # type: ignore[index]
        {**packet, case["tamper_field"]: case["tamper_value"]}, "LabExportPacket"
    )


def _build_oversize_packet() -> None:
    """Build enough safe objects to exceed the 1 MiB cap; no truncation."""
    summary = "convergence result " * 100
    big = [ExportObject(_VALID_DIGEST, "claim", summary) for _ in range(700)]
    policy = DisclosurePolicy(private_identities="digest_replaced", summary_max_bytes=2000)
    build_packet(big, policy)


def _build_nested_smuggling(case: dict[str, object], placeholder_map: dict[str, str]) -> None:
    """A forbidden value hidden in a NESTED non-exempt field; scan_payload refuses."""
    smuggled = _summary(case, placeholder_map)
    field_name = case.get("smuggle_field", "notes")  # type: ignore[union-attr]
    scan_payload(
        {
            "objects": [
                {
                    "object_digest": _VALID_DIGEST,
                    "object_type": "claim",
                    "sanitized_summary": "a clean summary",
                    "provenance_refs": [_VALID_PROV],
                    field_name: smuggled,
                }
            ]
        }
    )


def _build_unicode_evasion(case: dict[str, object], placeholder_map: dict[str, str]) -> None:
    """A unicode-evasion ATTEMPT with a co-occurring ASCII forbidden substring."""
    summary = _substitute(  # type: ignore[arg-type]
        case.get("prefix", "") + " " + case.get("token_template", ""),  # type: ignore[operator]
        placeholder_map,
    ).strip()
    build_packet([_claim(summary)], _policy())


# Dispatch table: case["class"] -> handler. Each handler MUST raise.
_DISPATCH: dict[str, Any] = {
    "unknown_object_type": _build_unknown_object_type,
    "unknown_schema_version": _build_unknown_schema_version,
    "unknown_license": _build_unknown_license,
    "self_referential_hash": _build_hash_guard,
    "stale_hash": _build_hash_guard,
    "wrong_type": _build_wrong_type,
    "grants_authority_tamper": _build_grants_authority_tamper,
    "oversize_packet": lambda _c, _pm: _build_oversize_packet(),
    "nested_smuggling": _build_nested_smuggling,
    "unicode_evasion": _build_unicode_evasion,
}


def _build_for_case(case: dict[str, object], placeholder_map: dict[str, str]) -> None:
    """Drive a single adversarial case through the real exporter. Must raise."""
    handler = _DISPATCH.get(case["class"])  # type: ignore[index]
    if handler is not None:
        handler(case, placeholder_map)  # type: ignore[operator]
        return
    # default: a forbidden-class summary.
    build_packet([_claim(_summary(case, placeholder_map))], _policy())


# ---------------------------------------------------------------------------
# Fixtures load and are well-formed.
# ---------------------------------------------------------------------------


def test_corpus_fixtures_exist() -> None:
    """Both corpus fixtures exist on disk."""
    assert _VALID_FIXTURE.is_file(), f"missing valid corpus: {_VALID_FIXTURE}"
    assert _ADVERSARIAL_FIXTURE.is_file(), f"missing adversarial corpus: {_ADVERSARIAL_FIXTURE}"


def test_corpus_fixtures_schema_version() -> None:
    """Both corpus fixtures carry the BridgeCorpusDoc/v1 schema_version."""
    valid = _load_corpus(_VALID_FIXTURE)
    adv = _load_corpus(_ADVERSARIAL_FIXTURE)
    assert valid["schema_version"] == "BridgeCorpusDoc/v1"
    assert adv["schema_version"] == "BridgeCorpusDoc/v1"


def test_corpus_counts_meet_floors() -> None:
    """The corpus meets the plan's minimum-case floors."""
    valid = _load_corpus(_VALID_FIXTURE)
    adv = _load_corpus(_ADVERSARIAL_FIXTURE)
    assert len(valid["cases"]) >= _MIN_VALID_CASES  # type: ignore[arg-type]
    assert len(adv["cases"]) >= _MIN_ADVERSARIAL_CASES  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Valid corpus: every case builds, validates, under cap.
# ---------------------------------------------------------------------------


def _valid_cases() -> list[dict[str, object]]:
    return _load_corpus(_VALID_FIXTURE)["cases"]  # type: ignore[return-value]


@pytest.mark.parametrize("case", _valid_cases(), ids=lambda c: str(c["case_id"]))
def test_valid_corpus_case_builds(case: dict[str, object]) -> None:
    """Each valid case builds, schema-validates, and is under the 1 MiB cap."""
    objects = _objects_from_case(case)
    policy = _policy_from_case(case)
    packet = build_packet(
        objects,
        policy,
        created_utc=case.get("created_utc", "2026-07-28T00:00:00Z"),  # type: ignore[arg-type]
        source_snapshot_digest=case.get("source_snapshot_digest"),  # type: ignore[arg-type]
    )
    schema_validate(packet, "LabExportPacket")
    encoded = dumps(packet)
    assert len(encoded) <= PACKET_MAX_BYTES
    # Safety consts (the valid corpus must carry them).
    assert packet["review_only"] is True
    assert packet["canonical_effect"] == "none"
    assert packet["grants_authority"] is False
    assert packet["canonical_writes"] == 0


def test_valid_corpus_covers_both_policies() -> None:
    """The valid corpus exercises both digest_replaced and omitted policies."""
    policies = {c["policy"]["private_identities"] for c in _valid_cases()}  # type: ignore[index]
    assert policies == {"digest_replaced", "omitted"}


# ---------------------------------------------------------------------------
# Adversarial corpus: every case rejected typed (no wrong-reason passes).
# ---------------------------------------------------------------------------


def _adversarial_doc() -> dict[str, object]:
    return _load_corpus(_ADVERSARIAL_FIXTURE)


def _adversarial_cases() -> list[dict[str, object]]:
    return _adversarial_doc()["cases"]  # type: ignore[return-value]


@pytest.mark.parametrize("case", _adversarial_cases(), ids=lambda c: str(c["case_id"]))
def test_adversarial_corpus_case_rejected_typed(case: dict[str, object]) -> None:
    """Each adversarial case is rejected with its expected typed fail_reason."""
    placeholder_map = _adversarial_doc()["placeholder_map"]  # type: ignore[index]
    expected = case["expected_fail_reason"]
    with pytest.raises(ContractError) as exc_info:
        _build_for_case(case, placeholder_map)
    actual = getattr(exc_info.value, "fail_reason", None)
    assert actual == expected, (
        f"{case['case_id']}: expected fail_reason {expected!r}, got {actual!r}"
    )
    # The reason must be one of the two documented typed reasons.
    assert actual in {
        BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
        CONTRACT_INVALID_FAIL_REASON,
    }


def test_adversarial_corpus_covers_required_classes() -> None:
    """The adversarial corpus covers every required forbidden class."""
    required = {
        "local_path",
        "unix_path",
        "argv_flag",
        "shell_command",
        "env_assignment",
        "env_reference",
        "credential_pattern",
        "credential_keyword",
        "raw_dataset_marker",
        "t7_uuidv7",
        "vps_topology_marker",
        "private_key_marker",
        "promotion_flag",
        "self_referential_hash",
        "stale_hash",
        "unknown_schema_version",
        "unknown_license",
        "unknown_object_type",
        "oversize_packet",
        "nested_smuggling",
        "unicode_evasion",
        "wrong_type",
        "grants_authority_tamper",
    }
    present = {c["forbidden_class"] for c in _adversarial_cases()}  # type: ignore[index]
    missing = required - present
    assert not missing, f"adversarial corpus missing required classes: {sorted(missing)}"


def test_adversarial_corpus_no_wrong_reason_passes() -> None:
    """No adversarial case passes with a reason other than its expected one."""
    placeholder_map = _adversarial_doc()["placeholder_map"]  # type: ignore[index]
    wrong: list[str] = []
    for case in _adversarial_cases():
        expected = case["expected_fail_reason"]
        try:
            _build_for_case(case, placeholder_map)
            wrong.append(f"{case['case_id']}: NOT rejected (expected {expected!r})")
        except ContractError as exc:
            actual = getattr(exc, "fail_reason", None)
            if actual != expected:
                wrong.append(f"{case['case_id']}: expected {expected!r}, got {actual!r}")
        except Exception as exc:  # a non-contract error is a corpus failure.
            wrong.append(f"{case['case_id']}: {type(exc).__name__}: {exc}")
    assert not wrong, "wrong-reason passes: " + "; ".join(wrong)
