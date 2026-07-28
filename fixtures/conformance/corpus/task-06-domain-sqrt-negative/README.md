# task-06: Square root of a negative in the reals

Category: `domain-violations` — Expected outcome: `REJECT_IR`

Pins that a real-domain square-root-of-a-negative is rejected at the IR layer: `arith1.sqrt` is outside the closed MathIR allowlist, so the operator is refused before any evaluation. The domain violation is surfaced structurally, not numerically.
