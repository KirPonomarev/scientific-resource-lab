# Interface Convergence

S10 routes common user-facing interface semantics through
`srl.interfaces.InterfaceService`.

The service is read-only and authority-negative. It backs:

- CLI `doctor`, `version`, `catalog list`, `catalog inspect`, and
  `labctl enter`;
- MCP `list_capabilities` and `inspect_capability`;
- the portal build report's interface manifest.

Every shared service result carries or preserves `canonical_writes: 0` and
`grants_authority: false` where the public surface exposes those fields. The
service does not run experiments, open network transports, mutate native health,
or replace repository governance. Surfaces remain wrappers: CLI handles process
exit and stdout/stderr, MCP handles JSON-RPC framing, and portal handles static
HTML generation.
