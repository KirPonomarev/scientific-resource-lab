"""Read-only stdio MCP server for SRL (WP-F51).

This package exposes the SRL planning, claims, knowledge, catalog, and
execution-inspection surfaces as a read-only Model Context Protocol server
over stdio. It is standard-library + existing-SRL-packages only — no ``mcp``
PyPI dependency (see ``docs/adr/0004-mcp-handrolled-stdio.md``).

The server speaks JSON-RPC 2.0 wrapped in ``Content-Length`` frames
(:mod:`srl.mcp.framing`), handles the MCP ``initialize`` / ``tools/list`` /
``tools/call`` meta-methods (:mod:`srl.mcp.server`), and dispatches exactly
seven read-only P0 tools (:mod:`srl.mcp.methods`). No execution or mutation
method is exposed; any such request is rejected with JSON-RPC ``-32601``.

Read-only guarantee
-------------------
The server holds an in-memory, offline :class:`~srl.mcp.methods.MethodContext`
and never opens a socket, never writes canonical state, and never carries a
secret. The two safety consts (``canonical_writes`` and ``grants_authority``)
are echoed on every method result.
"""

from __future__ import annotations

from srl.mcp.framing import (
    FRAME_MALFORMED_FAIL_REASON,
    FRAME_PARSE_FAIL_REASON,
    FRAME_TOO_LARGE_FAIL_REASON,
    MAX_FRAME_BYTES,
    FrameError,
    encode_frame,
    parse_content_length,
)
from srl.mcp.methods import (
    MCP_RESULT_SCHEMA,
    WAIT_CAPABILITY_FAIL_REASON,
    WAIT_ENVIRONMENT_FAIL_REASON,
    McpMethodError,
    MethodContext,
    OfflineTransport,
)
from srl.mcp.server import (
    MCP_ERROR_SCHEMA,
    METHOD_NOT_FOUND_FAIL_REASON,
    P0_TOOLS,
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    McpServer,
    serve,
)

__all__ = [
    "FRAME_MALFORMED_FAIL_REASON",
    "FRAME_PARSE_FAIL_REASON",
    "FRAME_TOO_LARGE_FAIL_REASON",
    "MAX_FRAME_BYTES",
    "MCP_ERROR_SCHEMA",
    "MCP_RESULT_SCHEMA",
    "METHOD_NOT_FOUND_FAIL_REASON",
    "P0_TOOLS",
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "WAIT_CAPABILITY_FAIL_REASON",
    "WAIT_ENVIRONMENT_FAIL_REASON",
    "FrameError",
    "McpMethodError",
    "McpServer",
    "MethodContext",
    "OfflineTransport",
    "encode_frame",
    "parse_content_length",
    "serve",
]
