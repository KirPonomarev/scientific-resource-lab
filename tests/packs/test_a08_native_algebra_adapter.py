"""Tests for the A08 native algebra/SMT adapter."""

from __future__ import annotations

import ast
from pathlib import Path

from srl.packs.adapters.native_algebra import (
    A08_NATIVE_SCHEMA_VERSION,
    A08ToolState,
    run_a08_native_smoke,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADAPTER = _REPO_ROOT / "src" / "srl" / "packs" / "adapters" / "native_algebra.py"


def test_native_smoke_shape_and_truth_states() -> None:
    smoke = run_a08_native_smoke()
    data = smoke.to_dict()
    assert data["schema_version"] == A08_NATIVE_SCHEMA_VERSION
    component_ids = {item["component_id"] for item in data["tools"]}  # type: ignore[index]
    assert component_ids == {"pari-gp", "maxima", "gap", "singular", "z3-native", "cvc5"}
    for item in smoke.tools:
        assert item.state in {A08ToolState.ACTIVE, A08ToolState.WAIT_TOOLCHAIN}
        assert (
            item.license_boundary == "external native executable; not vendored and not in uv.lock"
        )
        if item.active:
            assert item.executable
            assert item.version_detail
            assert item.smoke_detail != "not run"
            assert item.crosscheck_detail


def test_native_adapter_uses_fixed_subprocess_vectors() -> None:
    tree = ast.parse(_ADAPTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "run":
                keyword_values = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                shell_value = keyword_values.get("shell")
                assert shell_value is None or (
                    isinstance(shell_value, ast.Constant) and shell_value.value is False
                )
