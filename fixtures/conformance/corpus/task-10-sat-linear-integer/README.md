# task-10: Linear integer SAT (x + y = 5, x > 0, y > 0)

Category: `sat-unsat-unknown` — Expected outcome: `WAIT_CAPABILITY`

Pins that a linear-integer-SAT claim engages the nonlinear-constraint profile; the z3 adapter is `future` in the catalog, so the router yields `WAIT_CAPABILITY` (no fabricated solver, no fabricated sat witness).
