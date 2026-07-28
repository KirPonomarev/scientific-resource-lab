# task-01: Distributivity check (a*(b+c) = a*b + a*c)

Category: `algebraic-identities` — Expected outcome: `WAIT_CAPABILITY`

Pins that a distributivity (algebraic-identity) claim engages the `algebra_exact` profile, and because no CAS adapter ships in this codebase the router yields an honest `WAIT_CAPABILITY` rather than fabricating a symbolic check. The identity is never silently ratified.
