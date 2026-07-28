"""Read-only stdio MCP server: JSON-RPC 2.0 over Content-Length frames (WP-F51).

This module is a hand-rolled JSON-RPC 2.0 server that speaks the Model Context
Protocol over stdio. It deliberately does **not** depend on the ``mcp`` PyPI
package (stdlib + the existing SRL packages only); see
``docs/adr/0004-mcp-handrolled-stdio.md`` for the decision record.

What the server does
--------------------
- ``initialize`` — MCP handshake: advertises a protocol version, the single
  ``tools`` capability, and ``serverInfo``.
- ``tools/list`` — returns exactly the seven read-only P0 tools.
- ``tools/call`` — dispatches a named tool to its implementation in
  :mod:`srl.mcp.methods`, wrapping the typed result as a JSON-RPC response.

What the server refuses (load-bearing)
--------------------------------------
- **No execution/mutation.** Any method name that looks like it runs or mutates
  (``run``, ``execute``, ``mutate``, ``write``, ``delete``, …) is rejected with
  JSON-RPC error ``-32601`` (method not found) carrying a typed note
  (``fail_reason`` :data:`METHOD_NOT_FOUND_FAIL_REASON`).
- **No listener, no scheduler, no database, no secret, no raw-dataset access.**
  The server reads only stdin and writes only stdout; it never opens a socket
  and never touches canonical state (the :class:`~srl.mcp.methods.MethodContext`
  is in-memory and offline by default).

Read-only invariant
-------------------
The read-only property is structural: the server holds a
:class:`~srl.mcp.methods.MethodContext` whose only write-adjacent surface is a
knowledge transport that is offline by default, and no tool exposes a write
path. A gate (``scripts/checks/wp51-gate.py``) asserts both the method
rejection and that the server process opens no listener socket.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, Final

from srl import __version__
from srl.mcp import methods as mcp_methods
from srl.mcp.framing import (
    FRAME_MALFORMED_FAIL_REASON,
    FRAME_PARSE_FAIL_REASON,
    FRAME_TOO_LARGE_FAIL_REASON,
    MAX_FRAME_BYTES,
    FrameError,
    encode_frame,
    parse_content_length,
)

# ---------------------------------------------------------------------------
# MCP / JSON-RPC identity anchors.
# ---------------------------------------------------------------------------

# The MCP protocol version this server speaks.
PROTOCOL_VERSION: Final[str] = "2025-06-18"

# The server's reported name/version for the initialize handshake.
SERVER_NAME: Final[str] = "srl-mcp"
SERVER_VERSION: Final[str] = __version__

# The schema-version anchor for the server's structured error data.
MCP_ERROR_SCHEMA: Final[str] = "McpError/v1"

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 error codes (per the spec).
# ---------------------------------------------------------------------------

# Parse error: invalid JSON was received.
ERR_PARSE: Final[int] = -32700
# Invalid request: the JSON is not a valid request object.
ERR_INVALID_REQUEST: Final[int] = -32600
# Method not found: the method does not exist or is not available.
ERR_METHOD_NOT_FOUND: Final[int] = -32601
# Invalid params: invalid method parameters.
ERR_INVALID_PARAMS: Final[int] = -32602
# Internal error.
ERR_INTERNAL: Final[int] = -32603

# The typed fail reason for a refused (read-only-violating) method.
METHOD_NOT_FOUND_FAIL_REASON: Final[str] = "METHOD_NOT_FOUND"
# The typed fail reason echoed on a frame-level refusal.
FRAME_FAIL_REASON: Final[str] = "FRAME_ERROR"

# ---------------------------------------------------------------------------
# Read-only enforcement: method names that are ALWAYS refused.
# ---------------------------------------------------------------------------

# A method name matching one of these substrings (case-insensitive) is treated
# as a mutation/execution attempt and refused with -32601. This is a deny-list
# on top of the explicit allow-list: only the seven P0 tools (and the three
# JSON-RPC meta-methods) ever dispatch.
_MUTATION_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "run",
        "execute",
        "exec",
        "mutate",
        "mutation",
        "write",
        "create",
        "delete",
        "destroy",
        "update",
        "patch",
        "post",
        "put",
        "materialize",
        "stage",
        "seal",
        "commit",
        "submit",
        "schedule",
        "spawn",
        "launch",
        "install",
        "deploy",
    }
)

# The three JSON-RPC/MCP meta-methods the server handles directly.
_META_INITIALIZE: Final[str] = "initialize"
_META_TOOLS_LIST: Final[str] = "tools/list"
_META_TOOLS_CALL: Final[str] = "tools/call"

# The seven P0 tool names exposed via tools/list and tools/call.
_TOOL_LIST_CAPABILITIES: Final[str] = "list_capabilities"
_TOOL_INSPECT_CAPABILITY: Final[str] = "inspect_capability"
_TOOL_VALIDATE_CLAIM: Final[str] = "validate_claim"
_TOOL_BUILD_PLAN: Final[str] = "build_plan"
_TOOL_INSPECT_RUN: Final[str] = "inspect_run"
_TOOL_SEARCH_KNOWLEDGE: Final[str] = "search_knowledge"
_TOOL_BUILD_EXPORT_PACKET: Final[str] = "build_export_packet"

# Ordered, exhaustive list of the P0 tools. A gate asserts this is exactly 7.
P0_TOOLS: Final[tuple[str, ...]] = (
    _TOOL_LIST_CAPABILITIES,
    _TOOL_INSPECT_CAPABILITY,
    _TOOL_VALIDATE_CLAIM,
    _TOOL_BUILD_PLAN,
    _TOOL_INSPECT_RUN,
    _TOOL_SEARCH_KNOWLEDGE,
    _TOOL_BUILD_EXPORT_PACKET,
)

# Short human descriptions for each tool (used in tools/list).
_TOOL_DESCRIPTIONS: Final[dict[str, str]] = {
    _TOOL_LIST_CAPABILITIES: "List the shipped capability catalog entries (read-only).",
    _TOOL_INSPECT_CAPABILITY: "Inspect one catalog entry by profile (read-only).",
    _TOOL_VALIDATE_CLAIM: "Validate a ScientificClaim/v1 (schema + invariants, read-only).",
    _TOOL_BUILD_PLAN: "Build a ScienceLabPlan/v1 from a request + claim (read-only).",
    _TOOL_INSPECT_RUN: "Inspect a RunReceipt/v1 (read-only; never executes).",
    _TOOL_SEARCH_KNOWLEDGE: "Search a declared knowledge endpoint (read-only; offline by default).",
    _TOOL_BUILD_EXPORT_PACKET: (
        "Build an export packet (stubbed: typed WAIT_CAPABILITY; exporter lands in WP-I80)."
    ),
}

# Input-schema sketch per tool (JSON Schema 2020-12 fragments). Kept loose: the
# method implementations validate strictly; this is for tool discoverability.
_TOOL_INPUT_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    _TOOL_LIST_CAPABILITIES: {"type": "object", "properties": {}, "additionalProperties": False},
    _TOOL_INSPECT_CAPABILITY: {
        "type": "object",
        "properties": {"profile": {"type": "string"}},
        "required": ["profile"],
        "additionalProperties": False,
    },
    _TOOL_VALIDATE_CLAIM: {
        "type": "object",
        "properties": {"claim": {"type": "object"}},
        "required": ["claim"],
        "additionalProperties": False,
    },
    _TOOL_BUILD_PLAN: {
        "type": "object",
        "properties": {
            "request": {"type": "object"},
            "claim": {"type": "object"},
        },
        "required": ["request", "claim"],
        "additionalProperties": False,
    },
    _TOOL_INSPECT_RUN: {
        "type": "object",
        "properties": {
            "receipt": {"type": "object"},
            "receipt_path": {"type": "string"},
        },
        "additionalProperties": False,
    },
    _TOOL_SEARCH_KNOWLEDGE: {
        "type": "object",
        "properties": {
            "endpoint_id": {"type": "string"},
            "path": {"type": "string"},
            "params": {"type": "object"},
        },
        "required": ["endpoint_id"],
        "additionalProperties": False,
    },
    _TOOL_BUILD_EXPORT_PACKET: {
        "type": "object",
        "properties": {"plan_id": {"type": "string"}},
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC response builders.
# ---------------------------------------------------------------------------


def _result_response(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error_response(
    msg_id: Any, code: int, message: str, *, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a JSON-RPC error response with optional structured ``data``."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def _typed_error_data(
    fail_reason: str, *, note: str = "", status: str = "", extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the structured ``data`` for a typed JSON-RPC error."""
    out: dict[str, Any] = {
        "schema_version": MCP_ERROR_SCHEMA,
        "fail_reason": fail_reason,
        "read_only": True,
    }
    if note:
        out["note"] = note
    if status:
        out["status"] = status
    if extra:
        out["extra"] = extra
    return out


def _is_mutation(name: str) -> bool:
    """Return True iff ``name`` looks like a run/execute/mutate attempt.

    Matching is on the lowercased method name. A bare token (e.g. ``run``) or a
    slash-path token (e.g. ``run/execute``) matches.
    """
    lowered = name.lower()
    # First: exact meta-method match is never a mutation.
    if lowered in {_META_INITIALIZE, _META_TOOLS_LIST, _META_TOOLS_CALL}:
        return False
    # Exact tool match is never a mutation (the allowed read-only tools).
    if lowered in set(P0_TOOLS):
        return False
    # Otherwise: if any deny token appears as a path segment, refuse.
    parts = lowered.replace("/", " ").replace(".", " ").replace("_", " ").split()
    return bool(set(parts) & _MUTATION_TOKENS)


# The typed note carried on every read-only-violating method rejection.
_MUTATION_NOTE: Final[str] = (
    "this MCP server is read-only; run/execute/mutate methods are refused (JSON-RPC -32601)"
)


def _mutation_rejection(msg_id: Any, *, what: str) -> dict[str, Any]:
    """Build the JSON-RPC -32601 response for a mutation-shaped ``what``."""
    return _error_response(
        msg_id,
        ERR_METHOD_NOT_FOUND,
        f"{what} is not available (read-only server)",
        data=_typed_error_data(
            METHOD_NOT_FOUND_FAIL_REASON,
            note=_MUTATION_NOTE,
            status="METHOD_NOT_FOUND",
        ),
    )


def _unknown_method_rejection(msg_id: Any, *, method: str) -> dict[str, Any]:
    """Build the JSON-RPC -32601 response for a genuinely unknown method."""
    return _error_response(
        msg_id,
        ERR_METHOD_NOT_FOUND,
        f"unknown method {method!r}",
        data=_typed_error_data(
            METHOD_NOT_FOUND_FAIL_REASON,
            note=f"unknown method {method!r}",
            status="METHOD_NOT_FOUND",
        ),
    )


def _invalid_request(msg_id: Any, *, note: str) -> dict[str, Any]:
    """Build the JSON-RPC -32600 invalid-request response."""
    return _error_response(
        msg_id,
        ERR_INVALID_REQUEST,
        note,
        data=_typed_error_data("INVALID_REQUEST", note=note, status="INVALID_REQUEST"),
    )


def _invalid_params(msg_id: Any, *, note: str) -> dict[str, Any]:
    """Build the JSON-RPC -32602 invalid-params response."""
    return _error_response(
        msg_id,
        ERR_INVALID_PARAMS,
        note,
        data=_typed_error_data("INVALID_PARAMS", note=note, status="INVALID_PARAMS"),
    )


# ---------------------------------------------------------------------------
# The dispatcher.
# ---------------------------------------------------------------------------

# Type alias for a tool implementation: (ctx, args) -> typed result dict.
_ToolImpl = Callable[[mcp_methods.MethodContext, dict[str, Any]], dict[str, Any]]

# The tool dispatch table. Built once at module import.
_TOOL_IMPLS: Final[dict[str, _ToolImpl]] = {
    _TOOL_LIST_CAPABILITIES: mcp_methods.m_list_capabilities,
    _TOOL_INSPECT_CAPABILITY: mcp_methods.m_inspect_capability,
    _TOOL_VALIDATE_CLAIM: mcp_methods.m_validate_claim,
    _TOOL_BUILD_PLAN: mcp_methods.m_build_plan,
    _TOOL_INSPECT_RUN: mcp_methods.m_inspect_run,
    _TOOL_SEARCH_KNOWLEDGE: mcp_methods.m_search_knowledge,
    _TOOL_BUILD_EXPORT_PACKET: mcp_methods.m_build_export_packet,
}


class McpServer:
    """A read-only stdio MCP server.

    The server is constructed with an in-memory, offline
    :class:`~srl.mcp.methods.MethodContext`. It reads JSON-RPC frames from
    ``stdin`` and writes responses to ``stdout``. It never opens a socket.

    The dispatch surface is intentionally tiny: three meta-methods and seven
    read-only tools. Everything else is rejected.

    Attributes
    ----------
    ctx:
        The in-memory, no-store context the tools read from.
    initialized:
        True after a successful ``initialize`` handshake.
    """

    def __init__(self, ctx: mcp_methods.MethodContext | None = None) -> None:
        self.ctx: mcp_methods.MethodContext = (
            ctx if ctx is not None else mcp_methods.MethodContext()
        )
        self.initialized: bool = False

    # -----------------------------------------------------------------
    # Meta-methods.
    # -----------------------------------------------------------------

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return the MCP initialize result and mark the server initialized."""
        del params  # client capabilities/protocol version are acknowledged only
        self.initialized = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _handle_tools_list(self) -> dict[str, Any]:
        """Return the seven P0 tools as MCP tool descriptors."""
        tools = [
            {
                "name": name,
                "description": _TOOL_DESCRIPTIONS[name],
                "inputSchema": _TOOL_INPUT_SCHEMAS[name],
            }
            for name in P0_TOOLS
        ]
        return {"tools": tools}

    def _handle_tools_call(  # noqa: PLR0911
        self, params: dict[str, Any], msg_id: Any
    ) -> dict[str, Any]:
        """Dispatch a tool call. Returns a JSON-RPC response dict.

        A missing/unknown tool name is a JSON-RPC error (-32601). A mutation
        attempt is the same error with the typed read-only note. A tool that
        raises a typed :class:`~srl.mcp.methods.McpMethodError` is surfaced as
        a JSON-RPC error (-32601) carrying the typed data. A tool that returns
        a typed WAIT envelope is surfaced as a normal result (it ran to
        completion and reported an honest wait).
        """
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _invalid_params(msg_id, note="tools/call requires a 'name' string")
        # Read-only enforcement: any mutation-shaped name is refused here too.
        if _is_mutation(name):
            return _mutation_rejection(msg_id, what=f"method {name!r}")
        impl = _TOOL_IMPLS.get(name)
        if impl is None:
            return _unknown_method_rejection(msg_id, method=name)
        raw_args = params.get("arguments")
        if raw_args is None:
            raw_args = {}
        if not isinstance(raw_args, dict):
            return _invalid_params(msg_id, note="tools/call 'arguments' must be an object")
        args: dict[str, Any] = dict(raw_args)
        try:
            outcome = impl(self.ctx, args)
        except mcp_methods.McpMethodError as exc:
            return _error_response(
                msg_id,
                ERR_METHOD_NOT_FOUND,
                str(exc),
                data=_typed_error_data(
                    exc.fail_reason, note=str(exc), status=exc.status or "INVALID"
                ),
            )
        except Exception as exc:  # defensive: never leak a stack trace to the host
            return _error_response(
                msg_id,
                ERR_INTERNAL,
                f"tool {name!r} raised an internal error",
                data=_typed_error_data(
                    "INTERNAL", note=f"{type(exc).__name__}: {exc}", status="INTERNAL"
                ),
            )
        # Wrap the typed method result as an MCP content response. A typed WAIT
        # envelope (status != SUCCESS) is an honest result the host should still
        # see as a normal response; isError marks only a hard failure. The
        # method envelopes always carry a status word: SUCCESS means the tool
        # completed with a usable result; anything else is a typed wait/error
        # surfaced via isError=True so the host can route it.
        is_error = outcome.get("status") != "SUCCESS"
        content = {"type": "text", "text": json.dumps(outcome, sort_keys=True)}
        return _result_response(msg_id, {"content": [content], "isError": is_error})

    # -----------------------------------------------------------------
    # Request dispatch (single message).
    # -----------------------------------------------------------------

    def dispatch(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one parsed JSON-RPC request; return a response or ``None``.

        Returns ``None`` for a JSON-RPC notification (a request without an
        ``id``), which per spec receives no response. Returns a response dict
        for everything else, including parse/invalid-request errors (which use
        ``id: null``).

        Parameters
        ----------
        message:
            The parsed JSON-RPC request object.

        Returns
        -------
        dict[str, Any] | None
            A JSON-RPC response, or ``None`` for a notification.
        """
        if message.get("jsonrpc") != "2.0":
            return _invalid_request(message.get("id"), note="not a JSON-RPC 2.0 message")
        method = message.get("method")
        msg_id = message.get("id")
        is_notification = "id" not in message
        if not isinstance(method, str) or not method:
            return _invalid_request(msg_id, note="missing or non-string 'method'")

        # Read-only enforcement on the method name itself.
        if _is_mutation(method):
            return (
                None if is_notification else _mutation_rejection(msg_id, what=f"method {method!r}")
            )

        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return (
                None
                if is_notification
                else _invalid_params(msg_id, note="'params' must be an object")
            )

        return self._dispatch_meta(method, params, msg_id, is_notification)

    def _dispatch_meta(
        self,
        method: str,
        params: dict[str, Any],
        msg_id: Any,
        is_notification: bool,
    ) -> dict[str, Any] | None:
        """Route a validated request to its meta-method handler.

        Returns ``None`` for a notification. Known meta-methods dispatch to
        their handlers; anything else is an unknown method (already known not
        to be a mutation token).
        """
        if is_notification:
            return None
        if method == _META_INITIALIZE:
            return _result_response(msg_id, self._handle_initialize(params))
        if method == _META_TOOLS_LIST:
            return _result_response(msg_id, self._handle_tools_list())
        if method == _META_TOOLS_CALL:
            return self._handle_tools_call(params, msg_id)
        return _unknown_method_rejection(msg_id, method=method)


# ---------------------------------------------------------------------------
# stdio loop.
# ---------------------------------------------------------------------------


def _read_exact(stream: Any, n: int) -> bytes:
    """Read exactly ``n`` bytes from ``stream``; raise on short read.

    A short read (stream closed mid-frame) is a :class:`FrameError` so the loop
    surfaces it as a typed parse error rather than emitting a truncated body.
    """
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            msg = f"stream closed mid-frame (read {n - remaining} of {n} bytes)"
            raise FrameError(msg, fail_reason=FRAME_PARSE_FAIL_REASON)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_frame(stream: Any) -> dict[str, Any] | None:
    """Read one Content-Length-framed message from ``stream``.

    Returns the parsed JSON object, or ``None`` at clean EOF (no partial frame).

    Raises
    ------
    FrameError
        On an oversized frame, malformed header, malformed JSON, or short read.
    """
    # Read until the header terminator.
    header_buf = bytearray()
    while True:
        byte = stream.read(1)
        if not byte:
            if not header_buf:
                return None  # clean EOF before any header byte
            msg = "stream closed mid-header"
            raise FrameError(msg, fail_reason=FRAME_PARSE_FAIL_REASON)
        header_buf += byte
        if header_buf.endswith(b"\r\n\r\n"):
            break
        if len(header_buf) > MAX_FRAME_BYTES:
            msg = (
                f"frame header exceeded {MAX_FRAME_BYTES} bytes without a terminator "
                "(FRAME_TOO_LARGE)"
            )
            raise FrameError(msg, fail_reason=FRAME_TOO_LARGE_FAIL_REASON)
    header_block = header_buf.decode("ascii", errors="replace")
    content_length = parse_content_length(header_block)
    if content_length > MAX_FRAME_BYTES:
        msg = (
            f"declared Content-Length {content_length} exceeds the {MAX_FRAME_BYTES}-byte "
            "cap (FRAME_TOO_LARGE)"
        )
        raise FrameError(msg, fail_reason=FRAME_TOO_LARGE_FAIL_REASON)
    body = _read_exact(stream, content_length)
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"frame body is not valid JSON: {exc}"
        raise FrameError(msg, fail_reason=FRAME_PARSE_FAIL_REASON) from exc
    if not isinstance(parsed, dict):
        msg = f"frame body must be a JSON object, got {type(parsed).__name__}"
        raise FrameError(msg, fail_reason=FRAME_PARSE_FAIL_REASON)
    return parsed


def serve(
    *,
    stdin: Any = None,
    stdout: Any = None,
    ctx: mcp_methods.MethodContext | None = None,
) -> int:
    """Run the read-only stdio MCP server until stdin reaches EOF.

    Reads Content-Length-framed JSON-RPC messages from ``stdin`` and writes one
    framed response per request (notifications get no response) to ``stdout``.
    A frame-level error (oversized/malformed) is surfaced as a JSON-RPC parse
    error (``-32700``) with ``id: null`` and continues the loop; an internal
    dispatcher error is surfaced as ``-32603``.

    Returns 0 on a clean EOF.

    Parameters
    ----------
    stdin:
        A binary stream to read frames from. Defaults to ``sys.stdin.buffer``.
    stdout:
        A binary stream to write frames to. Defaults to ``sys.stdout.buffer``.
    ctx:
        Optional :class:`~srl.mcp.methods.MethodContext`. Defaults to an
        in-memory, offline context.
    """
    in_stream = stdin if stdin is not None else sys.stdin.buffer
    out_stream = stdout if stdout is not None else sys.stdout.buffer
    server = McpServer(ctx=ctx)
    while True:
        try:
            message = _read_frame(in_stream)
        except FrameError as exc:
            # Frame-level error: emit a JSON-RPC parse error and continue.
            code = (
                ERR_INVALID_REQUEST if exc.fail_reason == FRAME_TOO_LARGE_FAIL_REASON else ERR_PARSE
            )
            fail_reason = (
                FRAME_TOO_LARGE_FAIL_REASON
                if exc.fail_reason == FRAME_TOO_LARGE_FAIL_REASON
                else (
                    FRAME_MALFORMED_FAIL_REASON
                    if exc.fail_reason == FRAME_MALFORMED_FAIL_REASON
                    else FRAME_PARSE_FAIL_REASON
                )
            )
            resp = _error_response(
                None,
                code,
                f"frame error: {exc}",
                data=_typed_error_data(
                    fail_reason,
                    note=str(exc),
                    status=fail_reason,
                ),
            )
            out_stream.write(encode_frame(resp))
            out_stream.flush()
            continue
        if message is None:
            return 0  # clean EOF
        try:
            response = server.dispatch(message)
        except Exception as exc:  # defensive: never crash the loop on a bug
            response = _error_response(
                message.get("id"),
                ERR_INTERNAL,
                f"internal error: {exc}",
                data=_typed_error_data(
                    "INTERNAL", note=f"{type(exc).__name__}: {exc}", status="INTERNAL"
                ),
            )
        if response is not None:
            out_stream.write(encode_frame(response))
            out_stream.flush()


__all__ = [
    "FRAME_FAIL_REASON",
    "MCP_ERROR_SCHEMA",
    "METHOD_NOT_FOUND_FAIL_REASON",
    "P0_TOOLS",
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "McpServer",
    "serve",
]
