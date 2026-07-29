from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from srl.capabilities import truth
from srl.capabilities.truth import (
    CURRENT_V101_ACTIVE_INVENTORY,
    TRUTH_STATES,
    build_truth_ledger,
    evaluate_release_candidate,
)


def test_truth_ledger_reproduces_current_v101_inventory() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json;"
                "from srl.capabilities.truth import build_truth_ledger;"
                "print(json.dumps(build_truth_ledger(), sort_keys=True))"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    ledger = json.loads(proc.stdout)

    assert ledger["truth_states"] == list(TRUTH_STATES)
    component_states = {
        item["component_id"]: {
            "state": item["state"],
            "probe_error": item["probe_error"],
            "scientific_smoke_detail": item["scientific_smoke_detail"],
        }
        for item in ledger["components"]
    }
    assert ledger["current_v101_active_inventory_observed"] == list(
        CURRENT_V101_ACTIVE_INVENTORY
    ), component_states


def test_active_entries_have_full_nonfixture_evidence_chain() -> None:
    ledger = build_truth_ledger()

    for item in ledger["components"]:
        if item["state"] != "ACTIVE":
            continue
        assert item["installed"] is True
        assert item["scientific_smoke_passed"] is True
        assert item["crosschecked"] is True
        assert item["evidence_axis"] in {
            "hash_bound_stage_receipt_and_scientific_smoke",
            "nonfixture_executable_probe_and_scientific_smoke",
        }


def test_a09_truth_projection_is_offline_and_receipt_backed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a09_specs = tuple(item for item in truth._SPECS if item.stage == "A09")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "A09 truth projection must not probe executables or spawn subprocesses"
        )

    monkeypatch.setattr(truth, "_SPECS", a09_specs)
    monkeypatch.setattr(truth.shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    first = truth.build_truth_ledger()
    second = truth.build_truth_ledger()

    assert first["a09_active_inventory_observed"] == [
        "lean",
        "lake",
        "mathlib",
        "cslib-index",
        "erdos-problems-metadata",
        "formal-conjectures",
    ]
    assert second["a09_active_inventory_observed"] == first["a09_active_inventory_observed"]
    assert {item["probe_kind"] for item in first["components"]} == {"stage_receipt"}


def test_release_gate_rejects_fixture_signer_policy_sandbox_and_waits() -> None:
    ledger = build_truth_ledger()
    candidate = {
        "target_release": "v2.0.0",
        "target_result": "DONE",
        "production_signer": "fixture_hmac_sha256",
        "sandbox": "policy_only",
        "t7_binding": "WAIT_T7_BINDING",
        "ledger": ledger,
    }

    decision = evaluate_release_candidate(candidate)

    assert decision["verdict"] == "REJECT"
    assert "PRODUCTION_SIGNER_NOT_ED25519_NATIVE" in decision["blockers"]
    assert "SANDBOX_NOT_ENFORCED_T2_T3" in decision["blockers"]
    assert "T7_NOT_ACTIVE" in decision["blockers"]
    assert any(item.startswith("MANDATORY_NOT_ACTIVE:") for item in decision["blockers"])


def test_active_without_crosscheck_is_rejected() -> None:
    ledger = build_truth_ledger()
    mutated = copy.deepcopy(ledger)
    for item in mutated["components"]:
        if item["component_id"] == "numpy":
            item["state"] = "ACTIVE"
            item["crosschecked"] = False
            break

    decision = evaluate_release_candidate(
        {
            "target_release": "v2.0.0",
            "target_result": "DONE",
            "production_signer": "ed25519_native",
            "sandbox": "enforced_t2_t3",
            "t7_binding": "ACTIVE",
            "ledger": mutated,
        }
    )

    assert decision["verdict"] == "REJECT"
    assert "ACTIVE_WITHOUT_CROSSCHECKED:numpy" in decision["blockers"]


def test_generated_capability_truth_ledger_doc_is_current() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/docs/generate_capability_truth_ledger.py", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout
