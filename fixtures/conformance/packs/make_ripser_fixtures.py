#!/usr/bin/env python3
"""Generate the WP-E42 ripser conformance fixtures (golden + control vectors).

Produces canonical JSON fixtures under ``fixtures/conformance/ripser/`` that
encode the topology of the three synthetic point clouds in ``fixtures/public/``:

- ``p01-circle-h1-golden``: the circle has one long-lived H1 class.
- ``p02-two-cluster-h0-golden``: the two-cluster cloud has exactly two
  long-lived H0 classes (one essential + one inter-cluster merge).
- ``p03-uniform-square-h1-control``: the uniform square has no H1 above the
  threshold (the null/topology-free control).
- ``p04-surrogate-control``: a phase-randomized surrogate of a 1-D signal is
  reproducible and distinct from the original (the null-hypothesis control).
- ``n01-oversized-cloud``: a cloud above MAX_POINTS is rejected with
  RESOURCE_LIMIT before compute (the hard-limit negative).

The golden values (max persistence, long-lived counts, thresholds) are computed
from the actual ripser output on the fixtures so the gate asserts against real
topology, not hand-waved numbers. The fixtures are written as canonical JSON
(sorted keys, compact, trailing newline) to match the rest of the tree.

This script is run once to author the fixtures; the gate re-derives the
topology at check time and compares to the thresholds recorded here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# fixtures/conformance/packs/make_ripser_fixtures.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

from srl.contracts.canonical import dumps  # noqa: E402
from srl.packs.adapters.ripser_adapter import (  # noqa: E402
    MAX_POINTS,
    compute_persistence,
    long_lived_classes,
    max_finite_persistence,
    phase_randomized_surrogate,
)

_PUBLIC = _REPO_ROOT / "fixtures" / "public"
_OUT = _REPO_ROOT / "fixtures" / "conformance" / "ripser"

# The persistence threshold that separates topological signal from noise. The
# circle's dominant H1 has persistence ~1.24; the uniform square's max H1 is
# ~0.28. A threshold of 0.5 cleanly separates them with a wide margin.
H1_THRESHOLD = 0.5

# The H0 threshold for the two-cluster golden: the inter-cluster merge has
# persistence ~1.16; the next-largest H0 is ~0.29. A threshold of 0.8
# isolates the two clusters (1 essential + 1 inter-cluster = 2 long-lived H0).
H0_THRESHOLD = 0.8


def _load_cloud(variant: str) -> list[list[float]]:
    """Load a synthetic point cloud from fixtures/public as a list of floats."""
    path = _PUBLIC / f"cloud-{variant}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [[float(x), float(y)] for x, y in doc["points"]]


def _write(path: Path, obj: object) -> None:
    """Write canonical JSON (sorted keys, compact, trailing newline)."""
    path.write_bytes(dumps(obj))


def _require(condition: bool, message: str) -> None:
    """Raise ``RuntimeError`` if ``condition`` is false (assert-free check)."""
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    cases: list[str] = []

    # Named counts so the comparisons are self-documenting (no magic values).
    one_long_lived = 1
    two_long_lived = 2
    zero_long_lived = 0

    # --- p01: circle H1 golden -------------------------------------------------
    circle = _load_cloud("circle")
    res_circle = compute_persistence(circle, maxdim=1, seed=20260728)
    circle_max_h1 = max_finite_persistence(res_circle, 1)
    circle_long_h1 = long_lived_classes(res_circle, 1, H1_THRESHOLD)
    _require(
        circle_max_h1 is not None and circle_max_h1 > H1_THRESHOLD,
        "circle H1 too weak",
    )
    _require(
        circle_long_h1 == one_long_lived,
        f"expected 1 long H1, got {circle_long_h1}",
    )
    _write(
        _OUT / "p01-circle-h1-golden.input.json",
        {
            "vector_id": "wp42-p01-circle-h1-golden",
            "description": (
                "The synthetic unit-radius circle (100 pts, radial noise 0.03) "
                "has exactly one long-lived H1 class above the threshold; that "
                "class is the topological loop."
            ),
            "expected": "accept",
            "cloud_ref": "fixtures/public/cloud-circle.json",
            "maxdim": 1,
            "metric": "euclidean",
            "seed": 20260728,
            "h1_threshold": H1_THRESHOLD,
            "expected_long_lived_h1": one_long_lived,
            "expected_min_max_h1_persistence": 0.8,
            "golden_max_h1_persistence": round(circle_max_h1, 6),
        },
    )
    cases.append("p01-circle-h1-golden")

    # --- p02: two-cluster H0 golden -------------------------------------------
    two_cluster = _load_cloud("two-cluster")
    res_tc = compute_persistence(two_cluster, maxdim=1, seed=20260728)
    tc_long_h0 = long_lived_classes(res_tc, 0, H0_THRESHOLD)
    tc_max_finite_h0 = max_finite_persistence(res_tc, 0)
    _require(
        tc_long_h0 == two_long_lived,
        f"expected 2 long H0, got {tc_long_h0}",
    )
    _write(
        _OUT / "p02-two-cluster-h0-golden.input.json",
        {
            "vector_id": "wp42-p02-two-cluster-h0-golden",
            "description": (
                "The synthetic two-cluster cloud (128 pts, centers at (-1,0) "
                "and (1,0), Gaussian noise 0.25) has exactly two long-lived "
                "H0 classes above the threshold: one essential component and "
                "one inter-cluster merge."
            ),
            "expected": "accept",
            "cloud_ref": "fixtures/public/cloud-two-cluster.json",
            "maxdim": 1,
            "metric": "euclidean",
            "seed": 20260728,
            "h0_threshold": H0_THRESHOLD,
            "expected_long_lived_h0": two_long_lived,
            "expected_min_max_finite_h0_persistence": 0.8,
            "golden_max_finite_h0_persistence": round(tc_max_finite_h0 or 0, 6),
        },
    )
    cases.append("p02-two-cluster-h0-golden")

    # --- p03: uniform-square H1 control (null) --------------------------------
    uniform = _load_cloud("uniform-square")
    res_us = compute_persistence(uniform, maxdim=1, seed=20260728)
    us_max_h1 = max_finite_persistence(res_us, 1)
    us_long_h1 = long_lived_classes(res_us, 1, H1_THRESHOLD)
    _require(
        us_long_h1 == zero_long_lived,
        f"uniform square should have 0 long H1, got {us_long_h1}",
    )
    _write(
        _OUT / "p03-uniform-square-h1-control.input.json",
        {
            "vector_id": "wp42-p03-uniform-square-h1-control",
            "description": (
                "The synthetic uniform square (128 pts, x,y ~ Uniform(-1,1)) "
                "has no long-lived H1 class above the threshold. This is the "
                "topology-free control: a non-topological point cloud should "
                "not produce a spurious loop."
            ),
            "expected": "accept",
            "cloud_ref": "fixtures/public/cloud-uniform-square.json",
            "maxdim": 1,
            "metric": "euclidean",
            "seed": 20260728,
            "h1_threshold": H1_THRESHOLD,
            "expected_long_lived_h1": zero_long_lived,
            "expected_max_h1_persistence_below": H1_THRESHOLD,
            "golden_max_h1_persistence": round(us_max_h1 or 0, 6),
        },
    )
    cases.append("p03-uniform-square-h1-control")

    # --- p04: surrogate control (null-hypothesis) -----------------------------
    # A phase-randomized surrogate of a pure sinusoid preserves the spectrum
    # but randomizes phases; the helper must be reproducible (same seed -> same
    # surrogate) and produce a distinct signal (different from the original).
    # Build a test signal: a sum of two sinusoids (200 samples).
    t = np.linspace(0, 4 * np.pi, 200)
    signal = (np.sin(t) + 0.5 * np.sin(2 * t)).tolist()
    surr_1 = phase_randomized_surrogate(signal, seed=999)
    surr_2 = phase_randomized_surrogate(signal, seed=999)
    surr_diff_seed = phase_randomized_surrogate(signal, seed=1000)
    _require(surr_1 == surr_2, "surrogate not reproducible across runs")
    _require(surr_1 != surr_diff_seed, "surrogate not seed-dependent")
    _require(
        surr_1 != [_format(v) for v in signal],
        "surrogate identical to input",
    )
    _write(
        _OUT / "p04-surrogate-control.input.json",
        {
            "vector_id": "wp42-p04-surrogate-control",
            "description": (
                "A phase-randomized surrogate of a 1-D signal (sum of two "
                "sinusoids) is reproducible (same seed -> same surrogate) and "
                "distinct from the original. This is the null-hypothesis "
                "control for TDA on time series: compare a feature in the "
                "original to the distribution across surrogate ensembles."
            ),
            "expected": "accept",
            "signal_length": len(signal),
            "seed_reproducible": 999,
            "seed_distinct": 1000,
            "expected_reproducible": True,
            "expected_distinct_across_seeds": True,
        },
    )
    cases.append("p04-surrogate-control")

    # --- n01: oversized cloud negative ----------------------------------------
    _write(
        _OUT / "n01-oversized-cloud.input.json",
        {
            "vector_id": "wp42-n01-oversized-cloud",
            "description": (
                "A point cloud with more than MAX_POINTS ("
                f"{MAX_POINTS}) points is rejected with RESOURCE_LIMIT before "
                "any compute. The adapter never silently truncates or samples."
            ),
            "expected": "reject",
            "operation": "compute_persistence",
            "n_points": MAX_POINTS + 1,
            "ambient_dim": 2,
            "maxdim": 0,
        },
    )
    _write(
        _OUT / "n01-oversized-cloud.expected_error.json",
        {
            "fail_reason": "RESOURCE_LIMIT",
            "detail": (
                f"point cloud has {MAX_POINTS + 1} points; the hard limit is "
                f"{MAX_POINTS} (RESOURCE_LIMIT)."
            ),
        },
    )
    cases.append("n01-oversized-cloud")

    # --- manifest --------------------------------------------------------------
    _write(
        _OUT / "manifest.json",
        {
            "schema_version": "ConformanceVectorManifest/v1",
            "description": (
                "WP-E42 ripser TDA conformance vectors. The goldens encode the "
                "topology of the synthetic point clouds in fixtures/public; "
                "the controls assert the null (no spurious topology) and the "
                "surrogate discipline."
            ),
            "positive": cases[:4],
            "negative": cases[4:],
        },
    )

    print(f"Authored {len(cases)} fixtures under {_OUT}")
    for c in cases:
        print(f"  {c}")
    return 0


def _format(v: float) -> str:
    """Render a float for comparison (kept simple; not the policy renderer)."""
    return repr(v)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
