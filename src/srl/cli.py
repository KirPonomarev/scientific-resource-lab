"""JSON-first command-line dispatcher for SRL.

This module is deliberately free of :mod:`argparse`. The dispatcher is a small,
explicit table so that the CLI contract is auditable: every command produces
canonical JSON on stdout (see :mod:`srl.canonical`) and a deterministic exit
code.

Contracts
---------
- ``srlab doctor`` / ``srlab version``
      Legacy Phase-A reports (unchanged, A02 tests rely on them).
- ``srlab schema validate <schema-name> <file>``
      Validate a JSON file against a shipped schema.
- ``srlab claim validate <file>``
      Validate a ScientificClaim JSON + invariants.
- ``srlab plan build <bundle-file>`` / ``srlab plan inspect <file>``
      Build or inspect a ScienceLabPlan.
- ``srlab cas status|verify|fsck <root>``
      Local artifact store operations.
- ``srlab run execute <run-spec-file>`` / ``srlab run verify <receipt-file>``
      Bounded execution via the runner.
- ``srlab knowledge query <endpoint-id> <path> [params-json]``
      Budgeted API query; offline-safe.
- ``srlab catalog list|inspect``
      View the shipped capability catalog.
- any unknown or missing command
      Error report and exit 2.

Exit code semantics
-------------------
``0`` means the operation completed and a receipt was emitted; it never means a
scientific claim is supported. The typed error codes are ``2`` for an unknown
command, ``3`` for fsck corruption findings, and ``4`` for a run policy
violation. All other command failures exit ``1``.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from srl.canonical import canonical_json_line
from srl.cas.store import LocalArtifactStore
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.contracts.schema import ContractValidationError, SchemaError
from srl.contracts.schema import validate as schema_validate
from srl.execution.policy import load_policy
from srl.execution.runner import POLICY_VIOLATION_FAIL_REASON, RunStatus, run_adapter
from srl.execution.sandbox import prepare_scratch
from srl.interfaces import InterfaceService, InterfaceServiceError
from srl.knowledge.adapters import p0_registry
from srl.knowledge.retriever import (
    ApiRetriever,
    NetworkPolicyError,
    QueryReceipt,
    RateLimitedError,
    ResourceLimitError,
    RetrievalTimeoutError,
    TransportResponse,
)
from srl.planning import build_plan, default_policy, load_default_catalog, route
from srl.semantic.claims import ClaimInvariantError
from srl.semantic.claims import validate as claim_validate

# Exit codes. Named to avoid magic-value lint and to document intent.
EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_FSCK: Final[int] = 3
EXIT_POLICY: Final[int] = 4

# Schema versions emitted by this dispatcher. Bumped only on a contract change.
DOCTOR_SCHEMA: Final[str] = "DoctorReport/v1"
VERSION_SCHEMA: Final[str] = "VersionReport/v1"
ERROR_SCHEMA: Final[str] = "ErrorReport/v1"

# Generic typed fail reason for command-level structural failures.
_COMMAND_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Minimum argument counts for commands that validate argument length.
_SCHEMA_VALIDATE_ARG_COUNT: Final[int] = 2
_KNOWLEDGE_MIN_ARGS: Final[int] = 2
_KNOWLEDGE_PARAMS_INDEX: Final[int] = 3


# ---------------------------------------------------------------------------
# Low-level helpers.
# ---------------------------------------------------------------------------


def _error_report(
    command: str,
    message: str,
    *,
    fail_reason: str = _COMMAND_FAIL_REASON,
) -> dict[str, Any]:
    """Build an ErrorReport/v1 payload for a failed command."""
    return {
        "schema_version": ERROR_SCHEMA,
        "error": message,
        "command": command,
        "fail_reason": fail_reason,
    }


def _emit(report: dict[str, Any]) -> None:
    """Write one canonical JSON record (with trailing newline) to stdout."""
    _ = sys.stdout.write(canonical_json_line(report))


def _emit_err(report: dict[str, Any]) -> None:
    """Write one canonical JSON record (with trailing newline) to stderr."""
    _ = sys.stderr.write(canonical_json_line(report))


def _doctor_report() -> dict[str, Any]:
    """Build the DoctorReport/v1 payload describing the runtime."""
    return dict(InterfaceService().doctor())


def _version_report() -> dict[str, Any]:
    """Build the VersionReport/v1 payload."""
    return dict(InterfaceService().version())


def _load_json_file(path_str: str, command: str) -> dict[str, Any] | int:
    """Load a JSON object from ``path_str``; on failure emit an error and return 1."""
    path = Path(path_str)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        _emit_err(_error_report(command, f"could not read {path_str!r}: {exc}"))
        return EXIT_ERROR
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit_err(_error_report(command, f"{path_str!r} is not valid JSON: {exc}"))
        return EXIT_ERROR
    if not isinstance(doc, dict):
        _emit_err(_error_report(command, f"{path_str!r} must be a JSON object"))
        return EXIT_ERROR
    return doc


# ---------------------------------------------------------------------------
# Global option parsing.
# ---------------------------------------------------------------------------


def _pop_options(args: list[str]) -> tuple[dict[str, str | None], list[str]]:
    """Extract ``--cache-dir`` and ``--transport`` options; return the rest.

    Supports both ``--option value`` and ``--option=value`` forms. If an option
    is passed without a value the returned dict maps it to ``None`` so the caller
    can treat that as an explicit-but-empty flag.
    """
    options: dict[str, str | None] = {}
    rest: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--cache-dir":
            options["cache-dir"] = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if arg == "--transport":
            options["transport"] = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if arg.startswith("--cache-dir="):
            options["cache-dir"] = arg.split("=", 1)[1]
            i += 1
            continue
        if arg.startswith("--transport="):
            options["transport"] = arg.split("=", 1)[1]
            i += 1
            continue
        rest.append(arg)
        i += 1
    return options, rest


# ---------------------------------------------------------------------------
# Command handlers.
# ---------------------------------------------------------------------------


def _cmd_schema_validate(args: list[str], options: dict[str, str | None]) -> int:
    """``schema validate <schema-name> <file>``."""
    del options
    if len(args) < _SCHEMA_VALIDATE_ARG_COUNT:
        _emit_err(_error_report("schema validate", "expected <schema-name> <file>"))
        return EXIT_ERROR
    schema_name, path_str = args[0], args[1]
    doc = _load_json_file(path_str, "schema validate")
    if isinstance(doc, int):
        return doc
    try:
        schema_validate(doc, schema_name)
    except (SchemaError, ContractValidationError) as exc:
        extra: dict[str, Any] = {}
        if isinstance(exc, ContractValidationError):
            extra["json_path"] = exc.json_path
            extra["validator"] = exc.validator
        _emit_err(
            {
                "schema_version": ERROR_SCHEMA,
                "error": str(exc),
                "command": "schema validate",
                "fail_reason": _COMMAND_FAIL_REASON,
                **extra,
            }
        )
        return EXIT_ERROR
    _emit(
        {
            "schema_version": "SchemaValidationReport/v1",
            "schema_name": schema_name,
            "file": path_str,
            "valid": True,
        }
    )
    return EXIT_OK


def _cmd_claim_validate(args: list[str], options: dict[str, str | None]) -> int:
    """``claim validate <file>``."""
    del options
    if not args:
        _emit_err(_error_report("claim validate", "expected <file>"))
        return EXIT_ERROR
    path_str = args[0]
    doc = _load_json_file(path_str, "claim validate")
    if isinstance(doc, int):
        return doc
    try:
        schema_validate(doc, "ScientificClaim")
        claim_validate(doc)
    except (SchemaError, ContractValidationError, ClaimInvariantError) as exc:
        extra: dict[str, Any] = {}
        fail_reason = _COMMAND_FAIL_REASON
        if isinstance(exc, ClaimInvariantError):
            extra["invariant"] = exc.invariant
        if isinstance(exc, ContractValidationError):
            extra["json_path"] = exc.json_path
            extra["validator"] = exc.validator
        _emit_err(
            {
                "schema_version": ERROR_SCHEMA,
                "error": str(exc),
                "command": "claim validate",
                "fail_reason": fail_reason,
                **extra,
            }
        )
        return EXIT_ERROR
    _emit(
        {
            "schema_version": "ClaimValidationReport/v1",
            "file": path_str,
            "valid": True,
            "claim_class": doc.get("claim_class"),
            "claim_status": doc.get("claim_status"),
        }
    )
    return EXIT_OK


def _cmd_plan_build(args: list[str], options: dict[str, str | None]) -> int:
    """``plan build <bundle-file>``.

    The bundle file is a JSON object with two keys: ``request`` (a valid
    ScienceLabRunRequest/v1) and ``claim`` (a valid ScientificClaim/v1).
    """
    del options
    if not args:
        _emit_err(_error_report("plan build", "expected <bundle-file>"))
        return EXIT_ERROR
    path_str = args[0]
    bundle = _load_json_file(path_str, "plan build")
    if isinstance(bundle, int):
        return bundle
    request = bundle.get("request")
    claim = bundle.get("claim")
    if not isinstance(request, dict) or not isinstance(claim, dict):
        _emit_err(
            _error_report("plan build", f"{path_str!r} must contain 'request' and 'claim' objects")
        )
        return EXIT_ERROR
    try:
        catalog = load_default_catalog()
        policy = default_policy()
        routing = route(request, claim, catalog, policy)
        plan = build_plan(request, routing, catalog, policy)
    except Exception as exc:
        fail_reason = getattr(exc, "fail_reason", _COMMAND_FAIL_REASON)
        if not isinstance(fail_reason, str):
            fail_reason = _COMMAND_FAIL_REASON
        _emit_err(_error_report("plan build", str(exc), fail_reason=fail_reason))
        return EXIT_ERROR
    _emit(
        {
            "schema_version": "PlanBuildReport/v1",
            "file": path_str,
            "plan_id": plan.get("plan_id"),
            "plan_digest": plan.get("plan_digest"),
            "steps": len(plan.get("steps", [])),
            "plan": plan,
        }
    )
    return EXIT_OK


def _cmd_plan_inspect(args: list[str], options: dict[str, str | None]) -> int:
    """``plan inspect <file>``."""
    del options
    if not args:
        _emit_err(_error_report("plan inspect", "expected <file>"))
        return EXIT_ERROR
    path_str = args[0]
    doc = _load_json_file(path_str, "plan inspect")
    if isinstance(doc, int):
        return doc
    try:
        schema_validate(doc, "ScienceLabPlan")
    except (SchemaError, ContractValidationError) as exc:
        _emit_err(_error_report("plan inspect", str(exc)))
        return EXIT_ERROR
    steps = doc.get("steps", [])
    selected = sum(1 for s in steps if s.get("selection") == "SELECTED")
    wait = sum(1 for s in steps if s.get("selection") == "WAIT_CAPABILITY")
    _emit(
        {
            "schema_version": "PlanInspectionReport/v1",
            "file": path_str,
            "plan_id": doc.get("plan_id"),
            "plan_digest": doc.get("plan_digest"),
            "step_count": len(steps),
            "selected_count": selected,
            "wait_capability_count": wait,
        }
    )
    return EXIT_OK


def _cmd_cas(args: list[str], subcommand: str) -> int:
    """``cas status|verify|fsck <root>``."""
    if not args:
        _emit_err(_error_report(f"cas {subcommand}", "expected <root>"))
        return EXIT_ERROR
    root = args[0]
    try:
        store = LocalArtifactStore(root)
    except Exception as exc:
        _emit_err(_error_report(f"cas {subcommand}", f"cannot open store {root!r}: {exc}"))
        return EXIT_ERROR

    try:
        report = store.fsck()
    except Exception as exc:
        _emit_err(_error_report(f"cas {subcommand}", f"store sweep failed: {exc}"))
        return EXIT_ERROR

    if subcommand == "status":
        _emit(
            {
                "schema_version": "CasStatusReport/v1",
                "root": store.store_root_redacted,
                "objects_checked": report.objects_checked,
                "objects_passed": report.objects_passed,
                "failed_count": len(report.failed_digests),
            }
        )
        return EXIT_OK

    if subcommand == "verify":
        _emit(
            {
                "schema_version": "CasVerifyReport/v1",
                "root": store.store_root_redacted,
                "objects_checked": report.objects_checked,
                "objects_passed": report.objects_passed,
                "failed_digests": report.failed_digests,
                "valid": len(report.failed_digests) == 0,
            }
        )
        return EXIT_OK if not report.failed_digests else EXIT_ERROR

    # subcommand == "fsck"
    _emit(
        {
            "schema_version": "CasFsckReport/v1",
            "root": store.store_root_redacted,
            "objects_checked": report.objects_checked,
            "objects_passed": report.objects_passed,
            "failed_digests": report.failed_digests,
        }
    )
    return EXIT_OK if not report.failed_digests else EXIT_FSCK


# ---------------------------------------------------------------------------
# Run handlers.
# ---------------------------------------------------------------------------


def _run_policy_path() -> Path:
    """Return the path to the shipped M1 resource policy file."""
    return Path(__file__).resolve().parents[2] / "policies" / "resource-policy-m1.json"


def _load_run_spec(args: list[str]) -> tuple[dict[str, Any] | None, int]:
    """Load and validate a run-spec file; return (spec, 0) or (None, code)."""
    if not args:
        _emit_err(_error_report("run execute", "expected <run-spec-file>"))
        return None, EXIT_ERROR
    doc = _load_json_file(args[0], "run execute")
    if isinstance(doc, int):
        return None, doc
    adapter_id = doc.get("adapter_id")
    input_payload = doc.get("input")
    if not isinstance(adapter_id, str) or not adapter_id:
        _emit_err(_error_report("run execute", "run spec must contain a non-empty 'adapter_id'"))
        return None, EXIT_ERROR
    return {"adapter_id": adapter_id, "input": input_payload}, EXIT_OK


def _run_adapter_command(spec: dict[str, Any]) -> tuple[Any, str]:
    """Execute a bounded run and return (outcome, ""). On failure return (None, message)."""
    policy_path = _run_policy_path()
    try:
        policy = load_policy(str(policy_path))
        scratch = prepare_scratch()
        try:
            outcome = run_adapter(
                adapter_id=spec["adapter_id"],
                input_payload=spec["input"],
                policy=policy,
                scratch=scratch,
                wall_seconds=5,
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return outcome, ""
    except Exception as exc:
        return None, str(exc)


def _cmd_run_execute(args: list[str], options: dict[str, str | None]) -> int:
    """``run execute <run-spec-file>``.

    The run spec is a JSON object with ``adapter_id`` and ``input`` keys.
    """
    del options
    spec, code = _load_run_spec(args)
    if spec is None:
        return code
    outcome, error = _run_adapter_command(spec)
    if outcome is None:
        _emit_err(_error_report("run execute", error))
        return EXIT_ERROR
    if outcome.status == RunStatus.COMPLETED:
        _emit(
            {
                "schema_version": "RunExecutionReport/v1",
                "adapter_id": outcome.adapter_id,
                "status": outcome.status.value,
                "receipt_written": outcome.receipt_written,
                "usage": outcome.usage.to_dict(),
                "output": outcome.output,
            }
        )
        return EXIT_OK
    if outcome.status == RunStatus.POLICY_VIOLATION:
        _emit_err(
            {
                "schema_version": ERROR_SCHEMA,
                "error": outcome.detail,
                "command": "run execute",
                "fail_reason": POLICY_VIOLATION_FAIL_REASON,
            }
        )
        return EXIT_POLICY
    _emit_err(
        _error_report(
            "run execute",
            f"run ended with status {outcome.status.value}: {outcome.detail}",
        )
    )
    return EXIT_ERROR


def _cmd_run_verify(args: list[str], options: dict[str, str | None]) -> int:
    """``run verify <receipt-file>``."""
    del options
    if not args:
        _emit_err(_error_report("run verify", "expected <receipt-file>"))
        return EXIT_ERROR
    path_str = args[0]
    doc = _load_json_file(path_str, "run verify")
    if isinstance(doc, int):
        return doc
    if doc.get("schema_version") != "RunReceipt/v1":
        _emit_err(_error_report("run verify", "receipt must have schema_version RunReceipt/v1"))
        return EXIT_ERROR
    output_path = doc.get("output_path")
    if not isinstance(output_path, str) or not output_path:
        _emit_err(_error_report("run verify", "receipt missing 'output_path'"))
        return EXIT_ERROR
    output_exists = Path(output_path).is_file()
    _emit(
        {
            "schema_version": "RunReceiptVerificationReport/v1",
            "file": path_str,
            "output_path": output_path,
            "output_exists": output_exists,
            "status": doc.get("status"),
            "adapter_id": doc.get("adapter_id"),
            "valid": output_exists and doc.get("status") == "completed",
        }
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Knowledge handlers.
# ---------------------------------------------------------------------------


class _FixtureTransport:
    """A no-network transport that returns a fixed payload over HTTPS."""

    def __init__(self, payload: bytes, host: str) -> None:
        self.payload = payload
        self.host = host

    def fetch(self, url: str, *, timeout_seconds: int) -> TransportResponse:
        """Return the canned payload with an HTTPS final scheme/host."""
        del url, timeout_seconds
        return TransportResponse(
            payload=self.payload,
            final_scheme="https",
            final_host=self.host,
            status=200,
        )


class _KnowledgeArgs:
    """Parsed positional arguments for ``knowledge query``."""

    def __init__(self, endpoint_id: str, path: str, params: dict[str, Any]) -> None:
        self.endpoint_id = endpoint_id
        self.path = path
        self.params = params


def _parse_knowledge_args(args: list[str]) -> tuple[_KnowledgeArgs | None, int]:
    """Parse endpoint/path/params for ``knowledge query``."""
    if len(args) < _KNOWLEDGE_MIN_ARGS:
        _emit_err(_error_report("knowledge query", "expected <endpoint-id> <path> [params-json]"))
        return None, EXIT_ERROR
    endpoint_id = args[0]
    path = args[1]
    params: dict[str, Any] = {}
    if len(args) >= _KNOWLEDGE_PARAMS_INDEX:
        try:
            parsed = json.loads(args[2])
        except json.JSONDecodeError as exc:
            _emit_err(_error_report("knowledge query", f"params-json is not valid JSON: {exc}"))
            return None, EXIT_ERROR
        if not isinstance(parsed, dict):
            _emit_err(_error_report("knowledge query", "params-json must be a JSON object"))
            return None, EXIT_ERROR
        params = parsed
    return _KnowledgeArgs(endpoint_id, path, params), EXIT_OK


def _build_fixture_transport(
    transport_path: str, endpoint_id: str
) -> tuple[_FixtureTransport | None, int]:
    """Build a no-network transport from a fixture payload file."""
    payload_path = Path(transport_path)
    try:
        payload = payload_path.read_bytes()
    except OSError as exc:
        _emit_err(_error_report("knowledge query", f"could not read transport fixture: {exc}"))
        return None, EXIT_ERROR
    registry = p0_registry()
    if endpoint_id in registry:
        host = registry.get(endpoint_id).base_url.split("//", 1)[-1]
    else:
        host = "unknown"
    return _FixtureTransport(payload, host), EXIT_OK


def _knowledge_fetch_status(exc: Exception) -> tuple[str, str, str]:
    """Map a retriever exception to a (status, fail_reason, detail) triple."""
    if isinstance(exc, NetworkPolicyError):
        return "NETWORK_POLICY_VIOLATION", exc.fail_reason, str(exc)
    if isinstance(exc, ResourceLimitError):
        return "RESOURCE_LIMIT", exc.fail_reason, str(exc)
    if isinstance(exc, RateLimitedError):
        return "WAIT_RESOURCE", exc.fail_reason, str(exc)
    if isinstance(exc, RetrievalTimeoutError):
        return "TIMEOUT", exc.fail_reason, str(exc)
    return "WAIT_ENVIRONMENT", "WAIT_ENVIRONMENT", str(exc)


def _cmd_knowledge_query(args: list[str], options: dict[str, str | None]) -> int:
    """``knowledge query <endpoint-id> <path> [params-json]``.

    Requires ``--cache-dir``. Accepts ``--transport <file>`` for hermetic tests.
    """
    cache_dir = options.get("cache-dir")
    if not isinstance(cache_dir, str) or not cache_dir:
        _emit_err(_error_report("knowledge query", "missing required --cache-dir"))
        return EXIT_ERROR
    parsed, code = _parse_knowledge_args(args)
    if parsed is None:
        return code

    transport = None
    transport_path = options.get("transport")
    if isinstance(transport_path, str) and transport_path:
        transport, code = _build_fixture_transport(transport_path, parsed.endpoint_id)
        if transport is None:
            return code

    retriever = ApiRetriever()
    try:
        result = retriever.fetch(
            endpoint_id=parsed.endpoint_id,
            path=parsed.path,
            params=parsed.params,
            cache_dir=cache_dir,
            policy_registry=p0_registry(),
            transport=transport,
        )
        receipt: QueryReceipt = result.receipt
        _emit(
            {
                "schema_version": "KnowledgeQueryReport/v1",
                "endpoint_id": parsed.endpoint_id,
                "status": "COMPLETED",
                "receipt": receipt.to_dict(),
                "bytes": len(result.payload),
            }
        )
        return EXIT_OK
    except Exception as exc:
        status, fail_reason, detail = _knowledge_fetch_status(exc)
    _emit_err(
        {
            "schema_version": ERROR_SCHEMA,
            "error": detail,
            "command": "knowledge query",
            "fail_reason": fail_reason,
            "status": status,
        }
    )
    return EXIT_ERROR


# ---------------------------------------------------------------------------
# Catalog handlers.
# ---------------------------------------------------------------------------


def _cmd_catalog(args: list[str], subcommand: str) -> int:
    """``catalog list|inspect``."""
    del args
    try:
        service = InterfaceService()
    except Exception as exc:
        _emit_err(_error_report(f"catalog {subcommand}", str(exc)))
        return EXIT_ERROR
    if subcommand == "list":
        _emit(service.capability_list())
        return EXIT_OK
    # subcommand == "inspect"
    _emit(service.capability_report())
    return EXIT_OK


# ---------------------------------------------------------------------------
# Labctl handlers.
# ---------------------------------------------------------------------------


def _cmd_labctl_enter(args: list[str], options: dict[str, str | None]) -> int:
    """``labctl enter [cell-id]`` emits a scope-only LabAccessReceipt."""
    del options
    cell_id = args[0] if args else "standalone"
    try:
        report = InterfaceService().enter(cell_id)
    except InterfaceServiceError as exc:
        _emit_err(_error_report("labctl enter", str(exc)))
        return EXIT_ERROR
    _emit(report)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Dispatch table.
# ---------------------------------------------------------------------------

_Handler = Callable[[list[str], dict[str, str | None]], int]


def _cas_handler(subcommand: str) -> _Handler:
    """Return a handler that forwards the cas subcommand."""

    def _handler(args: list[str], options: dict[str, str | None]) -> int:
        del options
        return _cmd_cas(args, subcommand)

    return _handler


def _catalog_handler(subcommand: str) -> _Handler:
    """Return a handler that forwards the catalog subcommand."""

    def _handler(args: list[str], options: dict[str, str | None]) -> int:
        del options
        return _cmd_catalog(args, subcommand)

    return _handler


_SUBCOMMANDS: Final[dict[str, dict[str, _Handler]]] = {
    "schema": {"validate": _cmd_schema_validate},
    "claim": {"validate": _cmd_claim_validate},
    "plan": {"build": _cmd_plan_build, "inspect": _cmd_plan_inspect},
    "cas": {
        "status": _cas_handler("status"),
        "verify": _cas_handler("verify"),
        "fsck": _cas_handler("fsck"),
    },
    "run": {"execute": _cmd_run_execute, "verify": _cmd_run_verify},
    "knowledge": {"query": _cmd_knowledge_query},
    "catalog": {
        "list": _catalog_handler("list"),
        "inspect": _catalog_handler("inspect"),
    },
    "labctl": {"enter": _cmd_labctl_enter},
}


# Legacy Phase-A top-level commands (kept on stdout for A02 compatibility).
_LEGACY_COMMANDS: Final[dict[str, Callable[[], dict[str, Any]]]] = {
    "doctor": _doctor_report,
    "version": _version_report,
}


# Namespaced top-level commands recognized by the dispatcher.
_NAMESPACES: Final[set[str]] = set(_SUBCOMMANDS)


def _unknown_top_level(command: str) -> int:
    """Emit an error report for an unknown top-level command (A02 stdout contract)."""
    _emit(_error_report(command, "unknown command", fail_reason=_COMMAND_FAIL_REASON))
    return EXIT_USAGE


def _missing_command() -> int:
    """Emit an error report for a missing command (A02 stdout contract)."""
    _emit(_error_report("", "missing command", fail_reason=_COMMAND_FAIL_REASON))
    return EXIT_USAGE


def _unknown_subcommand(namespace: str, subcommand: str) -> int:
    """Emit an error report for an unknown subcommand."""
    _emit_err(
        _error_report(
            f"{namespace} {subcommand}",
            f"unknown {namespace} subcommand",
        )
    )
    return EXIT_USAGE


def _handle_namespace(namespace: str, args: list[str], options: dict[str, str | None]) -> int:
    """Dispatch a namespaced command via the subcommand table."""
    subcommand = args[0] if args else ""
    table = _SUBCOMMANDS.get(namespace)
    if table is None:
        return _unknown_top_level(namespace)
    handler = table.get(subcommand)
    if handler is None:
        return _unknown_subcommand(namespace, subcommand)
    return handler(args[1:], options)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI dispatcher and return an exit code.

    Parameters
    ----------
    argv:
        Optional argument vector excluding the program name. When ``None`` the
        real :data:`sys.argv` is used (minus the program name).

    Returns
    -------
    int
        :data:`EXIT_OK` for a completed command, :data:`EXIT_USAGE` for an
        unknown or missing top-level command, :data:`EXIT_FSCK` for fsck
        corruption findings, :data:`EXIT_POLICY` for a run policy violation,
        or :data:`EXIT_ERROR` for other command failures.
    """
    raw_args = sys.argv[1:] if argv is None else argv
    options, args = _pop_options(raw_args)
    command = args[0] if args else ""

    if command in _LEGACY_COMMANDS:
        _emit(_LEGACY_COMMANDS[command]())
        return EXIT_OK

    if command == "":
        return _missing_command()

    if command not in _NAMESPACES:
        return _unknown_top_level(command)

    return _handle_namespace(command, args[1:], options)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
