"""Pack adapters: the executable capability surface of SRL resource packs.

An adapter is the Python module a resource pack's ``entrypoint`` points at. It
owns one scientific capability and is the boundary between the control plane
(manifest, admission, materialization) and the compute plane.

WP-E40 ships the first adapter: :mod:`srl.packs.adapters.units`, the units
semantic core (dimensional analysis and conversion, backed by Pint and isolated
behind a typed surface).
"""

from __future__ import annotations

from srl.packs.adapters.units import (
    CONVERSION_SIG_DIGITS,
    PINNED_QUDT_SUBSET,
    SI_BASE_DIMENSIONS,
    UNIT_FAIL_REASON,
    Dimension,
    UnitError,
    convert,
    parse_unit,
    pint_version,
    validate_dimensions,
)

__all__ = [
    "CONVERSION_SIG_DIGITS",
    "PINNED_QUDT_SUBSET",
    "SI_BASE_DIMENSIONS",
    "UNIT_FAIL_REASON",
    "Dimension",
    "UnitError",
    "convert",
    "parse_unit",
    "pint_version",
    "validate_dimensions",
]
