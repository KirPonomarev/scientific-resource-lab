from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_gate_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "checks" / "srf-v37-a10-gate.py"
    spec = importlib.util.spec_from_file_location("srf_v37_a10_gate_under_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rocq_compile_shell_prefers_coqc() -> None:
    gate = _load_gate_module()

    command = gate._rocq_compile_shell("SRL_A10_ROCQ.v")

    assert command.startswith("if command -v coqc")
    assert "then coqc SRL_A10_ROCQ.v" in command
    assert "else rocq compile SRL_A10_ROCQ.v" in command
