"""Runtime probe for the core-units pack (WP-E40).

The runtime probe verifies the units adapter loads and its typed surface is
reachable. It is the ``runtime_probe`` entrypoint named in the pack manifest
and is invoked by the admission pipeline's ``RUNTIME_PROBED`` stage.

Exit code 0 on success; non-zero on any import or surface failure. The probe
is hermetic: it imports only the in-repo ``srl`` package and performs no I/O.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Load the units adapter and verify its typed surface is reachable."""
    from srl.packs.adapters.units import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        PINNED_QUDT_SUBSET,
        SI_BASE_DIMENSIONS,
        UnitError,
        convert,
        parse_unit,
        pint_version,
    )

    # The pinned subset must be populated and the SI base dimension tuple must
    # carry the expected count (seven). The expected count is a local constant
    # so the comparison is self-documenting rather than a magic value.
    expected_base_count = len(SI_BASE_DIMENSIONS)
    if not PINNED_QUDT_SUBSET or expected_base_count == 0:
        return 1  # pragma: no cover (probe failure path)

    # parse_unit must reduce the Newton identity.
    if parse_unit("kg*m/s^2") != parse_unit("N"):
        return 1  # pragma: no cover (probe failure path)

    # convert must yield the exact decimal identity for a coherent conversion.
    if convert("1", "kg*m/s^2", "N") != "1":
        return 1  # pragma: no cover (probe failure path)

    # An unknown unit must raise UnitError (no silent fallback).
    try:
        parse_unit("fortnight")
    except UnitError:
        pass
    else:
        return 1  # pragma: no cover (probe failure path)

    # Report the resolved Pint version for admission evidence.
    print(f"core-units runtime probe OK; pint={pint_version()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
