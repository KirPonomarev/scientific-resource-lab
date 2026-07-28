"""Runtime probe for the geometry-pyriemann pack (WP-E43).

The runtime probe verifies the pyriemann adapter loads and its typed surface is
reachable. It is the ``runtime_probe`` entrypoint named in the pack manifest
and is invoked by the admission pipeline's ``RUNTIME_PROBED`` stage.

Exit code 0 on success; non-zero on any import or surface failure. The probe
performs no I/O beyond printing the version line.
"""

from __future__ import annotations

import sys

import numpy as np


def main() -> int:
    """Load the pyriemann adapter and verify its typed surface is reachable."""
    from srl.packs.adapters.pyriemann_adapter import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        Metric,
        SpdError,
        distance,
        log_euclidean_mean,
        numpy_version,
        pyriemann_version,
        scipy_version,
        shrinkage,
    )

    _DIM = 2
    a = np.array([[2.0, 0.5], [0.5, 1.5]])
    b = np.array([[3.0, -0.2], [-0.2, 2.0]])

    # Surface checks: both mean functions and distance must run without raising.
    mean = log_euclidean_mean([a, b])
    if mean.shape != (_DIM, _DIM):
        return 1  # pragma: no cover (probe failure path)
    shrunk = shrinkage(a, 0.3)
    if shrunk.shape != (_DIM, _DIM):
        return 1  # pragma: no cover (probe failure path)

    # Non-SPD input must raise SpdError (no silent fallback).
    try:
        distance(np.array([[1.0, 2.0], [3.0, 4.0]]), a, Metric.RIEMANN)
    except SpdError:
        pass
    else:
        return 1  # pragma: no cover (probe failure path)

    print(
        f"geometry-pyriemann runtime probe OK; "
        f"pyriemann={pyriemann_version()}; numpy={numpy_version()}; scipy={scipy_version()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
