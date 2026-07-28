# task-08: Decimal string preservation (0.1 stays 0.1)

Category: `exact-arithmetic` — Expected outcome: `PASS`

Pins that a decimal constant is preserved exactly as a decimal string through the IR (the decimal-string policy forbids exponents and non-finite floats); the IR validates cleanly, so the structural contract admits with no capability waiting and no violation raised.
