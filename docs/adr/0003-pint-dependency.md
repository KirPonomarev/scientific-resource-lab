# ADR 0003: Pint for the units semantic core

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-E40 (Units and semantic core)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

WP-E40 introduces the units semantic core: a real dimensional-analysis layer
that replaces the fixture-scoped dimensional checker shipped in WP-B11 (see
`scripts/checks/wp11-gate.py`, which hand-canoncialised `kg.m.s-2` ≡ `N` with a
hard-coded table). The units adapter
(`src/srl/packs/adapters/units.py`) must:

1. **Parse** a pinned subset of QUDT/UCUM unit strings into a dimensional
   representation (the seven SI base dimensions plus the derived units the
   scientific IR needs: `N`, `Pa`, `J`, `W`, `Hz`, `V`, `C`, `Ohm`).
2. **Validate** that a `SymbolTable/v1` and its referenced `ConstantRef/v1`
   entries are dimensionally coherent (e.g. `kg*m/s^2` ≡ `N` is accepted,
   `kg` vs `m` is rejected) *before* any compute runs.
3. **Convert** a decimal-string value between dimensionally equivalent units
   (e.g. `1 kg*m/s^2` → `1 N`) under an explicit, reproducible precision policy.

Through WP-C23 the package had a single runtime third-party dependency
(`jsonschema`, ADR-0002). The units core is the fabric's first *numerical*
dependency: dimensional analysis is intricate (dimension reduction, exponent
arithmetic, prefix handling, the SI coherence identity), easy to get wrong by
hand, and exactly the kind of code where a silent bug corrupts every downstream
computation. The choice affects:

1. Whether SI base/derived reduction and dimensional equivalence are correct
   (the `N` ≡ `kg·m·s⁻²` identity must hold exactly, not approximately).
2. The supply-chain surface (a units library is imported wherever the adapter
   runs, and may pull transitive numerical dependencies).
3. The precision story: SRL carries constants as decimal strings
   (`^-?[0-9]+(\.[0-9]+)?$`) so precision survives a round trip. The library
   must not coerce to float during conversion.
4. Lockfile and reproducibility posture (`uv.lock` must pin the library and its
   transitive closure).

## Alternatives considered

### 1. `pint` (chosen)

- The de-facto Python physical-quantities library; maintained under
  `hgrecco/pint`, in continuous development since 2012.
- Pure Python, no compiled extension, no native numerical dependency beyond the
  standard library. Runs on every platform SRL targets (linux/macos,
  x86_64/arm64).
- Full dimensional analysis: base dimensions, derived-unit reduction, SI
  coherence, prefix handling, and a unit registry that recognises both symbol
  (`N`) and factored (`kg*m/s**2`) forms. The dimensional identity
  `kg*m/s**2 == N` is exact because Pint reduces both to the same dimension.
- Ships a `py.typed` marker, so `mypy --strict` (the SRL gate) type-checks
  against the real stubs rather than needing a third-party stub package.
- BSD-3-Clause licensed (see *License impact*); compatible with the project's
  Apache-2.0 license and the SRL pack allowlist.
- Adds three transitive pure-Python packages: `flexparser` and `flexcache`
  (Pint's own declarative-definition parser/cache, BSD) and `platformdirs`
  (MIT), all pinned in `uv.lock`.

### 2. `unyt`

- NumPy-backed units library from the SciPy/astropy community (`yt-project/unyt`).
- Strong NumPy integration and good array performance, but its central design
  point is *array* quantities. SRL's adapter operates on scalar decimal strings,
  not NumPy arrays, so the NumPy coupling is pure overhead.
- Pulls in `numpy` (and transitively a BLAS/LAPACK or the bundled
  `numpy.linalg`) as a hard dependency — a heavy native closure for a scalar
  dimensional checker.
- BSD-3-Clause licensed, but the NumPy dependency and the array-first API make
  it a poor fit for a precision-first, decimal-string fabric.

### 3. `astropy.units`

- Mature and very complete (UCUM-adjacent vocabulary, extensive physical
  constants), but its scope is the whole astropy ecosystem.
- Pulls in a large native + scientific closure (NumPy, PyERFA, possibly
  SciPy), far beyond what a dimensional gate needs.
- Licensed BSD-3-Clause, but the import cost and the astropy-version coupling
  are disproportionate for an admission-time dimensional checker.

### 4. Hand-rolled dimensional algebra

- Implement base-dimension exponent vectors and the derived-unit reduction by
  hand (a dict from dimension symbol to integer exponent, plus product/quotient/
  power rules).
- Avoids the runtime dependency entirely and is tractable for the *pinned QUDT
  subset* WP-E40 ships (the table fits on one screen).
- But: SI-prefix handling, the full derived-unit vocabulary, and the conversion
  factor arithmetic are easy to get subtly wrong; a hand-rolled algebra must be
  re-tested against CODATA identities on every extension; and it offers no path
  to the larger unit vocabulary future work packages will need. The WP-B11
  fixture checker already demonstrated the maintenance smell (a `_NAMED_UNIT_TO_BASE`
  table that hard-coded exactly one identity).
- Trades one well-tested dependency for a permanent in-house maintenance burden
  with no headroom.

## Decision

Adopt **`pint`** as the dimensional-analysis engine for the units core, **fully
isolated behind the adapter** `src/srl/packs/adapters/units.py`. Pint is the
only module in the SRL tree that imports `pint`; every other consumer goes
through the adapter's typed surface (`parse_unit`, `validate_dimensions`,
`convert`, `Dimension`, `UnitError`).

Configuration (see `pyproject.toml`):

```toml
[project]
dependencies = [
    "jsonschema>=4.23",
    "pint>=0.25.3",
]
```

No dev-group stub is needed: Pint ships `py.typed`, so `mypy --strict`
type-checks the adapter against the library's own annotations.

The adapter constructs a single module-level `pint.UnitRegistry` configured for
determinism (no auto-download, the default `en` locale, the standard
definition file shipped inside the wheel) and restricts parsing to a pinned
QUDT subset plus a compact UCUM alias table. An unknown unit raises
`UnitError` (`CONTRACT_INVALID`) *before* any compute — there is no silent
fallback to a guessed unit. Conversion renders the result to the SRL
decimal-string policy via `decimal.Decimal`, never a float.

## Consequences

### Positive

- SI coherence is correct by construction: `kg*m/s**2` and `N` reduce to the
  identical dimension and the `1 → 1` conversion is an exact decimal identity.
- The WP-B11 fixture-scoped checker is retired in favour of a real algebra;
  the gate (`scripts/checks/wp40-gate.py`) proves both the positive (coherent)
  and negative (mismatch, unknown, malformed) vectors.
- Headroom for future work packages: derived units beyond the initial subset,
  temperature offsets, and logarithmic units are available without re-authoring
  an in-house algebra.
- `mypy --strict` covers the adapter end-to-end with no stub package.

### Negative

- Adds `pint` as the second runtime third-party dependency, with three
  transitive pure-Python packages (`flexparser`, `flexcache`, `platformdirs`).
  All are pinned in `uv.lock`.
- The `srl.packs.adapters` layer is no longer stdlib-only; the WP-E40 gate
  runs under `uv run python` (the WP-A03 autonomy gate remains stdlib-only
  under bare `python3`).

### Security impact

Pint is imported only inside the units adapter and performs no I/O of its own
in SRL's usage: the registry is built from the definition file packaged inside
the wheel (auto-download is disabled), and conversions operate on in-memory
decimal strings. It does not touch the runner boundary, the content-addressed
store, pack materialization, or the disclosure sanitizer. Pinning a lower bound
(`>=0.25.3`) and recording the resolved version in `uv.lock` bounds the
supply-chain surface. Reversibility is covered below.

### Resource impact

Small. The adapter builds one `UnitRegistry` once per process (module-level,
effectively memoised); `parse_unit` / `validate_dimensions` / `convert` run at
admission time, not in a tight loop. Well within the 15-minute CI budget.

Installed size (measured on the resolved 0.25.3 closure, CPython 3.12):

| package       | bytes     | files | notes                          |
| ------------- | --------- | ----- | ------------------------------ |
| `pint`        | 1,740,120 | 179   | registry + default definitions |
| `flexparser`  | 167,258   | 14    | Pint's declarative parser      |
| `flexcache`   | 53,419    | 10    | Pint's safe cache              |
| `platformdirs`| 191,922   | 15    | shared util (MIT)              |
| **total new** | **≈ 2.13 MiB** | 218 | pure Python, no native code    |

### License impact

`pint` is distributed under the **BSD 3-Clause** License ("New BSD"). The full
text (Copyright (c) 2012 by Hernan E. Grecco and contributors) carries the
three canonical BSD-3-Clause conditions: retain the copyright notice in source
redistributions; reproduce it in binary distributions; and do not use the
contributors' names to endorse or promote derived products without prior
written permission. The PyPI metadata records the generic classifier
`License :: OSI Approved :: BSD License`; the authoritative LICENSE text is
BSD-3-Clause, compatible with the project's Apache-2.0 license and present in
the SRL pack allowlist (`BSD-3-Clause`).

The transitive dependencies are likewise permissive: `flexparser` (BSD-3-Clause),
`flexcache` (BSD), and `platformdirs` (MIT). The CI license inventory
(`scripts/checks/license_inventory.py`) classifies all four as allowed; no
`denied` or `unknown` entries are introduced.

The pack manifest for the units core (`packs/core-units/manifest.json`)
declares the license as `BSD-3-Clause` for the bundled Pint distribution and
the adapter source.

## Reversibility

Reversible. Pint is isolated behind `src/srl/packs/adapters/units.py`: that
module is the only import site of `pint` in the SRL tree (asserted by an
architecture test in `tests/packs/test_units_adapter.py`). Removing Pint is:

1. a `pyproject.toml` change (drop `pint>=0.25.3` from `[project].dependencies`);
2. a `uv lock` to drop `pint`, `flexparser`, `flexcache`, `platformdirs`;
3. replacing the body of `units.py` with a hand-rolled or alternative algebra
   behind the same typed surface (`parse_unit`, `validate_dimensions`,
   `convert`, `Dimension`, `UnitError`).

Because the public surface is stable and is the only consumer, callers
(`wp40-gate.py`, future routers, the symbol-table validator) would not need to
change. The shipped fixtures and the pinned QUDT subset are independent of the
implementation.

## Evidence

- `pyproject.toml` declares `pint>=0.25.3` in `[project].dependencies`.
- `uv.lock` pins `pint==0.25.3` and its transitive closure (`flexparser`,
  `flexcache`, `platformdirs`).
- `src/srl/packs/adapters/units.py` is the sole `pint` import site; the
  architecture test `tests/packs/test_units_adapter.py` asserts no other module
  imports it.
- `scripts/checks/wp40-gate.py` reports the resolved Pint version in its
  `GateReceipt/v1` evidence block.
- The CI license inventory (`scripts/checks/license_inventory.py`) classifies
  Pint and its transitive dependencies as allowed (BSD/MIT family).
- `docs/architecture/units-core.md` documents the pinned QUDT subset, the UCUM
  alias table, and the precision policy.
