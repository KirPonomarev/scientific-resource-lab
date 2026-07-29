"""A07 P0 Python core adapter.

This module owns the V3.7 A07 Python-native scientific core surface:
SymPy for exact symbolic algebra and mpmath for high-precision/interval
numerics. ``python-flint`` is intentionally not imported here: its current
published package metadata declares an LGPL-family closure, which the SRL
default dependency policy cannot admit without an explicit license decision.

The adapter exposes bounded smoke tasks, not a general expression evaluator.
Callers cannot pass raw Python/SymPy text into this module.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass
from typing import Any, Final

from srl.packs.adapters.units import parse_unit

P0_PYTHON_CORE_SCHEMA_VERSION: Final[str] = "P0PythonCoreSmoke/v1"
P0_PYTHON_CORE_ACTIVE_PACKS: Final[tuple[str, ...]] = ("sympy", "mpmath")
P0_PYTHON_CORE_WAIT_PACKS: Final[tuple[str, ...]] = ("python-flint",)
FLINT_WAIT_REASON: Final[str] = (
    "WAIT_LICENSE: current python-flint metadata declares MIT AND LGPL-3.0-or-later; "
    "SRL default dependency policy denies LGPL-family closure"
)


@dataclass(frozen=True, slots=True)
class P0PythonCoreSmoke:
    """Stable evidence from the A07 bounded scientific smoke suite."""

    schema_version: str
    sympy_version: str
    mpmath_version: str
    exact_factorization: str
    exact_factorization_crosscheck: str
    high_precision_value: str
    high_precision_crosscheck: str
    interval_enclosure: dict[str, str]
    interval_crosscheck: str
    dimensional_consistency: str
    flint_status: str
    flint_reason: str
    canonical_writes: int = 0
    grants_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return this smoke evidence as a JSON-compatible mapping."""
        return {
            "schema_version": self.schema_version,
            "sympy_version": self.sympy_version,
            "mpmath_version": self.mpmath_version,
            "exact_factorization": self.exact_factorization,
            "exact_factorization_crosscheck": self.exact_factorization_crosscheck,
            "high_precision_value": self.high_precision_value,
            "high_precision_crosscheck": self.high_precision_crosscheck,
            "interval_enclosure": self.interval_enclosure,
            "interval_crosscheck": self.interval_crosscheck,
            "dimensional_consistency": self.dimensional_consistency,
            "flint_status": self.flint_status,
            "flint_reason": self.flint_reason,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }


def _distribution_version(name: str) -> str:
    return importlib.metadata.version(name)


def _sympy() -> Any:
    return importlib.import_module("sympy")


def _mpmath() -> Any:
    return importlib.import_module("mpmath")


def _interval_endpoint_text(endpoint: Any) -> str:
    rendered = str(endpoint).strip()
    if rendered.startswith("[") and "," in rendered:
        return rendered[1:].split(",", 1)[0].strip()
    return rendered


def run_p0_python_core_smoke() -> P0PythonCoreSmoke:
    """Run the bounded A07 smoke suite and return stable evidence."""
    sympy = _sympy()
    mpmath = _mpmath()

    x = sympy.symbols("x")
    polynomial = x**4 - 1
    factorized = sympy.factor(polynomial)
    if sympy.expand(factorized) != polynomial:
        raise RuntimeError("SymPy factorization failed expansion crosscheck")

    old_dps = mpmath.mp.dps
    try:
        mpmath.mp.dps = 80
        value = mpmath.sqrt(2)
        high_precision_value = mpmath.nstr(value, 82)
        squared = value * value
        residual = abs(squared - 2)
        if not (residual < mpmath.mpf("1e-78")):
            raise RuntimeError(f"mpmath sqrt(2) residual too large: {residual}")

        interval = mpmath.iv.sqrt(mpmath.iv.mpf([2, 2]))
        lower = _interval_endpoint_text(interval.a)
        upper = _interval_endpoint_text(interval.b)
        if not (mpmath.mpf(lower) <= value <= mpmath.mpf(upper)):
            raise RuntimeError(f"interval does not enclose decimal sqrt(2): {interval}")
    finally:
        mpmath.mp.dps = old_dps

    if parse_unit("kg*m/s^2") != parse_unit("N"):
        raise RuntimeError("dimensional identity kg*m/s^2 == N failed")

    return P0PythonCoreSmoke(
        schema_version=P0_PYTHON_CORE_SCHEMA_VERSION,
        sympy_version=_distribution_version("sympy"),
        mpmath_version=_distribution_version("mpmath"),
        exact_factorization=str(factorized),
        exact_factorization_crosscheck="expand(factor(x^4 - 1)) == x^4 - 1",
        high_precision_value=high_precision_value,
        high_precision_crosscheck="sqrt(2)^2 residual < 1e-78 at 80 dps",
        interval_enclosure={"lower": str(lower), "upper": str(upper)},
        interval_crosscheck="mpmath sqrt(2) lies inside mpmath.iv.sqrt([2,2])",
        dimensional_consistency="parse_unit('kg*m/s^2') == parse_unit('N')",
        flint_status="WAIT_LICENSE",
        flint_reason=FLINT_WAIT_REASON,
    )


__all__ = [
    "FLINT_WAIT_REASON",
    "P0_PYTHON_CORE_ACTIVE_PACKS",
    "P0_PYTHON_CORE_SCHEMA_VERSION",
    "P0_PYTHON_CORE_WAIT_PACKS",
    "P0PythonCoreSmoke",
    "run_p0_python_core_smoke",
]
