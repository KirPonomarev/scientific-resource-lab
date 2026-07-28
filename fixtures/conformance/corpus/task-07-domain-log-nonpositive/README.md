# task-07: Logarithm of a non-positive number

Category: `domain-violations` — Expected outcome: `REJECT_IR`

Pins that a log-of-non-positive is rejected at the IR layer: `arith1.log` is outside the closed MathIR allowlist (log is intentionally excluded to keep evaluation platform-independent), so the operator is refused.
