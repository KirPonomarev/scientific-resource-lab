# P0 Core Admission

S11 records P0 components independently. An installed package is not enough for
scientific authority, and one solver cannot inherit another solver's evidence.

Current governed runtime after V3.7 A07 partial activation:

- `ACTIVE`: NumPy, SciPy, Pint units, Z3, SymPy, mpmath.
- `DEGRADED`: cvc5, held behind license/runtime closure.
- `WAIT_LICENSE`: FLINT/Arb/Calcium through `python-flint`.
- `WAIT_CAPABILITY`: PARI/GP, Maxima, GAP, Singular.

The `P0CoreAdmissionBundle/v1` carries method cards, cross-check requirements,
component status lists, and `integration_authority: none`. It is an admission
bundle for compute capability only. It never promotes a scientific claim.
