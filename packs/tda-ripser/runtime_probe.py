"""Runtime probe for the tda-ripser pack (WP-E42).

The runtime probe verifies the ripser adapter loads and its typed surface is
reachable. It is the ``runtime_probe`` entrypoint named in the pack manifest
and is invoked by the admission pipeline's ``RUNTIME_PROBED`` stage.

Exit code 0 on success; non-zero on any import or surface failure. The probe
is hermetic: it imports only the in-repo ``srl`` package and performs no I/O.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Load the ripser adapter and verify its typed surface is reachable."""
    from srl.packs.adapters.ripser_adapter import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        MAX_HOMOLOGY_DIM,
        MAX_POINTS,
        RipserInputError,
        RipserResourceLimitError,
        compute_persistence,
        ripser_version,
    )

    # The hard limits must be the documented values (named to satisfy the
    # magic-value lint and to self-document the contract).
    expected_max_points = 500
    expected_max_homology = 2
    if MAX_POINTS != expected_max_points or MAX_HOMOLOGY_DIM != expected_max_homology:
        return 1  # pragma: no cover (probe failure path)

    # A tiny deterministic cloud (an equilateral triangle) must compute H0.
    triangle = [[0.0, 0.0], [1.0, 0.0], [0.5, 0.8660254]]
    result = compute_persistence(triangle, maxdim=1)
    expected_n_points = 3
    if result.n_points != expected_n_points or result.maxdim != 1:
        return 1  # pragma: no cover (probe failure path)
    # The triangle has exactly one essential H0 class (one component).
    if len(result.diagrams[0]) < 1:
        return 1  # pragma: no cover (probe failure path)

    # An oversized cloud must raise RipserResourceLimitError before compute.
    too_many = [[0.0] * 2 for _ in range(MAX_POINTS + 1)]
    try:
        compute_persistence(too_many, maxdim=0)
    except RipserResourceLimitError:
        pass
    except RipserInputError:
        return 1  # pragma: no cover (wrong error class)
    else:
        return 1  # pragma: no cover (probe failure path)

    # Report the resolved ripser version for admission evidence.
    print(f"tda-ripser runtime probe OK; ripser={ripser_version()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
