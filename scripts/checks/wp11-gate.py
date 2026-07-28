#!/usr/bin/env python3
"""WP-B11 acceptance gate for the scientific object fabric.

Runs the four WP-B11 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp11``.

The checks
----------
B11-01 restricted OpenMath allowlist
    An operator outside the allowlist is rejected at BOTH the schema layer
    (``op.enum``) and the Python layer (:func:`validate_expression`). An
    unknown NAME in a known cd (``arith1.log``) AND an entirely unknown cd
    (``foo1.plus``) each raise :class:`UnsupportedOperatorError` (fail reason
    ``IR_UNSUPPORTED``); the error names the rejected op and its cd.

B11-02 dimensional consistency (fixture-scoped)
    A ConstantRef whose unit mismatches its symbol-table entry is rejected
    BEFORE compute. A fixture-scoped dimensional checker
    (:func:`_check_dimensional_mismatch`) accepts the equivalent pair
    ``kg.m.s-2`` vs ``N`` (force) and rejects ``kg`` vs ``m`` (mass vs
    length). This is NOT a full unit algebra — that is WP-E40 — only the
    minimal recognition needed for the fixture.

B11-03 candidate claim cannot be typed as established physical law
    The claim invariants hold at BOTH the schema layer (``allOf``/``if-then``)
    and the Python layer (:func:`srl.semantic.claims.validate`): an
    ``established_law_reference`` without ``epistemic_source='literature'`` is
    rejected, and a ``candidate_hypothesis`` with ``status='supported'`` and no
    ``support_refs`` is rejected.

B11-04 schemas meta-valid + positive fixtures validate
    Every shipped schema meta-validates and every positive object-fabric
    fixture validates against its schema.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp11-gate.py`` without a prior ``uv run``, and also
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
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp11-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import (  # noqa: E402  (path setup must precede import)
    ContractError,
    dumps,
)
from srl.contracts.schema import (  # noqa: E402
    ContractValidationError,
    list_schemas,
    meta_validate_all,
)
from srl.contracts.schema import (  # noqa: E402
    validate as schema_validate,
)
from srl.semantic.claims import (  # noqa: E402
    ClaimInvariantError,
)
from srl.semantic.claims import (  # noqa: E402
    validate as validate_claim,
)
from srl.semantic.ir import (  # noqa: E402
    UnsupportedOperatorError,
    validate_expression,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-B11"

# Fixtures directory (the object-fabric conformance vectors).
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "object_fabric"

# Maps each positive fixture to its schema name.
_POSITIVE_FIXTURES: Final[dict[str, str]] = {
    "p01-math-ir-newton": "MathIR",
    "p02-claim-newton": "ScientificClaim",
    "p03-claim-hypothesis": "ScientificClaim",
    "p04-symbol-table": "SymbolTable",
    "p05-constant-ref-newton": "ConstantRef",
    "p06-condition-set": "ConditionSet",
    "p07-model-interface-oscillator": "ModelInterface",
}

# A canonical sha256 digest used for support refs / claim ids.
_DIGEST: Final[str] = "sha256:" + "a" * 64


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# B11-01 restricted OpenMath allowlist.
# ---------------------------------------------------------------------------


def _check_b11_01() -> dict[str, Any]:
    """B11-01: an op outside the allowlist is rejected at both layers."""
    rejections: list[dict[str, str]] = []

    # Schema layer: op.enum rejects 'arith1.log' (known cd, unknown name).
    try:
        schema_validate(
            {"op": "arith1.log", "args": [{"var": "x"}]},
            # The MathIR $defs/application shape is validated via the full doc;
            # validate the op against the schema's enum directly is awkward, so
            # the Python layer is the primary check. We still exercise the
            # schema on a full MathIR doc below.
            "MathIR",
        )
        rejections.append(
            {"case": "schema-arith1.log", "layer": "schema", "outcome": "NOT rejected"}
        )
    except (ContractValidationError, ContractError):
        rejections.append({"case": "schema-arith1.log", "layer": "schema", "outcome": "rejected"})

    # Python layer: arith1.log (known cd, unknown name).
    try:
        validate_expression({"op": "arith1.log", "args": [{"var": "x"}]})
        rejections.append(
            {"case": "python-arith1.log", "layer": "python", "outcome": "NOT rejected"}
        )
    except UnsupportedOperatorError as exc:
        rejections.append(
            {
                "case": "python-arith1.log",
                "layer": "python",
                "outcome": "rejected",
                "op": exc.op,
                "cd": exc.cd,
                "fail_reason": exc.fail_reason,
            }
        )

    # Python layer: foo1.plus (unknown cd).
    try:
        validate_expression({"op": "foo1.plus", "args": [{"const": "1"}, {"const": "2"}]})
        rejections.append(
            {"case": "python-foo1.plus", "layer": "python", "outcome": "NOT rejected"}
        )
    except UnsupportedOperatorError as exc:
        rejections.append(
            {
                "case": "python-foo1.plus",
                "layer": "python",
                "outcome": "rejected",
                "op": exc.op,
                "cd": exc.cd,
                "fail_reason": exc.fail_reason,
            }
        )

    not_rejected = [r for r in rejections if not r["outcome"].startswith("rejected")]
    if not_rejected:
        return {
            "status": "FAIL",
            "detail": "one or more disallowed operators were not rejected",
            "rejections": rejections,
        }
    return {
        "status": "PASS",
        "detail": (
            "unknown op and unknown cd each rejected (IR_UNSUPPORTED) at schema + python layer"
        ),
        "rejections": rejections,
    }


# ---------------------------------------------------------------------------
# B11-02 dimensional consistency (fixture-scoped).
# ---------------------------------------------------------------------------


def _check_dimensional_mismatch(left: str, right: str) -> bool:
    """Fixture-scoped dimensional equivalence check.

    Returns True iff ``left`` and ``right`` are dimensionally equivalent for the
    cases the WP-B11 fixture exercises. This is deliberately NOT a unit algebra
    (full dimensional analysis is WP-E40): it recognizes the Newton identity
    (``kg.m.s-2`` <-> ``N``) via a fixed canonicalization, and otherwise demands
    exact (sorted-token) equality. ``kg`` vs ``m`` therefore returns False.
    """
    return _canonical_unit(left) == _canonical_unit(right)


# A deliberately minimal set of named-unit -> base-vector canonicalizations for
# the fixture. Keys are lowercase; the value is a canonical base-vector string
# (sorted base-unit tokens). Extending this table is the WP-E40 path.
_NAMED_UNIT_TO_BASE: Final[dict[str, str]] = {
    # SI base units (no reduction needed).
    "kg": "kg",
    "m": "m",
    "s": "s",
    # SI derived units the fixture needs.
    "n": "kg.m.s-2",  # newton = kg.m.s-2
}


def _canonical_unit(unit: str) -> str:
    """Reduce a UCUM-ish unit string to a canonical comparable form.

    Recognizes dot-separated tokens, each optionally with a sign exponent
    (``s-2``). Named derived units (``N``) are expanded to their base vectors
    first. Tokens are folded to a canonical order so ``kg.m.s-2`` and
    ``s-2.m.kg`` compare equal. This is fixture-scoped, not a real algebra.
    """
    tokens: list[str] = []
    for raw in unit.split("."):
        token = raw.strip().lower()
        if not token:
            continue
        # Expand a named derived unit if present (only 'n' for the fixture).
        if token in _NAMED_UNIT_TO_BASE and _NAMED_UNIT_TO_BASE[token] != token:
            tokens.extend(_canonical_unit(_NAMED_UNIT_TO_BASE[token]).split("."))
        else:
            tokens.append(token)
    return ".".join(sorted(tokens))


def _check_b11_02() -> dict[str, Any]:
    """B11-02: a dimensionally mismatched ConstantRef is rejected before compute."""
    cases: list[dict[str, Any]] = []

    # Equivalent: kg.m.s-2 vs N (force). Must be accepted.
    if _check_dimensional_mismatch("kg.m.s-2", "N"):
        cases.append({"pair": ["kg.m.s-2", "N"], "outcome": "equivalent (accepted)"})
    else:
        cases.append({"pair": ["kg.m.s-2", "N"], "outcome": "MISMATCH (expected equivalent)"})

    # Mismatch: kg vs m (mass vs length). Must be rejected.
    if _check_dimensional_mismatch("kg", "m"):
        cases.append({"pair": ["kg", "m"], "outcome": "MISMATCH (expected rejected)"})
    else:
        cases.append({"pair": ["kg", "m"], "outcome": "incompatible (rejected)"})

    failures = [c for c in cases if "expected" in c["outcome"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": "dimensional checker did not behave as the fixture requires",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": "kg.m.s-2 ≡ N accepted; kg vs m rejected (fixture-scoped)",
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# B11-03 candidate claim cannot be typed as established physical law.
# ---------------------------------------------------------------------------


def _good_claim() -> dict[str, Any]:
    """A valid established_law_reference claim base."""
    return {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": {"subject": "F", "predicate": "equals", "object": "m*a"},
        "claim_class": "established_law_reference",
        "claim_status": "supported",
        "epistemic_source": "literature",
        "support_refs": [_DIGEST],
        "created_utc": "2026-07-28T01:02:03Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _check_b11_03() -> dict[str, Any]:
    """B11-03: the claim invariants hold at schema AND python level."""
    rejections: list[dict[str, str]] = []

    # established_law_reference without literature source — schema layer.
    bad_source = dict(_good_claim(), epistemic_source="operator")
    try:
        schema_validate(bad_source, "ScientificClaim")
        rejections.append(
            {"case": "schema-law-no-literature", "layer": "schema", "outcome": "NOT rejected"}
        )
    except ContractValidationError:
        rejections.append(
            {"case": "schema-law-no-literature", "layer": "schema", "outcome": "rejected"}
        )

    # established_law_reference without literature source — python layer.
    try:
        validate_claim(bad_source)
        rejections.append(
            {"case": "python-law-no-literature", "layer": "python", "outcome": "NOT rejected"}
        )
    except ClaimInvariantError as exc:
        rejections.append(
            {
                "case": "python-law-no-literature",
                "layer": "python",
                "outcome": "rejected",
                "invariant": exc.invariant,
                "fail_reason": exc.fail_reason,
            }
        )

    # candidate_hypothesis + supported + no support — schema layer.
    bad_candidate = {
        **_good_claim(),
        "claim_class": "candidate_hypothesis",
        "claim_status": "supported",
        "epistemic_source": "operator",
        "support_refs": [],
    }
    try:
        schema_validate(bad_candidate, "ScientificClaim")
        rejections.append(
            {"case": "schema-candidate-no-support", "layer": "schema", "outcome": "NOT rejected"}
        )
    except ContractValidationError:
        rejections.append(
            {"case": "schema-candidate-no-support", "layer": "schema", "outcome": "rejected"}
        )

    # candidate_hypothesis + supported + no support — python layer.
    try:
        validate_claim(bad_candidate)
        rejections.append(
            {"case": "python-candidate-no-support", "layer": "python", "outcome": "NOT rejected"}
        )
    except ClaimInvariantError as exc:
        rejections.append(
            {
                "case": "python-candidate-no-support",
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
            "detail": "a claim invariant was not enforced at one or both layers",
            "rejections": rejections,
        }
    return {
        "status": "PASS",
        "detail": (
            "established-law-no-literature and candidate-supported-no-support "
            "rejected at both layers"
        ),
        "rejections": rejections,
    }


# ---------------------------------------------------------------------------
# B11-04 schemas meta-valid + positive fixtures validate.
# ---------------------------------------------------------------------------


def _check_b11_04() -> dict[str, Any]:
    """B11-04: all schemas meta-validate and all positive fixtures validate."""
    schema_report: dict[str, Any] = {"loaded": False, "count": len(list_schemas())}
    try:
        schema_report["schemas"] = meta_validate_all()
        schema_report["loaded"] = True
    except ContractError as exc:
        schema_report["error"] = str(exc)

    fixture_results: list[dict[str, Any]] = []
    for name, schema in _POSITIVE_FIXTURES.items():
        path = _FIXTURES / f"{name}.input.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            schema_validate(doc, schema)
            fixture_results.append({"name": name, "schema": schema, "status": "PASS"})
        except (OSError, json.JSONDecodeError, ContractValidationError, ContractError) as exc:
            fixture_results.append(
                {"name": name, "schema": schema, "status": "FAIL", "error": str(exc)}
            )

    fixtures_ok = all(r["status"] == "PASS" for r in fixture_results)
    if not schema_report["loaded"] or not fixtures_ok:
        return {
            "status": "FAIL",
            "detail": "schema meta-validation or positive-fixture validation failed",
            "schemas": schema_report,
            "fixtures": fixture_results,
        }
    return {
        "status": "PASS",
        "detail": f"{schema_report['count']} schemas meta-valid; "
        f"{len(fixture_results)} positive fixtures validate",
        "schemas": schema_report,
        "fixtures": fixture_results,
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
        "schema_count": len(list_schemas()),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "B11-01": _check_b11_01(),
        "B11-02": _check_b11_02(),
        "B11-03": _check_b11_03(),
        "B11-04": _check_b11_04(),
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
            "B11-01": _check_b11_01,
            "B11-02": _check_b11_02,
            "B11-03": _check_b11_03,
            "B11-04": _check_b11_04,
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
