from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from srl.products import sciml_domain
from srl.products.sciml_domain import (
    A14JuliaContext,
    SciMLDomainActivationError,
    prepare_a14_julia_project,
    resolve_a14_julia_runtime,
    run_a14_sciml_domain_smoke,
)


def test_a14_runtime_fails_closed_without_julia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SRL_A14_JULIA_EXE", raising=False)
    monkeypatch.delenv("SRL_A14_JULIA_PROJECT_DIR", raising=False)
    monkeypatch.setattr(sciml_domain.shutil, "which", lambda _name: None)

    with pytest.raises(SciMLDomainActivationError, match="explicit Julia executable"):
        resolve_a14_julia_runtime()


def test_a14_runtime_requires_prepared_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    julia = tmp_path / "julia"
    julia.write_text("#!/bin/sh\nprintf 'julia version 1.12.6\\n'\n", encoding="utf-8")
    julia.chmod(0o755)
    monkeypatch.setattr(sciml_domain.shutil, "which", lambda _name: str(julia))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [str(julia), "--version"],
            0,
            stdout="julia version 1.12.6\n",
            stderr="",
        ),
    )

    with pytest.raises(SciMLDomainActivationError, match="not prepared"):
        resolve_a14_julia_runtime(julia_project_dir=tmp_path / "project")


def test_a14_prepare_julia_project_is_bounded_and_authority_negative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    julia = tmp_path / "julia"
    julia.write_text("#!/bin/sh\nprintf 'julia version 1.12.6\\n'\n", encoding="utf-8")
    julia.chmod(0o755)
    project = tmp_path / "project"
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd == [str(julia), "--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="julia version 1.12.6\n", stderr="")
        project.mkdir(parents=True, exist_ok=True)
        (project / "Project.toml").write_text("[deps]\n", encoding="utf-8")
        (project / "Manifest.toml").write_text("# manifest\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(sciml_domain.shutil, "which", lambda _name: str(julia))
    monkeypatch.setattr(subprocess, "run", fake_run)

    receipt = prepare_a14_julia_project(
        julia_executable=str(julia),
        julia_project_dir=project,
        julia_depot_path=str(tmp_path / "depot"),
    )

    assert receipt["schema_version"] == "A14JuliaProjectPrepareReceipt/v1"
    assert receipt["prepared"] is True
    assert receipt["julia_project_role"] == "isolated_stage_project"
    assert receipt["julia_depot_role"] == "explicit_env"
    assert receipt["promotion_allowed"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False
    assert calls[0][0] == str(julia)


def test_a14_receipt_model_rejects_bitwise_identity_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = A14JuliaContext(
        julia_executable="/usr/bin/julia",
        julia_version="julia version fixture",
        julia_project_dir=tmp_path,
        julia_depot_role="fixture",
        project_toml_sha256="0" * 64,
        manifest_toml_sha256="1" * 64,
    )

    def workload(pack_id: str) -> dict[str, object]:
        return {
            "family": "sciml" if "ode" in pack_id else "fixture",
            "language": "julia" if pack_id == "julia_sciml_ode" else "python",
            "backend_versions": {"fixture": "1"},
            "solver": {"name": "fixture", "family": "ode_explicit_runge_kutta"},
            "unit_bindings": ["time:s"],
            "tolerance": {"abs": 1e-6, "rel": 1e-6},
            "dataset": {"kind": "synthetic"},
            "diagnostics": {"terminal": 0.1},
            "trace_sha256": "a" * 64,
            "trace_digest_algorithm": "sha256",
            "bitwise_identity_claimed": pack_id == "python_diffrax_ode",
        }

    monkeypatch.setattr(sciml_domain, "resolve_a14_julia_runtime", lambda **_kwargs: context)
    monkeypatch.setattr(
        sciml_domain,
        "_run_julia_sciml_ode",
        lambda _ctx: workload("julia_sciml_ode"),
    )
    monkeypatch.setattr(sciml_domain, "_run_diffrax_ode", lambda: workload("python_diffrax_ode"))
    monkeypatch.setattr(
        sciml_domain,
        "_run_qutip_quantum",
        lambda: workload("python_qutip_quantum"),
    )
    monkeypatch.setattr(
        sciml_domain,
        "_run_astropy_astronomy",
        lambda: workload("python_astropy_astronomy"),
    )
    monkeypatch.setattr(
        sciml_domain,
        "_run_cantera_combustion",
        lambda: workload("python_cantera_combustion"),
    )
    monkeypatch.setattr(
        sciml_domain,
        "_run_native_battery_rc",
        lambda: workload("native_battery_rc"),
    )
    monkeypatch.setattr(
        sciml_domain,
        "_run_quimb_many_body",
        lambda: workload("python_quimb_many_body"),
    )
    monkeypatch.setattr(
        sciml_domain,
        "_run_cotengra_tensor_network",
        lambda: workload("python_cotengra_tensor_network"),
    )

    with pytest.raises(SciMLDomainActivationError, match="claimed bitwise identity"):
        run_a14_sciml_domain_smoke()


def test_native_battery_workload_is_bounded_and_unit_bound() -> None:
    receipt = sciml_domain._run_native_battery_rc()

    assert receipt["family"] == "battery"
    assert receipt["backend_versions"] == {"native": "srl-a14-rc-battery-v1"}
    assert "voltage:V" in receipt["unit_bindings"]
    assert receipt["diagnostics"]["final_soc"] == pytest.approx(0.8)
    assert receipt["bitwise_identity_claimed"] is False
    assert "trace_sha256" in receipt
