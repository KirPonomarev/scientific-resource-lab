# ADR 0010: python-flint LGPL-family closure for A07

- Status: Accepted
- Date: 2026-07-31
- Work package: A07 (P0 Python core)
- Decider: SRL maintainers
- Supersedes: the A07 `WAIT_LICENSE` parking decision for `python-flint`
- Superseded by: none

## Context

A07 originally activated SymPy and mpmath while parking `python-flint` because
the published PyPI metadata declared `MIT AND LGPL-3.0-or-later`. That was the
right fail-closed state before an explicit license closure existed: the SRL pack
policy denies GPL/LGPL families by default, and no adapter may turn an
LGPL-family package ACTIVE from importability alone.

The V3.7 release target requires the FLINT/Arb/Calcium exact-arithmetic contour
to be either honestly removed from the mandatory surface or admitted through a
specific reviewed closure. The package remains important for exact algebra and
number-theory workloads, and PyPI now ships `python-flint==0.9.0` wheels for the
supported CPython and platform families. The observed metadata on 2026-07-31 is
still `MIT AND LGPL-3.0-or-later`.

## Decision

Admit `python-flint>=0.9,<0.10` into the default runtime dependency closure under
a package-specific exception recorded by
`docs/verification/srf-v3-7-a07-python-flint-license-closure-receipt.json`.

This exception is narrow:

- It applies only to the `python-flint` 0.9.x package family.
- It accepts the published `MIT AND LGPL-3.0-or-later` closure for runtime use.
- It does not permit vendored source modifications, static relinking, or private
  forks without a new review.
- It does not clear any other LGPL/GPL package, including PyMC's `cons`
  transitive dependency or cvc5 wheel license uncertainty.
- The general pack/license inventory policy still denies GPL/LGPL families by
  default.

The A07 gate must still prove real executable evidence: import `flint`, run
bounded exact-arithmetic smoke, crosscheck the results, and verify that the
license inventory admitted `python-flint` only through this exact exception.

## Obligations

Release evidence and SBOM generation must preserve upstream license metadata for
`python-flint`, FLINT, Arb and Calcium. Future changes to the package version
range, linking posture, vendoring strategy, or source modifications require a
new license review and receipt.

## Consequences

`python-flint` can now become truth-ledger `ACTIVE` only when all of the
following are true:

- the package is installed from the locked dependency closure;
- the committed A07 license-closure receipt is `ACTIVE`;
- the bounded smoke proves integer partitions, rational arithmetic, integer
  matrix powers and polynomial factorization;
- the license inventory reports the package as allowed only through
  `A07_PYTHON_FLINT_LGPL_CLOSURE_ADR_0010`.

Any other GPL/LGPL package remains `denied` or `WAIT_LICENSE`.
