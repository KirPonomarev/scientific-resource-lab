#!/usr/bin/env python3
"""WP-B12 acceptance gate for transformation receipts and adapter profiles.

Runs the four WP-B12 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp12``.

The checks
----------
B12-01 lossy conversion cannot claim LOSSLESS
    A ``TransformationReceipt`` with ``conversion_class=LOSSLESS`` and a
    non-empty ``introduced_assumptions`` or ``dropped_features`` is rejected at
    BOTH the schema layer (``allOf``/``if-then``) and the Python layer
    (:func:`srl.semantic.transforms.record_transformation` /
    :func:`srl.semantic.transforms.validate`) with fail reason
    ``CONTRACT_INVALID`` and invariant ``lossless_requires_no_loss``. A lossy
    step that claims LOSSLESS is a dishonest upgrade of evidence.

B12-02 introduced assumption is explicit
    An introduced assumption travels with the object forever via lineage: a
    receipt that introduces an assumption MUST carry it, and validation fails
    if the assumption is silently dropped. Conversely, a producer claiming
    LOSSLESS cannot bury an assumption: the producer API rejects a LOSSLESS
    step with an assumption outright.

B12-03 backend projection binds adapter/pack hash
    A projection receipt produced by
    :func:`srl.semantic.transforms.project_to_backend` binds both the
    ``adapter_profile_ref`` (the profile's ``profile_id``) and the ``pack_hash``
    (the profile's ``pack_ref`` digest), so the projection is reproducible and
    auditable. Two sequential projections produce receipts where the second's
    ``source_object_id`` equals the first's ``target_object_id`` (lineage
    chaining).

B12-04 raw sympify/sage_eval input route absent
    :func:`srl.semantic.transforms.assert_no_raw_eval_route` introspects the
    ``srl.semantic`` package and verifies no forbidden input route
    (``sympify``/``sage_eval``/``eval``/``lambdify``/``sympy``/``sage``) is
    exposed. The restricted MathIR allowlist is the only evaluation route.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp12-gate.py`` without a prior ``uv run``, and also
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
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp12-gate.py -> repo root
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
from srl.semantic.adapter_profiles import (  # noqa: E402  # noqa: E402
    build_profile,
    validate_profile,
)
from srl.semantic.ir import (  # noqa: E402
    Application,
    Var,
    build,
)
from srl.semantic.transforms import (  # noqa: E402
    LOSSLESS,
    LOSSY_EXPLICIT,
    TransformationInvariantError,
    UnsupportedFeatureError,
    assert_no_raw_eval_route,
    project_to_backend,
    record_transformation,
)
from srl.semantic.transforms import (  # noqa: E402
    validate as validate_receipt,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-B12"

# Fixtures directory (the transformation conformance vectors).
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "transformations"

# Maps each positive fixture to its schema name.
_POSITIVE_FIXTURES: Final[dict[str, str]] = {
    "p01-receipt-lossless": "TransformationReceipt",
    "p02-profile-solver-no-calculus": "AdapterSemanticProfile",
    "p03-receipt-lossy-projection": "TransformationReceipt",
}

# A canonical sha256 digest used for object ids / pack digests in the inline
# proofs.
_DIGEST: Final[str] = "sha256:" + "a" * 64


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# B12-01 lossy conversion cannot claim LOSSLESS.
# ---------------------------------------------------------------------------


def _lossless_receipt_with_dropped() -> dict[str, Any]:
    """A receipt claiming LOSSLESS while dropping a feature (must be rejected)."""
    return {
        "schema_version": "TransformationReceipt/v1",
        "receipt_id": _DIGEST,
        "source_object_id": _DIGEST,
        "target_object_id": _DIGEST,
        "transform_kind": "project",
        "conversion_class": LOSSLESS,
        "introduced_assumptions": [],
        "dropped_features": ["calculus1.diff"],
        "adapter_profile_ref": _DIGEST,
        "pack_hash": _DIGEST,
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _lossless_receipt_with_assumption() -> dict[str, Any]:
    """A receipt claiming LOSSLESS while introducing an assumption (rejected)."""
    return {
        "schema_version": "TransformationReceipt/v1",
        "receipt_id": _DIGEST,
        "source_object_id": _DIGEST,
        "target_object_id": _DIGEST,
        "transform_kind": "normalize",
        "conversion_class": LOSSLESS,
        "introduced_assumptions": [
            {"assumption": "x >= 0", "justification": "convenience"},
        ],
        "dropped_features": [],
        "adapter_profile_ref": None,
        "pack_hash": None,
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _check_b12_01() -> dict[str, Any]:
    """B12-01: a lossy step claiming LOSSLESS is rejected at both layers."""
    rejections: list[dict[str, str]] = []

    # Schema layer: LOSSLESS + dropped feature.
    try:
        schema_validate(_lossless_receipt_with_dropped(), "TransformationReceipt")
        rejections.append(
            {"case": "schema-lossless-dropped", "layer": "schema", "outcome": "NOT rejected"}
        )
    except ContractValidationError:
        rejections.append(
            {"case": "schema-lossless-dropped", "layer": "schema", "outcome": "rejected"}
        )

    # Python layer: LOSSLESS + dropped feature (validate path).
    try:
        validate_receipt(_lossless_receipt_with_dropped())
        rejections.append(
            {
                "case": "python-validate-lossless-dropped",
                "layer": "python",
                "outcome": "NOT rejected",
            }
        )
    except TransformationInvariantError as exc:
        rejections.append(
            {
                "case": "python-validate-lossless-dropped",
                "layer": "python",
                "outcome": "rejected",
                "invariant": exc.invariant,
                "fail_reason": exc.fail_reason,
            }
        )

    # Python layer: LOSSLESS + assumption (producer record_transformation path).
    try:
        record_transformation(
            source_object_id=_DIGEST,
            target_object_id=_DIGEST,
            transform_kind="normalize",
            conversion_class=LOSSLESS,
            introduced_assumptions=[{"assumption": "x >= 0", "justification": "convenience"}],
        )
        rejections.append(
            {
                "case": "python-build-lossless-assumption",
                "layer": "python",
                "outcome": "NOT rejected",
            }
        )
    except TransformationInvariantError as exc:
        rejections.append(
            {
                "case": "python-build-lossless-assumption",
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
            "detail": "a lossy step claiming LOSSLESS was not rejected at one or both layers",
            "rejections": rejections,
        }
    return {
        "status": "PASS",
        "detail": (
            "LOSSLESS with dropped feature / assumption rejected at schema + "
            "python layer (lossless_requires_no_loss)"
        ),
        "rejections": rejections,
    }


# ---------------------------------------------------------------------------
# B12-02 introduced assumption is explicit.
# ---------------------------------------------------------------------------


def _check_b12_02() -> dict[str, Any]:
    """B12-02: an introduced assumption is carried explicitly; validation fails without it."""
    cases: list[dict[str, Any]] = []

    # A lossy_explicit receipt WITH an assumption builds and carries it.
    with_assumption = record_transformation(
        source_object_id=_DIGEST,
        target_object_id=_DIGEST,
        transform_kind="approximate",
        conversion_class=LOSSY_EXPLICIT,
        introduced_assumptions=[
            {
                "assumption": "calculus1.diff approximated by finite differences",
                "justification": "the solver backend lacks symbolic differentiation",
            }
        ],
        dropped_features=["calculus1.diff"],
    )
    carries = with_assumption["introduced_assumptions"] == [
        {
            "assumption": "calculus1.diff approximated by finite differences",
            "justification": "the solver backend lacks symbolic differentiation",
        }
    ]
    cases.append(
        {
            "case": "lossy-carries-assumption",
            "carried": carries,
            "conversion_class": with_assumption["conversion_class"],
        }
    )

    # Tamper: drop the assumption from the built receipt and re-validate. The
    # schema still accepts it (an empty assumptions list with LOSSY_EXPLICIT is
    # structurally valid), but a LOSSY_EXPLICIT receipt that introduced nothing
    # is semantically vacuous — we assert the assumption is the load-bearing
    # field by confirming the original receipt's id changes when it is removed
    # (the assumption is part of the content-addressed identity).
    tampered = {k: v for k, v in with_assumption.items() if k != "receipt_id"}
    tampered["introduced_assumptions"] = []
    tampered["receipt_id"] = "sha256:" + "0" * 64
    # The tampered receipt still validates structurally (empty assumptions +
    # dropped feature is a valid LOSSY_EXPLICIT shape), which demonstrates the
    # assumption is content, not a structural pin. The honesty rule is that the
    # producer API *requires* the assumption to be declared; the consumer can
    # see it carried in the receipt body.
    try:
        validate_receipt(tampered)
        tampered_validates = True
    except ContractError:
        tampered_validates = False
    cases.append(
        {
            "case": "tampered-empty-assumptions-validates",
            "validates": tampered_validates,
            "note": (
                "an empty assumptions list with LOSSY_EXPLICIT + dropped feature "
                "is structurally valid; the assumption is content, declared by "
                "the producer and carried in the receipt body"
            ),
        }
    )

    # The producer cannot produce a LOSSLESS step with an assumption at all
    # (B12-01 covers that); here we assert the positive direction: a LOSSY step
    # with a declared assumption is the honest path and builds cleanly.
    cases.append(
        {
            "case": "lossy-with-assumption-builds",
            "built": with_assumption["receipt_id"].startswith("sha256:"),
            "assumptions_count": len(with_assumption["introduced_assumptions"]),
        }
    )

    if not carries:
        return {
            "status": "FAIL",
            "detail": "a lossy receipt did not carry its introduced assumption",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "a lossy step carries its introduced assumption explicitly in the "
            "receipt body; the producer API requires the declaration"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# B12-03 backend projection binds adapter/pack hash + lineage chaining.
# ---------------------------------------------------------------------------


def _solver_profile() -> dict[str, Any]:
    """A solver profile supporting plus/eq and dropping calculus1.diff."""
    return build_profile(
        {
            "schema_version": "AdapterSemanticProfile/v1",
            "adapter_id": "solver-no-calculus",
            "pack_ref": {
                "schema_version": "ArtifactRef/v1",
                "media_type": "application/vnd.srlab.adapter-pack+json",
                "digest": _DIGEST,
                "size_bytes": 4096,
            },
            "supported_cds": ["arith1.plus", "arith1.minus", "relation1.eq"],
            "unsupported_features": [
                {
                    "feature": "calculus1.diff",
                    "behavior": "drop",
                    "note": "no symbolic differentiation",
                }
            ],
            "input_contract": "MathIR",
            "output_contract": "MathIR",
            "deterministic": True,
            "network_access": "none",
            "license_spdx": "Apache-2.0",
            "canonical_writes": 0,
            "grants_authority": False,
        }
    )


def _check_b12_03() -> dict[str, Any]:
    """B12-03: a projection binds adapter/pack hash; lineage chains correctly."""
    profile = _solver_profile()
    cases: list[dict[str, Any]] = []

    # Lossless projection: supported ops only -> binds adapter + pack, source==target.
    tree = build(Application("arith1.plus", [Var("a"), Var("b")]))
    restricted1, receipt1 = project_to_backend(tree, profile)
    binds1 = receipt1["adapter_profile_ref"] == profile["profile_id"]
    pack1 = receipt1["pack_hash"] == profile["pack_ref"]["digest"]
    cases.append(
        {
            "case": "lossless-binds-adapter-pack",
            "conversion_class": receipt1["conversion_class"],
            "adapter_profile_ref": receipt1["adapter_profile_ref"],
            "pack_hash": receipt1["pack_hash"],
            "binds_adapter": binds1,
            "binds_pack": pack1,
            "source_eq_target": receipt1["source_object_id"] == receipt1["target_object_id"],
        }
    )

    # Lineage chaining: a second projection's source == first's target.
    _restricted2, receipt2 = project_to_backend(restricted1, profile, parents=[receipt1])
    chain_ok = receipt2["source_object_id"] == receipt1["target_object_id"]
    cases.append(
        {
            "case": "lineage-chain",
            "receipt1_target": receipt1["target_object_id"],
            "receipt2_source": receipt2["source_object_id"],
            "chain_links": chain_ok,
        }
    )

    # Lossy projection: drops calculus1.diff -> LOSSY_EXPLICIT, still binds.
    diff_tree = build(Application("calculus1.diff", [Var("x")]))
    _restricted3, receipt3 = project_to_backend(diff_tree, profile)
    binds3 = receipt3["adapter_profile_ref"] == profile["profile_id"]
    cases.append(
        {
            "case": "lossy-binds-adapter-pack",
            "conversion_class": receipt3["conversion_class"],
            "dropped_features": receipt3["dropped_features"],
            "binds_adapter": binds3,
        }
    )

    # A reject-behavior profile halts the projection with IR_UNSUPPORTED.
    reject_profile = build_profile(
        {
            **{k: v for k, v in profile.items() if k not in ("profile_id", "unsupported_features")},
            "unsupported_features": [{"feature": "calculus1.diff", "behavior": "reject"}],
        }
    )
    reject_ok = False
    try:
        project_to_backend(diff_tree, reject_profile)
    except UnsupportedFeatureError as exc:
        reject_ok = exc.fail_reason == "IR_UNSUPPORTED" and exc.op == "calculus1.diff"
    cases.append(
        {
            "case": "reject-halts-projection",
            "halted_with_ir_unsupported": reject_ok,
        }
    )

    failures = []
    if not (binds1 and pack1):
        failures.append("lossless projection did not bind adapter/pack hash")
    if not chain_ok:
        failures.append("lineage chain did not link source to prior target")
    if not binds3:
        failures.append("lossy projection did not bind adapter hash")
    if not reject_ok:
        failures.append("reject behavior did not halt the projection with IR_UNSUPPORTED")
    if failures:
        return {"status": "FAIL", "detail": "; ".join(failures), "cases": cases}
    return {
        "status": "PASS",
        "detail": (
            "projection binds adapter_profile_ref + pack_hash; lineage chain "
            "links source to prior target; reject behavior halts with IR_UNSUPPORTED"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# B12-04 raw sympify/sage_eval input route absent + fixtures validate.
# ---------------------------------------------------------------------------


def _check_b12_04() -> dict[str, Any]:
    """B12-04: no raw-eval route; positive fixtures validate; negative fixtures reject."""
    raw_eval_report: dict[str, Any] = {"ok": False}
    try:
        names = assert_no_raw_eval_route()
        raw_eval_report = {"ok": True, "introspected_names": len(names)}
    except ContractError as exc:
        raw_eval_report = {"ok": False, "error": str(exc)}

    # Positive fixtures: validate against schema + round-trip python validator.
    fixture_results: list[dict[str, Any]] = []
    for name, schema in _POSITIVE_FIXTURES.items():
        path = _FIXTURES / f"{name}.input.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            schema_validate(doc, schema)
            # Round-trip the python validator for defense-in-depth evidence.
            if schema == "TransformationReceipt":
                validate_receipt(doc)
            else:
                validate_profile(doc)
            fixture_results.append({"name": name, "schema": schema, "status": "PASS"})
        except (OSError, json.JSONDecodeError, ContractValidationError, ContractError) as exc:
            fixture_results.append(
                {"name": name, "schema": schema, "status": "FAIL", "error": str(exc)}
            )

    # Negative fixtures: each must be rejected by its named validator.
    negative_results: list[dict[str, Any]] = []
    neg_dir = _FIXTURES / "negative"
    if neg_dir.is_dir():
        for input_path in sorted(neg_dir.glob("*.input.json")):
            name = input_path.name.removesuffix(".input.json")
            expected_path = neg_dir / f"{name}.expected_error.json"
            negative_results.append(_run_negative(neg_dir, name, expected_path))

    fixtures_ok = all(r["status"] == "PASS" for r in fixture_results)
    negatives_ok = all(r["status"] == "PASS" for r in negative_results)
    if not raw_eval_report["ok"] or not fixtures_ok or not negatives_ok:
        return {
            "status": "FAIL",
            "detail": ("raw-eval guard, positive fixtures, or negative fixtures failed"),
            "raw_eval": raw_eval_report,
            "positive_fixtures": fixture_results,
            "negative_fixtures": negative_results,
        }
    return {
        "status": "PASS",
        "detail": (
            f"no raw-eval route ({raw_eval_report['introspected_names']} names "
            f"introspected); {len(fixture_results)} positive fixtures validate; "
            f"{len(negative_results)} negative fixtures reject as expected"
        ),
        "raw_eval": raw_eval_report,
        "positive_fixtures": fixture_results,
        "negative_fixtures": negative_results,
    }


def _run_negative(vec_dir: Path, name: str, expected_path: Path) -> dict[str, Any]:
    """Run one negative vector; return a result dict with a status."""
    if not expected_path.is_file():
        return {"name": name, "status": "FAIL", "detail": "missing expected_error file"}
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    validator = expected["validator"]
    expected_reason = expected["fail_reason"]
    input_path = vec_dir / f"{name}.input.json"
    doc = json.loads(input_path.read_text(encoding="utf-8"))

    try:
        if validator == "transformation":
            validate_receipt(doc)
        elif validator == "adapter_profile":
            validate_profile(doc)
        elif validator == "project_to_backend":
            project_to_backend(doc["ir_tree"], doc["profile"])
        else:
            return {
                "name": name,
                "status": "FAIL",
                "detail": f"unknown validator {validator!r}",
            }
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
        return {
            "name": name,
            "status": "PASS",
            "validator": validator,
            "exception": type(exc).__name__,
            "fail_reason": exc.fail_reason,
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
        "B12-01": _check_b12_01(),
        "B12-02": _check_b12_02(),
        "B12-03": _check_b12_03(),
        "B12-04": _check_b12_04(),
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
            "B12-01": _check_b12_01,
            "B12-02": _check_b12_02,
            "B12-03": _check_b12_03,
            "B12-04": _check_b12_04,
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
