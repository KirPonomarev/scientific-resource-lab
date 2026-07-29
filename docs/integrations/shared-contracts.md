# Shared Contract Child Mission

S19 prepares the SRF-side child mission packet for native DualContour
validation of domain-neutral schemas and conformance vectors.

Committed artifact:

- `docs/child-missions/dual-contour/shared-contract-child-mission-request.json`

Current target evidence:

- DualContour read-only HEAD: `a3cc68227387954417931fe08f9d66b6212f3308`
- DualContour worktree status observed clean
- Native closeout: `WAIT_NATIVE_CHILD_CLOSEOUT`

The request is proposal-only. It does not write to DualContour, does not claim
domain truth, does not grant authority and does not bypass native repository
startup or stage ownership. The deterministic `test-hmac-sha256` signature is a
fixture protocol for local conformance; a native child agent must bind its own
repository policy before returning any closeout.
