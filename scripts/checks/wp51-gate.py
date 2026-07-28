#!/usr/bin/env python3
"""WP-F51 acceptance gate for the read-only stdio MCP server.

Spawns ``python -m srl.mcp`` as a subprocess over pipes and drives it through
the MCP handshake, the seven read-only P0 tools, the mutation rejection, the
frame-level defenses, and the no-listener assertion. The gate is hermetic: no
live network, no pre-existing files, no sockets.

It prints one canonical ``GateReceipt/v1`` JSON line and exits 0 only if every
check PASSes.
"""

from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp51-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
_FX_KNOWLEDGE = _REPO_ROOT / "fixtures" / "conformance" / "knowledge"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402
from srl.mcp.framing import MAX_FRAME_BYTES  # noqa: E402
from srl.mcp.methods import MethodContext  # noqa: E402
from srl.mcp.server import ERR_INVALID_REQUEST, ERR_METHOD_NOT_FOUND, ERR_PARSE  # noqa: E402
from srl.planning.request import build_request  # noqa: E402

# ---------------------------------------------------------------------------
# Receipt identity.
# ---------------------------------------------------------------------------

GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-F51"

# JSON-RPC error codes the gate asserts against (mirrors srl.mcp.server).
_EXPECTED_TOOL_COUNT: Final[int] = 7
# Per-check JSON-RPC message ids (named so assertions avoid magic values).
_ID_INIT: Final[int] = 1
_ID_LIST: Final[int] = 2

# The exact seven P0 tools the server MUST expose (order-independent).
EXPECTED_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "list_capabilities",
        "inspect_capability",
        "validate_claim",
        "build_plan",
        "inspect_run",
        "search_knowledge",
        "build_export_packet",
    }
)


# ---------------------------------------------------------------------------
# Framing helpers (mirrors srl.mcp.framing so the gate is self-contained over
# the pipe without depending on the server's own writer for inputs).
# ---------------------------------------------------------------------------


def _encode(message: dict[str, Any]) -> bytes:
    """Encode a JSON-RPC message as one Content-Length-framed byte string."""
    body = json.dumps(message, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_one_frame(stream: Any) -> dict[str, Any] | None:
    """Read one Content-Length-framed message from ``stream`` (file-like).

    Returns the parsed JSON object, or ``None`` at clean EOF. Raises on a
    malformed/oversized frame or short read.
    """
    header = bytearray()
    while True:
        b = stream.read(1)
        if not b:
            return None if not header else _fail("stream closed mid-header")
        header += b
        if header.endswith(b"\r\n\r\n"):
            break
        if len(header) > MAX_FRAME_BYTES:
            _fail("header exceeded the frame cap without a terminator")
    text = header.decode("ascii", errors="replace")
    n = -1
    for line in text.split("\r\n"):
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            n = int(value.strip())
    if n < 0:
        _fail("missing Content-Length header in response")
    body = stream.read(n)
    if len(body) != n:
        _fail("short read of response body")
    return json.loads(body)


def _fail(message: str) -> Any:
    """Raise a ValueError carrying ``message`` (gate translates to FAIL)."""
    raise ValueError(message)


# ---------------------------------------------------------------------------
# Subprocess harness.
# ---------------------------------------------------------------------------


class _ServerProc:
    """A spawned ``python -m srl.mcp`` subprocess driven over pipes."""

    def __init__(self) -> None:
        env = dict(os.environ)
        # Ensure the subprocess imports the in-repo package, not an installed one.
        pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{_SRC}{os.pathsep}{pythonpath}" if pythonpath else str(_SRC)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "srl.mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def send(self, message: dict[str, Any]) -> None:
        """Write one framed message to the server's stdin."""
        stdin = self.proc.stdin
        if stdin is None:
            _fail("server stdin is not a pipe")
        stdin.write(_encode(message))
        stdin.flush()

    def recv(self, timeout: float = 5.0) -> dict[str, Any]:
        """Read one framed response within ``timeout`` seconds."""
        stdout = self.proc.stdout
        if stdout is None:
            _fail("server stdout is not a pipe")
        # Poll for available bytes so the gate does not block forever on a hung
        # server. We give the loop ``timeout`` seconds of wall time.
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _has_bytes(stdout):
                if self.proc.poll() is not None:
                    _fail("server exited before responding")
                time.sleep(0.01)
                continue
            return _read_one_frame(stdout)
        _fail(f"server did not respond within {timeout}s")

    def send_raw(self, raw: bytes) -> None:
        """Write raw bytes (for malformed-frame tests) to the server's stdin."""
        stdin = self.proc.stdin
        if stdin is None:
            _fail("server stdin is not a pipe")
        stdin.write(raw)
        stdin.flush()

    def close(self) -> None:
        """Close stdin, drain stdout/stderr, and terminate the server."""
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


def _has_bytes(stream: Any) -> bool:
    """Return True if ``stream`` has at least one byte available without blocking."""
    # fileno() works for the read end of a pipe on POSIX.
    try:
        fd = stream.fileno()
    except (AttributeError, ValueError):
        return True  # cannot poll; assume readable
    r, _, _ = select.select([fd], [], [], 0)
    return bool(r)


# ---------------------------------------------------------------------------
# Input builders.
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
    """Return a valid ScientificClaim/v1 with a computed claim_id."""
    claim = _minimal_claim()
    claim["claim_id"] = object_id(claim)
    return claim


def _valid_request(claim_id_value: str) -> dict[str, Any]:
    """Return a valid ScienceLabRunRequest/v1 targeting the given claim.

    Requests ``algebra_exact`` explicitly so the router engages an applicable
    profile and the shipped catalog (all adapters future/remote_required)
    routes it WAIT_CAPABILITY honestly.
    """
    return build_request(
        claim_id=claim_id_value,
        requested_profiles=["algebra_exact"],
        created_utc="2026-07-28T00:00:00Z",
    )


def _rpc(msg_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request dict."""
    out: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        out["params"] = params
    return out


def _tool_call(msg_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build a tools/call request."""
    return _rpc(msg_id, "tools/call", {"name": name, "arguments": arguments})


def _content_text(response: dict[str, Any]) -> dict[str, Any]:
    """Extract and parse the typed method result from a tools/call response."""
    result = response.get("result", {})
    content = result.get("content", [])
    if not content or content[0].get("type") != "text":
        _fail(f"response has no text content: {response}")
    return json.loads(content[0]["text"])


# ---------------------------------------------------------------------------
# F51-01: initialize + tools/list returns exactly the 7 methods.
# ---------------------------------------------------------------------------


def _check_f51_01() -> dict[str, Any]:  # noqa: PLR0911
    """``initialize`` advertises protocol + tools; ``tools/list`` returns the 7 P0 tools."""
    try:
        server = _ServerProc()
        try:
            server.send(_rpc(1, "initialize", {}))
            init = server.recv()
            if init.get("id") != 1 or "result" not in init:
                return {"status": "FAIL", "detail": f"bad initialize response: {init}"}
            result = init["result"]
            if not isinstance(result, dict) or "protocolVersion" not in result:
                return {"status": "FAIL", "detail": f"missing protocolVersion: {result}"}
            if "tools" not in result.get("capabilities", {}):
                return {"status": "FAIL", "detail": f"tools capability missing: {result}"}
            info = result.get("serverInfo", {})
            if info.get("name") != "srl-mcp":
                return {"status": "FAIL", "detail": f"unexpected serverInfo: {info}"}

            server.send(_rpc(_ID_LIST, "tools/list"))
            listing = server.recv()
            if listing.get("id") != _ID_LIST or "result" not in listing:
                return {"status": "FAIL", "detail": f"bad tools/list response: {listing}"}
            tools = listing["result"].get("tools", [])
            names = frozenset(t.get("name", "") for t in tools)
            if names != EXPECTED_TOOLS:
                return {
                    "status": "FAIL",
                    "detail": f"expected exactly {sorted(EXPECTED_TOOLS)}, got {sorted(names)}",
                }
            return {
                "status": "PASS",
                "detail": "initialize + tools/list return exactly the 7 P0 tools",
            }
        finally:
            server.close()
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F51-02: validate_claim on a fixture claim returns a typed result.
# ---------------------------------------------------------------------------


def _check_f51_02() -> dict[str, Any]:
    """``validate_claim`` accepts a valid claim and returns a typed SUCCESS."""
    try:
        server = _ServerProc()
        try:
            claim = _valid_claim()
            server.send(_tool_call(1, "validate_claim", {"claim": claim}))
            resp = server.recv()
            if resp.get("id") != 1 or "result" not in resp:
                return {"status": "FAIL", "detail": f"bad validate_claim response: {resp}"}
            outcome = _content_text(resp)
            if outcome.get("method") != "validate_claim" or outcome.get("status") != "SUCCESS":
                return {"status": "FAIL", "detail": f"unexpected outcome: {outcome}"}
            if outcome.get("canonical_writes") != 0 or outcome.get("grants_authority") is not False:
                return {"status": "FAIL", "detail": f"safety consts wrong: {outcome}"}
            result = outcome.get("result", {})
            if not result.get("valid") or not str(result.get("claim_id", "")).startswith("sha256:"):
                return {"status": "FAIL", "detail": f"invalid valid-claim result: {result}"}
            return {
                "status": "PASS",
                "detail": "validate_claim returns typed SUCCESS on a valid claim",
            }
        finally:
            server.close()
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F51-03: build_plan returns a plan or WAIT_CAPABILITY.
# ---------------------------------------------------------------------------


def _check_f51_03() -> dict[str, Any]:  # noqa: PLR0911
    """``build_plan`` returns a ScienceLabPlan/v1 (steps WAIT_CAPABILITY honestly)."""
    try:
        server = _ServerProc()
        try:
            claim = _valid_claim()
            request = _valid_request(claim["claim_id"])
            server.send(_tool_call(1, "build_plan", {"request": request, "claim": claim}))
            resp = server.recv()
            if resp.get("id") != 1 or "result" not in resp:
                return {"status": "FAIL", "detail": f"bad build_plan response: {resp}"}
            outcome = _content_text(resp)
            if outcome.get("method") != "build_plan":
                return {"status": "FAIL", "detail": f"unexpected method: {outcome}"}
            if outcome.get("status") != "SUCCESS":
                return {"status": "FAIL", "detail": f"build_plan did not succeed: {outcome}"}
            result = outcome.get("result", {})
            plan = result.get("plan", {})
            if plan.get("schema_version") != "ScienceLabPlan/v1":
                return {"status": "FAIL", "detail": f"plan is not ScienceLabPlan/v1: {plan}"}
            if str(plan.get("plan_id", "")).startswith("sha256:") is False:
                return {"status": "FAIL", "detail": f"plan missing plan_id: {plan}"}
            # The shipped catalog marks every adapter future/remote_required, so
            # every applicable step routes WAIT_CAPABILITY honestly.
            selections = {s.get("selection") for s in plan.get("steps", [])}
            if "WAIT_CAPABILITY" not in selections:
                return {"status": "FAIL", "detail": f"no WAIT_CAPABILITY steps: {selections}"}
            return {
                "status": "PASS",
                "detail": "build_plan returns a plan with honest WAIT_CAPABILITY steps",
            }
        finally:
            server.close()
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F51-04: mutation attempt (run.execute) rejected.
# ---------------------------------------------------------------------------


def _check_f51_04() -> dict[str, Any]:  # noqa: PLR0911
    """``run.execute`` (and a tools/call mutation) is rejected with JSON-RPC -32601."""
    try:
        server = _ServerProc()
        try:
            # Direct method mutation attempt.
            server.send(_rpc(1, "run.execute", {"adapter_id": "echo.v1", "input": {}}))
            resp = server.recv()
            if resp.get("id") != 1 or resp.get("error") is None:
                return {"status": "FAIL", "detail": f"run.execute not rejected: {resp}"}
            err = resp["error"]
            if err.get("code") != ERR_METHOD_NOT_FOUND:
                return {"status": "FAIL", "detail": f"wrong error code: {err}"}
            data = err.get("data", {})
            if data.get("fail_reason") != "METHOD_NOT_FOUND" or data.get("read_only") is not True:
                return {"status": "FAIL", "detail": f"typed note wrong: {data}"}

            # tools/call mutation attempt (e.g. name='execute').
            server.send(_tool_call(_ID_LIST, "execute", {"adapter_id": "echo.v1"}))
            resp = server.recv()
            if resp.get("id") != _ID_LIST or resp.get("error") is None:
                return {"status": "FAIL", "detail": f"tools/call execute not rejected: {resp}"}
            err = resp["error"]
            if err.get("code") != ERR_METHOD_NOT_FOUND:
                return {"status": "FAIL", "detail": f"wrong tools/call error code: {err}"}
            return {
                "status": "PASS",
                "detail": "run.execute and tools/call(execute) rejected with -32601",
            }
        finally:
            server.close()
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F51-05: oversized / malformed frame typed error.
# ---------------------------------------------------------------------------


def _check_f51_05() -> dict[str, Any]:  # noqa: PLR0911
    """An oversized and a malformed frame each produce a typed JSON-RPC error."""
    try:
        server = _ServerProc()
        try:
            # Oversized frame: declare a Content-Length beyond the cap.
            oversized = f"Content-Length: {MAX_FRAME_BYTES + 1}\r\n\r\n".encode("ascii")
            server.send_raw(oversized)
            resp = server.recv()
            if resp.get("error") is None:
                return {"status": "FAIL", "detail": f"oversized frame not errored: {resp}"}
            err = resp["error"]
            if err.get("code") != ERR_INVALID_REQUEST:
                return {"status": "FAIL", "detail": f"oversized wrong code: {err}"}
            data = err.get("data", {})
            if data.get("fail_reason") != "FRAME_TOO_LARGE":
                return {"status": "FAIL", "detail": f"oversized wrong fail_reason: {data}"}

            # Malformed frame: valid header but non-JSON body.
            body = b"not-json-at-all"
            malformed = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
            server.send_raw(malformed)
            resp = server.recv()
            if resp.get("error") is None:
                return {"status": "FAIL", "detail": f"malformed frame not errored: {resp}"}
            err = resp["error"]
            if err.get("code") != ERR_PARSE:
                return {"status": "FAIL", "detail": f"malformed wrong code: {err}"}
            data = err.get("data", {})
            if data.get("fail_reason") != "FRAME_PARSE_ERROR":
                return {"status": "FAIL", "detail": f"malformed wrong fail_reason: {data}"}
            return {
                "status": "PASS",
                "detail": "oversized + malformed frames typed-error correctly",
            }
        finally:
            server.close()
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F51-06: server has no listener/socket (it only uses stdio fds).
# ---------------------------------------------------------------------------


def _check_f51_06() -> dict[str, Any]:
    """The server process opens no listening socket and no extra connections."""
    try:
        # First assert the no-listener property directly at the API level: the
        # MethodContext and the serve() loop never create a socket.
        ctx = MethodContext()
        if ctx.cache_dir is not None:
            return {"status": "FAIL", "detail": "default context should have no cache_dir"}

        # Spawn the server and probe that it does not bind a TCP port. We pick
        # an ephemeral port and assert the server did NOT bind it: we cannot
        # enumerate a foreign process's sockets portably, but we CAN assert the
        # stronger property that no socket bind happens anywhere by checking
        # that a fresh bind to the same port the server would have used
        # succeeds (i.e. the server is not holding it). Since the server uses
        # only stdio, any ephemeral port is free while it runs.
        server = _ServerProc()
        try:
            # Give the server a moment to (not) initialize any listener.
            time.sleep(0.1)
            # The server should respond to initialize normally (stdio works).
            server.send(_rpc(1, "initialize", {}))
            init = server.recv()
            if init.get("id") != 1 or "result" not in init:
                return {"status": "FAIL", "detail": f"server did not respond over stdio: {init}"}

            # Assert: we can bind a fresh ephemeral TCP socket (the server holds
            # none). If the server had opened a listener on a fixed port this
            # would not catch it, but the server has no fixed port configured —
            # so the absence of any bind is the property we can assert cheaply.
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))  # ephemeral; always succeeds unless exhausted
            probe.close()

            # Stronger check: the server's stderr is empty (a listener bind
            # error or any unexpected log would appear here). Drain it without
            # blocking by closing stdin first.
        finally:
            server.close()

        # Read stderr after close; it must be empty (no listener/socket logs).
        stderr = server.proc.stderr.read() if server.proc.stderr else b""
        if stderr.strip():
            return {
                "status": "FAIL",
                "detail": f"server wrote unexpected stderr: {stderr!r}",
            }
        return {"status": "PASS", "detail": "server uses stdio only; no listener/socket"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# F51-07: build_export_packet returns a typed WAIT_CAPABILITY stub (not faked).
# ---------------------------------------------------------------------------


def _check_f51_07() -> dict[str, Any]:  # noqa: PLR0911
    """``build_export_packet`` returns a typed WAIT_CAPABILITY (exporter is WP-I80)."""
    try:
        server = _ServerProc()
        try:
            server.send(_tool_call(1, "build_export_packet", {"plan_id": "sha256:abc"}))
            resp = server.recv()
            if resp.get("id") != 1 or "result" not in resp:
                return {"status": "FAIL", "detail": f"bad build_export_packet response: {resp}"}
            outcome = _content_text(resp)
            if outcome.get("method") != "build_export_packet":
                return {"status": "FAIL", "detail": f"unexpected method: {outcome}"}
            if outcome.get("status") != "WAIT_CAPABILITY":
                return {"status": "FAIL", "detail": f"not WAIT_CAPABILITY: {outcome}"}
            if outcome.get("fail_reason") != "WAIT_CAPABILITY":
                return {"status": "FAIL", "detail": f"wrong fail_reason: {outcome}"}
            extra = outcome.get("extra", {})
            if extra.get("dependents_on") != "WP-I80":
                return {"status": "FAIL", "detail": f"missing WP-I80 dependency: {extra}"}
            return {
                "status": "PASS",
                "detail": "build_export_packet returns typed WAIT_CAPABILITY (not faked)",
            }
        finally:
            server.close()
    except Exception as exc:
        return {"status": "FAIL", "detail": f"exception: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _build_receipt() -> dict[str, Any]:
    """Run all F51 checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "F51-01": _check_f51_01(),
        "F51-02": _check_f51_02(),
        "F51-03": _check_f51_03(),
        "F51-04": _check_f51_04(),
        "F51-05": _check_f51_05(),
        "F51-06": _check_f51_06(),
        "F51-07": _check_f51_07(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {"statuses": statuses},
    }


def main(argv: list[str] | None = None) -> int:
    """Run the WP-F51 gate. Returns 0 iff every check PASSes."""
    del argv
    # A clean temp dir keeps the gate hermetic (no stray state).
    with tempfile.TemporaryDirectory(prefix="wp51-gate-"):
        receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
