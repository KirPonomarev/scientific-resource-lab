# task-26: Unproven obligation stays CHECKED-not-PROVEN

Category: `proof-obligations` — Expected outcome: `WAIT_CAPABILITY`

Pins that an unproven-proof-obligation engages `theorem_or_proof_obligation`; no proof adapter ships, so the router yields `WAIT_CAPABILITY` — the obligation is never silently promoted to proven (mirrors the evidence-model invariant `proven_requires_certificate`).
