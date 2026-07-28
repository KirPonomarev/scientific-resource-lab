"""Hermetic tests for the JSON-RPC dispatch and read-only enforcement (WP-F51)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from srl.contracts.ids import object_id
from srl.mcp.server import (
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    ERR_METHOD_NOT_FOUND,
    METHOD_NOT_FOUND_FAIL_REASON,
    P0_TOOLS,
    PROTOCOL_VERSION,
    SERVER_NAME,
    McpServer,
)

# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _minimal_claim() -> dict[str, Any]:
    """Return a valid ScientificClaim/v1 skeleton."""
    return {
        "schema_version": "ScientificClaim/v1",
        "statement": {"subject": "mass", "predicate": "equals", "object": "energy"},
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _valid_claim() -> dict[str, Any]:
    """Return a valid claim with a computed claim_id."""
    claim = _minimal_claim()
    claim["claim_id"] = object_id(claim)
    return claim


def _call(server: McpServer, msg_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tools/call and return the parsed typed result."""
    resp = server.dispatch(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert resp is not None
    content = resp["result"]["content"][0]
    return json.loads(content["text"])


# ---------------------------------------------------------------------------
# initialize.
# ---------------------------------------------------------------------------


class TestInitialize:
    """The MCP initialize handshake."""

    def test_advertises_protocol_tools_and_server_info(self) -> None:
        server = McpServer()
        resp = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp is not None
        result = resp["result"]
        assert result["protocolVersion"] == PROTOCOL_VERSION
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == SERVER_NAME
        assert server.initialized is True


# ---------------------------------------------------------------------------
# tools/list.
# ---------------------------------------------------------------------------


class TestToolsList:
    """``tools/list`` returns exactly the seven P0 tools."""

    def test_returns_exactly_seven_tools(self) -> None:
        server = McpServer()
        resp = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp is not None
        tools = resp["result"]["tools"]
        names = frozenset(t["name"] for t in tools)
        assert names == frozenset(P0_TOOLS)
        assert len(P0_TOOLS) == 7
        # Each tool has a description and an inputSchema.
        for tool in tools:
            assert tool["description"]
            assert isinstance(tool["inputSchema"], dict)


# ---------------------------------------------------------------------------
# tools/call dispatch.
# ---------------------------------------------------------------------------


class TestToolsCall:
    """``tools/call`` dispatches a named tool and wraps the typed result."""

    def test_validate_claim_success(self) -> None:
        out = _call(McpServer(), 1, "validate_claim", {"claim": _valid_claim()})
        assert out["status"] == "SUCCESS"
        assert out["result"]["valid"] is True

    def test_list_capabilities_success(self) -> None:
        out = _call(McpServer(), 1, "list_capabilities", {})
        assert out["status"] == "SUCCESS"
        assert out["result"]["entries"]

    def test_unknown_tool_is_method_not_found(self) -> None:
        server = McpServer()
        resp = server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            }
        )
        assert resp["error"]["code"] == ERR_METHOD_NOT_FOUND
        assert resp["error"]["data"]["fail_reason"] == METHOD_NOT_FOUND_FAIL_REASON

    def test_missing_name_is_invalid_params(self) -> None:
        server = McpServer()
        resp = server.dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"arguments": {}}}
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS

    def test_non_object_arguments_is_invalid_params(self) -> None:
        server = McpServer()
        resp = server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_capabilities", "arguments": []},
            }
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS

    def test_typed_wait_is_iserror_true(self) -> None:
        out_response = McpServer().dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "build_export_packet", "arguments": {}},
            }
        )
        assert out_response["result"]["isError"] is True


# ---------------------------------------------------------------------------
# Read-only enforcement: mutation rejection.
# ---------------------------------------------------------------------------


class TestReadOnlyEnforcement:
    """Any run/execute/mutate method is rejected with -32601."""

    @pytest.mark.parametrize(
        "method",
        [
            "run.execute",
            "run",
            "execute",
            "mutate",
            "write",
            "delete",
            "create",
            "run/execute",
            "tools/call.run",
        ],
    )
    def test_method_level_rejection(self, method: str) -> None:
        server = McpServer()
        resp = server.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})
        assert resp is not None
        assert resp["error"]["code"] == ERR_METHOD_NOT_FOUND
        data = resp["error"]["data"]
        assert data["fail_reason"] == METHOD_NOT_FOUND_FAIL_REASON
        assert data["read_only"] is True

    @pytest.mark.parametrize("name", ["run", "execute", "write", "delete", "spawn", "materialize"])
    def test_tool_level_rejection(self, name: str) -> None:
        server = McpServer()
        resp = server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            }
        )
        assert resp["error"]["code"] == ERR_METHOD_NOT_FOUND
        assert resp["error"]["data"]["read_only"] is True

    def test_allowed_tools_are_not_flagged_as_mutation(self) -> None:
        # The seven P0 tools must never be flagged as mutations even though
        # some contain tokens like 'build'/'list'/'inspect'. A mutation
        # rejection carries the read-only refusal note; a real tool that errors
        # on missing args carries a CONTRACT_INVALID note instead.
        server = McpServer()
        for name in P0_TOOLS:
            resp = server.dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": {}},
                }
            )
            assert resp is not None
            if "error" in resp:
                note = resp["error"]["data"].get("note", "")
                assert "read-only server" not in note, f"{name} flagged as mutation: {resp}"


# ---------------------------------------------------------------------------
# JSON-RPC structural errors.
# ---------------------------------------------------------------------------


class TestJsonRpcErrors:
    """Malformed JSON-RPC messages get the right codes."""

    def test_wrong_jsonrpc_version_is_invalid_request(self) -> None:
        resp = McpServer().dispatch({"jsonrpc": "1.0", "id": 1, "method": "initialize"})
        assert resp["error"]["code"] == ERR_INVALID_REQUEST

    def test_missing_method_is_invalid_request(self) -> None:
        resp = McpServer().dispatch({"jsonrpc": "2.0", "id": 1})
        assert resp["error"]["code"] == ERR_INVALID_REQUEST

    def test_non_object_params_is_invalid_params(self) -> None:
        resp = McpServer().dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": []}
        )
        assert resp["error"]["code"] == ERR_INVALID_PARAMS

    def test_unknown_method_is_method_not_found(self) -> None:
        resp = McpServer().dispatch({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert resp["error"]["code"] == ERR_METHOD_NOT_FOUND

    def test_notification_returns_none(self) -> None:
        # A request without an id is a notification and gets no response.
        resp = McpServer().dispatch({"jsonrpc": "2.0", "method": "initialize", "params": {}})
        assert resp is None
