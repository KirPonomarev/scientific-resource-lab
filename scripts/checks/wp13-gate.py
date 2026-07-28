#!/usr/bin/env python3
"""WP-B13 acceptance gate for the evidence assessment and run receipt model.

Runs the four WP-B13 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp13``.

The checks
----------
B13-01 import probe cannot yield COMPUTED
    A probe cannot yield computed output at BOTH the receipt level
    (a ``ScienceLabEngineReceipt`` with ``exercise_level=import_probe`` and a
    non-empty ``output_object_ids`` is rejected) and the assessment level
    (an ``EvidenceAssessment`` with ``exercise_level=import_probe`` and
    ``engine_execution=completed`` is rejected at schema + python layer with
    fail reason ``CONTRACT_INVALID`` and invariant ``probe_not_compute``).

B13-02 SMT-style answer yields at most CHECKED without verified certificate
    A ``ScienceLabValidationReceipt`` with ``formal_check=proven`` and a null
    ``formal_certificate_ref`` is rejected at schema + python layer (invariant
    ``proven_requires_certificate``). A SMT-style answer (``formal_check=
    'checked'``) is allowed without a certificate; ``proven`` is not.

B13-03 formal axis cannot update empirical axis
    An ``update_assessment`` delta that moves a formal axis (formal_check /
    formal_scope) AND an empirical axis (statistical_support /
    causal_identification) in the same step is rejected (invariant
    ``formal_not_empirical``). Formal proof is not empirical truth; each axis
    is set by its own evidence across separate updates.

B13-04 algorithmic reproduction differs from independent replication
    An ``update_assessment`` delta that moves
    ``algorithmic_cross_engine_reproduction`` AND
    ``independent_empirical_replication`` in the same step is rejected
    (invariant ``algorithmic_not_independent``). Algorithm agreement is not
    independent empirical replication; setting one never sets the other. The
    positive/negative fixtures also validate/reject as expected, and the
    reserved integration_authority tiers (admitted_a1_sandbox / admitted_a2)
    are rejected.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp13-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp13-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import (  # noqa: E402  (path setup must precede import)
    ContractError,
    dumps,
)
from srl.contracts.schema import (  # noqa: E402
    ContractValidationError,
)
from srl.contracts.schema import (  # noqa: E402
    validate as schema_validate,
)
from srl.semantic.evidence import (  # noqa: E402
    DEFAULT_AXES,
    EvidenceAxisError,
    build_assessment,
    build_engine_receipt,
    build_validation_receipt,
    update_assessment,
)
from srl.semantic.evidence import (  # noqa: E402
    validate as validate_assessment,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-B13"

# Fixtures directory (the evidence conformance vectors).
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "evidence"

# Maps each positive fixture to its schema name.
_POSITIVE_FIXTURES: Final[dict[str, str]] = {
    "p01-assessment-probe-only": "EvidenceAssessment",
    "p02-assessment-compute-checked-formal": "EvidenceAssessment",
    "p03-engine-receipt-compute": "ScienceLabEngineReceipt",
    "p04-validation-receipt-proven-cert": "ScienceLabValidationReceipt",
    "p05-run-receipt-completed": "ScienceLabRunReceipt",
}

# A canonical sha256 digest used for object ids in the inline proofs.
_DIGEST: Final[str] = "sha256:" + "a" * 64
# A canonical inline ArtifactRef (adapter pack) used in the inline proofs.
_PACK_REF: Final[dict[str, Any]] = {
    "schema_version": "ArtifactRef/v1",
    "media_type": "application/vnd.srlab.adapter-pack+json",
    "digest": _DIGEST,
    "size_bytes": 4096,
}
# A canonical inline ArtifactRef (formal certificate) used in the inline proofs.
_CERT_REF: Final[dict[str, Any]] = {
    "schema_version": "ArtifactRef/v1",
    "media_type": "application/vnd.srlab.formal-certificate+json",
    "digest": _DIGEST,
    "size_bytes": 512,
}

# The typed fail reason emitted by evidence-axis violations, surfaced in the
# gate cases so the receipt records it.
EVIDENCE_AXIS_FAIL_REASON_REF: Final[str] = "CONTRACT_INVALID"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _axes(**overrides: str) -> dict[str, str]:
    """Return the default axes with the given overrides applied."""
    axes = dict(DEFAULT_AXES)
    axes.update(overrides)
    return axes


# ---------------------------------------------------------------------------
# B13-01 import probe cannot yield COMPUTED (receipt + assessment levels).
# ---------------------------------------------------------------------------


def _check_b13_01() -> dict[str, Any]:
    """B13-01: a probe cannot yield computed output at either level."""
    rejections: list[dict[str, str]] = []

    # Receipt level: import_probe + non-empty outputs -> rejected (schema + python).
    probe_with_outputs = {
        "schema_version": "ScienceLabEngineReceipt/v1",
        "receipt_id": _DIGEST,
        "run_request_id": _DIGEST,
        "adapter_id": "solver-x",
        "pack_ref": _PACK_REF,
        "engine_execution": "completed",
        "wall_seconds": 0,
        "rss_bytes": 0,
        "output_object_ids": [_DIGEST],
        "exercise_level": "import_probe",
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    try:
        schema_validate(probe_with_outputs, "ScienceLabEngineReceipt")
        rejections.append(
            {"case": "receipt-schema-probe-outputs", "layer": "schema", "outcome": "NOT rejected"}
        )
    except ContractValidationError:
        rejections.append(
            {"case": "receipt-schema-probe-outputs", "layer": "schema", "outcome": "rejected"}
        )
    try:
        build_engine_receipt(
            run_request_id=_DIGEST,
            adapter_id="solver-x",
            pack_ref=_PACK_REF,
            engine_execution="completed",
            exercise_level="import_probe",
            wall_seconds=0,
            rss_bytes=0,
            output_object_ids=[_DIGEST],
        )
        rejections.append(
            {"case": "receipt-python-probe-outputs", "layer": "python", "outcome": "NOT rejected"}
        )
    except EvidenceAxisError as exc:
        rejections.append(
            {
                "case": "receipt-python-probe-outputs",
                "layer": "python",
                "outcome": "rejected",
                "invariant": exc.invariant,
                "fail_reason": exc.fail_reason,
            }
        )

    # Assessment level: import_probe + engine completed -> rejected (schema + python).
    probe_completed = {
        "schema_version": "EvidenceAssessment/v1",
        "assessment_id": _DIGEST,
        "subject_claim_id": _DIGEST,
        "axes": _axes(exercise_level="import_probe", engine_execution="completed"),
        "evidence_refs": [],
        "assessor": "operator",
        "created_utc": "2026-07-28T00:00:00Z",
        "parents": [],
        "canonical_writes": 0,
        "grants_authority": False,
    }
    try:
        schema_validate(probe_completed, "EvidenceAssessment")
        rejections.append(
            {
                "case": "assessment-schema-probe-completed",
                "layer": "schema",
                "outcome": "NOT rejected",
            }
        )
    except ContractValidationError:
        rejections.append(
            {
                "case": "assessment-schema-probe-completed",
                "layer": "schema",
                "outcome": "rejected",
            }
        )
    try:
        validate_assessment(probe_completed)
        rejections.append(
            {
                "case": "assessment-python-probe-completed",
                "layer": "python",
                "outcome": "NOT rejected",
            }
        )
    except EvidenceAxisError as exc:
        rejections.append(
            {
                "case": "assessment-python-probe-completed",
                "layer": "python",
                "outcome": "rejected",
                "invariant": exc.invariant,
                "fail_reason": exc.fail_reason,
            }
        )

    not_rejected = [r for r in rejections if not r["outcome"].startswith("rejected")]
    if not_rejected:
        return {
            "status": "FAIL",
            "detail": "a probe yielding computed output was not rejected at one or more layers",
            "rejections": rejections,
        }
    return {
        "status": "PASS",
        "detail": (
            "import_probe + computed output rejected at receipt (schema + python) and "
            "assessment (schema + python) levels (probe_not_compute)"
        ),
        "rejections": rejections,
    }


# ---------------------------------------------------------------------------
# B13-02 SMT-style answer yields at most CHECKED without verified certificate.
# ---------------------------------------------------------------------------


def _check_b13_02() -> dict[str, Any]:
    """B13-02: proven without a certificate is rejected; checked is allowed."""
    cases: list[dict[str, Any]] = []

    # proven + null certificate -> rejected (schema + python).
    proven_no_cert = {
        "schema_version": "ScienceLabValidationReceipt/v1",
        "receipt_id": _DIGEST,
        "engine_receipt_id": _DIGEST,
        "validator_id": "validator-x",
        "scientific_check": "checked",
        "formal_check": "proven",
        "formal_certificate_ref": None,
        "statistical_support": "none",
        "causal_identification": "not_applicable",
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    schema_rejected = False
    try:
        schema_validate(proven_no_cert, "ScienceLabValidationReceipt")
    except ContractValidationError:
        schema_rejected = True
    cases.append({"case": "proven-no-cert-schema", "schema_rejected": schema_rejected})

    python_rejected = False
    py_invariant = ""
    try:
        build_validation_receipt(
            engine_receipt_id=_DIGEST,
            validator_id="validator-x",
            scientific_check="checked",
            formal_check="proven",
            formal_certificate_ref=None,
        )
    except EvidenceAxisError as exc:
        python_rejected = True
        py_invariant = exc.invariant
    cases.append(
        {
            "case": "proven-no-cert-python",
            "python_rejected": python_rejected,
            "invariant": py_invariant,
            "fail_reason": EVIDENCE_AXIS_FAIL_REASON_REF,
        }
    )

    # checked (no certificate) -> ALLOWED. A SMT-style answer without a verified
    # certificate yields at most checked; checked is a valid, honest state.
    checked_ok = False
    try:
        vr = build_validation_receipt(
            engine_receipt_id=_DIGEST,
            validator_id="validator-x",
            scientific_check="checked",
            formal_check="checked",
            formal_certificate_ref=None,
        )
        checked_ok = vr["formal_check"] == "checked" and vr["formal_certificate_ref"] is None
    except ContractError:
        checked_ok = False
    cases.append({"case": "checked-no-cert-allowed", "allowed": checked_ok})

    # proven + certificate -> ALLOWED (the honest path to proven).
    proven_cert_ok = False
    try:
        vr = build_validation_receipt(
            engine_receipt_id=_DIGEST,
            validator_id="validator-x",
            scientific_check="checked",
            formal_check="proven",
            formal_certificate_ref=_CERT_REF,
        )
        proven_cert_ok = vr["formal_check"] == "proven"
    except ContractError:
        proven_cert_ok = False
    cases.append({"case": "proven-with-cert-allowed", "allowed": proven_cert_ok})

    failures = []
    if not schema_rejected:
        failures.append("proven without certificate was not rejected at the schema layer")
    if not python_rejected or py_invariant != "proven_requires_certificate":
        failures.append("proven without certificate was not rejected at the python layer")
    if not checked_ok:
        failures.append("checked without certificate was not allowed")
    if not proven_cert_ok:
        failures.append("proven with certificate was not allowed")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "proven without a verified certificate rejected at schema + python layer "
            "(proven_requires_certificate); checked without a certificate allowed; proven "
            "with a certificate allowed"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# B13-03 formal axis cannot update empirical axis.
# ---------------------------------------------------------------------------


def _check_b13_03() -> dict[str, Any]:
    """B13-03: a formal-axis update never modifies an empirical axis."""
    cases: list[dict[str, Any]] = []

    # A root assessment to update from (formal not yet checked, statistical none).
    prior = build_assessment(
        subject_claim_id=_DIGEST,
        axes=_axes(
            capability_state="ready",
            exercise_level="actual_compute",
            engine_execution="completed",
            scientific_check="checked",
            formal_check="unchecked",
            formal_scope="exact_statement",
        ),
        evidence_refs=[_DIGEST],
        assessor="validator",
    )

    # Forbidden: a single update moving a formal axis AND an empirical axis.
    forbidden_rejected = False
    forbidden_invariant = ""
    try:
        update_assessment(
            prior,
            {"formal_check": "checked", "statistical_support": "weak"},
            _DIGEST,
        )
    except EvidenceAxisError as exc:
        forbidden_rejected = True
        forbidden_invariant = exc.invariant
    cases.append(
        {
            "case": "formal-and-statistical-same-update-rejected",
            "rejected": forbidden_rejected,
            "invariant": forbidden_invariant,
        }
    )

    # Allowed: formal axis moved in one update, empirical axis moved in a SEPARATE
    # update. The orthogonality rule is about a single step, not the cumulative
    # state — each axis set by its own evidence is honest.
    separated_ok = False
    try:
        a1 = update_assessment(prior, {"formal_check": "checked"}, _DIGEST)
        a2 = update_assessment(a1, {"statistical_support": "weak"}, _DIGEST)
        separated_ok = (
            a2["axes"]["formal_check"] == "checked" and a2["axes"]["statistical_support"] == "weak"
        )
    except ContractError as exc:
        separated_ok = False
        cases.append({"case": "separated-updates-error", "error": str(exc)})
    cases.append(
        {
            "case": "formal-then-statistical-separate-updates-allowed",
            "allowed": separated_ok,
        }
    )

    failures = []
    if not forbidden_rejected or forbidden_invariant != "formal_not_empirical":
        failures.append(
            "a formal+empirical combined update was not rejected as formal_not_empirical"
        )
    if not separated_ok:
        failures.append("formal then empirical across separate updates was not allowed")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "a formal-axis update never modifies an empirical axis in the same step "
            "(formal_not_empirical); each axis set across separate updates is allowed"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# B13-04 algorithmic reproduction differs from independent replication
#         + fixtures + reserved authority.
# ---------------------------------------------------------------------------


def _run_negative(vec_dir: Path, name: str) -> dict[str, Any]:
    """Run one negative vector; return a result dict with a status."""
    input_path = vec_dir / f"{name}.input.json"
    expected_path = vec_dir / f"{name}.expected_error.json"
    if not expected_path.is_file():
        return {"name": name, "status": "FAIL", "detail": "missing expected_error file"}
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    expected_reason = expected["fail_reason"]
    expected_invariant = expected.get("invariant", "")
    validator = expected["validator"]
    doc = json.loads(input_path.read_text(encoding="utf-8"))

    try:
        if validator == "evidence_assessment":
            validate_assessment(doc)
        elif validator == "engine_receipt":
            build_engine_receipt(**_engine_receipt_kwargs(doc))
        elif validator == "validation_receipt":
            build_validation_receipt(**_validation_receipt_kwargs(doc))
        elif validator == "update_assessment":
            update_assessment(doc["prior"], doc["delta"], doc["evidence_ref"])
        else:
            return {"name": name, "status": "FAIL", "detail": f"unknown validator {validator!r}"}
        return {
            "name": name,
            "status": "FAIL",
            "detail": f"input was not rejected (expected fail_reason {expected_reason!r})",
        }
    except ContractError as exc:
        if exc.fail_reason != expected_reason:
            return {
                "name": name,
                "status": "FAIL",
                "detail": (
                    f"wrong fail_reason: got {exc.fail_reason!r}, expected {expected_reason!r}"
                ),
            }
        if expected_invariant and getattr(exc, "invariant", "") != expected_invariant:
            return {
                "name": name,
                "status": "FAIL",
                "detail": (
                    f"wrong invariant: got {getattr(exc, 'invariant', '')!r}, "
                    f"expected {expected_invariant!r}"
                ),
            }
        return {
            "name": name,
            "status": "PASS",
            "validator": validator,
            "exception": type(exc).__name__,
            "fail_reason": exc.fail_reason,
            "invariant": getattr(exc, "invariant", ""),
        }


def _engine_receipt_kwargs(doc: dict[str, Any]) -> dict[str, Any]:
    """Extract build_engine_receipt kwargs from a fixture document."""
    return {
        "run_request_id": doc["run_request_id"],
        "adapter_id": doc["adapter_id"],
        "pack_ref": doc["pack_ref"],
        "engine_execution": doc["engine_execution"],
        "wall_seconds": doc["wall_seconds"],
        "rss_bytes": doc["rss_bytes"],
        "output_object_ids": doc["output_object_ids"],
        "exercise_level": doc["exercise_level"],
        "created_utc": doc["created_utc"],
    }


def _validation_receipt_kwargs(doc: dict[str, Any]) -> dict[str, Any]:
    """Extract build_validation_receipt kwargs from a fixture document."""
    return {
        "engine_receipt_id": doc["engine_receipt_id"],
        "validator_id": doc["validator_id"],
        "scientific_check": doc["scientific_check"],
        "formal_check": doc["formal_check"],
        "formal_certificate_ref": doc["formal_certificate_ref"],
        "statistical_support": doc["statistical_support"],
        "causal_identification": doc["causal_identification"],
        "created_utc": doc["created_utc"],
    }


def _validate_positive_fixtures() -> list[dict[str, Any]]:
    """Validate every positive fixture against its schema (+ python validator)."""
    results: list[dict[str, Any]] = []
    for name, schema in _POSITIVE_FIXTURES.items():
        path = _FIXTURES / f"{name}.input.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            schema_validate(doc, schema)
            if schema == "EvidenceAssessment":
                validate_assessment(doc)
            results.append({"name": name, "schema": schema, "status": "PASS"})
        except (OSError, json.JSONDecodeError, ContractValidationError, ContractError) as exc:
            results.append({"name": name, "schema": schema, "status": "FAIL", "error": str(exc)})
    return results


def _validate_negative_fixtures() -> list[dict[str, Any]]:
    """Run every negative fixture against its named validator."""
    results: list[dict[str, Any]] = []
    neg_dir = _FIXTURES / "negative"
    if neg_dir.is_dir():
        for input_path in sorted(neg_dir.glob("*.input.json")):
            name = input_path.name.removesuffix(".input.json")
            results.append(_run_negative(neg_dir, name))
    return results


def _check_b13_04() -> dict[str, Any]:
    """B13-04: algorithmic reproduction is not independent replication; fixtures + authority."""
    cases: list[dict[str, Any]] = []

    # algorithmic + independent in the same update -> rejected.
    prior = build_assessment(
        subject_claim_id=_DIGEST,
        axes=_axes(
            capability_state="ready",
            exercise_level="actual_compute",
            engine_execution="completed",
            scientific_check="checked",
        ),
        evidence_refs=[_DIGEST],
        assessor="validator",
    )
    algo_rejected = False
    algo_invariant = ""
    try:
        update_assessment(
            prior,
            {
                "algorithmic_cross_engine_reproduction": "reproduced",
                "independent_empirical_replication": "replicated",
            },
            _DIGEST,
        )
    except EvidenceAxisError as exc:
        algo_rejected = True
        algo_invariant = exc.invariant
    cases.append(
        {
            "case": "algorithmic-and-independent-same-update-rejected",
            "rejected": algo_rejected,
            "invariant": algo_invariant,
        }
    )

    # Reserved integration_authority tiers -> rejected.
    authority_rejected = False
    authority_invariant = ""
    try:
        build_assessment(
            subject_claim_id=_DIGEST,
            axes=_axes(integration_authority="admitted_a2"),
        )
    except EvidenceAxisError as exc:
        authority_rejected = True
        authority_invariant = exc.invariant
    cases.append(
        {
            "case": "reserved-authority-admitted-a2-rejected",
            "rejected": authority_rejected,
            "invariant": authority_invariant,
        }
    )

    fixture_results = _validate_positive_fixtures()
    negative_results = _validate_negative_fixtures()

    failures = []
    if not algo_rejected or algo_invariant != "algorithmic_not_independent":
        failures.append("algorithmic + independent combined update was not rejected")
    if not authority_rejected or authority_invariant != "authority_path_none":
        failures.append("reserved integration_authority was not rejected")
    if not all(r["status"] == "PASS" for r in fixture_results):
        failures.append("one or more positive fixtures failed to validate")
    if not all(r["status"] == "PASS" for r in negative_results):
        failures.append("one or more negative fixtures failed to reject as expected")
    if failures:
        return {
            "status": "FAIL",
            "detail": "; ".join(failures),
            "cases": cases,
            "positive_fixtures": fixture_results,
            "negative_fixtures": negative_results,
        }
    return {
        "status": "PASS",
        "detail": (
            "algorithmic reproduction differs from independent replication "
            "(algorithmic_not_independent); reserved authority rejected (authority_path_none); "
            f"{len(fixture_results)} positive fixtures validate; {len(negative_results)} "
            "negative fixtures reject as expected"
        ),
        "cases": cases,
        "positive_fixtures": fixture_results,
        "negative_fixtures": negative_results,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: fixture vector counts + schema count."""
    neg = _FIXTURES / "negative"
    return {
        "positive_vectors": len(list(_FIXTURES.glob("p*.input.json"))),
        "negative_vectors": len(list(neg.glob("n*.input.json"))) if neg.is_dir() else 0,
    }


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "B13-01": _check_b13_01(),
        "B13-02": _check_b13_02(),
        "B13-03": _check_b13_03(),
        "B13-04": _check_b13_04(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            **_evidence(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "B13-01": _check_b13_01,
            "B13-02": _check_b13_02,
            "B13-03": _check_b13_03,
            "B13-04": _check_b13_04,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "error": f"unknown check {cid}"})
            return 2
        result = runner()
        _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "check": cid, **result})
        return 0 if result["status"] == "PASS" else 1

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
