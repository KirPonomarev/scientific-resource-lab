# Security Integration

S21 implements only the SRF-side inactive Security bridge. A20 adds the native
closeout import projection. It maps sanitized
scientific service requests and observations through shared SRF envelopes while
leaving native execution, policy and evidence handling inside the Security
repository.

Boundaries:

- `activation_state=INACTIVE`
- `native_executor_boundary=ebashim`
- `security_actions=0`
- `target_actions=0`
- `D2_D3_transfers=0`
- `direct_scanner_control=false`

The adapter accepts only D0/D1 public-safe advisory material. It rejects
target identifiers, exploit or payload material, credentials, private paths,
D2/D3 labels, prompt-injection text, authority claims, non-ebashim executor
claims, duplicate observations and stale Security HEAD bindings.

At the recorded V3.7 evidence generation, no native Security closeout was
present, so SRF emitted `WAIT_NATIVE_CHILD_CLOSEOUT` plus
`WAIT_SECURITY_HEALTH` rather than treating the bridge as active. These are
historical bound observations, not current Security runtime truth. Current
state requires exact native bootstrap evidence; without it, report
`NOT_CHARACTERIZED`. A native closeout, when supplied later, must be
hash-bound to the child request, preserve `ebashim`, pass native/SRF/
containment suites, keep all action and transfer counters at zero, and grant no
scientific or Security authority.
