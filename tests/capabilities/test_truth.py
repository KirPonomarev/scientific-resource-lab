from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

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
    monkeypatch.setattr(cast(Any, truth).shutil, "which", forbidden)
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
    monkeypatch.setattr(cast(Any, truth).shutil, "which", forbidden)
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
    monkeypatch.setattr(cast(Any, truth).shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    first = truth.build_truth_ledger()
    second = truth.build_truth_ledger()

    assert first["a11_active_inventory_observed"] == sources
    assert second["a11_active_inventory_observed"] == first["a11_active_inventory_observed"]
    assert {item["probe_kind"] for item in first["components"]} == {"stage_receipt"}


def test_a12_truth_projection_is_offline_and_receipt_backed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    packs = ["pysr", "pysindy", "pydmd"]
    replaced = ["sr4mdl", "operon", "gplearn", "ai_feynman", "pykoopman", "dysts"]
    receipt = {
        "schema_version": "StageCompletionReceipt/v1",
        "stage_id": "A12",
        "result": "PASS",
        "stage_closure": "A12_ACTIVE",
        "active_packs": packs,
        "parked_packs": [],
        "remaining_internal_waits": [],
        "remaining_external_waits": [],
        "checks": [
            {
                "check_id": "A12-01-real-discovery-dynamics-smoke",
                "status": "PASS",
                "activation_receipt": {
                    "schema_version": "DiscoveryDynamicsActivationReceipt/v1",
                    "active_pack_ids": packs,
                    "formally_replaced_pack_ids": replaced,
                    "pack_receipts": [_a12_pack_receipt(pack_id) for pack_id in packs],
                    "public_benchmark_receipt": {"observed_above_null": True},
                    "promotion_allowed": False,
                    "automatic_scientific_promotion": False,
                    "canonical_writes": 0,
                    "grants_authority": False,
                },
            },
            {
                "check_id": "A12-02-no-automatic-scientific-promotion",
                "status": "PASS",
            },
        ],
        "canonical_writes": 0,
        "grants_authority": False,
        "receipt_id": "sha256:fixture-a12-receipt",
    }
    receipt_path = tmp_path / "a12-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    a12_specs = tuple(item for item in truth._SPECS if item.stage == "A12")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "A12 truth projection must not import discovery engines or spawn subprocesses"
        )

    monkeypatch.setattr(truth, "_SPECS", a12_specs)
    monkeypatch.setattr(truth, "_A12_RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(cast(Any, truth).importlib, "import_module", forbidden)
    monkeypatch.setattr(cast(Any, truth).shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    first = truth.build_truth_ledger()
    second = truth.build_truth_ledger()

    assert first["a12_active_inventory_observed"] == packs
    assert second["a12_active_inventory_observed"] == first["a12_active_inventory_observed"]
    assert {item["probe_kind"] for item in first["components"]} == {"stage_receipt"}


def test_a13_truth_projection_is_offline_and_receipt_backed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    packs = [
        "ripser",
        "pyriemann",
        "cvxpy",
        "native_bayesian_conjugate",
        "native_causal_backdoor",
    ]
    replaced = [
        "gudhi",
        "geomstats",
        "pot",
        "pymanopt",
        "keplermapper",
        "toponetx",
        "regina",
        "pymc",
        "arviz",
        "dowhy",
        "tigramite",
        "econml",
        "jaxopt",
        "botorch",
    ]
    receipt = {
        "schema_version": "StageCompletionReceipt/v1",
        "stage_id": "A13",
        "result": "PASS",
        "stage_closure": "A13_ACTIVE",
        "active_packs": packs,
        "parked_packs": [],
        "remaining_internal_waits": [],
        "remaining_external_waits": [],
        "checks": [
            {
                "check_id": "A13-01-real-applied-science-workloads",
                "status": "PASS",
                "activation_receipt": {
                    "schema_version": "AppliedScienceActivationReceipt/v1",
                    "active_pack_ids": packs,
                    "formally_replaced_pack_ids": replaced,
                    "workload_receipts": [_a13_workload_receipt(pack_id) for pack_id in packs],
                    "promotion_allowed": False,
                    "automatic_scientific_promotion": False,
                    "canonical_writes": 0,
                    "grants_authority": False,
                },
            },
            {
                "check_id": "A13-02-diagnostics-falsification-license-and-no-promotion",
                "status": "PASS",
            },
        ],
        "canonical_writes": 0,
        "grants_authority": False,
        "receipt_id": "sha256:fixture-a13-receipt",
    }
    receipt_path = tmp_path / "a13-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    a13_specs = tuple(item for item in truth._SPECS if item.stage == "A13")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "A13 truth projection must not import applied engines or spawn subprocesses"
        )

    monkeypatch.setattr(truth, "_SPECS", a13_specs)
    monkeypatch.setattr(truth, "_A13_RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(cast(Any, truth).importlib, "import_module", forbidden)
    monkeypatch.setattr(cast(Any, truth).shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    first = truth.build_truth_ledger()
    second = truth.build_truth_ledger()

    assert first["a13_active_inventory_observed"] == packs
    assert second["a13_active_inventory_observed"] == first["a13_active_inventory_observed"]
    assert {item["probe_kind"] for item in first["components"]} == {"stage_receipt"}


def test_a14_truth_projection_is_offline_and_receipt_backed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    packs = [
        "julia_sciml_ode",
        "python_diffrax_ode",
        "python_qutip_quantum",
        "python_astropy_astronomy",
        "python_cantera_combustion",
        "native_battery_rc",
        "python_quimb_many_body",
        "python_cotengra_tensor_network",
    ]
    replaced = [
        "julia_modelingtoolkit",
        "julia_datadrivendiffeq",
        "python_cadabra",
        "python_pybamm",
    ]
    activation = {
        "schema_version": "SciMLDomainActivationReceipt/v1",
        "stage_id": "A14",
        "active_pack_ids": packs,
        "formally_replaced_pack_ids": replaced,
        "workload_receipts": [_a14_workload_receipt(pack_id) for pack_id in packs],
        "cross_language_receipt": {
            "comparison_label": "julia_sciml_vs_python_diffrax_ode",
            "receipt_ids": ["sha256:fixture-julia", "sha256:fixture-python"],
            "languages": ["julia", "python"],
            "solver_families": ["ode_explicit_runge_kutta"],
            "tolerance_abs": 5e-7,
            "tolerance_rel": 5e-6,
            "observed_delta": 0.0,
            "comparison_scope": "bounded_real_workload_tolerance_only",
            "bitwise_identity_claimed": False,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt = {
        "schema_version": "StageCompletionReceipt/v1",
        "stage_id": "A14",
        "result": "PASS",
        "stage_closure": "A14_ACTIVE",
        "active_packs": packs,
        "formally_replaced_packs": replaced,
        "remaining_internal_waits": [],
        "remaining_external_waits": [],
        "checks": [
            {
                "check_id": "A14-01-real-sciml-domain-workloads",
                "status": "PASS",
                "activation_receipt": activation,
            },
            {
                "check_id": "A14-02-units-tolerances-domain-diagnostics-and-no-bitwise-claim",
                "status": "PASS",
            },
        ],
        "canonical_writes": 0,
        "grants_authority": False,
        "receipt_id": "sha256:fixture-a14-receipt",
    }
    receipt_path = tmp_path / "a14-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    a14_specs = tuple(item for item in truth._SPECS if item.stage == "A14")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "A14 truth projection must not import SciML/domain engines or spawn subprocesses"
        )

    monkeypatch.setattr(truth, "_SPECS", a14_specs)
    monkeypatch.setattr(truth, "_A14_RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(cast(Any, truth).importlib, "import_module", forbidden)
    monkeypatch.setattr(cast(Any, truth).shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    first = truth.build_truth_ledger()
    second = truth.build_truth_ledger()

    assert first["a14_active_inventory_observed"] == packs
    assert second["a14_active_inventory_observed"] == first["a14_active_inventory_observed"]
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


def _a12_pack_receipt(pack_id: str) -> dict[str, object]:
    backend_versions: dict[str, object] = {"python_package": "fixture"}
    if pack_id == "pysr":
        backend_versions["julia"] = "julia version fixture"
    return {
        "pack_id": pack_id,
        "status": "ACTIVE",
        "observed_above_null": True,
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
        "resource_envelope": {"bounded": True},
        "candidate": {"kind": "fixture"},
        "dataset": {"kind": "fixture"},
        "backend_versions": backend_versions,
    }


def _a13_workload_receipt(pack_id: str) -> dict[str, object]:
    base: dict[str, object] = {
        "pack_id": pack_id,
        "status": "ACTIVE",
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
        "resource_envelope": {"bounded": True},
        "dataset": {"kind": "fixture"},
        "backend_versions": {"backend": "fixture"},
        "causal_identification": "not_applicable",
        "diagnostics": {},
    }
    if pack_id == "ripser":
        base["diagnostics"] = {
            "circle_long_lived_h1": 1,
            "control_long_lived_h1": 0,
        }
    elif pack_id == "native_bayesian_conjugate":
        base["diagnostics"] = {
            "convergence_claim": False,
            "rhat": None,
            "ess": None,
            "posterior_predictive_tail_probability": 0.5,
        }
    elif pack_id == "native_causal_backdoor":
        base["causal_identification"] = "identified"
        base["diagnostics"] = {
            "adjusted_treatment_effect": 2.0,
            "permuted_treatment_effect": 0.0,
        }
    elif pack_id == "cvxpy":
        base["diagnostics"] = {
            "solve_status": "optimal",
            "license_verified": True,
            "denied_solvers": ["cbc", "glpk"],
        }
    return base


def _a14_workload_receipt(pack_id: str) -> dict[str, object]:
    language = "julia" if pack_id == "julia_sciml_ode" else "python"
    family_by_pack = {
        "julia_sciml_ode": "sciml",
        "python_diffrax_ode": "sciml",
        "python_qutip_quantum": "quantum",
        "python_astropy_astronomy": "astronomy",
        "python_cantera_combustion": "combustion",
        "native_battery_rc": "battery",
        "python_quimb_many_body": "quantum_many_body",
        "python_cotengra_tensor_network": "tensor_networks",
    }
    return {
        "pack_id": pack_id,
        "status": "ACTIVE",
        "family": family_by_pack[pack_id],
        "language": language,
        "backend_versions": {"backend": "fixture"},
        "solver": {"name": "fixture", "family": "ode_explicit_runge_kutta"},
        "unit_bindings": ["time:s"],
        "tolerance": {"abs": 1e-6, "rel": 1e-6},
        "dataset": {"kind": "fixture"},
        "diagnostics": {"terminal": 0.1},
        "trace_sha256": "a" * 64,
        "trace_digest_algorithm": "sha256",
        "bitwise_identity_claimed": False,
        "promotion_allowed": False,
        "automatic_scientific_promotion": False,
        "canonical_writes": 0,
        "grants_authority": False,
        "resource_envelope": {"bounded": True},
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
