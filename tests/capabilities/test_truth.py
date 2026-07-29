from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

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


def test_a10_truth_projection_is_offline_and_receipt_backed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = {
        "schema_version": "StageCompletionReceipt/v1",
        "stage_id": "A10",
        "result": "PASS",
        "stage_closure": "A10_ACTIVE",
        "active_packs": ["rocq", "isabelle", "hol4"],
        "parked_packs": [],
        "remaining_internal_waits": [],
        "remaining_external_waits": [],
        "checks": [
            {
                "check_id": "A10-00-receipt-projects-truth-ledger-active",
                "status": "PASS",
            },
            {
                "check_id": "A10-01-independent-prover-pins",
                "status": "PASS",
                "pin_manifest_sha256": "fixture-a10-pins",
            },
            _a10_proof_check("A10-02-rocq-proof", "rocq"),
            _a10_proof_check("A10-03-isabelle-proof", "isabelle"),
            _a10_proof_check("A10-04-hol4-proof", "hol4"),
            {
                "check_id": "A10-05-semantic-gap-manifests",
                "status": "PASS",
                "admission_bundle": {
                    "automatic_equivalence_claims": 0,
                    "wait_contour_ids": [],
                    "translation_manifests": [
                        {"equivalence_claimed": False},
                        {"equivalence_claimed": False},
                        {"equivalence_claimed": False},
                    ],
                },
            },
        ],
        "canonical_writes": 0,
        "grants_authority": False,
        "receipt_id": "sha256:fixture-a10-receipt",
    }
    receipt_path = tmp_path / "a10-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    a10_specs = tuple(item for item in truth._SPECS if item.stage == "A10")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "A10 truth projection must not probe executables or spawn subprocesses"
        )

    monkeypatch.setattr(truth, "_SPECS", a10_specs)
    monkeypatch.setattr(truth, "_A10_RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(truth, "independent_prover_pin_manifest_hash", lambda: "fixture-a10-pins")
    monkeypatch.setattr(truth.shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    first = truth.build_truth_ledger()
    second = truth.build_truth_ledger()

    assert first["a10_active_inventory_observed"] == ["rocq", "isabelle", "hol4"]
    assert second["a10_active_inventory_observed"] == first["a10_active_inventory_observed"]
    assert {item["probe_kind"] for item in first["components"]} == {"stage_receipt"}


def test_a11_truth_projection_is_offline_and_receipt_backed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sources = [
        "openalex",
        "crossref",
        "arxiv",
        "oeis",
        "opencitations",
        "zbmath",
        "lmfdb",
        "cslib",
        "erdos_problems",
        "formal_conjectures",
    ]
    source_results = [_a11_source_result(source_id) for source_id in sources]
    receipt = {
        "schema_version": "StageCompletionReceipt/v1",
        "stage_id": "A11",
        "result": "PASS",
        "stage_closure": "A11_ACTIVE",
        "active_packs": sources,
        "parked_packs": [],
        "remaining_internal_waits": [],
        "remaining_external_waits": [],
        "checks": [
            {
                "check_id": "A11-00-receipt-projects-truth-ledger-active",
                "status": "PASS",
            },
            {
                "check_id": "A11-01-source-policy-admission",
                "status": "PASS",
                "active_sources": sources,
            },
            {
                "check_id": "A11-02-live-source-probes-and-replay",
                "status": "PASS",
                "source_results": source_results,
            },
            {
                "check_id": "A11-03-knowledge-graph-taint-and-citation-contract",
                "status": "PASS",
                "manifest": {
                    "active_source_ids": sources,
                    "wait_source_ids": [],
                    "prompt_injection_fact_ids": ["sha256:fixture"],
                    "raw_corpus_in_privileged_prompt": 0,
                },
            },
        ],
        "canonical_writes": 0,
        "grants_authority": False,
        "receipt_id": "sha256:fixture-a11-receipt",
    }
    receipt_path = tmp_path / "a11-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    a11_specs = tuple(item for item in truth._SPECS if item.stage == "A11")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("A11 truth projection must not fetch network or spawn subprocesses")

    monkeypatch.setattr(truth, "_SPECS", a11_specs)
    monkeypatch.setattr(truth, "_A11_RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(truth.shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    first = truth.build_truth_ledger()
    second = truth.build_truth_ledger()

    assert first["a11_active_inventory_observed"] == sources
    assert second["a11_active_inventory_observed"] == first["a11_active_inventory_observed"]
    assert {item["probe_kind"] for item in first["components"]} == {"stage_receipt"}


def _a10_proof_check(check_id: str, prover_id: str) -> dict[str, object]:
    return {
        "check_id": check_id,
        "status": "PASS",
        "proof_receipt": {
            "prover_id": prover_id,
            "theorem_label": "srl_a10_zero_add",
            "formal_check": "checked",
            "canonical_writes": 0,
            "grants_authority": False,
            "version_probe": {"returncode": 0},
            "proof_probe": {"returncode": 0},
        },
    }


def _a11_source_result(endpoint_id: str) -> dict[str, object]:
    return {
        "endpoint_id": endpoint_id,
        "status": "PASS",
        "live_query_receipt": {
            "endpoint_id": endpoint_id,
            "cached": False,
            "response_sha256": "sha256:" + "ab" * 32,
        },
        "offline_replay_receipt": {
            "endpoint_id": endpoint_id,
            "cached": True,
            "response_sha256": "sha256:" + "ab" * 32,
        },
        "record_ids": ["sha256:" + "cd" * 32],
        "source_uris": [f"https://example.org/{endpoint_id}"],
    }


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
