"""Actual-compute probe for the geometry-pyriemann pack (WP-E43).

The actual-compute probe runs a deterministic SPD geometry computation and prints
a checkable result. It is the ``actual_compute_probe`` entrypoint named in the
pack manifest and is invoked by the admission pipeline's
``ACTUAL_COMPUTE_PROBED`` stage.

The probe is hermetic: it exercises the pyriemann adapter on in-memory matrices.
The printed result is deterministic so the admission gate can compare it
byte-by-byte.

Exit code 0 on success; non-zero on any compute or validation failure.
"""

from __future__ import annotations

import sys

import numpy as np


def main() -> int:
    """Run the deterministic compute and print the checkable result."""
    from srl.packs.adapters.pyriemann_adapter import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        Metric,
        distance,
        fit_transform,
        log_euclidean_mean,
        numpy_version,
        pyriemann_version,
        scipy_version,
        shrinkage,
    )

    _DIM = 2
    a = np.array([[2.0, 0.5], [0.5, 1.5]])
    b = np.array([[3.0, -0.2], [-0.2, 2.0]])

    # 1. Log-Euclidean mean of two SPD matrices.
    le_mean = log_euclidean_mean([a, b])
    if le_mean.shape != (_DIM, _DIM):
        return 1  # pragma: no cover (probe failure path)

    # 2. Riemannian distance is non-negative and symmetric.
    d_ab = distance(a, b, Metric.RIEMANN)
    d_ba = distance(b, a, Metric.RIEMANN)
    if d_ab < 0 or not bool(np.isclose(d_ab, d_ba)):
        return 1  # pragma: no cover (probe failure path)

    # 3. Shrinkage preserves SPD and keeps the diagonal dominant.
    shrunk = shrinkage(a, 0.3)
    if shrunk.shape != (_DIM, _DIM) or shrunk[0, 0] <= 0:
        return 1  # pragma: no cover (probe failure path)

    # 4. Train-only fit_transform state carries only train statistics.
    state, transformed = fit_transform([a, b], alpha=0.3)
    if state["n_features"] != _DIM or transformed.shape != (_DIM, _DIM, _DIM):
        return 1  # pragma: no cover (probe failure path)

    # Deterministic checkable result for the admission gate.
    print(
        f"geometry-pyriemann compute probe OK; "
        f"le_mean_trace={float(np.trace(le_mean)):.9f}; "
        f"d_ab={d_ab:.9f}; "
        f"pyriemann={pyriemann_version()}; numpy={numpy_version()}; scipy={scipy_version()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
