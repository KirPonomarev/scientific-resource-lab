# Sandbox Boundary

SRF uses trust-class admission before a pack can run. The decision is made by
`srl.security.sandbox_policy` from a `HostCapabilityManifest/v1`; chat, urgency,
or adapter availability never grant missing capabilities.

| Class | Local admission requirement | Missing requirement |
|---|---|---|
| `T0` | process limits, sanitized env, private scratch, output cap | `WAIT_COMPUTE_NODE` |
| `T1` | `T0` plus read-only input and no inherited secrets | `WAIT_COMPUTE_NODE` |
| `T2` | `T1` plus container isolation and network deny | `WAIT_COMPUTE_NODE` |
| `T3` | `T1` plus microVM isolation, network deny and taint tracking | `WAIT_COMPUTE_NODE` |
| `T4` | no secrets, egress allowlist, redaction, budget receipt and provider receipt | `WAIT_AUTHORITY` if budget/provider authority is missing |

The local Python runner can prove only the subprocess properties it implements:
sanitized environment, private scratch, read-only input, output caps, no
inherited secrets and POSIX process limits where available. It does not claim a
container, microVM, network namespace, taint engine, egress allowlist, budget
receipt or provider receipt.

That means a normal operator Mac admits `T0` and `T1` bounded work only. `T2`
and `T3` return `WAIT_COMPUTE_NODE` unless a native host manifest proves the
stronger boundary. `T4` returns `WAIT_AUTHORITY` until budget/provider evidence
is present. There is no fallback that silently runs a stronger trust class in a
weaker sandbox.

The existing execution runner still enforces the per-run cage:

- parent environment is not inherited;
- input is canonical JSON and read-only;
- scratch is unique and private;
- child runs through the fixed `srl.execution.child` entrypoint;
- POSIX limits, wall timeout, output caps and process-group reaping apply;
- receipts are written only after successful output validation.

Sandbox admission is an execution safety decision, not scientific evidence and
not canonical authority. Every admission receipt carries `canonical_writes=0`
and `grants_authority=false`.
