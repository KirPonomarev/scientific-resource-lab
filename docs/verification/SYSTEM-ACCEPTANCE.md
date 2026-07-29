# System Acceptance Verification

S25 binds the accepted SRF candidate to a layered validation matrix and focused
failure evidence. The receipt is `docs/verification/system-acceptance-receipt.json`.

The receipt is authority-negative: it grants no canonical write permission, no
live action permission, no trading permission and no target-specific security
permission. Protected lanes remain explicit `WAIT_*` states.

Focused failure routes are intentionally mapped to existing executable checks:

| Focus | Evidence route |
| --- | --- |
| crash | CAS transaction crash matrix and adversarial runner conformance |
| duplicate | spool idempotency and bridge duplicate-import guards |
| revoke | pack revocation and heavy remote image revocation guards |
| corrupt | CAS corruption, materialization and bridge/export corrupt-input guards |
| stale | SRF pulse, cross-head bridge and stale hash guards |
| injection | runner, export and bridge injection adversarial suites |
| low disk | T7 capacity policy and storage gate |

The S25 candidate is accepted only when every required matrix command exits
cleanly on the same candidate tree and all residual waits are machine-visible.
The default dependency closure is restored before license-sensitive gates; the
Bayesian `WP-H71a` gate runs last with the declared optional `bayesian` extra so
that optional proof does not contaminate default license inventory evidence.
