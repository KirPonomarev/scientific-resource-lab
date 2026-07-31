"""A07 P0 Python core adapter.

This module owns the V3.7 A07 Python-native scientific core surface:
SymPy for exact symbolic algebra, mpmath for high-precision/interval numerics,
and python-flint for FLINT/Arb/Calcium exact arithmetic. python-flint is
admitted only through the A07 package-specific LGPL-family license closure
receipt; the bounded smoke below is still required before truth-ledger ACTIVE.

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
P0_PYTHON_CORE_ACTIVE_PACKS: Final[tuple[str, ...]] = ("sympy", "mpmath", "python-flint")
P0_PYTHON_CORE_WAIT_PACKS: Final[tuple[str, ...]] = ()
FLINT_WAIT_REASON: Final[str] = (
    "A07_LICENSE_CLOSED: python-flint 0.9.0 declares MIT AND LGPL-3.0-or-later; "
    "SRL admits this exact package through ADR-0010 obligations without broadening "
    "the general GPL/LGPL denial policy"
)


@dataclass(frozen=True, slots=True)
class P0PythonCoreSmoke:
    """Stable evidence from the A07 bounded scientific smoke suite."""

    schema_version: str
    sympy_version: str
    mpmath_version: str
    flint_version: str
    exact_factorization: str
    exact_factorization_crosscheck: str
    high_precision_value: str
    high_precision_crosscheck: str
    interval_enclosure: dict[str, str]
    interval_crosscheck: str
    dimensional_consistency: str
    flint_status: str
    flint_integer_partition: str
    flint_rational_identity: str
    flint_matrix_entry: str
    flint_polynomial_factorization: str
    flint_crosscheck: str
    flint_license_closure: str
    canonical_writes: int = 0
    grants_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return this smoke evidence as a JSON-compatible mapping."""
        return {
            "schema_version": self.schema_version,
            "sympy_version": self.sympy_version,
            "mpmath_version": self.mpmath_version,
            "flint_version": self.flint_version,
            "exact_factorization": self.exact_factorization,
            "exact_factorization_crosscheck": self.exact_factorization_crosscheck,
            "high_precision_value": self.high_precision_value,
            "high_precision_crosscheck": self.high_precision_crosscheck,
            "interval_enclosure": self.interval_enclosure,
            "interval_crosscheck": self.interval_crosscheck,
            "dimensional_consistency": self.dimensional_consistency,
            "flint_status": self.flint_status,
            "flint_integer_partition": self.flint_integer_partition,
            "flint_rational_identity": self.flint_rational_identity,
            "flint_matrix_entry": self.flint_matrix_entry,
            "flint_polynomial_factorization": self.flint_polynomial_factorization,
            "flint_crosscheck": self.flint_crosscheck,
            "flint_license_closure": self.flint_license_closure,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }


def _distribution_version(name: str) -> str:
    return importlib.metadata.version(name)


def _sympy() -> Any:
    return importlib.import_module("sympy")


def _mpmath() -> Any:
    return importlib.import_module("mpmath")


def _flint() -> Any:
    return importlib.import_module("flint")


def _interval_endpoint_text(endpoint: Any) -> str:
    rendered = str(endpoint).strip()
    if rendered.startswith("[") and "," in rendered:
        return rendered[1:].split(",", 1)[0].strip()
    return rendered


def run_p0_python_core_smoke() -> P0PythonCoreSmoke:
    """Run the bounded A07 smoke suite and return stable evidence."""
    sympy = _sympy()
    mpmath = _mpmath()
    flint = _flint()

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

    partition_20 = flint.fmpz(20).partitions_p()
    if str(partition_20) != "627":
        raise RuntimeError(f"python-flint partition smoke failed: {partition_20}")
    rational_sum = flint.fmpq(1, 3) + flint.fmpq(1, 6)
    if rational_sum != flint.fmpq(1, 2):
        raise RuntimeError(f"python-flint rational identity failed: {rational_sum}")
    fib_matrix = flint.fmpz_mat([[1, 1], [1, 0]]) ** 10
    if str(fib_matrix[0, 0]) != "89":
        raise RuntimeError(f"python-flint matrix power failed: {fib_matrix}")
    factorization = flint.fmpz_poly([1, 0, -1]).factor()
    if "x + (-1)" not in str(factorization) or "x + 1" not in str(factorization):
        raise RuntimeError(f"python-flint polynomial factorization failed: {factorization}")

    return P0PythonCoreSmoke(
        schema_version=P0_PYTHON_CORE_SCHEMA_VERSION,
        sympy_version=_distribution_version("sympy"),
        mpmath_version=_distribution_version("mpmath"),
        flint_version=_distribution_version("python-flint"),
        exact_factorization=str(factorized),
        exact_factorization_crosscheck="expand(factor(x^4 - 1)) == x^4 - 1",
        high_precision_value=high_precision_value,
        high_precision_crosscheck="sqrt(2)^2 residual < 1e-78 at 80 dps",
        interval_enclosure={"lower": str(lower), "upper": str(upper)},
        interval_crosscheck="mpmath sqrt(2) lies inside mpmath.iv.sqrt([2,2])",
        dimensional_consistency="parse_unit('kg*m/s^2') == parse_unit('N')",
        flint_status="ACTIVE",
        flint_integer_partition=str(partition_20),
        flint_rational_identity=str(rational_sum),
        flint_matrix_entry=str(fib_matrix[0, 0]),
        flint_polynomial_factorization=str(factorization),
        flint_crosscheck=(
            "p(20)=627, 1/3+1/6=1/2, Fibonacci matrix M^10[0,0]=89, and factor(1-x^2)=-(x-1)(x+1)"
        ),
        flint_license_closure=FLINT_WAIT_REASON,
    )


__all__ = [
    "FLINT_WAIT_REASON",
    "P0_PYTHON_CORE_ACTIVE_PACKS",
    "P0_PYTHON_CORE_SCHEMA_VERSION",
    "P0_PYTHON_CORE_WAIT_PACKS",
    "P0PythonCoreSmoke",
    "run_p0_python_core_smoke",
]
