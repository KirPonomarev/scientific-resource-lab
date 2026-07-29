"""Read-only P0 method implementations for the MCP server (WP-F51).

This module is the bridge between an MCP ``tools/call`` invocation and the
existing, well-tested SRL packages (planning router/planner, claims validation,
knowledge retriever, catalog, execution receipts). It exposes exactly seven
read-only methods and reuses the canonical JSON and typed-fail-reason
contracts every other SRL surface uses.

Read-only guarantee (load-bearing)
---------------------------------
Every method here is read-only: it inspects inputs and existing packages and
returns a typed result. No method writes canonical state, mutates a store,
launches a process, or fetches the network. The two safety consts
(``canonical_writes`` and ``grants_authority``) are echoed on every result so
a caller can verify the read-only property structurally.

Honest typing
-------------
A result is either a typed SUCCESS carrying the requested object, or a typed
WAIT/error carrying a ``fail_reason`` drawn from the registry. The exporter
(``build_export_packet``) is honestly stubbed: it returns a typed
``WAIT_CAPABILITY`` with the exact reason (the exporter lands in WP-I80 and is
NEVER faked here). ``search_knowledge`` returns ``WAIT_ENVIRONMENT`` when no
network transport is configured (the default, in-memory, offline context).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.contracts.schema import (
    ContractValidationError,
    SchemaError,
)
from srl.contracts.schema import (
    validate as schema_validate,
)
from srl.interfaces import InterfaceService, InterfaceServiceError
from srl.knowledge.adapters import p0_registry
from srl.knowledge.retriever import (
    ApiRetriever,
    NetworkPolicyError,
    QueryReceipt,
    RateLimitedError,
    ResourceLimitError,
    RetrievalTimeoutError,
    Transport,
    TransportResponse,
)
from srl.planning import build_plan, default_policy, load_default_catalog, route
from srl.semantic.claims import ClaimInvariantError
from srl.semantic.claims import claim_id as compute_claim_id
from srl.semantic.claims import validate as claim_validate

# ---------------------------------------------------------------------------
# Typed fail reasons. Mirrors automation/fail-reasons.json.
# ---------------------------------------------------------------------------

# A capability the method needs is not present yet (honest wait, no fabrication).
WAIT_CAPABILITY_FAIL_REASON: Final[str] = "WAIT_CAPABILITY"
# The environment the method needs (e.g. a network transport) is not configured.
WAIT_ENVIRONMENT_FAIL_REASON: Final[str] = "WAIT_ENVIRONMENT"
# A structural contract failure on the inputs (bad claim, bad request, etc.).
CONTRACT_INVALID: Final[str] = CONTRACT_INVALID_FAIL_REASON

# ---------------------------------------------------------------------------
# Identity anchors.
# ---------------------------------------------------------------------------

# Result schema-version anchor for the per-method result envelope.
MCP_RESULT_SCHEMA: Final[str] = "McpMethodResult/v1"
# The schema identity for a knowledge search receipt bundle.
KNOWLEDGE_SEARCH_SCHEMA: Final[str] = "McpKnowledgeSearch/v1"
# The schema identity for an export-packet stub.
EXPORT_PACKET_SCHEMA: Final[str] = "McpExportPacket/v1"

# The shipped catalog marks every adapter future/remote_required, so every
# applicable plan step routes WAIT_CAPABILITY. This is the honest wait the
# router MUST produce until a real adapter lands.
_EXPORT_WAIT_REASON: Final[str] = (
    "export-packet materialization is not implemented in WP-F51; the exporter "
    "lands in WP-I80 (WAIT_CAPABILITY)"
)
# The honest reason search_knowledge returns when no transport is configured.
_SEARCH_OFFLINE_REASON: Final[str] = (
    "no network transport configured; the MCP server runs offline by default (WAIT_ENVIRONMENT)"
)


class McpMethodError(Exception):
    """A typed error raised by a method implementation.

    Carries a ``fail_reason`` and an optional ``status`` word so the server can
    surface them in the JSON-RPC error payload without guessing.

    Attributes
    ----------
    fail_reason:
        Typed fail reason for routing/diagnostics.
    status:
        Optional status word (e.g. ``WAIT_ENVIRONMENT``).
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID,
        status: str = "",
    ) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason
        self.status: str = status


# ---------------------------------------------------------------------------
# Offline transport: the default for the read-only, no-network server.
# ---------------------------------------------------------------------------


class OfflineTransport:
    """A transport that always refuses: no network is configured.

    The MCP server is read-only and offline by default. ``search_knowledge``
    uses this transport so a fetch resolves to a typed ``WAIT_ENVIRONMENT``
    rather than touching the network. A caller that wants live retrieval must
    inject a real transport (tests may inject a fixture transport).
    """

    def __init__(self, reason: str = _SEARCH_OFFLINE_REASON) -> None:
        self.reason: str = reason

    def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:  # pragma: no cover
        """Refuse the fetch with a typed WAIT_ENVIRONMENT."""
        del url, timeout_seconds
        raise McpMethodError(
            self.reason,
            fail_reason=WAIT_ENVIRONMENT_FAIL_REASON,
            status="WAIT_ENVIRONMENT",
        )


# ---------------------------------------------------------------------------
# Method context: the in-memory, no-store context every method reads from.
# ---------------------------------------------------------------------------


class MethodContext:
    """The in-memory, no-store context the methods read from.

    The context carries only read-only inputs: a knowledge transport (offline
    by default), an optional cache directory for the retriever's content store,
    and nothing else. It is explicitly *not* a store, a scheduler, or a secret
    holder: the read-only property of the server is enforced by the context
    never exposing a write surface.
    """

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        # Offline by default: the server never opens the network on its own.
        self.transport: Transport = transport if transport is not None else OfflineTransport()
        self.cache_dir: str | Path | None = cache_dir


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _safety_consts() -> dict[str, Any]:
    """Return the read-only safety consts echoed on every result."""
    return {"canonical_writes": 0, "grants_authority": False}


def _success(method: str, *, result: dict[str, Any]) -> dict[str, Any]:
    """Assemble a typed SUCCESS envelope for ``method`` carrying ``result``."""
    return {
        "schema_version": MCP_RESULT_SCHEMA,
        "method": method,
        "status": "SUCCESS",
        "result": result,
        **_safety_consts(),
    }


def _typed_wait(
    method: str, *, fail_reason: str, status: str, detail: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble a typed WAIT/error envelope for ``method``.

    A typed wait is an honest result (not a JSON-RPC error): the method ran to
    completion and reported that the requested capability/environment is not
    available. The ``fail_reason`` and ``status`` carry the typed routing info.
    """
    out: dict[str, Any] = {
        "schema_version": MCP_RESULT_SCHEMA,
        "method": method,
        "status": status,
        "fail_reason": fail_reason,
        "detail": detail,
        **_safety_consts(),
    }
    if extra:
        out["extra"] = extra
    return out


def _require_dict(value: object, *, name: str) -> dict[str, Any]:
    """Return ``value`` if it is a dict, else raise a typed CONTRACT_INVALID."""
    if not isinstance(value, dict):
        msg = f"argument {name!r} must be an object, got {type(value).__name__}"
        raise McpMethodError(msg, fail_reason=CONTRACT_INVALID)
    return value


def _require_str(value: object, *, name: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise CONTRACT_INVALID."""
    if not isinstance(value, str) or not value:
        msg = f"argument {name!r} must be a non-empty string"
        raise McpMethodError(msg, fail_reason=CONTRACT_INVALID)
    return value


# ---------------------------------------------------------------------------
# P0 method: list_capabilities.
# ---------------------------------------------------------------------------


def m_list_capabilities(_ctx: MethodContext, _args: dict[str, Any]) -> dict[str, Any]:
    """List the shipped capability catalog entries (read-only).

    Mirrors ``srlab catalog list``. Returns the catalog digest and the sorted
    list of ``{profile, capability_id, availability}`` entries.
    """
    service = InterfaceService()
    listed = service.capability_list()
    result = {"catalog_digest": listed["catalog_digest"], "entries": listed["entries"]}
    return _success("list_capabilities", result=result)


# ---------------------------------------------------------------------------
# P0 method: inspect_capability.
# ---------------------------------------------------------------------------


def m_inspect_capability(_ctx: MethodContext, args: dict[str, Any]) -> dict[str, Any]:
    """Inspect one catalog entry by profile (read-only).

    Mirrors ``srlab catalog inspect`` scoped to one profile. The argument is
    ``{"profile": "<name>"}``. An unknown profile is a typed CONTRACT_INVALID.
    """
    profile = _require_str(args.get("profile"), name="profile")
    try:
        inspected = InterfaceService().inspect_capability(profile)
    except InterfaceServiceError as exc:
        raise McpMethodError(str(exc), fail_reason=CONTRACT_INVALID) from exc
    result = {"catalog_digest": inspected["catalog_digest"], "entry": inspected["entry"]}
    return _success("inspect_capability", result=result)


# ---------------------------------------------------------------------------
# P0 method: validate_claim.
# ---------------------------------------------------------------------------


def m_validate_claim(_ctx: MethodContext, args: dict[str, Any]) -> dict[str, Any]:
    """Validate a ScientificClaim/v1 (schema + invariants, read-only).

    Mirrors ``srlab claim validate``. The argument is the claim object itself.
    A schema or invariant failure is a typed CONTRACT_INVALID; a valid claim
    returns its class, status, and computed claim_id.
    """
    claim = _require_dict(args.get("claim"), name="claim")
    try:
        schema_validate(claim, "ScientificClaim")
        claim_validate(claim)
    except (SchemaError, ContractValidationError, ClaimInvariantError) as exc:
        extra: dict[str, Any] = {}
        if isinstance(exc, ClaimInvariantError):
            extra["invariant"] = exc.invariant
        if isinstance(exc, ContractValidationError):
            extra["json_path"] = exc.json_path
            extra["validator"] = exc.validator
        return _typed_wait(
            "validate_claim",
            fail_reason=CONTRACT_INVALID,
            status="INVALID",
            detail=str(exc),
            extra=extra or None,
        )
    result = {
        "valid": True,
        "claim_id": compute_claim_id(claim),
        "claim_class": claim.get("claim_class"),
        "claim_status": claim.get("claim_status"),
    }
    return _success("validate_claim", result=result)


# ---------------------------------------------------------------------------
# P0 method: build_plan.
# ---------------------------------------------------------------------------


def m_build_plan(_ctx: MethodContext, args: dict[str, Any]) -> dict[str, Any]:
    """Build a ScienceLabPlan/v1 from a request + claim (read-only).

    Mirrors ``srlab plan build``. The argument is
    ``{"request": <ScienceLabRunRequest/v1>, "claim": <ScientificClaim/v1>}``.
    Returns the plan, or a typed WAIT_REMOTE_EXECUTOR if the summed estimates
    overflow the admission caps.
    """
    request = _require_dict(args.get("request"), name="request")
    claim = _require_dict(args.get("claim"), name="claim")
    try:
        catalog = load_default_catalog()
        policy = default_policy()
        routing = route(request, claim, catalog, policy)
        plan = build_plan(request, routing, catalog, policy)
    except McpMethodError:
        raise
    except Exception as exc:
        fail_reason = getattr(exc, "fail_reason", CONTRACT_INVALID)
        if not isinstance(fail_reason, str) or not fail_reason:
            fail_reason = CONTRACT_INVALID
        status = "WAIT_REMOTE_EXECUTOR" if fail_reason == "WAIT_REMOTE_EXECUTOR" else "INVALID"
        return _typed_wait(
            "build_plan",
            fail_reason=fail_reason,
            status=status,
            detail=str(exc),
        )
    result = {
        "plan_id": plan.get("plan_id"),
        "plan_digest": plan.get("plan_digest"),
        "step_count": len(plan.get("steps", [])),
        "plan": plan,
    }
    return _success("build_plan", result=result)


# ---------------------------------------------------------------------------
# P0 method: inspect_run.
# ---------------------------------------------------------------------------


def m_inspect_run(_ctx: MethodContext, args: dict[str, Any]) -> dict[str, Any]:
    """Inspect a RunReceipt/v1 file (read-only).

    Mirrors ``srlab run verify`` (inspection only — never execution). The
    argument is ``{"receipt": <RunReceipt/v1 object>}`` or
    ``{"receipt_path": "<path>"}``. The receipt is loaded (never executed) and
    its structural validity is reported. If an ``output_path`` is present and
    the file exists, ``output_exists`` is true.
    """
    receipt_obj = args.get("receipt")
    receipt_path = args.get("receipt_path")
    if isinstance(receipt_path, str) and receipt_path:
        try:
            raw = Path(receipt_path).read_text(encoding="utf-8")
            receipt_obj = json.loads(raw)
        except OSError as exc:
            msg = f"could not read receipt {receipt_path!r}: {exc}"
            raise McpMethodError(msg, fail_reason=CONTRACT_INVALID) from exc
        except json.JSONDecodeError as exc:
            msg = f"receipt {receipt_path!r} is not valid JSON: {exc}"
            raise McpMethodError(msg, fail_reason=CONTRACT_INVALID) from exc
    receipt = _require_dict(receipt_obj, name="receipt")
    if receipt.get("schema_version") != "RunReceipt/v1":
        msg = "receipt must have schema_version RunReceipt/v1"
        raise McpMethodError(msg, fail_reason=CONTRACT_INVALID)
    output_path = receipt.get("output_path")
    output_exists = (
        isinstance(output_path, str) and bool(output_path) and Path(output_path).is_file()
    )
    result = {
        "schema_version": "RunReceiptInspection/v1",
        "status": receipt.get("status"),
        "adapter_id": receipt.get("adapter_id"),
        "output_path": output_path,
        "output_exists": output_exists,
        "valid": output_exists and receipt.get("status") == "completed",
    }
    return _success("inspect_run", result=result)


# ---------------------------------------------------------------------------
# P0 method: search_knowledge.
# ---------------------------------------------------------------------------


def m_search_knowledge(ctx: MethodContext, args: dict[str, Any]) -> dict[str, Any]:
    """Search a declared knowledge endpoint under the P0 policy (read-only).

    Mirrors ``srlab knowledge query``. The argument is
    ``{"endpoint_id": "...", "path": "...", "params": {...}}``. With the default
    offline transport this resolves to a typed ``WAIT_ENVIRONMENT`` (no network
    configured). A fixture transport (injected in tests/gates) returns the
    canned bytes as a real receipt.
    """
    endpoint_id = _require_str(args.get("endpoint_id"), name="endpoint_id")
    path = args.get("path")
    if path is None:
        path = ""
    if not isinstance(path, str):
        msg = "argument 'path' must be a string"
        raise McpMethodError(msg, fail_reason=CONTRACT_INVALID)
    raw_params = args.get("params", {})
    if not isinstance(raw_params, dict):
        msg = "argument 'params' must be an object"
        raise McpMethodError(msg, fail_reason=CONTRACT_INVALID)
    params: dict[str, Any] = dict(raw_params)

    retriever = ApiRetriever(transport=ctx.transport)
    # The cache dir is required by the retriever; use a temp dir when none is
    # configured (the offline transport never writes there because it refuses
    # before any fetch).
    cache_dir = ctx.cache_dir
    if cache_dir is None:
        cache_dir = tempfile.mkdtemp(prefix="srl-mcp-search-")
    try:
        fetched = retriever.fetch(
            endpoint_id=endpoint_id,
            path=path,
            params=params,
            cache_dir=str(cache_dir),
            policy_registry=p0_registry(),
            transport=ctx.transport,
        )
    except (NetworkPolicyError, RateLimitedError, ResourceLimitError, RetrievalTimeoutError) as exc:
        status, fail_reason = _knowledge_status(exc)
        return _typed_wait(
            "search_knowledge",
            fail_reason=fail_reason,
            status=status,
            detail=str(exc),
        )
    except McpMethodError as exc:
        # The offline transport raises McpMethodError (WAIT_ENVIRONMENT).
        return _typed_wait(
            "search_knowledge",
            fail_reason=exc.fail_reason,
            status=exc.status or "WAIT_ENVIRONMENT",
            detail=str(exc),
        )
    receipt: QueryReceipt = fetched.receipt
    result = {
        "schema_version": KNOWLEDGE_SEARCH_SCHEMA,
        "endpoint_id": endpoint_id,
        "status": "COMPLETED",
        "receipt": receipt.to_dict(),
        "bytes": len(fetched.payload),
    }
    return _success("search_knowledge", result=result)


def _knowledge_status(exc: Exception) -> tuple[str, str]:
    """Map a retriever exception to a (status, fail_reason) pair."""
    if isinstance(exc, NetworkPolicyError):
        return "NETWORK_POLICY_VIOLATION", exc.fail_reason
    if isinstance(exc, ResourceLimitError):
        return "RESOURCE_LIMIT", exc.fail_reason
    if isinstance(exc, RateLimitedError):
        return "WAIT_RESOURCE", exc.fail_reason
    if isinstance(exc, RetrievalTimeoutError):
        return "TIMEOUT", exc.fail_reason
    return "WAIT_ENVIRONMENT", WAIT_ENVIRONMENT_FAIL_REASON


# ---------------------------------------------------------------------------
# P0 method: build_export_packet (honestly stubbed -> WAIT_CAPABILITY).
# ---------------------------------------------------------------------------


def m_build_export_packet(_ctx: MethodContext, args: dict[str, Any]) -> dict[str, Any]:
    """Build an export packet (honestly stubbed: WAIT_CAPABILITY).

    The export-packet materializer lands in WP-I80. This method does NOT fake
    an export: it returns a typed ``WAIT_CAPABILITY`` carrying the exact reason
    and the WP it depends on. The argument is echoed back (validated as an
    object) so a caller can match the request to the wait.
    """
    _require_dict(args, name="args")
    result = {
        "schema_version": EXPORT_PACKET_SCHEMA,
        "plan_id": args.get("plan_id"),
        "dependents_on": "WP-I80",
        "reason": _EXPORT_WAIT_REASON,
    }
    return _typed_wait(
        "build_export_packet",
        fail_reason=WAIT_CAPABILITY_FAIL_REASON,
        status="WAIT_CAPABILITY",
        detail=_EXPORT_WAIT_REASON,
        extra=result,
    )


__all__ = [
    "CONTRACT_INVALID",
    "EXPORT_PACKET_SCHEMA",
    "KNOWLEDGE_SEARCH_SCHEMA",
    "MCP_RESULT_SCHEMA",
    "WAIT_CAPABILITY_FAIL_REASON",
    "WAIT_ENVIRONMENT_FAIL_REASON",
    "McpMethodError",
    "MethodContext",
    "OfflineTransport",
    "m_build_export_packet",
    "m_build_plan",
    "m_inspect_capability",
    "m_inspect_run",
    "m_list_capabilities",
    "m_search_knowledge",
    "m_validate_claim",
]
