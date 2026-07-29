from __future__ import annotations

import importlib.util
import subprocess
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

    command = gate._rocq_compile_shell("/work/SRL_A10_ROCQ.v")

    assert command.startswith("test -f /work/SRL_A10_ROCQ.v && if command -v coqc")
    assert "then coqc /work/SRL_A10_ROCQ.v" in command
    assert "else rocq compile /work/SRL_A10_ROCQ.v" in command


def test_rocq_docker_probe_uses_container_absolute_source_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    gate = _load_gate_module()
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: float = 180.0,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, timeout_seconds
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setenv("SRL_A10_ROCQ_DOCKER_IMAGE", "rocq/rocq-prover:9.2.0")
    monkeypatch.setenv("SRL_A10_TMPDIR", str(tmp_path))
    monkeypatch.setattr(gate, "_run", fake_run)

    result = gate._check_rocq()

    assert result["status"] == "PASS"
    assert len(commands) == 2
    proof_command = commands[1]
    assert "-v" in proof_command
    assert f"{tmp_path}" not in proof_command[-1]
    assert "test -f /work/SRL_A10_ROCQ.v" in proof_command[-1]
    assert "coqc /work/SRL_A10_ROCQ.v" in proof_command[-1]
