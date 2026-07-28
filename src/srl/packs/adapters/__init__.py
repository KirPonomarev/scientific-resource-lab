"""Pack adapters: the executable capability surface of SRL resource packs.

An adapter is the Python module a resource pack's ``entrypoint`` points at. It
owns one scientific capability and is the boundary between the control plane
(manifest, admission, materialization) and the compute plane.

WP-E40 ships the units adapter: :mod:`srl.packs.adapters.units`, the units
semantic core (dimensional analysis and conversion, backed by Pint and isolated
behind a typed surface). WP-E42 ships the TDA adapter:
:mod:`srl.packs.adapters.ripser_adapter`, the persistent-homology core (backed
by ripser + numpy and isolated behind a typed surface).
"""

from __future__ import annotations

from srl.packs.adapters.ripser_adapter import (
    INF_DEATH_SENTINEL,
    MAX_AMBIENT_DIM,
    MAX_HOMOLOGY_DIM,
    MAX_POINTS,
    PERSISTENCE_SIG_DIGITS,
    RIPSER_CONTRACT_INVALID_FAIL_REASON,
    RIPSER_RESOURCE_LIMIT_FAIL_REASON,
    PersistenceResult,
    PreprocessingReceipt,
    RipserInputError,
    RipserResourceLimitError,
    compute_persistence,
    long_lived_classes,
    max_finite_persistence,
    numpy_version,
    phase_randomized_surrogate,
    ripser_version,
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
    "CONVERSION_SIG_DIGITS",
    "INF_DEATH_SENTINEL",
    "MAX_AMBIENT_DIM",
    "MAX_HOMOLOGY_DIM",
    "MAX_POINTS",
    "PERSISTENCE_SIG_DIGITS",
    "PINNED_QUDT_SUBSET",
    "RIPSER_CONTRACT_INVALID_FAIL_REASON",
    "RIPSER_RESOURCE_LIMIT_FAIL_REASON",
    "SI_BASE_DIMENSIONS",
    "UNIT_FAIL_REASON",
    "Dimension",
    "PersistenceResult",
    "PreprocessingReceipt",
    "RipserInputError",
    "RipserResourceLimitError",
    "UnitError",
    "compute_persistence",
    "convert",
    "long_lived_classes",
    "max_finite_persistence",
    "numpy_version",
    "parse_unit",
    "phase_randomized_surrogate",
    "pint_version",
    "ripser_version",
    "validate_dimensions",
]
