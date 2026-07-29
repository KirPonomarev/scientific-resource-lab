from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from srl.products import (
    DiscoveryDynamicsError,
    default_a12_pack_policy,
    discovery_dynamics,
    prepare_a12_julia_depot,
    resolve_a12_runtime,
)


def test_a12_policy_activates_three_mandatory_packs_and_replaces_legacy_candidates() -> None:
    policies = default_a12_pack_policy()
    by_id = {policy.pack_id: policy for policy in policies}

    assert [policy.pack_id for policy in policies if policy.mandatory_for_a12] == [
        "pysr",
        "pysindy",
        "pydmd",
    ]
    assert by_id["pysr"].decision == "ACTIVE_REQUIRED"
    assert by_id["pysindy"].decision == "ACTIVE_REQUIRED"
    assert by_id["pydmd"].decision == "ACTIVE_REQUIRED"
    assert by_id["sr4mdl"].decision == "FORMALLY_REPLACED"
    assert by_id["pykoopman"].decision == "FORMALLY_REPLACED"
    assert by_id["dysts"].mandatory_for_a12 is False


def test_a12_runtime_fails_closed_without_julia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SRL_A12_JULIA_EXE", raising=False)
    monkeypatch.setenv("PATH", os.devnull)

    with pytest.raises(DiscoveryDynamicsError, match="explicit Julia executable"):
        resolve_a12_runtime()


def test_a12_runtime_rejects_nonexecutable_absolute_path(tmp_path: Path) -> None:
    fake = tmp_path / "julia"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")

    with pytest.raises(DiscoveryDynamicsError, match="not executable"):
        resolve_a12_runtime(julia_executable=str(fake))


def test_a12_runtime_binds_juliacall_and_juliapkg_to_same_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    julia = tmp_path / "julia"
    julia.write_text("#!/bin/sh\nprintf 'julia version 1.12.6\\n'\n", encoding="utf-8")
    julia.chmod(0o755)

    context = resolve_a12_runtime(julia_executable=str(julia), julia_depot_path=str(tmp_path))

    assert context.julia_version == "julia version 1.12.6"
    assert os.environ["PYTHON_JULIACALL_EXE"] == str(julia)
    assert os.environ["PYTHON_JULIAPKG_EXE"] == str(julia)
    assert os.environ["PYTHON_JULIACALL_HANDLE_SIGNALS"] == "yes"
    assert os.environ["JULIA_DEPOT_PATH"] == str(tmp_path)


def test_a12_prepare_julia_depot_is_bounded_and_authority_negative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    julia = tmp_path / "julia"
    julia.write_text("#!/bin/sh\nprintf 'julia version 1.12.6\\n'\n", encoding="utf-8")
    julia.chmod(0o755)
    calls: list[tuple[list[str], int | None, str | None]] = []
    real_run = subprocess.run

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        cmd = list(args[0]) if args else list(kwargs["args"])  # type: ignore[arg-type]
        if cmd == [str(julia), "--version"]:
            return real_run(cmd, check=False, capture_output=True, text=True, timeout=30)
        calls.append((cmd, kwargs.get("timeout"), kwargs.get("env", {}).get("PYTHON_JULIAPKG_EXE")))  # type: ignore[union-attr]
        return subprocess.CompletedProcess(cmd, 0, stdout="Resolved dependencies.\n", stderr="")

    monkeypatch.setattr(discovery_dynamics.subprocess, "run", fake_run)

    receipt = prepare_a12_julia_depot(
        julia_executable=str(julia),
        julia_depot_path=str(tmp_path / "depot"),
        timeout_seconds=17,
    )

    assert calls == [
        (
            [discovery_dynamics.sys.executable, "-m", "juliapkg", "resolve"],
            17,
            str(julia),
        )
    ]
    assert receipt["schema_version"] == "A12JuliaDepotPrepareReceipt/v1"
    assert receipt["prepared"] is True
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
    assert receipt["promotion_allowed"] is False
    assert receipt["receipt_id"].startswith("sha256:")
