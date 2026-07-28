"""Actual-compute probe for the core-units pack (WP-E40).

The actual-compute probe runs a deterministic dimensional computation and
prints a checkable result. It is the ``actual_compute_probe`` entrypoint named
in the pack manifest and is invoked by the admission pipeline's
``ACTUAL_COMPUTE_PROBED`` stage.

The probe is hermetic: it exercises the units adapter on in-memory values,
computing a dimensional-coherence report and the Newton conversion identity.
The printed result is deterministic so the admission gate can compare it
byte-for-byte.

Exit code 0 on success; non-zero on any compute or coherence failure.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Run the deterministic compute and print the checkable result."""
    from srl.packs.adapters.units import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        convert,
        parse_unit,
        pint_version,
        validate_dimensions,
    )

    # 1. The Newton identity: 1 kg*m/s^2 converts to exactly 1 N.
    newton = convert("1", "kg*m/s^2", "N")
    if newton != "1":
        return 1  # pragma: no cover (probe failure path)

    # 2. Coherent derived units are dimensionally equivalent.
    equivalences = [
        ("kg*m/s^2", "N"),
        ("J", "N*m"),
        ("Pa", "N/m^2"),
        ("W", "J/s"),
        ("V", "J/C"),
    ]
    for left, right in equivalences:
        if parse_unit(left) != parse_unit(right):
            return 1  # pragma: no cover (probe failure path)

    # 3. A symbol table over a CODATA-style unit is coherent.
    symbol_table = {
        "schema_version": "SymbolTable/v1",
        "symbols": [
            {"symbol_id": "force", "name": "force", "role": "variable", "unit_ref": "const.N"},
        ],
    }
    constant_refs = {
        "const.N": {
            "schema_version": "ConstantRef/v1",
            "constant_id": "const.N",
            "source": "pack_local",
            "symbol": "N_unit",
            "value": "1",
            "unit": "kg*m/s^2",
            "vintage": "pack-2026-07",
        },
    }
    report = validate_dimensions(symbol_table, constant_refs)
    if report["status"] != "coherent":
        return 1  # pragma: no cover (probe failure path)
    if report["checked"] != 1:
        return 1  # pragma: no cover (probe failure path)

    # Deterministic checkable result for the admission gate.
    print(
        f"core-units compute probe OK; newton={newton}; "
        f"equivalences={len(equivalences)}; pint={pint_version()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
