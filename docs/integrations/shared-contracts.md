# Shared Contract Child Mission

S19 prepares the SRF-side child mission packet for native DualContour
validation of domain-neutral schemas and conformance vectors.

Committed artifact:

- `docs/child-missions/dual-contour/shared-contract-child-mission-request.json`
- `docs/child-missions/dual-contour/dual-contour-native-startup-evidence.json`
- `docs/verification/srf-v3-7-a18-dual-contour-closeout-receipt.json`

Current target evidence:

- DualContour read-only HEAD: `a3cc68227387954417931fe08f9d66b6212f3308`
- DualContour worktree status observed clean
- Native startup command: `make contracts`
- Native startup result: `FAIL`, `provider proof identity or currentness is invalid`
- Child request id: `sha256:2edec83b076be0846fb7c72b556fdcb21794e06514e0104e2fbd15df4e457d71`
- A18 import receipt id: `sha256:977baa6a751bfcccd430f24083fe261d6dc1749ce2d2936f149069b556ea8fb1`
- A18 stage receipt id: `sha256:d60e2fe35a732cbb29107b549ca4b6c89a280a0e5128b432a2b5cb1743896b50`
- Native closeout: `WAIT_NATIVE_CHILD_CLOSEOUT`

The request is proposal-only. It does not write to DualContour, does not claim
domain truth, does not grant authority and does not bypass native repository
startup or stage ownership. The deterministic `test-hmac-sha256` signature is a
fixture protocol for local conformance; a native child agent must bind its own
repository policy before returning any closeout.

The A18 SRF gate is intentionally fail-closed: without a native closeout it
passes only as a truthful `WAIT_NATIVE_CHILD_CLOSEOUT` projection. A future
native closeout must match the child request id, source and target heads,
schema hashes, conformance-vector hash, producer and consumer `PASS` suites, and
authority-negative fields before SRF can import it as active evidence.
