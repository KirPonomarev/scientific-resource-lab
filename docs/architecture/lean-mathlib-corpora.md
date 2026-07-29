# Lean, Mathlib And Formal Corpora

V3.7 A09 activates the primary Lean contour as executable software evidence.
It does not grant canonical authority, does not claim external theorem
formalization correctness, and does not promote any mathematical statement.

## Native Checks

A09 uses pinned Lean `leanprover/lean4:v4.32.2`:

- Lean version: `4.32.2`
- Lean commit: `f3b06c705e6c85f5314019d5d3baab0fec5b580c`
- mathlib tag: `v4.32.2`
- mathlib revision: `905b95818eb32af7874a58b427f50c1711a5e96c`

The gate must run real executables:

- `lean --version`
- `lake --version`
- a valid theorem accepted by the Lean kernel
- an invalid theorem rejected by the Lean kernel
- `import Mathlib.Data.Nat.Basic` through a pinned Lake project
- a theorem checked through `lake env lean`
- `#print axioms` captured in the proof receipt

## Corpus Pins

The corpus/index surfaces are pinned but authority-negative:

- CSLib index: `leanprover/cslib`
  revision `93aa05752a62ad3498e734d5b75fcbff965891ce`
- Erdős Problems metadata: `teorth/erdosproblems`
  revision `3dbe8fc67b59da26f59f0fb42b006f4218fe206b`
- Formal Conjectures: `google-deepmind/formal-conjectures`
  tag `v4.32.0`, revision `9e36e7c2c7777f8ac5a3bea283cc138f3f485b1a`

The traversal seed is the real upstream file
`FormalConjectures/ErdosProblems/12.lean`, blob
`a8680192c46f4183e727e3c72ba0a940f4f07e91`, SHA-256
`7b999f416f15608a603cdc35c906ec3a860161dd2f0615490e2f898786558fd4`.
The gate fetches the pinned remote revision and verifies the blob hash and
parser markers before accepting the traversal receipt.

## T7 Boundary

A09 software evidence can run in CI or a bounded local worktree. Installing or
binding the pinned Lean/mathlib project on physical T7 remains a protected
storage operation and requires explicit target authority. Until that exists,
the stage receipt records:

`WAIT_AUTHORITY:A09_BIND_PINNED_LEAN_MATHLIB_PROJECT_TO_T7`.
