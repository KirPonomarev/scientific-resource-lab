# LawMiner And Dynamical Discovery

S15 provides a bounded validation layer for candidate law and one-step dynamics
discovery. The active implementation is a deterministic linear baseline used to
prove split, null and candidate-only receipt semantics.

A12 activates the mandatory discovery/dynamics engines through a separate real
smoke gate and hash-bound receipt:

- PySR: `ACTIVE` through the explicit Julia-backed symbolic-regression smoke.
- PySINDy: `ACTIVE` through sparse dynamics identification on a bounded
  synthetic derivative task.
- PyDMD: `ACTIVE` through dynamic mode decomposition on rank-2 exponential
  snapshots.

The remaining legacy wishlist engines are formally replaced for v2 A12 rather
than silently treated as successes: SR4MDL, Operon, gplearn, AI-Feynman,
pyKoopman and dysts.

Validation receipts carry null metrics, reject train/validation overlap, set
`promotion_allowed=false`, and never materialize a prospective holdout.
