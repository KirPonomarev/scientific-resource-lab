"""``python -m srl.mcp`` entry point: run the read-only stdio MCP server.

Reads Content-Length-framed JSON-RPC 2.0 messages from stdin and writes one
framed response per request to stdout until stdin reaches EOF. The server is
read-only and offline by default; it never opens a socket.
"""

from __future__ import annotations

from srl.mcp.server import serve

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve())
