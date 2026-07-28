# task-11: UNSAT contradiction (x > 1 and x < 0)

Category: `sat-unsat-unknown` — Expected outcome: `WAIT_CAPABILITY`

Pins that an UNSAT-contradiction claim engages the nonlinear-constraint profile; the z3 adapter is `future`, so the router yields `WAIT_CAPABILITY` rather than fabricating an unsat certificate.
