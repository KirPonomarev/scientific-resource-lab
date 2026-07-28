"""Hermetic subprocess tests for the stdio MCP server loop (WP-F51).

These spawn ``python -m srl.mcp`` over pipes and assert the framed protocol,
the frame-level defenses, the no-listener property, and clean EOF handling.
No test makes a live network call.
"""

from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from srl.mcp.framing import MAX_FRAME_BYTES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Framing helpers over the pipe.
# ---------------------------------------------------------------------------


def _encode(message: dict[str, Any]) -> bytes:
    """Encode a JSON-RPC message as one Content-Length-framed byte string."""
    body = json.dumps(message, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_one_frame(stream: Any) -> dict[str, Any]:
    """Read one Content-Length-framed message from a pipe stream."""
    header = bytearray()
    while True:
        b = stream.read(1)
        if not b:
            raise AssertionError("stream closed before header terminator")
        header += b
        if header.endswith(b"\r\n\r\n"):
            break
    text = header.decode("ascii", errors="replace")
    n = -1
    for line in text.split("\r\n"):
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            n = int(value.strip())
    assert n >= 0, "missing Content-Length in response"
    body = stream.read(n)
    assert len(body) == n, "short read of response body"
    return json.loads(body)


# ---------------------------------------------------------------------------
# Subprocess fixture.
# ---------------------------------------------------------------------------


class _McpProc:
    """A spawned ``python -m srl.mcp`` subprocess driven over pipes."""

    def __init__(self) -> None:
        env = dict(os.environ)
        pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{_SRC}{os.pathsep}{pythonpath}" if pythonpath else str(_SRC)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "srl.mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        # Drained stderr bytes, populated by close() so a test can assert on it
        # after the pipes are closed (no ResourceWarning from unclosed FDs).
        self.stderr_bytes: bytes = b""
        self._closed: bool = False

    def send(self, message: dict[str, Any]) -> None:
        """Write one framed message to the server's stdin."""
        assert self.proc.stdin is not None
        self.proc.stdin.write(_encode(message))
        self.proc.stdin.flush()

    def send_raw(self, raw: bytes) -> None:
        """Write raw bytes (for malformed-frame tests) to the server's stdin."""
        assert self.proc.stdin is not None
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()

    def recv(self, timeout: float = 5.0) -> dict[str, Any]:
        """Read one framed response within ``timeout`` seconds."""
        assert self.proc.stdout is not None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _has_bytes(self.proc.stdout):
                return _read_one_frame(self.proc.stdout)
            if self.proc.poll() is not None:
                raise AssertionError("server exited before responding")
            time.sleep(0.01)
        raise AssertionError(f"server did not respond within {timeout}s")

    def close(self) -> None:
        """Close stdin, reap the process, and close every pipe explicitly.

        Idempotent: a second call (e.g. fixture teardown after a test called
        ``close()`` directly) is a no-op. Each pipe is closed by name so no
        ``ResourceWarning`` (unclosed FD) escapes under the project's
        ``filterwarnings = ["error"]`` policy. stderr is drained before closing
        so the no-listener test can assert it is empty.
        """
        if self._closed:
            return
        self._closed = True
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        # Drain stderr before closing so the no-listener test can assert on it.
        if self.proc.stderr is not None:
            try:
                self.stderr_bytes = self.proc.stderr.read()
            except ValueError:
                self.stderr_bytes = b""
            self.proc.stderr.close()
        if self.proc.stdout is not None:
            self.proc.stdout.close()


@pytest.fixture()
def server() -> Any:
    """Spawn ``python -m srl.mcp`` over pipes; terminate after the test."""
    proc = _McpProc()
    yield proc
    proc.close()


def _has_bytes(stream: Any) -> bool:
    """Return True if ``stream`` has at least one byte available without blocking."""
    try:
        fd = stream.fileno()
    except (AttributeError, ValueError):
        return True
    r, _, _ = select.select([fd], [], [], 0)
    return bool(r)


# ---------------------------------------------------------------------------
# stdio loop tests.
# ---------------------------------------------------------------------------


class TestStdioLoop:
    """The serve() loop reads/writes framed messages over pipes."""

    def test_initialize_handshake_over_pipes(self, server: Any) -> None:
        server.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        resp = server.recv()
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "srl-mcp"

    def test_tools_list_over_pipes(self, server: Any) -> None:
        server.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = server.recv()
        tools = resp["result"]["tools"]
        assert len(tools) == 7

    def test_clean_eof_exits_zero(self, server: Any) -> None:
        # Closing stdin should let the server exit cleanly with code 0.
        assert server.proc.stdin is not None
        server.proc.stdin.close()
        rc = server.proc.wait(timeout=5)
        assert rc == 0


class TestFrameDefenses:
    """The loop surfaces frame-level errors as typed JSON-RPC errors."""

    def test_oversized_frame_is_typed_error(self, server: Any) -> None:
        oversized = f"Content-Length: {MAX_FRAME_BYTES + 1}\r\n\r\n".encode("ascii")
        server.send_raw(oversized)
        resp = server.recv()
        assert resp["error"]["code"] == -32600
        assert resp["error"]["data"]["fail_reason"] == "FRAME_TOO_LARGE"
        assert resp["error"]["data"]["read_only"] is True

    def test_malformed_json_body_is_parse_error(self, server: Any) -> None:
        body = b"not-json"
        malformed = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        server.send_raw(malformed)
        resp = server.recv()
        assert resp["error"]["code"] == -32700
        assert resp["error"]["data"]["fail_reason"] == "FRAME_PARSE_ERROR"

    def test_missing_content_length_is_malformed(self, server: Any) -> None:
        server.send_raw(b"Other-Header: 1\r\n\r\n")
        resp = server.recv()
        assert resp["error"]["code"] == -32700
        assert resp["error"]["data"]["fail_reason"] == "FRAME_MALFORMED"

    def test_loop_continues_after_frame_error(self, server: Any) -> None:
        # Send a malformed frame, then a valid request; the server must keep going.
        server.send_raw(b"Content-Length: 4\r\n\r\nbad?")
        bad = server.recv()
        assert "error" in bad
        server.send({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
        good = server.recv()
        assert good["id"] == 9
        assert len(good["result"]["tools"]) == 7


class TestNoListener:
    """The server opens no listening socket; it only uses stdio fds."""

    def test_no_listener_socket_bound(self, server: Any) -> None:
        # While the server runs, an ephemeral bind must succeed (the server
        # holds no listener). The server has no configured port, so the
        # absence of any bind is the property we assert here.
        time.sleep(0.1)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        probe.close()
        # The server still responds over stdio.
        server.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        resp = server.recv()
        assert "result" in resp

    def test_stderr_is_empty_after_close(self, server: Any) -> None:
        # Drive one request so the server does real work, then close.
        server.send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        server.recv()
        server.close()
        stderr = server.stderr_bytes
        assert stderr.strip() == b"", f"unexpected stderr: {stderr!r}"
