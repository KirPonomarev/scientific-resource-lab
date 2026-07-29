# A07 P0 Python Core

V3.7 A07 activates the default Python-native P0 core for exact symbolic algebra
and high-precision numerics.

The admitted default runtime packs are:

- `sympy` for exact symbolic manipulation;
- `mpmath` for high-precision numerical evaluation and interval arithmetic.

The executable surface is `srl.packs.adapters.p0_python_core`. It exposes only
bounded smoke tasks; it does not accept raw expression text, call `eval`, or
delegate arbitrary user strings into SymPy.

## Smoke And Crosschecks

The A07 gate performs four real, bounded checks:

- exact factorization: `x^4 - 1` factors to `(x - 1)*(x + 1)*(x**2 + 1)` and
  expands back to the original polynomial;
- high-precision evaluation: `mpmath.sqrt(2)` at 80 dps squares back to `2`
  with residual below `1e-78`;
- interval enclosure: `mpmath.iv.sqrt([2, 2])` encloses the high-precision
  mpmath `sqrt(2)` value;
- dimensional consistency: the existing Pint-backed units adapter verifies
  `kg*m/s^2` and `N` reduce to the same dimension.

These checks produce a `P0PythonCoreSmoke/v1` card with `canonical_writes=0` and
`grants_authority=false`.

## FLINT Lane

`python-flint` / FLINT / Arb / Calcium remains parked at `WAIT_LICENSE`.
Current PyPI metadata observed for `python-flint` `0.9.0` declares
`MIT AND LGPL-3.0-or-later`. The SRL default dependency policy denies
LGPL-family closure, so A07 does not add `python-flint` to the default runtime
dependencies and does not claim `exact.flint` is `ACTIVE`.

The required operator action is recorded in
`docs/target-binding/a07-python-flint-license-operator-action.json`.
