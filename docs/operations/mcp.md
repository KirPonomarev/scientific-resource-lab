# Read-only stdio MCP server (WP-F51)

This document describes the read-only Model Context Protocol (MCP) server
introduced in WP-F51. The server exposes the SRL planning, claims, knowledge,
catalog, and execution-inspection surfaces to an MCP host **without ever
executing, mutating, or opening the network**. It speaks JSON-RPC 2.0 over
Content-Length-framed stdio — hand-rolled on the standard library plus the
existing SRL packages, with **no `mcp` PyPI dependency** (see
`docs/adr/0004-mcp-handrolled-stdio.md`).

> A green MCP result means a tool **completed** and produced a typed envelope.
> It never means a scientific claim is *supported* or that an authority was
> granted. The MCP server is a read-only control surface, not an evidence or
> execution surface.

## Read-only guarantee (load-bearing)

The server is read-only by construction. It holds an in-memory, offline
`MethodContext` and **never**:

- opens a network **listener** or socket;
- runs a **scheduler** or launches a process;
- writes a **database** or the canonical artifact store;
- reads a **secret** or credential (the knowledge retriever is credential-free
  by design);
- streams a **raw dataset** (knowledge results are content-addressed receipts,
  never raw response bytes carried as authority).

The two safety consts (`canonical_writes=0`, `grants_authority=false`) are
echoed on **every** method result so a host can verify the read-only property
structurally. The WP-F51 gate (`scripts/checks/wp51-gate.py`) asserts that the
server process opens no listener socket and uses stdio file descriptors only.

## What the server refuses

Any method or tool name that looks like it runs or mutates (`run`, `execute`,
`mutate`, `write`, `delete`, `create`, `materialize`, `spawn`, …) is rejected
with JSON-RPC error **`-32601`** (method not found). The structured `data`
carries `fail_reason: "METHOD_NOT_FOUND"`, `read_only: true`, and a note
explaining the refusal. There is **no** execution method on this server.

## Running the server

```bash
uv run python -m srl.mcp
```

The server reads Content-Length-framed JSON-RPC 2.0 messages from stdin and
writes one framed response per request to stdout until stdin reaches EOF. It
runs offline by default (the knowledge transport refuses with a typed
`WAIT_ENVIRONMENT` when no transport is configured).

## MCP handshake

`initialize` advertises the protocol version, the single `tools` capability,
and the server info:

```jsonc
// -> request
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
// <- response.result
{
  "protocolVersion": "2025-06-18",
  "capabilities": {"tools": {}},
  "serverInfo": {"name": "srl-mcp", "version": "0.2.0"}
}
```

`tools/list` returns exactly the seven P0 tools below.

## The seven read-only P0 tools

| Tool                  | Mirrors            | Description                                            |
|-----------------------|--------------------|--------------------------------------------------------|
| `list_capabilities`   | `srlab catalog list`   | List the shipped capability catalog entries.       |
| `inspect_capability`  | `srlab catalog inspect`| Inspect one catalog entry by `profile`.            |
| `validate_claim`      | `srlab claim validate` | Validate a `ScientificClaim/v1` (schema + invariants). |
| `build_plan`          | `srlab plan build`     | Build a `ScienceLabPlan/v1` from a request + claim.|
| `inspect_run`         | `srlab run verify`     | Inspect a `RunReceipt/v1` (never executes).        |
| `search_knowledge`    | `srlab knowledge query`| Search a declared knowledge endpoint (offline default). |
| `build_export_packet` | *(WP-I80)*             | Typed `WAIT_CAPABILITY` stub (exporter not yet landed). |

Every tool result is a typed `McpMethodResult/v1` envelope:

```jsonc
{
  "schema_version": "McpMethodResult/v1",
  "method": "validate_claim",
  "status": "SUCCESS",            // or a typed wait: INVALID / WAIT_CAPABILITY / WAIT_ENVIRONMENT / ...
  "result": { /* method-specific */ },
  "canonical_writes": 0,
  "grants_authority": false
}
```

### Honest typing

- `build_plan` — the shipped catalog marks every adapter `future` /
  `remote_required`, so every applicable profile routes `WAIT_CAPABILITY`
  honestly. The router never fabricates a local substitute for a capability
  that is not present.
- `search_knowledge` — with the default offline transport, returns a typed
  `WAIT_ENVIRONMENT` (no network configured). A caller that wants live
  retrieval must inject a real transport; the server never opens the network
  on its own.
- `build_export_packet` — the export materializer lands in **WP-I80**. This
  tool does **not** fake an export: it returns a typed `WAIT_CAPABILITY`
  carrying the exact reason and the WP it depends on.

## Framing and defenses

The stdio transport wraps each JSON-RPC message in a `Content-Length` header
frame (the same framing the MCP specification uses). The framing layer
(`src/srl/mcp/framing.py`) is defensive on every boundary an untrusted host
could abuse:

| Condition                          | JSON-RPC code | `fail_reason`      |
|------------------------------------|---------------|--------------------|
| Declared `Content-Length` > 1 MiB  | `-32600`      | `FRAME_TOO_LARGE`  |
| Malformed header / missing length  | `-32700`      | `FRAME_MALFORMED`  |
| Body is not valid JSON             | `-32700`      | `FRAME_PARSE_ERROR`|

The 1 MiB cap is enforced **before** any body bytes are buffered, so an
oversized header cannot exhaust memory. A frame-level error surfaces a typed
JSON-RPC error with `id: null` and the loop continues — the server does not
crash on a hostile frame.

## Acceptance gate

Run the WP-F51 gate with `uv`:

```bash
uv run python scripts/checks/wp51-gate.py
```

The gate spawns `python -m srl.mcp` as a subprocess over pipes and exercises:

- **F51-01** — `initialize` + `tools/list` return exactly the seven P0 tools;
- **F51-02** — `validate_claim` on a fixture claim returns a typed result;
- **F51-03** — `build_plan` returns a plan with honest `WAIT_CAPABILITY` steps;
- **F51-04** — a mutation attempt (`run.execute`, `tools/call(execute)`) is
  rejected with JSON-RPC `-32601`;
- **F51-05** — an oversized and a malformed frame each produce a typed error;
- **F51-06** — the server opens no listener/socket (stdio only);
- **F51-07** — `build_export_packet` returns a typed `WAIT_CAPABILITY` stub.

The gate prints one canonical `GateReceipt/v1` JSON line and exits `0` only if
every check PASSes. No check makes a live network call.

## CI

`.github/workflows/mcp.yml` runs the `mcp-gate (WP-F51)` job on every
`pull_request`, `push` to `main`, and `merge_group`. The job pins the same
`actions/checkout` and `astral-sh/setup-uv` SHAs as `ci.yml`, runs on
`ubuntu-24.04`, and times out after 15 minutes. It runs `uv sync --locked`
then `uv run python scripts/checks/wp51-gate.py`.

## Module layout

| Module                  | Responsibility                                             |
|-------------------------|------------------------------------------------------------|
| `src/srl/mcp/framing.py`| Content-Length stdio framing + defensive parsing.          |
| `src/srl/mcp/methods.py`| The seven read-only P0 method implementations.             |
| `src/srl/mcp/server.py` | JSON-RPC 2.0 dispatch, handshake, mutation rejection.      |
| `src/srl/mcp/__main__.py`| `python -m srl.mcp` entry point.                          |
| `scripts/checks/wp51-gate.py` | The `GateReceipt/v1` acceptance gate.                |
| `tests/mcp/`            | Hermetic framing, methods, server, and subprocess tests.   |
