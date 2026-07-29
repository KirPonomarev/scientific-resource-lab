# Lean Formal Pack

V3.7 A09 activates Lean and mathlib as the primary formal environment:

- Lean toolchain: `leanprover/lean4:v4.32.2`
- Lean commit: `f3b06c705e6c85f5314019d5d3baab0fec5b580c`
- mathlib tag: `v4.32.2`
- mathlib revision: `905b95818eb32af7874a58b427f50c1711a5e96c`

The adapter records kernel acceptance for the declared Lean statement only.
It does not claim that the statement is the correct formalization of an
external theorem, does not update empirical axes, and grants no authority.

A09 evidence requires:

- native `lean` and `lake` version probes;
- Lean kernel acceptance of a valid theorem;
- Lean kernel rejection of an invalid theorem;
- `import Mathlib.Data.Nat.Basic` through a pinned Lake project;
- `#print axioms` recorded in theorem receipts;
- pinned corpus traversal for CSLib, Erdős Problems metadata and Formal
  Conjectures.

Physical T7 binding of the pinned Lean/mathlib cache remains protected by
`WAIT_AUTHORITY:A09_BIND_PINNED_LEAN_MATHLIB_PROJECT_TO_T7`.
