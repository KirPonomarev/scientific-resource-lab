# ADR 0004: Hand-rolled JSON-RPC 2.0 over stdio for the MCP server

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-F51 (Read-only stdio MCP)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

WP-F51 exposes the SRL planning, claims, knowledge, catalog, and
execution-inspection surfaces as a read-only Model Context Protocol (MCP)
server over stdio. MCP wraps JSON-RPC 2.0 messages in a `Content-Length`
header frame (the same framing LSP uses). The server must:

1. Speak the MCP handshake (`initialize`, `tools/list`, `tools/call`) and
   dispatch exactly seven read-only P0 tools.
2. Run **read-only**: never execute, mutate, open a listener, or touch the
   canonical store. The WP-F51 plan constrains dependencies to stdlib +
   `jsonschema` (no new runtime dependency without an ADR).
3. Reuse the existing, well-tested SRL packages (planning router/planner,
   claims validation, knowledge retriever, catalog) — the value is in the
   read-only bridge, not in re-implementing JSON-RPC.

The choice affects:

1. The supply-chain surface (a runtime dependency is imported by every
   consumer that runs the MCP server, and MCP hosts run the server as a
   subprocess).
2. How much of the MCP feature surface SRL must carry (the server needs only
   `tools`; it does not need resources, prompts, sampling, roots, or
   streaming).
3. The read-only guarantee: the dependency must not pull in an async runtime,
   a socket server, or a scheduler that could undermine the no-listener
   property the WP-F51 gate asserts.

## Alternatives considered

### 1. Hand-roll JSON-RPC 2.0 over Content-Length stdio (chosen)

- The MCP subset SRL needs is tiny: three meta-methods (`initialize`,
  `tools/list`, `tools/call`) and seven tool dispatches. JSON-RPC 2.0 is a
  small, stable spec (one request/response/notification shape, five standard
  error codes); the `Content-Length` frame is a header line + blank line +
  body.
- The framing layer (`src/srl/mcp/framing.py`) is ~150 lines of defensive
  parsing (oversized cap, malformed header, malformed JSON). The dispatcher
  (`src/srl/mcp/server.py`) is an explicit table with read-only enforcement.
- Reuses `srl.contracts.canonical.dumps` for byte-stable bodies and the
  typed-fail-reason registry every other SRL surface uses, so error typing is
  uniform across the CLI, the gate receipts, and MCP.
- No new runtime dependency; the server runs under the stdlib alone (plus the
  existing `jsonschema` used by the contracts layer the methods reuse).
- The read-only guarantee is structural: the server holds an in-memory,
  offline `MethodContext` and the framing layer touches only the stdio file
  descriptors. The WP-F51 gate asserts no listener socket is opened.

### 2. Adopt the official `mcp` Python SDK

- The reference implementation; would handle handshake, capability
  negotiation, and framing for free.
- Pulls in an async runtime (`anyio`/`pydantic`/`httpx` transitively), a much
  larger supply-chain surface than the problem warrants, and abstractions
  (resources, prompts, sampling, streaming) SRL does not use.
- The async runtime and built-in transports work against the WP-F51 plan's
  explicit read-only, no-listener, stdlib-where-possible posture: asserting
  "no scheduler, no socket" is harder when the SDK owns the event loop.
- Adds a fast-moving dependency (the MCP spec and SDK are evolving rapidly in
  2025-2026); pinning is possible but the maintenance coupling is real.

### 3. A tiny, well-licensed third-party JSON-RPC library

- A minimal sync JSON-RPC library (e.g. `jsonrpcserver`) would handle the
  envelope but not the `Content-Length` framing, which is the part that needs
  defensive care. The framing would still be hand-rolled.
- Adds a dependency for the trivial part (envelope) while leaving the hard
  part (framing, read-only enforcement, typed errors) in-house anyway. The
  cost/benefit is worse than hand-rolling both.

## Decision

Hand-roll JSON-RPC 2.0 over `Content-Length`-framed stdio. No new runtime
dependency is introduced; `pyproject.toml` and `uv.lock` are unchanged.

The implementation is split across three modules under `src/srl/mcp/`:

- `framing.py` — `Content-Length` frame encode/decode with a 1 MiB cap,
  malformed-header refusal, and malformed-JSON refusal (typed fail reasons
  `FRAME_TOO_LARGE`, `FRAME_MALFORMED`, `FRAME_PARSE_ERROR`).
- `methods.py` — the seven read-only P0 methods, reusing the planning router,
  claims validator, knowledge retriever (offline by default), catalog, and
  execution-receipt inspector. Every result echoes the safety consts
  (`canonical_writes=0`, `grants_authority=false`).
- `server.py` — JSON-RPC dispatch: `initialize` (protocol version + `tools`
  capability + serverInfo), `tools/list` (exactly seven tools), `tools/call`
  (typed dispatch). Any run/execute/mutate method is rejected with JSON-RPC
  `-32601` and a typed `METHOD_NOT_FOUND` note.

The server is invoked as `python -m srl.mcp` and reads/writes only stdio.

## Consequences

### Positive

- Zero new runtime dependency; the read-only, no-listener guarantee is
  structural and gate-enforced, not dependent on SDK configuration.
- Uniform error typing: MCP errors carry the same typed `fail_reason` registry
  the CLI and gate receipts use, so a host routes them identically.
- The MCP surface SRL does not need (resources, prompts, sampling, streaming)
  is simply absent — no dead abstraction surface to audit.

### Negative

- SRL owns the JSON-RPC envelope and the `Content-Length` framing. Both are
  small and stable, but future MCP spec additions (e.g. a new meta-method)
  require a hand edit here rather than an SDK bump.
- No async/concurrency: the server handles one request at a time over a single
  stdio pipe. This is intentional and correct for a read-only MCP tool server
  (an MCP host serializes tool calls over one subprocess), but it would be the
  wrong shape for a high-throughput service.

### Security impact

The server imports no networking, scheduling, or storage machinery beyond the
existing SRL packages the methods reuse. The framing layer performs no I/O of
its own beyond the stdin/stdout file descriptors; the methods perform no
canonical writes and no network fetches (the knowledge transport is offline by
default). The WP-F51 gate (`scripts/checks/wp51-gate.py`, check F51-06) asserts
the server process opens no listener socket and writes nothing to stderr.

### Resource impact

Negligible. The server is request/response over one pipe; each tool dispatch
reuses the existing admission-time code paths. Well within the 15-minute CI
budget.

### License impact

No new dependency, so no new license terms. The hand-rolled code is
Apache-2.0 like the rest of `srl`.

## Reversibility

Reversible. If a future WP needs richer MCP features (resources, prompts,
streaming), adopting the official `mcp` SDK is a drop-in replacement behind
the stable `src/srl/mcp/methods.py` interface: the seven method implementations
are plain `(ctx, args) -> typed_result` functions independent of the transport.
The framing and dispatch modules would be replaced; the methods and their
typed envelopes would not.

## Evidence

- `src/srl/mcp/framing.py`, `methods.py`, `server.py`, `__main__.py` implement
  the hand-rolled server.
- `pyproject.toml` and `uv.lock` are unchanged (no new runtime dependency).
- `scripts/checks/wp51-gate.py` asserts the seven P0 tools, the mutation
  rejection, the frame defenses, and the no-listener property.
- `.github/workflows/mcp.yml` runs the gate on every pull request.
- `docs/operations/mcp.md` documents the methods and the read-only guarantee.
