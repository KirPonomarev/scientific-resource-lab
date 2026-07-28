# Units semantic core conformance vectors (WP-E40)

This directory holds the conformance vectors for the SRL units semantic core
(`srl.packs.adapters.units`), introduced in WP-E40. It replaces the
fixture-scoped dimensional checker from WP-B11 with a real unit algebra over a
pinned QUDT subset.

## Layout

- `codata/` — six `ConstantRef/v1` fixtures for the CODATA 2018 fundamental
  constants (the 2019 SI redefinition values): speed of light `c`, Planck
  constant `h`, Boltzmann constant `k_B`, Avogadro constant `N_A`, elementary
  charge `e`, and electron mass `m_e`. Values are full decimal-string
  expansions (no exponent) so they survive a round trip with no float coercion;
  `source` is `CODATA2018`, `vintage` is `CODATA-2018`. The five defining
  constants (`c`, `h`, `k_B`, `N_A`, `e`) are exact (`uncertainty: null`);
  `m_e` carries its measured one-standard-deviation uncertainty.
- `positive/` — coherent unit sets that the units adapter MUST accept (SI base
  + derived, SI-coherence identities, UCUM alias forms).
- `negative/` — documents the adapter MUST reject (dimension mismatch, unknown
  unit, malformed UCUM), with the contract reason named in each
  `expected_error.json`.

## Positive vectors

- `p01-si-base-units.input.json` — the seven SI base units (`m`, `kg`, `s`, `A`,
  `K`, `mol`, `cd`) each parse to their singleton dimension.
- `p02-si-derived-coherent.input.json` — the coherent SI derived units (`N`,
  `Pa`, `J`, `W`, `Hz`, `V`, `C`, `ohm`) parse and reduce correctly.
- `p03-si-coherence-identity.input.json` — `kg*m/s^2` and `N` are dimensionally
  equivalent (the Newton identity); `J` and `N*m` are equivalent.
- `p04-ucum-alias-forms.input.json` — UCUM dotted/signed-exponent notation
  (`kg.m.s-2`, `m.s-1`, `kg.m2.s-2`) and the `Ohm` alias parse to the same
  dimensions as their Python-notation forms.
- `p05-codata-units-parse.input.json` — every CODATA-2018 constant's `unit`
  field parses to a dimension in the pinned subset.
- `p06-conversion-identity.input.json` — coherent conversions are exact decimal
  identities: `1 kg*m/s^2 -> 1 N`, `1 J -> 1 N*m`.

## Negative vectors

- `negative/n01-dimension-mismatch.input.json` — `kg` vs `m` (mass vs length) is
  rejected as `CONTRACT_INVALID` before any compute.
- `negative/n02-unknown-unit.input.json` — `fortnight` (a Pint-known but
  out-of-subset unit) is rejected as `CONTRACT_INVALID` with no silent fallback.
- `negative/n03-malformed-ucum.input.json` — a structurally malformed unit
  string is rejected as `CONTRACT_INVALID`.
- `negative/n04-dimensionally-invalid-convert.input.json` — converting `1 kg`
  to `m` is rejected as a dimensional mismatch (`CONTRACT_INVALID`).
