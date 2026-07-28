"""Pack adapters: the executable capability surface of SRL resource packs.

An adapter is the Python module a resource pack's ``entrypoint`` points at. It
owns one scientific capability and is the boundary between the control plane
(manifest, admission, materialization) and the compute plane.

WP-E40 ships the first adapter: :mod:`srl.packs.adapters.units`, the units
semantic core (dimensional analysis and conversion, backed by Pint and isolated
behind a typed surface). WP-E41 adds the SMT satisfiability adapter:
:mod:`srl.packs.adapters.smt`, backed by Z3 and isolated behind a typed
surface that yields at most ``formal_check=checked`` (never ``proven``
without a verified certificate).
"""

from __future__ import annotations

from srl.packs.adapters.smt import (
    AVAILABLE_SOLVERS,
    FORMAL_CHECK_CEILING,
    MAX_FORMULA_NODES,
    MAX_WALL_SECONDS,
    SMT_FAIL_REASON,
    SUPPORTED_OPERATORS,
    WAIT_LICENSE_SOLVERS,
    SmtError,
    SmtOutcome,
    SmtResult,
    SolverChoice,
    check,
    z3_version,
)
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
    "AVAILABLE_SOLVERS",
    "CONVERSION_SIG_DIGITS",
    "FORMAL_CHECK_CEILING",
    "MAX_FORMULA_NODES",
    "MAX_WALL_SECONDS",
    "PINNED_QUDT_SUBSET",
    "SI_BASE_DIMENSIONS",
    "SMT_FAIL_REASON",
    "SUPPORTED_OPERATORS",
    "UNIT_FAIL_REASON",
    "WAIT_LICENSE_SOLVERS",
    "Dimension",
    "SmtError",
    "SmtOutcome",
    "SmtResult",
    "SolverChoice",
    "UnitError",
    "check",
    "convert",
    "parse_unit",
    "pint_version",
    "validate_dimensions",
    "z3_version",
]
