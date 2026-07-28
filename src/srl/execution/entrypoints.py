"""Fixed-entrypoint adapter registry for the bounded runner (WP-D31).

The runner does **not** execute raw commands. It executes *adapters*, and every
adapter is a hard-coded entry in a static allowlist in this module. An adapter
id is opaque to the scheduler: it is never split, interpolated, or passed to a
shell, so an adapter id that looks like ``"echo.v1; rm -rf /"`` is simply *not
in the allowlist* and is rejected before any process is created.

No runtime registration
-----------------------
There is deliberately **no** ``register`` function that takes data. Adapters are
added by editing this file and shipping a new revision. Concretely this module
contains:

- no :func:`eval` of untrusted data;
- no :func:`importlib` import from a string supplied by input;
- no :func:`subprocess` of an arbitrary path.

The allowlist is static code; the registry is a frozen dict built at import
time. An unknown id raises :class:`UnknownAdapterError`
(``fail_reason='IR_UNSUPPORTED'``, routed via ``CONTRACT_INVALID`` per the WP
contract) — there is no fallback that turns an unknown id into a command.

Shipped adapters
----------------
Two built-in adapters ship with WP-D31:

``echo.v1``
    Returns its input payload unchanged. Used by the golden/conformance tests
    so the runner has a deterministic, side-effect-free adapter.
``uppercase.v1``
    Upper-cases the ``text`` field of its input payload. Exercises schema
    validation and output shaping on a tiny transformation.

Both are deterministic (``deterministic=True``) and carry a minimal
``input_schema`` used by the child to validate a payload before invoking the
handler.

Design notes
------------
This module is intentionally standard library only, mirroring the rest of
:mod:`srl.execution`. The registry is a module-level frozen mapping so it cannot
be mutated at runtime, and the handlers are plain callables (no metaprogramming).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

# The typed fail reason for an unknown adapter id. The WP contract routes an
# unknown adapter through ``CONTRACT_INVALID`` (the registry rejects before any
# process exists, so this is a contract/IR failure, not a compute failure).
UNKNOWN_ADAPTER_FAIL_REASON: Final[str] = "CONTRACT_INVALID"

# The IR-level fail reason mirrored from automation/fail-reasons.json for
# diagnostics: an unsupported intermediate representation.
IR_UNSUPPORTED_REASON: Final[str] = "IR_UNSUPPORTED"


class UnknownAdapterError(ValueError):
    """Raised when an adapter id is not in the static allowlist.

    A :class:`ValueError` (not an :class:`Exception`) so a caller handling
    malformed input via ``except ValueError`` still catches the family, mirroring
    :class:`srl.execution.policy.PolicyError`. The ``fail_reason`` is
    ``CONTRACT_INVALID`` (the registry rejects before any process is created).
    The ``adapter_id`` attribute records the rejected id for diagnostics.

    Attributes
    ----------
    adapter_id:
        The adapter id that was not in the allowlist.
    fail_reason:
        Typed fail reason (always ``CONTRACT_INVALID``).
    """

    def __init__(
        self, message: str, *, adapter_id: str, fail_reason: str = UNKNOWN_ADAPTER_FAIL_REASON
    ) -> None:
        super().__init__(message)
        self.adapter_id: str = adapter_id
        self.fail_reason: str = fail_reason


# A handler takes a validated payload dict and returns a payload dict. It is a
# plain callable: no I/O, no global state, no network. The type alias is kept
# explicit so mypy strict checks the handler signatures in the registry.
AdapterHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AdapterDescriptor:
    """A static entry in the adapter allowlist.

    The descriptor is immutable (frozen) and carries the minimal metadata the
    child needs to validate input and the runner needs to validate output.

    Attributes
    ----------
    adapter_id:
        The opaque id (e.g. ``"echo.v1"``). Must match the registry key.
    version:
        The adapter revision string (e.g. ``"v1"``). Bumping it is a code change.
    handler:
        The Python callable invoked with a validated payload. Pure: no I/O.
    input_schema:
        A minimal validation dict: ``required`` (list of field names that must be
        present) and ``optional`` (list of allowed optional field names). Any
        field not in either set is rejected so a payload cannot smuggle extra
        state into the handler.
    output_schema:
        Same shape as ``input_schema``; the runner validates the handler output
        against it so a misbehaving handler cannot emit an unbounded shape.
    deterministic:
        Always ``True`` for shipped adapters. A non-deterministic adapter would
        be a governance change (see GOVERNANCE.md).
    """

    adapter_id: str
    version: str
    handler: AdapterHandler
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    deterministic: bool


# ---------------------------------------------------------------------------
# Built-in handlers. Pure functions over dicts; no I/O, no network.
# ---------------------------------------------------------------------------


def _echo_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the payload unchanged (the ``echo.v1`` adapter).

    Used by the golden/conformance tests so the runner has a deterministic,
    side-effect-free adapter. The payload is already validated against the input
    schema by the child before this is called.
    """
    return dict(payload)


def _uppercase_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Upper-case the ``text`` field of the payload (the ``uppercase.v1`` adapter).

    Returns a new dict carrying the upper-cased ``text``. A missing or non-str
    ``text`` is rejected by schema validation (the ``text`` field is typed
    ``str``) before this runs, so the handler may narrow to ``str`` without a
    redundant check.
    """
    text = payload["text"]
    # Schema-validated as str; a non-str here would be a registry bug. Narrow
    # without an assert (production code does not use assertions).
    if not isinstance(text, str):
        msg = "uppercase.v1 handler received a non-str text despite schema typing"
        raise UnknownAdapterError(msg, adapter_id="uppercase.v1")
    return {"text": text.upper()}


# ---------------------------------------------------------------------------
# The static allowlist. Frozen at import time; no runtime mutation is exposed.
# ---------------------------------------------------------------------------

_ECHO_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="echo.v1",
    version="v1",
    handler=_echo_handler,
    # echo accepts any single field named "value" (optional, so an empty payload
    # is valid and echoes back empty). It must not carry arbitrary extra keys.
    input_schema={"required": [], "optional": ["value"]},
    output_schema={"required": [], "optional": ["value"]},
    deterministic=True,
)

_UPPERCASE_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="uppercase.v1",
    version="v1",
    handler=_uppercase_handler,
    # text is required and must be a str; output carries the upper-cased text.
    input_schema={"required": ["text"], "optional": [], "types": {"text": "str"}},
    output_schema={"required": ["text"], "optional": [], "types": {"text": "str"}},
    deterministic=True,
)

_REGISTRY: Final[dict[str, AdapterDescriptor]] = {
    _ECHO_V1.adapter_id: _ECHO_V1,
    _UPPERCASE_V1.adapter_id: _UPPERCASE_V1,
}

# The env-var gate for the test-only adapter hook. When this env var is set to
# "1", :func:`get_adapter` additionally consults :func:`_test_adapters` (a fixed
# in-repo test module). The hook exists so the WP-D31 gate and the unit tests
# can exercise timeout/output-cap/fork paths with a sleeper/bomb adapter
# without shipping those adapters in the production registry. It is NEVER set
# in production (CI production jobs, real runs); the shipped registry seen by
# any run without the gate is exactly {echo.v1, uppercase.v1}. Loading the test
# adapters is a normal import of a fixed module path, not an eval/importlib of
# caller-supplied data — there is no path from untrusted input to a handler.
_TEST_ADAPTERS_ENV: Final[str] = "SRL_RUNNER_TEST_ADAPTERS"


def _test_adapters() -> dict[str, AdapterDescriptor]:
    """Return test-only adapters when the gate env var is set; else empty.

    Imports :mod:`srl.execution._test_adapters` (a fixed module shipped under
    the package) only when ``SRL_RUNNER_TEST_ADAPTERS=1``. The module exposes
    ``ADAPTERS: dict[str, AdapterDescriptor]``; we trust it as in-repo code
    (same trust boundary as this file). Returns ``{}`` if the gate is unset or
    the module is unavailable, so a production run sees only the shipped set.
    """
    if os.environ.get(_TEST_ADAPTERS_ENV, "") != "1":
        return {}
    try:
        from srl.execution import _test_adapters as mod  # noqa: PLC0415  (gated lazy import)
    except ImportError:
        return {}
    got = getattr(mod, "ADAPTERS", None)
    if not isinstance(got, dict):
        return {}
    # Trust the in-repo module's descriptors (same trust boundary as _REGISTRY).
    return got


def _full_registry() -> dict[str, AdapterDescriptor]:
    """Return the shipped registry plus any gated test adapters (a snapshot)."""
    merged: dict[str, AdapterDescriptor] = dict(_REGISTRY)
    merged.update(_test_adapters())
    return merged


def _validate_against_schema(
    payload: object, schema: dict[str, Any], *, kind: str, adapter_id: str
) -> dict[str, Any]:
    """Validate ``payload`` against ``schema``; return it as a confirmed dict.

    Checks that ``payload`` is a JSON object (dict), that every ``required``
    field is present, that no field outside ``required | optional`` is present,
    and that any field listed in ``types`` carries the expected JSON type. A
    payload cannot smuggle extra state or a wrong-typed field. Raises
    :class:`UnknownAdapterError` (``CONTRACT_INVALID``) on any mismatch — the
    same fail reason is used for an unknown id and a malformed payload, because
    both are contract failures resolved before the handler runs.

    Parameters
    ----------
    payload:
        The decoded JSON payload to validate.
    schema:
        ``{"required": [...], "optional": [...], "types": {field: json_type}}``
        from the descriptor. ``types`` is optional; a listed field must match
        its JSON type name (``"str"``, ``"int"``, ``"bool"``, ``"object"``,
        ``"array"``).
    kind:
        ``"input"`` or ``"output"`` — used only in the diagnostic message.
    adapter_id:
        The adapter id — used only in the diagnostic message.
    """
    if not isinstance(payload, dict):
        msg = (
            f"adapter {adapter_id!r} {kind} payload must be a JSON object, "
            f"got {type(payload).__name__}"
        )
        raise UnknownAdapterError(msg, adapter_id=adapter_id)
    required = set(schema.get("required", []))
    optional = set(schema.get("optional", []))
    allowed = required | optional
    keys = set(payload.keys())
    missing = sorted(required - keys)
    if missing:
        msg = f"adapter {adapter_id!r} {kind} payload missing required field(s): {missing}"
        raise UnknownAdapterError(msg, adapter_id=adapter_id)
    extra = sorted(keys - allowed)
    if extra:
        msg = (
            f"adapter {adapter_id!r} {kind} payload has unexpected field(s): {extra} "
            f"(allowed: {sorted(allowed)})"
        )
        raise UnknownAdapterError(msg, adapter_id=adapter_id)
    # Type checks for fields listed in ``types``. Keeps a handler from receiving
    # a wrong-typed value it would then have to assert on.
    types = schema.get("types") or {}
    if isinstance(types, dict):
        for field, expected in types.items():
            if field not in keys:
                continue
            actual = _json_type_name(payload[field])
            if actual != expected:
                msg = (
                    f"adapter {adapter_id!r} {kind} field {field!r} must be "
                    f"{expected}, got {actual}"
                )
                raise UnknownAdapterError(msg, adapter_id=adapter_id)
    # ``payload`` is a dict[str, Any] at this point; the key set is bounded.
    return payload


# JSON type-name lookup keyed by the Python type. ``bool`` is listed before
# ``int`` because ``isinstance(True, int)`` is ``True`` and a flag must report
# as ``"bool"`` (mirrors the bool-rejecting discipline across srl.execution).
# Order matters: the first matching isinstance wins.
_JSON_TYPE_CHECKS: Final[tuple[tuple[type, str], ...]] = (
    (bool, "bool"),
    (str, "str"),
    (int, "int"),
    (float, "float"),
    (dict, "object"),
    (list, "array"),
)


def _json_type_name(value: object) -> str:
    """Return the JSON type name of ``value`` (``str``/``int``/``bool``/...).

    ``bool`` is reported as ``"bool"`` (not ``"int"``) even though
    ``isinstance(True, int)`` is ``True``, so a flag field typed ``bool``
    rejects an int and vice versa. Mirrors the bool-rejecting discipline used
    across :mod:`srl.execution`.
    """
    if value is None:
        return "null"
    for py_type, name in _JSON_TYPE_CHECKS:
        if isinstance(value, py_type):
            return name
    return type(value).__name__


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def list_adapters() -> list[str]:
    """Return the sorted list of allowed adapter ids (a snapshot copy).

    The returned list is a fresh copy so a caller cannot mutate the registry
    through it. In a production run (no test gate) it is exactly
    ``["echo.v1", "uppercase.v1"]``; under the test gate it additionally
    includes the fixed test adapters.
    """
    return sorted(_full_registry().keys())


def get_adapter(adapter_id: str) -> AdapterDescriptor:
    """Return the descriptor for ``adapter_id``; raise if unknown.

    The lookup is a plain dict membership test against the shipped registry
    (plus the gated test adapters, if the test hook is enabled). There is no
    fuzzy match, no command parsing, and no fallback: an unknown id is rejected
    here, before the runner ever builds a command line or spawns a process.

    Raises
    ------
    UnknownAdapterError
        If ``adapter_id`` is not in the registry. The ``fail_reason`` is
        ``CONTRACT_INVALID`` and the ``adapter_id`` attribute records the
        rejected id.
    """
    registry = _full_registry()
    desc = registry.get(adapter_id)
    if desc is None:
        msg = (
            f"unknown adapter id {adapter_id!r}: not in the static allowlist "
            f"(allowed: {sorted(registry.keys())})"
        )
        raise UnknownAdapterError(msg, adapter_id=adapter_id)
    return desc


def validate_input(adapter_id: str, payload: object) -> dict[str, Any]:
    """Validate ``payload`` against the adapter's input schema; return it.

    Convenience wrapper combining :func:`get_adapter` and schema validation. The
    runner/child call this before invoking the handler so a malformed payload is
    rejected as a contract failure, not a compute failure.
    """
    desc = get_adapter(adapter_id)
    return _validate_against_schema(payload, desc.input_schema, kind="input", adapter_id=adapter_id)


def validate_output(adapter_id: str, payload: object) -> dict[str, Any]:
    """Validate ``payload`` against the adapter's output schema; return it.

    Called by the runner after the handler returns / the child writes output, so
    a misbehaving handler that emits an unbounded shape is caught before a
    receipt is written.
    """
    desc = get_adapter(adapter_id)
    return _validate_against_schema(
        payload, desc.output_schema, kind="output", adapter_id=adapter_id
    )


def run_handler(adapter_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Look up ``adapter_id``, validate input, run the handler, validate output.

    This is the in-process entry point used by :mod:`srl.execution.child` (and
    directly by tests). It never touches the network or the filesystem beyond
    what the handler does (the shipped handlers do neither). A failure at any
    step raises :class:`UnknownAdapterError` (``CONTRACT_INVALID``).
    """
    desc = get_adapter(adapter_id)
    validated_in = _validate_against_schema(
        payload, desc.input_schema, kind="input", adapter_id=adapter_id
    )
    # A pure handler over a validated dict; the result is re-validated below.
    raw_out = desc.handler(validated_in)
    return _validate_against_schema(
        raw_out, desc.output_schema, kind="output", adapter_id=adapter_id
    )


__all__ = [
    "IR_UNSUPPORTED_REASON",
    "UNKNOWN_ADAPTER_FAIL_REASON",
    "AdapterDescriptor",
    "AdapterHandler",
    "UnknownAdapterError",
    "get_adapter",
    "list_adapters",
    "run_handler",
    "validate_input",
    "validate_output",
]
