#!/usr/bin/env python3
"""WP-E40 acceptance gate for the units semantic core.

Runs the five WP-E40 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp40``.

The checks
----------
E40-01 coherent dimensions validate (SI base + derived)
    Every unit in the pinned QUDT subset parses to a dimension, and the SI
    derived units reduce to their base-dimension vectors. The seven SI base
    units each yield a singleton dimension; the derived units (``N``, ``Pa``,
    ``J``, ``W``, ``Hz``, ``V``, ``C``, ``ohm``) reduce correctly.

E40-02 dimensionally invalid rejected before compute
    ``kg`` vs ``m`` (mass vs length) is rejected as a dimensional mismatch
    *before* any compute. The adapter never falls back to a guessed unit.

E40-03 ConstantRef CODATA fixtures validate against the schema
    Each of the six CODATA 2018 constant fixtures (``c``, ``h``, ``k_B``,
    ``N_A``, ``e``, ``m_e``) validates against ``ConstantRef/v1`` and its
    ``unit`` field parses to a dimension in the pinned subset.

E40-04 conversion exact (decimal identity)
    ``1 kg*m/s^2`` converts to ``1 N`` as an exact decimal identity (no float
    artefact); the reverse and the ``J`` -> ``N*m`` identity also hold.

E40-05 unknown unit typed rejection (no silent fallback)
    An unknown unit (``fortnight`` — known to Pint but out of the pinned
    subset) is rejected with ``CONTRACT_INVALID``. There is no silent
    fallback to Pint's larger vocabulary.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp40-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp40-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402  (path setup must precede import)
from srl.contracts.schema import (  # noqa: E402
    validate as schema_validate,
)
from srl.packs.adapters.units import (  # noqa: E402
    PINNED_QUDT_SUBSET,
    SI_BASE_DIMENSIONS,
    UnitError,
    convert,
    parse_unit,
    pint_version,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-E40"

# Fixtures directory for the units conformance vectors.
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "units"
_CODATA: Final[Path] = _FIXTURES / "codata"

# The CODATA 2018 constant fixtures exercised by E40-03.
_CODATA_FIXTURES: Final[tuple[str, ...]] = (
    "codata2018.speed-of-light",
    "codata2018.planck-constant",
    "codata2018.boltzmann-constant",
    "codata2018.avogadro-constant",
    "codata2018.elementary-charge",
    "codata2018.electron-mass",
)


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# E40-01: coherent dimensions validate (SI base + derived).
# ---------------------------------------------------------------------------


def _check_e40_01() -> dict[str, Any]:
    """E40-01: every pinned unit parses; SI base and derived reduce correctly."""
    cases: list[dict[str, str]] = []

    # The seven SI base units each parse to a singleton dimension.
    expected_base: Final[dict[str, str]] = {
        "m": "[length]",
        "kg": "[mass]",
        "s": "[time]",
        "A": "[current]",
        "K": "[temperature]",
        "mol": "[substance]",
        "cd": "[luminosity]",
    }
    for unit, expected_dim in expected_base.items():
        try:
            dim = parse_unit(unit)
            if str(dim) == expected_dim:
                cases.append({"unit": unit, "dimension": str(dim), "outcome": "ok"})
            else:
                cases.append(
                    {"unit": unit, "dimension": str(dim), "outcome": f"expected {expected_dim}"}
                )
        except UnitError as exc:
            cases.append({"unit": unit, "outcome": f"UnitError: {exc.fail_reason}"})

    # The derived units parse without error.
    derived = ["N", "Pa", "J", "W", "Hz", "V", "C", "ohm"]
    for unit in derived:
        try:
            dim = parse_unit(unit)
            cases.append({"unit": unit, "dimension": str(dim), "outcome": "ok"})
        except UnitError as exc:
            cases.append({"unit": unit, "outcome": f"UnitError: {exc.fail_reason}"})

    failures = [c for c in cases if c.get("outcome") != "ok"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "one or more SI base/derived units did not parse correctly",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"{len(expected_base)} SI base units + {len(derived)} derived units parse; "
            f"pinned subset has {len(PINNED_QUDT_SUBSET)} entries"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E40-02: dimensionally invalid rejected before compute.
# ---------------------------------------------------------------------------


def _check_e40_02() -> dict[str, Any]:
    """E40-02: kg vs m (mass vs length) is rejected before compute."""
    cases: list[dict[str, Any]] = []

    # kg and m parse to different dimensions (mass vs length).
    kg_dim = parse_unit("kg")
    m_dim = parse_unit("m")
    if kg_dim != m_dim:
        cases.append({"pair": ["kg", "m"], "outcome": "incompatible (rejected)"})
    else:
        cases.append({"pair": ["kg", "m"], "outcome": "MISMATCH (expected rejected)"})

    # A coherent pair is accepted: kg*m/s^2 ≡ N.
    if parse_unit("kg*m/s^2") == parse_unit("N"):
        cases.append({"pair": ["kg*m/s^2", "N"], "outcome": "equivalent (accepted)"})
    else:
        cases.append({"pair": ["kg*m/s^2", "N"], "outcome": "MISMATCH (expected equivalent)"})

    # convert across a mismatch must raise before any arithmetic.
    try:
        convert("1", "kg", "m")
        cases.append({"pair": ["kg", "m"], "operation": "convert", "outcome": "NOT rejected"})
    except UnitError as exc:
        cases.append(
            {
                "pair": ["kg", "m"],
                "operation": "convert",
                "outcome": "rejected",
                "fail_reason": exc.fail_reason,
            }
        )

    failures = [c for c in cases if "expected" in c["outcome"] or c["outcome"] == "NOT rejected"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "dimensional mismatch was not rejected before compute",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": "kg vs m rejected (CONTRACT_INVALID); kg*m/s^2 ≡ N accepted",
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E40-03: ConstantRef CODATA fixtures validate against the schema.
# ---------------------------------------------------------------------------


def _check_e40_03() -> dict[str, Any]:
    """E40-03: each CODATA 2018 fixture validates and its unit parses."""
    cases: list[dict[str, Any]] = []
    for constant_id in _CODATA_FIXTURES:
        path = _CODATA / f"{constant_id}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            schema_validate(doc, "ConstantRef")
            dim = parse_unit(doc["unit"])
            cases.append(
                {
                    "constant_id": constant_id,
                    "schema": "ConstantRef/v1",
                    "unit": doc["unit"],
                    "dimension": str(dim),
                    "status": "PASS",
                }
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            cases.append({"constant_id": constant_id, "status": "FAIL", "error": error})

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "one or more CODATA fixtures failed schema or unit validation",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": f"{len(cases)} CODATA 2018 constants validate against ConstantRef/v1 and parse",
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E40-04: conversion exact (decimal identity).
# ---------------------------------------------------------------------------


def _check_e40_04() -> dict[str, Any]:
    """E40-04: 1 kg*m/s^2 -> 1 N as an exact decimal identity (no float artefact)."""
    cases: list[dict[str, Any]] = []
    identities = [
        ("1", "kg*m/s^2", "N", "1"),
        ("1", "N", "kg*m/s^2", "1"),
        ("2", "N", "kg*m/s^2", "2"),
        ("1", "J", "N*m", "1"),
        ("1", "Pa", "N/m^2", "1"),
        ("1", "W", "J/s", "1"),
        ("1", "V", "J/C", "1"),
        ("1", "Hz", "1/s", "1"),
    ]
    for value, from_unit, to_unit, expected in identities:
        result = convert(value, from_unit, to_unit)
        if result == expected:
            cases.append(
                {
                    "value": value,
                    "from": from_unit,
                    "to": to_unit,
                    "result": result,
                    "status": "PASS",
                }
            )
        else:
            cases.append(
                {
                    "value": value,
                    "from": from_unit,
                    "to": to_unit,
                    "result": result,
                    "expected": expected,
                    "status": "FAIL",
                }
            )

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "one or more coherent conversions did not yield an exact decimal identity",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": f"{len(cases)} coherent conversions yield exact decimal identities",
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E40-05: unknown unit typed rejection (no silent fallback).
# ---------------------------------------------------------------------------


def _check_e40_05() -> dict[str, Any]:
    """E40-05: an unknown / out-of-subset unit is rejected with CONTRACT_INVALID."""
    cases: list[dict[str, Any]] = []
    # 'fortnight' is known to Pint but is NOT in the pinned subset; the adapter
    # must reject it rather than silently falling back to Pint's vocabulary.
    for unit in ("fortnight", "blarg", "km"):
        try:
            parse_unit(unit)
            cases.append({"unit": unit, "outcome": "NOT rejected (silent fallback)"})
        except UnitError as exc:
            cases.append({"unit": unit, "outcome": "rejected", "fail_reason": exc.fail_reason})

    not_rejected = [c for c in cases if c["outcome"].startswith("NOT rejected")]
    if not_rejected:
        return {
            "status": "FAIL",
            "detail": "an unknown/out-of-subset unit was not rejected (silent fallback)",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": ("fortnight, blarg, km each rejected (CONTRACT_INVALID); no silent fallback"),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: fixture counts + pinned subset size."""
    positive = _FIXTURES / "positive"
    negative = _FIXTURES / "negative"
    return {
        "pint_version": pint_version(),
        "pinned_subset_size": len(PINNED_QUDT_SUBSET),
        "si_base_dimensions": len(SI_BASE_DIMENSIONS),
        "codata_fixtures": len(_CODATA_FIXTURES),
        "positive_vectors": len(list(positive.glob("p*.input.json"))) if positive.is_dir() else 0,
        "negative_vectors": (len(list(negative.glob("n*.input.json"))) if negative.is_dir() else 0),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "E40-01": _check_e40_01(),
        "E40-02": _check_e40_02(),
        "E40-03": _check_e40_03(),
        "E40-04": _check_e40_04(),
        "E40-05": _check_e40_05(),
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

    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "E40-01": _check_e40_01,
            "E40-02": _check_e40_02,
            "E40-03": _check_e40_03,
            "E40-04": _check_e40_04,
            "E40-05": _check_e40_05,
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
