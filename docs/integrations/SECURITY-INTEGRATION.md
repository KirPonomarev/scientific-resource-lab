# Security Integration

S21 implements only the SRF-side inactive Security bridge. It maps sanitized
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
