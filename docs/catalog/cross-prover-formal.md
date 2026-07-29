# Cross-Prover Formal Contours

S13 adds independent formal contours without claiming theorem equivalence across
different logics.

- `lean.primary`: ACTIVE through the S12 Lean/mathlib admission receipt.
- `rocq.primary`: Rocq/Coq contour, `WAIT_TOOLCHAIN` until a native executable is available.
- `isabelle.hol`: Isabelle/HOL contour, `WAIT_TOOLCHAIN` until a native executable is available.
- `hol4.primary`: HOL4 contour, `WAIT_TOOLCHAIN` until a native executable is available.

Translation manifests compare logics and assumptions. They always set
`equivalence_claimed=false` and require independent review before any downstream
statement can treat two prover artifacts as related.
