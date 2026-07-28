#!/usr/bin/env python3
"""WP-I81 export-adversarial corpus check: emit ``CorpusReceipt/v1``.

Loads the twelve-case valid corpus and the forty-plus-case adversarial corpus
under ``fixtures/conformance/bridge/corpus/``, drives EVERY case through the
real, merged exporter (:func:`srl.bridge.exporter.build_packet`) and the
refuse-not-strip sanitizer (:mod:`srl.bridge.sanitizer`), and emits a single
canonical ``CorpusReceipt/v1`` JSON line to stdout. Exits 0 only if every check
PASSes; any failure makes the exit code non-zero so the check can gate CI
(the ``export-corpus-gate`` job in ``bridge.yml``).

The corpus VALIDATES AGAINST THE MERGED EXPORTER — it does not weaken it. The
exporter is the security-critical boundary; this gate exercises it from the
outside, exactly as a caller would, and asserts the documented refusal
behavior.

Checks
------
I81-01 valid corpus (>=12 accepted)
    Each valid fixture case builds through ``build_packet``, schema-validates
    against ``LabExportPacket``, has a content-addressed ``packet_id``, and its
    canonical encoded bytes are at most 1 MiB. The valid corpus covers the
    coarse object-type vocabulary (claim, math_ir, receipt, catalog, evidence,
    plan, request, pilot, ...) AND BOTH disclosure policies (digest_replaced,
    omitted).

I81-02 adversarial corpus (>=40 rejected typed)
    Every adversarial fixture case is rejected with a typed error whose
    ``fail_reason`` matches the case's ``expected_fail_reason``
    (``BRIDGE_CONTRACT_MISMATCH`` for a forbidden class, an oversize packet, or
    a smuggling hit; ``CONTRACT_INVALID`` for a structural/schema/object-
    construction failure). No case passes with the WRONG reason. The literal
    forbidden string is reconstructed at runtime from the fixture's SAFE
    placeholder pieces (character-level tokens + opaque credential labels), so
    the fixture file itself is scanner-clean.

I81-03 determinism
    Two runs of the whole receipt produce BYTE-IDENTICAL output. The receipt
    carries no wall-clock, no random ids, no dict-order-dependent fields;
    every collection is emitted in sorted-key canonical JSON.

I81-04 counts asserted
    The valid corpus has at least 12 cases AND the adversarial corpus has at
    least 40 cases; the receipt records the exact counts.

Honesty
-------
A corpus PASS never means the exporter is "secure". It means the documented
refusal behavior is reproduced for this synthetic corpus. See
``docs/security/export-adversarial.md``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp81-corpus.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.bridge import (  # noqa: E402
    BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
    LAB_EXPORT_PACKET_SCHEMA_VERSION,
    PACKET_MAX_BYTES,
)
from srl.bridge.exporter import (  # noqa: E402
    DisclosurePolicy,
    ExportObject,
    OversizePacketError,
    build_packet,
)
from srl.bridge.sanitizer import SanitizerRefusalError, scan_payload  # noqa: E402
from srl.contracts import dumps  # noqa: E402
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError  # noqa: E402
from srl.contracts.schema import validate as schema_validate  # noqa: E402

# Receipt identity.
RECEIPT_SCHEMA: Final[str] = "CorpusReceipt/v1"
WP_ID: Final[str] = "WP-I81"

# Canonical corpus paths.
_CORPUS_DIR: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "bridge" / "corpus"
_VALID_FIXTURE: Final[Path] = _CORPUS_DIR / "valid.v1.json"
_ADVERSARIAL_FIXTURE: Final[Path] = _CORPUS_DIR / "adversarial.v1.json"

# Minimum corpus sizes asserted by I81-04 (the plan's floor).
_MIN_VALID_CASES: Final[int] = 12
_MIN_ADVERSARIAL_CASES: Final[int] = 40

# A synthetic valid object digest reused across the adversarial build helpers.
_VALID_DIGEST: Final[str] = "sha256:" + "a" * 64
_VALID_PROV: Final[str] = "sha256:" + "c" * 64


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_json(path: Path) -> Any:
    """Read and JSON-decode a fixture file, returning the raw object."""
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Placeholder substitution.
# ---------------------------------------------------------------------------
# Credential-shaped opaque labels the fixture templates use. The fixture file
# carries ONLY the label (e.g. {GH}); the LITERAL expansion lives here in
# Python source, SPLIT across concatenation so no contiguous forbidden literal
# appears in this tracked .py file (the public-boundary scanner would otherwise
# flag it). Each expansion reconstructs the credential prefix a sanitizer must
# refuse.
_CRED_TOKEN_MAP: Final[dict[str, str]] = {
    "{GH}": "gh" + "p",  # GitHub classic PAT prefix
    "{SK}": "s" + "k",  # API key prefix
    "{AK}": "AK" + "IA",  # AWS access key ID prefix
    "{PEM}": "BEGI" + "N RSA PRIVATE K" + "EY",  # PEM private-key header
}


def _substitute_placeholders(template: str, placeholder_map: dict[str, str]) -> str:
    """Substitute placeholder tokens in ``template`` with their literal chars.

    The fixture stores CHARACTER-LEVEL placeholder tokens (``{S}`` for slash,
    ``{H}`` for hyphen, ``{U}`` for underscore, ``{E}`` for equals, ``{B}`` for
    backslash, ``{FW}`` for the fullwidth slash U+FF0F, ``{ZW}`` for the
    zero-width space U+200B) plus OPAQUE CREDENTIAL LABELS (``{GH}``, ``{SK}``,
    ``{AK}``, ``{PEM}`). This function merges the fixture's ``placeholder_map``
    with the gate-owned :data:`_CRED_TOKEN_MAP` (whose literal values are split
    in source so no contiguous forbidden literal appears in either tracked
    file). The gate reconstructs the literal forbidden string at runtime by
    direct string replacement. A placeholder absent from the template is a
    no-op.
    """
    merged = {**placeholder_map, **_CRED_TOKEN_MAP}
    out = template
    for token, literal in merged.items():
        out = out.replace(token, literal)
    return out


def _policy_from_case(case: dict[str, Any]) -> DisclosurePolicy:
    """Rebuild a DisclosurePolicy from a valid fixture case."""
    p = case["policy"]
    return DisclosurePolicy(
        private_identities=p["private_identities"],
        summary_max_bytes=p["summary_max_bytes"],
    )


def _objects_from_case(case: dict[str, Any]) -> list[ExportObject]:
    """Rebuild ExportObject instances from a valid fixture case."""
    out: list[ExportObject] = []
    for obj in case["objects"]:
        out.append(
            ExportObject(
                object_digest=obj["object_digest"],
                object_type=obj["object_type"],
                sanitized_summary=obj["sanitized_summary"],
                provenance_refs=tuple(obj.get("provenance_refs", [])),
            )
        )
    return out


# ---------------------------------------------------------------------------
# I81-01: valid corpus (>=12 accepted).
# ---------------------------------------------------------------------------


def _check_i81_01() -> dict[str, Any]:
    """I81-01: each valid fixture case builds, validates, and is <= 1 MiB."""
    try:
        doc = _load_json(_VALID_FIXTURE)
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"fixture load failed: {type(exc).__name__}: {exc}"}

    cases = doc.get("cases", [])
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for case in cases:
        cid = case["case_id"]
        try:
            objects = _objects_from_case(case)
            policy = _policy_from_case(case)
            packet = build_packet(
                objects,
                policy,
                created_utc=case.get("created_utc", "2026-07-28T00:00:00Z"),
                source_snapshot_digest=case.get("source_snapshot_digest"),
            )
        except Exception as exc:  # a valid case must build.
            errors.append(f"{cid}: build failed: {type(exc).__name__}: {exc}")
            continue
        # Schema validation (defense in depth; build_packet already validates).
        try:
            schema_validate(packet, "LabExportPacket")
        except ContractError as exc:
            errors.append(f"{cid}: schema validation failed: {exc}")
            continue
        encoded = dumps(packet)
        size_ok = len(encoded) <= PACKET_MAX_BYTES
        if not size_ok:
            errors.append(f"{cid}: canonical bytes {len(encoded)} > {PACKET_MAX_BYTES}")
        results.append(
            {
                "case_id": cid,
                "packet_id": packet["packet_id"],
                "object_count": len(packet["objects"]),
                "encoded_bytes": len(encoded),
                "under_cap": size_ok,
            }
        )

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors), "cases": results}
    return {
        "status": "PASS",
        "detail": (
            f"{len(results)} valid packet(s) built, schema-validated, and under "
            f"the {PACKET_MAX_BYTES} byte cap"
        ),
        "cases": results,
    }


# ---------------------------------------------------------------------------
# I81-02: adversarial corpus (>=40 rejected typed).
# ---------------------------------------------------------------------------


def _claim(summary: str) -> ExportObject:
    """Build a single claim-typed ExportObject with the given summary."""
    return ExportObject(
        object_digest=_VALID_DIGEST,
        object_type="claim",
        sanitized_summary=summary,
    )


def _substituted_summary(case: dict[str, Any], placeholder_map: dict[str, str]) -> str:
    """Reconstruct the literal forbidden summary from a case's prefix+token."""
    prefix = _substitute_placeholders(case.get("prefix", ""), placeholder_map)
    token = _substitute_placeholders(case.get("token_template", ""), placeholder_map)
    return (prefix + " " + token).strip() if token else prefix


def _build_packet_for_summary(summary: str) -> None:
    """Build a single-claim packet; must raise on a forbidden summary."""
    build_packet([_claim(summary)], DisclosurePolicy(private_identities="digest_replaced"))


def _build_unknown_object_type(case: dict[str, Any], _placeholder_map: dict[str, str]) -> None:
    """ExportObject construction rejects a bad object_type (CONTRACT_INVALID)."""
    ExportObject(
        object_digest=_VALID_DIGEST,
        object_type=case.get("object_type", "bogus"),
        sanitized_summary="valid summary",
    )


def _build_unknown_schema_version(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """Build a valid packet then tamper schema_version and re-validate."""
    summary = _substitute_placeholders(case.get("prefix", ""), placeholder_map)
    packet = build_packet([_claim(summary)], DisclosurePolicy(private_identities="digest_replaced"))
    packet["schema_version"] = "LabExportPacket/vBogus"
    schema_validate(packet, "LabExportPacket")


def _build_unknown_license(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """additionalProperties: false — a smuggled 'license' field is rejected."""
    summary = _substitute_placeholders(case.get("prefix", ""), placeholder_map)
    packet = build_packet([_claim(summary)], DisclosurePolicy(private_identities="digest_replaced"))
    schema_validate({**packet, "license": "unknown_license_v9"}, "LabExportPacket")


def _build_hash_guard(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """Self-referential / stale hash guard: a non-sha256 digest is rejected."""
    klass = case["class"]
    summary = _substitute_placeholders(case.get("prefix", ""), placeholder_map)
    packet = build_packet([_claim(summary)], DisclosurePolicy(private_identities="digest_replaced"))
    packet_id = packet["packet_id"]
    # Guard assertion: a well-built packet has no object_digest == packet_id.
    for obj in packet["objects"]:
        if obj["object_digest"] == packet_id:
            msg = f"{klass}: object_digest equals packet_id (guard failed)"
            raise ContractError(msg)
    structurally_bad = {
        **packet,
        "objects": [{**packet["objects"][0], "object_digest": "not-a-sha256-digest"}],
    }
    schema_validate(structurally_bad, "LabExportPacket")  # must raise


def _build_wrong_type(case: dict[str, Any], _placeholder_map: dict[str, str]) -> None:
    """A wrong-typed field is rejected (CONTRACT_INVALID)."""
    kind = case.get("wrong_value_kind", "")
    if kind == "numeric_summary":
        # sanitized_summary is a number; normalize_summary rejects it at build
        # time as CONTRACT_INVALID (the free-text disclosure surface must be a
        # string). Invoked directly so the type validator runs regardless of the
        # dataclass's annotation-only enforcement.
        from srl.bridge.sanitizer import normalize_summary  # noqa: PLC0415

        normalize_summary(123, max_bytes=1024)  # type: ignore[arg-type]
        return
    if kind == "integer_digest":
        # object_digest is an integer; ExportObject construction rejects it.
        ExportObject(12345, "claim", "A claim.")  # type: ignore[arg-type]
        return
    msg = f"wrong_type: unknown wrong_value_kind {kind!r}"
    raise ContractError(msg)


def _build_grants_authority_tamper(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """A safety const is pinned by the schema; tampering fails validation."""
    summary = _substitute_placeholders(case.get("prefix", ""), placeholder_map)
    packet = build_packet([_claim(summary)], DisclosurePolicy(private_identities="digest_replaced"))
    schema_validate({**packet, case["tamper_field"]: case["tamper_value"]}, "LabExportPacket")


def _build_oversize_packet() -> None:
    """Build enough safe objects to exceed the 1 MiB cap; no truncation."""
    summary = "convergence result " * 100  # ~1800 chars, all safe words
    big_objects = [_claim(summary) for _ in range(700)]
    policy = DisclosurePolicy(private_identities="digest_replaced", summary_max_bytes=2000)
    build_packet(big_objects, policy)


def _build_nested_smuggling(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """A forbidden value hidden in a NESTED non-exempt field; scan_payload refuses."""
    smuggled_value = _substituted_summary(case, placeholder_map)
    field_name = case.get("smuggle_field", "notes")
    payload = {
        "objects": [
            {
                "object_digest": _VALID_DIGEST,
                "object_type": "claim",
                "sanitized_summary": "a clean summary",
                "provenance_refs": [_VALID_PROV],
                field_name: smuggled_value,
            }
        ]
    }
    scan_payload(payload)


def _build_unicode_evasion(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """A unicode-evasion ATTEMPT with a co-occurring ASCII forbidden substring.

    The reconstructed summary carries the unicode char AND a co-occurring ASCII
    forbidden substring, so an ASCII detector fires and the attempt is REFUSED.
    (The sanitizer does not unicode-normalize; a standalone fullwidth-slash-only
    path would be an accepted gap — see docs/security/export-adversarial.md.)
    """
    summary = _substitute_placeholders(
        case.get("prefix", "") + " " + case.get("token_template", ""),
        placeholder_map,
    ).strip()
    _build_packet_for_summary(summary)


# Dispatch table: case["class"] -> handler. Each handler MUST raise. Handlers
# that need the placeholder map take it as a second arg; the dispatcher passes
# it positionally. Keeping each handler small keeps the per-function complexity
# under the mccabe/ruff limits.
_DISPATCH: Final[dict[str, Any]] = {
    "unknown_object_type": _build_unknown_object_type,
    "unknown_schema_version": _build_unknown_schema_version,
    "unknown_license": _build_unknown_license,
    "self_referential_hash": _build_hash_guard,
    "stale_hash": _build_hash_guard,
    "wrong_type": _build_wrong_type,
    "grants_authority_tamper": _build_grants_authority_tamper,
    "oversize_packet": lambda _case, _pm: _build_oversize_packet(),
    "nested_smuggling": _build_nested_smuggling,
    "unicode_evasion": _build_unicode_evasion,
}


def _build_for_case(case: dict[str, Any], placeholder_map: dict[str, str]) -> None:
    """Build a packet (or exercise a structural path) for an adversarial case.

    Must raise. The caller asserts the raised error's ``fail_reason`` matches
    the case's ``expected_fail_reason``. Dispatch is by ``case["class"]``; the
    default path builds a single-claim packet from the reconstructed forbidden
    summary.
    """
    handler = _DISPATCH.get(case["class"])
    if handler is not None:
        handler(case, placeholder_map)
        return
    # default: a forbidden-class summary.
    _build_packet_for_summary(_substituted_summary(case, placeholder_map))


def _check_i81_02() -> dict[str, Any]:
    """I81-02: every adversarial case is rejected with the EXPECTED typed reason."""
    try:
        doc = _load_json(_ADVERSARIAL_FIXTURE)
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"fixture load failed: {type(exc).__name__}: {exc}"}

    placeholder_map = doc.get("placeholder_map", {})
    if not placeholder_map:
        return {"status": "FAIL", "detail": "adversarial fixture has no placeholder_map"}
    cases = doc.get("cases", [])
    if not cases:
        return {"status": "FAIL", "detail": "adversarial fixture has no cases"}

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for case in cases:
        cid = case["case_id"]
        expected_reason = case["expected_fail_reason"]
        try:
            _build_for_case(case, placeholder_map)
        except (SanitizerRefusalError, OversizePacketError, ContractError) as exc:
            actual_reason = getattr(exc, "fail_reason", None)
            ok = actual_reason == expected_reason
            results.append(
                {
                    "case_id": cid,
                    "forbidden_class": case["forbidden_class"],
                    "expected_fail_reason": expected_reason,
                    "actual_fail_reason": actual_reason,
                    "passed": ok,
                }
            )
            if not ok:
                errors.append(
                    f"{cid}: expected fail_reason {expected_reason!r}, got {actual_reason!r}"
                )
            continue
        except Exception as exc:  # a different exception type is a gate failure.
            results.append(
                {
                    "case_id": cid,
                    "forbidden_class": case["forbidden_class"],
                    "expected_fail_reason": expected_reason,
                    "actual": f"{type(exc).__name__}: {exc}",
                    "passed": False,
                }
            )
            errors.append(
                f"{cid}: rejected with {type(exc).__name__}, expected a ContractError "
                f"with fail_reason {expected_reason!r}"
            )
            continue
        # No exception raised = failure.
        results.append(
            {
                "case_id": cid,
                "forbidden_class": case["forbidden_class"],
                "expected_fail_reason": expected_reason,
                "actual_fail_reason": None,
                "passed": False,
            }
        )
        errors.append(f"{cid}: was NOT rejected (expected {expected_reason!r})")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors), "cases": results}
    return {
        "status": "PASS",
        "detail": (
            f"all {len(results)} adversarial case(s) rejected with the expected typed "
            "reason (BRIDGE_CONTRACT_MISMATCH for forbidden classes / oversize / "
            "smuggling, CONTRACT_INVALID for structural failures)"
        ),
        "cases": results,
    }


# ---------------------------------------------------------------------------
# I81-03: determinism (two runs -> identical check bytes).
# ---------------------------------------------------------------------------


def _check_i81_03() -> dict[str, Any]:
    """I81-03: two runs of the substantive checks produce byte-identical bytes.

    Determinism is asserted over the substantive checks (I81-01 valid build,
    I81-02 adversarial rejection, I81-04 count assertion) — NOT over this check
    itself (which would recurse). Each substantive check is deterministic by
    construction: no wall-clock, no random ids, no dict-order-dependent fields;
    the corpus and the exporter are pure functions of their inputs. Two runs of
    the substantive checks must produce identical canonical bytes.
    """
    valid_doc = _load_json(_VALID_FIXTURE)
    adv_doc = _load_json(_ADVERSARIAL_FIXTURE)
    valid_count = len(valid_doc.get("cases", []))
    adv_count = len(adv_doc.get("cases", []))

    def _substantive() -> dict[str, Any]:
        return {
            "I81-01": _check_i81_01(),
            "I81-02": _check_i81_02(),
            "I81-04": _check_i81_04(valid_count, adv_count),
        }

    b1 = dumps(_substantive())
    b2 = dumps(_substantive())
    identical = b1 == b2
    if not identical:
        return {
            "status": "FAIL",
            "detail": "two substantive-check runs produced different canonical bytes",
            "evidence": {"bytes_run_1": len(b1), "bytes_run_2": len(b2)},
        }
    return {
        "status": "PASS",
        "detail": (
            f"two substantive-check runs produced identical canonical bytes "
            f"({len(b1)} bytes); no wall-clock, random, or order-dependent fields"
        ),
    }


# ---------------------------------------------------------------------------
# I81-04: counts asserted.
# ---------------------------------------------------------------------------


def _check_i81_04(valid_count: int, adversarial_count: int) -> dict[str, Any]:
    """I81-04: the corpus meets the plan's minimum-case floors."""
    ok_valid = valid_count >= _MIN_VALID_CASES
    ok_adv = adversarial_count >= _MIN_ADVERSARIAL_CASES
    errors: list[str] = []
    if not ok_valid:
        errors.append(f"valid corpus has {valid_count} cases, expected >= {_MIN_VALID_CASES}")
    if not ok_adv:
        errors.append(
            "adversarial corpus has "
            f"{adversarial_count} cases, expected >= {_MIN_ADVERSARIAL_CASES}"
        )
    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": (
            f"valid corpus has {valid_count} cases (>= {_MIN_VALID_CASES}); "
            f"adversarial corpus has {adversarial_count} cases (>= {_MIN_ADVERSARIAL_CASES})"
        ),
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the CorpusReceipt/v1 dict.

    I81-04 depends on the corpus counts, so it is computed from the same loaded
    fixtures the other checks consume (the counts are structural facts about the
    fixtures, independent of the build outcomes).
    """
    valid_doc = _load_json(_VALID_FIXTURE)
    adv_doc = _load_json(_ADVERSARIAL_FIXTURE)
    valid_count = len(valid_doc.get("cases", []))
    adv_count = len(adv_doc.get("cases", []))

    checks = {
        "I81-01": _check_i81_01(),
        "I81-02": _check_i81_02(),
        "I81-03": _check_i81_03(),
        "I81-04": _check_i81_04(valid_count, adv_count),
    }

    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": RECEIPT_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            "lab_export_packet_schema_version": LAB_EXPORT_PACKET_SCHEMA_VERSION,
            "packet_max_bytes": PACKET_MAX_BYTES,
            "valid_count": valid_count,
            "adversarial_count": adv_count,
            "min_valid_cases": _MIN_VALID_CASES,
            "min_adversarial_cases": _MIN_ADVERSARIAL_CASES,
            "valid_fixture": str(_VALID_FIXTURE.relative_to(_REPO_ROOT)),
            "adversarial_fixture": str(_ADVERSARIAL_FIXTURE.relative_to(_REPO_ROOT)),
            "fail_reasons": {
                "bridge_contract_mismatch": BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
                "contract_invalid": CONTRACT_INVALID_FAIL_REASON,
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the corpus check. Returns 0 iff every check PASSes."""
    _ = sys.argv[1:] if argv is None else argv  # accepted, ignored (no flags)

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
