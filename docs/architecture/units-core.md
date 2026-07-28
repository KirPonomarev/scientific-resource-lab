# Units semantic core (WP-E40)

The units semantic core is the SRL fabric's dimensional-analysis layer. It
parses unit strings into dimensional representations, validates that a model's
symbols and constants are dimensionally coherent, and converts decimal-string
values between dimensionally equivalent units under an explicit precision
policy. It replaces the fixture-scoped dimensional checker shipped in WP-B11
(which hand-canonicalised exactly one identity, `kg.m.s-2` ≡ `N`) with a real
unit algebra.

The implementation is `srl.packs.adapters.units`, the first pack adapter. It
is backed by [Pint](https://github.com/hgrecco/pint) and is the **only** module
in the SRL tree that imports Pint (see [ADR-0003](../adr/0003-pint-dependency.md)
and the isolation section below).

## Typed surface

The adapter exposes a small, typed surface. Every other consumer goes through
it; none touches Pint directly.

| Symbol                  | Kind      | Purpose                                                    |
| ----------------------- | --------- | ---------------------------------------------------------- |
| `Dimension`             | type      | Frozen, comparable dimensional representation (base-exponent map). |
| `UnitError`             | exception | Raised for any dimensional violation (`CONTRACT_INVALID`). |
| `parse_unit(unit)`      | function  | Map a UCUM/QUDT unit string to a `Dimension`.              |
| `validate_dimensions(symbol_table, constant_refs)` | function | Check a `SymbolTable/v1` + `ConstantRef/v1` set for coherence. |
| `convert(value, from_unit, to_unit)` | function | Convert a decimal-string value between equivalent units. |
| `PINNED_QUDT_SUBSET`    | constant  | The frozenset of accepted unit strings.                    |
| `SI_BASE_DIMENSIONS`    | constant  | The seven SI base dimension names.                         |
| `CONVERSION_SIG_DIGITS` | constant  | The conversion result precision (significant digits).      |
| `pint_version()`        | function  | The resolved Pint version (for gate evidence).             |

## Pinned QUDT subset

The adapter accepts a deliberately small, auditable set of units. Anything
outside this set is rejected with `UnitError` (`CONTRACT_INVALID`) — there is
**no silent fallback** to Pint's much larger vocabulary. This is the
security-relevant surface: a unit the fabric accepts is one a human has
reviewed.

The seven SI base units:

| Unit | Dimension         |
| ---- | ----------------- |
| `m`  | `[length]`        |
| `kg` | `[mass]`          |
| `s`  | `[time]`          |
| `A`  | `[current]`       |
| `K`  | `[temperature]`   |
| `mol`| `[substance]`     |
| `cd` | `[luminosity]`    |

The eight coherent SI derived units (with special names):

| Unit | Reduced dimension                                  |
| ---- | -------------------------------------------------- |
| `N`  | `[length] · [mass] · [time]⁻²`                     |
| `Pa` | `[length]⁻¹ · [mass] · [time]⁻²`                   |
| `J`  | `[length]² · [mass] · [time]⁻²`                    |
| `W`  | `[length]² · [mass] · [time]⁻³`                    |
| `Hz` | `[time]⁻¹`                                         |
| `V`  | `[current]⁻¹ · [length]² · [mass] · [time]⁻³`     |
| `C`  | `[current] · [time]`                               |
| `ohm`| `[current]⁻² · [length]² · [mass] · [time]⁻³`     |

Plus the composite factored forms accepted verbatim (`m/s`, `m/s^2`,
`kg*m/s^2`) and the `dimensionless` unit (empty dimension).

A unit outside the subset — even one Pint knows, like `fortnight` or `km` — is
rejected. Extending the subset is a documented change to
`PINNED_QUDT_SUBSET` in `srl.packs.adapters.units`.

### SI coherence

Two units are *dimensionally equivalent* iff their `Dimension` objects are
equal. Pint reduces both the named derived unit and its factored form to the
same base-dimension vector, so the Newton identity holds exactly:

```
parse_unit("kg*m/s^2") == parse_unit("N")   # True
parse_unit("J")         == parse_unit("N*m") # True
```

## UCUM alias table

The CODATA fixtures (and the `ConstantRef/v1` `unit` field convention) use
UCUM notation: dot-separated tokens with signed exponents (`kg.m2.s-2`,
`m.s-1`) and some symbol spellings Pint does not parse directly (`Ohm`). The
adapter normalises these to Pint's Python-notation form before parsing.

The normalisation:

1. replaces UCUM `.` separators (between unit symbols) with `*`, so
   `kg.m.s-2` → `kg*m*s-2`;
2. rewrites each token's signed/unsigned trailing exponent to Python power
   notation, so `s-2` → `s**-2`, `m2` → `m**2`;
3. applies a compact inline symbol-alias table (`Ohm` → `ohm`).

| UCUM form        | Pint form          | Notes                          |
| ---------------- | ------------------ | ------------------------------ |
| `kg.m.s-2`       | `kg*m*s**-2`       | signed-exponent rewrite        |
| `m.s-1`          | `m*s**-1`          | signed-exponent rewrite        |
| `kg.m2.s-2`      | `kg*m**2*s**-2`    | unsigned-exponent rewrite      |
| `Ohm`            | `ohm`              | symbol alias                   |
| `mol-1`          | `mol**-1`          | signed-exponent rewrite        |

The alias table is `_UCUM_ALIASES` in the adapter and is deliberately compact:
only the aliases needed for the pinned subset and the CODATA fixtures.

## Precision policy

Precision-sensitive values are carried as JSON **strings** matching the SRL
decimal-string policy (`^-?[0-9]+(\.[0-9]+)?$`; see
`srl.contracts.canonical`). The adapter never coerces to float on the wire:

- `convert` validates the input value against the policy first and rejects
  anything with an exponent or non-numeric content (`UnitError`).
- The conversion factor is rendered via Python's shortest round-trip `repr`
  (`str(factor)`), not `Decimal.create_from_float`, so a coherent conversion
  (factor exactly `1.0`) yields the exact decimal identity rather than a
  float artefact like `1.0000...208`.
- The result is quantised to `CONVERSION_SIG_DIGITS` (50) significant digits
  using round-half-up, then insignificant trailing zeros are stripped via
  `Decimal.normalize()`, so `1 kg*m/s^2` → `1 N` renders as `"1"`, not
  `"1.0000...0"`.

The consequence: a coherent conversion is a byte-exact decimal identity,
which is what the WP-E40 gate (E40-04) asserts.

## Why Pint is isolated

Pint is the fabric's first numerical dependency and its vocabulary is large
(several thousand units, prefixes, and aliases). The SRL adapter keeps a
deliberately small, auditable surface and hides Pint behind a typed boundary:

- `srl.packs.adapters.units` is the **only** module that imports `pint`. An
  architecture test (`tests/packs/test_units_adapter.py::TestPintIsolation`)
  walks the `src/srl` tree with `ast` and asserts no other module imports it.
- The adapter treats all Pint objects (registry, unit, quantity, container)
  as opaque `Any`; no Pint type leaks into the SRL type surface, so `mypy
  --strict` checks the adapter's own typed contract, not Pint's.
- The registry is built once per process from the definition file shipped
  inside the wheel (no network access); parsing is hermetic and reproducible.

This means removing Pint is a `pyproject.toml` change plus a rewrite of one
module's body behind the same typed surface (see ADR-0003, *Reversibility*).
Callers — the WP-E40 gate, future routers, the symbol-table validator — never
need to change.

## Fail-fast contract

Dimensional errors are raised **before** any compute:

- `parse_unit` gates each token against the pinned subset *before* consulting
  Pint, so an unknown unit never reaches the parser.
- `convert` validates the value, parses both units, and checks dimensional
  equivalence before any multiplication.
- `validate_dimensions` parses each referenced constant's unit and raises on
  the first one that fails.

Every dimensional error is a `UnitError` carrying `fail_reason =
CONTRACT_INVALID` (a terminal, non-retriable contract failure). There is no
silent fallback path: a unit the fabric cannot identify is always an error.

## Evidence

- `scripts/checks/wp40-gate.py` emits a `GateReceipt/v1` with five checks
  (E40-01..E40-05) and the resolved Pint version.
- `fixtures/conformance/units/codata/` ships the six CODATA 2018 constants.
- `fixtures/conformance/units/positive/` and `negative/` hold the conformance
  vectors.
- `tests/packs/test_units_adapter.py` is the hermetic test suite including the
  Pint-isolation architecture test.
- `docs/adr/0003-pint-dependency.md` records the dependency decision and the
  installed-size measurement.
