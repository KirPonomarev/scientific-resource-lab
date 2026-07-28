"""Actual-compute probe for the tda-ripser pack (WP-E42).

The actual-compute probe runs a deterministic persistent-homology computation
and prints a checkable result. It is the ``actual_compute_probe`` entrypoint
named in the pack manifest and is invoked by the admission pipeline's
``ACTUAL_COMPUTE_PROBED`` stage.

The probe is hermetic: it exercises the ripser adapter on an in-memory cloud
(an equilateral triangle, which has a well-known homology) and verifies the
preprocessing receipt is deterministic. The printed result is deterministic so
the admission gate can compare it byte-for-byte.

Exit code 0 on success; non-zero on any compute or determinism failure.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Run the deterministic compute and print the checkable result."""
    from srl.packs.adapters.ripser_adapter import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        compute_persistence,
        long_lived_classes,
        numpy_version,
        ripser_version,
    )

    # An equilateral triangle: one connected component (H0 essential), no
    # prominent H1. This is a minimal, topology-known example.
    triangle = [[0.0, 0.0], [1.0, 0.0], [0.5, 0.8660254]]

    result_1 = compute_persistence(triangle, maxdim=1, seed=7)
    result_2 = compute_persistence(triangle, maxdim=1, seed=7)

    # 1. The triangle has exactly one H0 class (the essential component).
    if len(result_1.diagrams[0]) != 1:
        return 1  # pragma: no cover (probe failure path)

    # 2. Determinism: two runs with the same seed produce byte-identical
    #    preprocessing receipts.
    if result_1.preprocessing_receipt.canonical_dumps() != (
        result_2.preprocessing_receipt.canonical_dumps()
    ):
        return 1  # pragma: no cover (probe failure path)

    # 3. The triangle has no long-lived H1 above a small threshold (the loop
    #    dies immediately because the triangle fills in).
    if long_lived_classes(result_1, dimension=1, threshold=0.5) != 0:
        return 1  # pragma: no cover (probe failure path)

    # Deterministic checkable result for the admission gate.
    print(
        f"tda-ripser compute probe OK; h0={len(result_1.diagrams[0])}; "
        f"h1={len(result_1.diagrams[1])}; seed=7; "
        f"ripser={ripser_version()}; numpy={numpy_version()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
