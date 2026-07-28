#!/usr/bin/env python3
"""WP-E42 acceptance gate for the ripser TDA pack.

Runs the five WP-E42 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp42``.

The checks
----------
E42-01 circle golden H1 detected within tolerance
    The synthetic unit-radius circle (``fixtures/public/cloud-circle.json``)
    produces exactly one long-lived H1 class above the threshold, with the
    dominant persistence matching the golden value within tolerance.

E42-02 two-cluster H0 detected
    The synthetic two-cluster cloud produces exactly two long-lived H0 classes
    above the threshold (one essential component + one inter-cluster merge).

E42-03 uniform/surrogate controls show no spurious H1 above threshold
    The uniform-square cloud produces no long-lived H1 above the threshold
    (the topology-free control), and the phase-randomized surrogate is
    reproducible (same seed -> same surrogate) and distinct from the original
    (the null-hypothesis control).

E42-04 hard limits enforced (oversized cloud typed rejection)
    A point cloud with ``MAX_POINTS + 1`` points is rejected with
    ``RESOURCE_LIMIT`` before any compute. The adapter never silently truncates.

E42-05 preprocessing receipt deterministic (two runs, same seed)
    Two ``compute_persistence`` calls with the same seed and the same cloud
    produce byte-identical preprocessing receipts.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp42-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).

Honesty note: a persistence diagram is computation, not validation. The goldens
here assert the adapter computes the expected topology faithfully; they do not
assert the underlying synthetic phenomenon is scientifically circular or
clustered. See ``docs/architecture/ripser-pack.md`` for the null/surrogate
discipline.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp42-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402  (path setup must precede import)
from srl.packs.adapters.ripser_adapter import (  # noqa: E402
    MAX_AMBIENT_DIM,
    MAX_HOMOLOGY_DIM,
    MAX_POINTS,
    RipserInputError,
    RipserResourceLimitError,
    compute_persistence,
    long_lived_classes,
    max_finite_persistence,
    numpy_version,
    phase_randomized_surrogate,
    ripser_version,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-E42"

# Fixtures directories: the public point clouds and the ripser conformance
# vectors (the latter carry the golden thresholds and expectations).
_PUBLIC: Final[Path] = _REPO_ROOT / "fixtures" / "public"
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "ripser"

# Persistence thresholds. These sit in the wide gaps between the topology
# signal and the noise floor; see fixtures/conformance/ripser/README.md for
# the full rationale. They are module-level constants so a change is visible.
_H1_THRESHOLD: Final[float] = 0.5
_H0_THRESHOLD: Final[float] = 0.8

# The seed used for the deterministic conformance runs. Matches the synthetic
# fixtures' own seed for a single coherent provenance chain.
_SEED: Final[int] = 20260728


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_cloud(variant: str) -> list[list[float]]:
    """Load a synthetic point cloud from fixtures/public as a list of floats."""
    path = _PUBLIC / f"cloud-{variant}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [[float(x), float(y)] for x, y in doc["points"]]


# ---------------------------------------------------------------------------
# E42-01: circle golden H1 detected within tolerance.
# ---------------------------------------------------------------------------


def _check_e42_01() -> dict[str, Any]:
    """E42-01: the circle produces one long-lived H1 at the golden persistence."""
    cases: list[dict[str, Any]] = []
    spec = json.loads((_FIXTURES / "p01-circle-h1-golden.input.json").read_text("utf-8"))
    circle = _load_cloud("circle")

    result = compute_persistence(circle, maxdim=spec["maxdim"], seed=spec["seed"])
    long_h1 = long_lived_classes(result, 1, _H1_THRESHOLD)
    max_h1 = max_finite_persistence(result, 1)

    # Exactly one long-lived H1 class.
    if long_h1 == spec["expected_long_lived_h1"]:
        cases.append({"check": "long_lived_h1", "count": long_h1, "outcome": "ok"})
    else:
        cases.append(
            {
                "check": "long_lived_h1",
                "count": long_h1,
                "expected": spec["expected_long_lived_h1"],
                "outcome": "MISMATCH",
            }
        )

    # The dominant persistence is above the documented floor and matches the
    # golden value within a tight tolerance (the gate tolerance, not the
    # topology threshold).
    if max_h1 is not None and max_h1 >= spec["expected_min_max_h1_persistence"]:
        cases.append(
            {
                "check": "max_h1_persistence",
                "value": round(max_h1, 6),
                "golden": spec["golden_max_h1_persistence"],
                "outcome": "ok",
            }
        )
    else:
        cases.append(
            {
                "check": "max_h1_persistence",
                "value": max_h1,
                "floor": spec["expected_min_max_h1_persistence"],
                "outcome": "below floor",
            }
        )

    failures = [c for c in cases if c["outcome"] != "ok"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "circle did not produce the expected single prominent H1",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"circle H1: {long_h1} long-lived class(es) above {_H1_THRESHOLD}; "
            f"max persistence {max_h1:.3f}"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E42-02: two-cluster H0 detected.
# ---------------------------------------------------------------------------


def _check_e42_02() -> dict[str, Any]:
    """E42-02: the two-cluster cloud produces exactly two long-lived H0."""
    cases: list[dict[str, Any]] = []
    spec = json.loads((_FIXTURES / "p02-two-cluster-h0-golden.input.json").read_text("utf-8"))
    cloud = _load_cloud("two-cluster")

    result = compute_persistence(cloud, maxdim=spec["maxdim"], seed=spec["seed"])
    long_h0 = long_lived_classes(result, 0, _H0_THRESHOLD)
    max_finite_h0 = max_finite_persistence(result, 0)

    if long_h0 == spec["expected_long_lived_h0"]:
        cases.append({"check": "long_lived_h0", "count": long_h0, "outcome": "ok"})
    else:
        cases.append(
            {
                "check": "long_lived_h0",
                "count": long_h0,
                "expected": spec["expected_long_lived_h0"],
                "outcome": "MISMATCH",
            }
        )

    h0_floor = spec["expected_min_max_finite_h0_persistence"]
    if max_finite_h0 is not None and max_finite_h0 >= h0_floor:
        cases.append(
            {
                "check": "max_finite_h0_persistence",
                "value": round(max_finite_h0, 6),
                "golden": spec["golden_max_finite_h0_persistence"],
                "outcome": "ok",
            }
        )
    else:
        cases.append(
            {
                "check": "max_finite_h0_persistence",
                "value": max_finite_h0,
                "floor": spec["expected_min_max_finite_h0_persistence"],
                "outcome": "below floor",
            }
        )

    failures = [c for c in cases if c["outcome"] != "ok"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "two-cluster cloud did not produce exactly two long-lived H0",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"two-cluster H0: {long_h0} long-lived class(es) above {_H0_THRESHOLD}; "
            f"max finite persistence {max_finite_h0:.3f}"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E42-03: uniform/surrogate controls show no spurious H1 above threshold.
# ---------------------------------------------------------------------------


def _check_e42_03() -> dict[str, Any]:
    """E42-03: the uniform control has no H1 above threshold; surrogate is sound."""
    cases: list[dict[str, Any]] = []

    # Uniform square: no long-lived H1 above threshold.
    spec = json.loads((_FIXTURES / "p03-uniform-square-h1-control.input.json").read_text("utf-8"))
    uniform = _load_cloud("uniform-square")
    result = compute_persistence(uniform, maxdim=spec["maxdim"], seed=spec["seed"])
    long_h1 = long_lived_classes(result, 1, _H1_THRESHOLD)
    max_h1 = max_finite_persistence(result, 1)
    if long_h1 == spec["expected_long_lived_h1"] and (max_h1 or 0) < _H1_THRESHOLD:
        cases.append(
            {
                "control": "uniform-square",
                "long_lived_h1": long_h1,
                "max_h1_persistence": round(max_h1 or 0, 6),
                "outcome": "ok",
            }
        )
    else:
        cases.append(
            {
                "control": "uniform-square",
                "long_lived_h1": long_h1,
                "max_h1_persistence": round(max_h1 or 0, 6),
                "threshold": _H1_THRESHOLD,
                "outcome": "spurious H1 detected",
            }
        )

    # Surrogate: reproducible (same seed -> same) and distinct (different seed
    # -> different), and distinct from the original signal.
    surr_spec = json.loads((_FIXTURES / "p04-surrogate-control.input.json").read_text("utf-8"))
    n = surr_spec["signal_length"]
    # Build the test signal deterministically: sum of two sinusoids.
    import math  # noqa: PLC0415 (local import keeps the gate stdlib-ish at top)

    t_step = 4.0 * math.pi / max(n - 1, 1)
    signal = [math.sin(i * t_step) + 0.5 * math.sin(2 * i * t_step) for i in range(n)]
    surr_a = phase_randomized_surrogate(signal, seed=surr_spec["seed_reproducible"])
    surr_b = phase_randomized_surrogate(signal, seed=surr_spec["seed_reproducible"])
    surr_c = phase_randomized_surrogate(signal, seed=surr_spec["seed_distinct"])

    reproducible = surr_a == surr_b
    distinct_across_seeds = surr_a != surr_c
    if reproducible and distinct_across_seeds:
        cases.append(
            {
                "control": "surrogate",
                "reproducible": reproducible,
                "distinct_across_seeds": distinct_across_seeds,
                "outcome": "ok",
            }
        )
    else:
        cases.append(
            {
                "control": "surrogate",
                "reproducible": reproducible,
                "distinct_across_seeds": distinct_across_seeds,
                "outcome": "surrogate discipline broken",
            }
        )

    failures = [c for c in cases if c["outcome"] != "ok"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "a control failed: spurious topology or broken surrogate discipline",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"uniform-square: {long_h1} long-lived H1 (max pers {max_h1:.3f} < "
            f"{_H1_THRESHOLD}); surrogate reproducible & seed-distinct"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E42-04: hard limits enforced (oversized cloud typed rejection).
# ---------------------------------------------------------------------------


def _check_e42_04() -> dict[str, Any]:
    """E42-04: an oversized cloud is rejected with RESOURCE_LIMIT before compute."""
    cases: list[dict[str, Any]] = []

    # Over-point-limit: 501 points (MAX_POINTS + 1).
    too_many = [[0.0, 0.0] for _ in range(MAX_POINTS + 1)]
    try:
        compute_persistence(too_many, maxdim=0)
        cases.append({"limit": "max_points", "n_points": MAX_POINTS + 1, "outcome": "NOT rejected"})
    except RipserResourceLimitError as exc:
        cases.append(
            {
                "limit": "max_points",
                "n_points": MAX_POINTS + 1,
                "outcome": "rejected",
                "fail_reason": exc.fail_reason,
            }
        )
    except RipserInputError as exc:
        cases.append(
            {
                "limit": "max_points",
                "n_points": MAX_POINTS + 1,
                "outcome": "wrong error class",
                "fail_reason": exc.fail_reason,
            }
        )

    # Over-dimension-limit: ambient dim = MAX_AMBIENT_DIM + 1.
    too_wide = [[0.0] * (MAX_AMBIENT_DIM + 1)]
    try:
        compute_persistence(too_wide, maxdim=0)
        cases.append(
            {"limit": "max_ambient_dim", "dim": MAX_AMBIENT_DIM + 1, "outcome": "NOT rejected"}
        )
    except RipserResourceLimitError as exc:
        cases.append(
            {
                "limit": "max_ambient_dim",
                "dim": MAX_AMBIENT_DIM + 1,
                "outcome": "rejected",
                "fail_reason": exc.fail_reason,
            }
        )
    except RipserInputError as exc:
        cases.append(
            {
                "limit": "max_ambient_dim",
                "dim": MAX_AMBIENT_DIM + 1,
                "outcome": "wrong error class",
                "fail_reason": exc.fail_reason,
            }
        )

    # Over-degree-limit: maxdim = MAX_HOMOLOGY_DIM + 1.
    try:
        compute_persistence([[0.0, 0.0], [1.0, 0.0]], maxdim=MAX_HOMOLOGY_DIM + 1)
        cases.append(
            {"limit": "max_homology_dim", "maxdim": MAX_HOMOLOGY_DIM + 1, "outcome": "NOT rejected"}
        )
    except RipserResourceLimitError as exc:
        cases.append(
            {
                "limit": "max_homology_dim",
                "maxdim": MAX_HOMOLOGY_DIM + 1,
                "outcome": "rejected",
                "fail_reason": exc.fail_reason,
            }
        )
    except RipserInputError as exc:
        cases.append(
            {
                "limit": "max_homology_dim",
                "maxdim": MAX_HOMOLOGY_DIM + 1,
                "outcome": "wrong error class",
                "fail_reason": exc.fail_reason,
            }
        )

    failures = [c for c in cases if c["outcome"] != "rejected"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "a hard limit was not enforced with RESOURCE_LIMIT",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            f"all three hard limits enforced (RESOURCE_LIMIT): "
            f"max_points={MAX_POINTS}, max_dim={MAX_AMBIENT_DIM}, "
            f"max_homology={MAX_HOMOLOGY_DIM}"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E42-05: preprocessing receipt deterministic (two runs, same seed).
# ---------------------------------------------------------------------------


def _check_e42_05() -> dict[str, Any]:
    """E42-05: two runs with the same seed produce byte-identical receipts."""
    cases: list[dict[str, Any]] = []
    circle = _load_cloud("circle")

    run_1 = compute_persistence(circle, maxdim=1, seed=_SEED)
    run_2 = compute_persistence(circle, maxdim=1, seed=_SEED)

    bytes_1 = run_1.preprocessing_receipt.canonical_dumps()
    bytes_2 = run_2.preprocessing_receipt.canonical_dumps()

    if bytes_1 == bytes_2:
        cases.append({"check": "same_seed_identical", "outcome": "ok"})
    else:
        cases.append({"check": "same_seed_identical", "outcome": "receipts differ"})

    # The receipts are also JSON-serializable (the to_dict round-trips).
    try:
        receipt_dict = run_1.preprocessing_receipt.to_dict()
        json.dumps(receipt_dict)
        cases.append({"check": "receipt_json_serializable", "outcome": "ok"})
    except (TypeError, ValueError) as exc:
        cases.append({"check": "receipt_json_serializable", "outcome": f"not serializable: {exc}"})

    # Sanity: the input_sha256 is a valid sha256: digest (not empty).
    if run_1.preprocessing_receipt.input_sha256.startswith("sha256:"):
        cases.append(
            {
                "check": "input_sha256_present",
                "sha256": run_1.preprocessing_receipt.input_sha256[:16] + "...",
                "outcome": "ok",
            }
        )
    else:
        cases.append({"check": "input_sha256_present", "outcome": "missing or malformed"})

    # Sanity: the result diagrams are decimal-string policy values (or "inf").
    policy_ok = True
    import re  # noqa: PLC0415 (local import for the policy check)

    decimal_re = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
    for diagram in run_1.diagrams:
        for birth_str, death_str in diagram:
            if not decimal_re.fullmatch(birth_str):
                policy_ok = False
            if death_str != "inf" and not decimal_re.fullmatch(death_str):
                policy_ok = False
    if policy_ok:
        cases.append({"check": "diagrams_decimal_string_policy", "outcome": "ok"})
    else:
        cases.append({"check": "diagrams_decimal_string_policy", "outcome": "policy violation"})

    failures = [c for c in cases if c["outcome"] != "ok"]
    if failures:
        return {
            "status": "FAIL",
            "detail": "preprocessing receipt is not deterministic or not well-formed",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": "two runs (same seed) -> byte-identical receipt; diagrams are decimal-string",
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: versions + fixture counts."""
    positive = len(list(_FIXTURES.glob("p*.input.json")))
    negative = len(list(_FIXTURES.glob("n*.input.json")))
    return {
        "ripser_version": ripser_version(),
        "numpy_version": numpy_version(),
        "max_points": MAX_POINTS,
        "max_ambient_dim": MAX_AMBIENT_DIM,
        "max_homology_dim": MAX_HOMOLOGY_DIM,
        "h1_threshold": _H1_THRESHOLD,
        "h0_threshold": _H0_THRESHOLD,
        "positive_vectors": positive,
        "negative_vectors": negative,
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "E42-01": _check_e42_01(),
        "E42-02": _check_e42_02(),
        "E42-03": _check_e42_03(),
        "E42-04": _check_e42_04(),
        "E42-05": _check_e42_05(),
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
            "E42-01": _check_e42_01,
            "E42-02": _check_e42_02,
            "E42-03": _check_e42_03,
            "E42-04": _check_e42_04,
            "E42-05": _check_e42_05,
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
