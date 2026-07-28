#!/usr/bin/env python3
"""WP-E43 acceptance gate for the pyRiemann SPD geometry pack.

Runs the five WP-E43 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp43``.

The checks
----------
E43-01 log-euclidean mean golden within tolerance
    The closed-form log-Euclidean mean of two commuting diagonal SPD matrices is
    the element-wise geometric mean. This check verifies the adapter returns it
    within tolerance.

E43-02 distance axioms on the golden set
    For a small set of SPD matrices, the Riemannian distance satisfies the
    metric axioms: d(a,a)=0, symmetry d(a,b)=d(b,a), and the triangle
    inequality d(a,c) <= d(a,b) + d(b,c).

E43-03 non-SPD and 1x1 rejected typed
    Non-symmetric, non-positive-definite, non-square, singular, and trivial 1x1
    inputs raise :class:`SpdError` with fail reason ``CONTRACT_INVALID`` before
    any compute.

E43-04 train-only leakage test
    ``fit_transform(train)`` returns a state dict that depends only on
    ``train``. ``transform(state, new)`` applies the saved target without
    recomputing any statistic from ``new``. The gate verifies the state is
    byte-identical across repeated fits on the same training data and that
    transformed test data matches the result obtained from the train-derived
    target.

E43-05 shrinkage preserves SPD
    ``shrinkage(cov, alpha)`` returns an SPD matrix for ``alpha`` in ``[0, 1]``.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp43-gate.py`` without a prior ``uv run``, and also
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
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp43-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402  (path setup must precede import)

from srl.contracts import dumps  # noqa: E402
from srl.packs.adapters.pyriemann_adapter import (  # noqa: E402
    DEFAULT_SHRINKAGE,
    Metric,
    SpdError,
    distance,
    fit_transform,
    log_euclidean_mean,
    numpy_version,
    pyriemann_version,
    scipy_version,
    shrinkage,
    transform,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-E43"

# Fixtures directory for the pyriemann conformance vectors.
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "pyriemann"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# E43-01: log-euclidean mean golden within tolerance.
# ---------------------------------------------------------------------------


def _check_e43_01() -> dict[str, Any]:
    """E43-01: closed-form log-Euclidean mean of two diagonal SPD matrices."""
    a = np.array([[2.0, 0.0], [0.0, 3.0]])
    b = np.array([[8.0, 0.0], [0.0, 12.0]])
    expected = np.array([[4.0, 0.0], [0.0, 6.0]])
    mean = log_euclidean_mean([a, b])
    error = float(np.max(np.abs(mean - expected)))
    tolerance = 1e-9
    if error <= tolerance:
        return {
            "status": "PASS",
            "detail": f"log-euclidean mean within {error:.3e} of closed-form diag(4,6)",
            "error": error,
        }
    return {
        "status": "FAIL",
        "detail": f"log-euclidean mean deviates by {error:.3e} from diag(4,6)",
        "expected": expected.tolist(),
        "actual": mean.tolist(),
        "error": error,
    }


# ---------------------------------------------------------------------------
# E43-02: distance axioms on the golden set.
# ---------------------------------------------------------------------------


def _check_e43_02() -> dict[str, Any]:
    """E43-02: Riemannian distance satisfies identity, symmetry, triangle."""
    matrices = [
        np.array([[2.0, 0.3], [0.3, 1.5]]),
        np.array([[3.0, -0.2], [-0.2, 2.0]]),
        np.array([[2.5, 0.1], [0.1, 1.8]]),
    ]
    cases: list[dict[str, Any]] = []
    identity_holds = True
    symmetry_holds = True
    triangle_holds = True

    for i, mat in enumerate(matrices):
        d_ii = distance(mat, mat, Metric.RIEMANN)
        identity_holds = bool(identity_holds and np.isclose(d_ii, 0.0))
        cases.append({"pair": [i, i], "distance": d_ii, "axiom": "identity"})

    for i in range(len(matrices)):
        for j in range(i + 1, len(matrices)):
            d_ij = distance(matrices[i], matrices[j], Metric.RIEMANN)
            d_ji = distance(matrices[j], matrices[i], Metric.RIEMANN)
            symmetry_holds = bool(symmetry_holds and np.isclose(d_ij, d_ji))
            cases.append({"pair": [i, j], "distance": d_ij, "axiom": "distance"})
            cases.append({"pair": [j, i], "distance": d_ji, "axiom": "distance"})

    d_01 = distance(matrices[0], matrices[1], Metric.RIEMANN)
    d_12 = distance(matrices[1], matrices[2], Metric.RIEMANN)
    d_02 = distance(matrices[0], matrices[2], Metric.RIEMANN)
    triangle_holds = triangle_holds and (d_02 <= d_01 + d_12 + 1e-9)
    cases.append({"triplet": [0, 2, 1], "sum": d_01 + d_12, "direct": d_02, "axiom": "triangle"})

    if identity_holds and symmetry_holds and triangle_holds:
        return {
            "status": "PASS",
            "detail": "Riemannian distance satisfies identity, symmetry, and triangle inequality",
            "cases": cases,
        }
    return {
        "status": "FAIL",
        "detail": "one or more metric axioms violated",
        "identity_holds": identity_holds,
        "symmetry_holds": symmetry_holds,
        "triangle_holds": triangle_holds,
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E43-03: non-SPD and 1x1 rejected typed.
# ---------------------------------------------------------------------------


def _check_e43_03() -> dict[str, Any]:
    """E43-03: malformed/non-SPD and trivial 1x1 inputs raise SpdError."""
    non_spd = json.loads((_FIXTURES / "non-spd.json").read_text(encoding="utf-8"))
    trivial = json.loads((_FIXTURES / "trivial-1x1.json").read_text(encoding="utf-8"))

    cases: list[dict[str, Any]] = []
    all_rejected = True
    all_typed = True

    for case in non_spd["cases"]:
        try:
            distance(case["matrix"], case["matrix"], Metric.RIEMANN)
            cases.append({"id": case["id"], "outcome": "NOT rejected"})
            all_rejected = False
        except SpdError as exc:
            cases.append(
                {
                    "id": case["id"],
                    "outcome": "rejected",
                    "fail_reason": exc.fail_reason,
                }
            )
            if exc.fail_reason != "CONTRACT_INVALID":
                all_typed = False
        except Exception as exc:
            cases.append({"id": case["id"], "outcome": f"unexpected {type(exc).__name__}"})
            all_rejected = False

    for case in trivial["cases"]:
        try:
            shrinkage(case["matrix"], DEFAULT_SHRINKAGE)
            cases.append({"id": case["id"], "outcome": "NOT rejected"})
            all_rejected = False
        except SpdError as exc:
            cases.append(
                {
                    "id": case["id"],
                    "outcome": "rejected",
                    "fail_reason": exc.fail_reason,
                }
            )
            if exc.fail_reason != "CONTRACT_INVALID":
                all_typed = False
        except Exception as exc:
            cases.append({"id": case["id"], "outcome": f"unexpected {type(exc).__name__}"})
            all_rejected = False

    if all_rejected and all_typed:
        return {
            "status": "PASS",
            "detail": "all non-SPD and 1x1 inputs rejected with CONTRACT_INVALID",
            "cases": cases,
        }
    return {
        "status": "FAIL",
        "detail": "one or more malformed inputs was not rejected or carried the wrong type",
        "all_rejected": all_rejected,
        "all_typed": all_typed,
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# E43-04: train-only leakage test.
# ---------------------------------------------------------------------------


def _check_e43_04() -> dict[str, Any]:
    """E43-04: fit_transform state depends only on training data."""
    train = [
        np.array([[2.0, 0.5], [0.5, 1.5]]),
        np.array([[3.0, -0.2], [-0.2, 2.0]]),
    ]
    test = np.array([[2.5, 0.1], [0.1, 1.8]])
    alpha = 0.3

    state1, _transformed_train = fit_transform(train, alpha=alpha)
    state2, _ = fit_transform(train, alpha=alpha)

    # The state must be deterministic and JSON-serializable.
    states_identical = state1 == state2

    # transform must use only the saved state, never recompute statistics.
    transformed_test = transform(state1, test)
    target = np.asarray(state1["target"], dtype=float)
    expected_test = (1.0 - alpha) * test + alpha * target
    test_matches_state = np.allclose(transformed_test, expected_test)

    # The train statistics must not depend on test data. We verify by checking
    # the saved target equals the mean isotropic target derived from train alone.
    n = state1["n_features"]
    mean_scale = float(np.mean([np.trace(m) / n for m in np.stack(train)]))
    expected_target = mean_scale * np.eye(n, dtype=float)
    target_matches_train = np.allclose(target, expected_target)

    if states_identical and test_matches_state and target_matches_train:
        return {
            "status": "PASS",
            "detail": "fit_transform state is deterministic, train-only, and reusable by transform",
            "state_keys": sorted(state1.keys()),
        }
    return {
        "status": "FAIL",
        "detail": "train-only discipline violated",
        "states_identical": states_identical,
        "test_matches_state": test_matches_state,
        "target_matches_train": target_matches_train,
    }


# ---------------------------------------------------------------------------
# E43-05: shrinkage preserves SPD.
# ---------------------------------------------------------------------------


def _check_e43_05() -> dict[str, Any]:
    """E43-05: shrinkage returns an SPD matrix for alpha in [0, 1]."""
    cov = np.array([[2.0, 0.5], [0.5, 1.5]])
    alpha = 0.3
    shrunk = shrinkage(cov, alpha)

    shape_ok = shrunk.shape == cov.shape
    spd_ok = bool(np.all(np.linalg.eigvalsh(shrunk) > 0))
    changed = not np.allclose(shrunk, cov)

    if shape_ok and spd_ok and changed:
        return {
            "status": "PASS",
            "detail": f"shrinkage with alpha={alpha} preserved SPD shape and positive definiteness",
            "smallest_eigenvalue": float(np.min(np.linalg.eigvalsh(shrunk))),
        }
    return {
        "status": "FAIL",
        "detail": "shrinkage did not preserve SPD structure",
        "shape_ok": shape_ok,
        "spd_ok": spd_ok,
        "changed": changed,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: dependency versions and fixture counts."""
    return {
        "pyriemann_version": pyriemann_version(),
        "numpy_version": numpy_version(),
        "scipy_version": scipy_version(),
        "goldens": 1 if (_FIXTURES / "goldens.json").is_file() else 0,
        "non_spd_cases": len(
            json.loads((_FIXTURES / "non-spd.json").read_text(encoding="utf-8")).get("cases", [])
        )
        if (_FIXTURES / "non-spd.json").is_file()
        else 0,
        "trivial_1x1_cases": len(
            json.loads((_FIXTURES / "trivial-1x1.json").read_text(encoding="utf-8")).get(
                "cases", []
            )
        )
        if (_FIXTURES / "trivial-1x1.json").is_file()
        else 0,
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "E43-01": _check_e43_01(),
        "E43-02": _check_e43_02(),
        "E43-03": _check_e43_03(),
        "E43-04": _check_e43_04(),
        "E43-05": _check_e43_05(),
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
            "E43-01": _check_e43_01,
            "E43-02": _check_e43_02,
            "E43-03": _check_e43_03,
            "E43-04": _check_e43_04,
            "E43-05": _check_e43_05,
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
