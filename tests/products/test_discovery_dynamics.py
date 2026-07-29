from __future__ import annotations

import os
from pathlib import Path

import pytest

from srl.products import (
    DiscoveryDynamicsError,
    default_a12_pack_policy,
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
