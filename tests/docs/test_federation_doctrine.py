"""Governance tests for the static federation ownership doctrine."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

POLICY_PATH = Path("policies/federation-ownership-policy-v1.json")
GATE_PATH = Path("scripts/checks/federation-doctrine-consistency.py")
EXPECTED_CANDIDATE_BASE_HEAD = "7adf5cd2c2d4af888c27126e01094981f821c98a"
DOCUMENTATION_CLOSURE_RECEIPT_PATH = Path("docs/verification/documentation-closure-receipt-v2.json")
INDEPENDENT_REVIEW_RECEIPT_PATH = Path(
    "docs/verification/federation-doctrine-independent-review-v1.json"
)
BOUND_DOCUMENT_PATHS = (
    "AGENTS.md",
    "AUTHORITY-MATRIX.md",
    "CELL-MATRIX.md",
    "CONTRACT-MATRIX.md",
    "CONTRIBUTING.md",
    "DATA-CLASSIFICATION.md",
    "GOVERNANCE.md",
    "MARKET-INTEGRATION.md",
    "README.md",
    "SECURITY-INTEGRATION.md",
    "SOLO-AGENT-RUNBOOK.md",
    "START-HERE.md",
    "SYSTEM-ATLAS.md",
    "TRADING-EXECUTION-BOUNDARY.md",
    "docs/adr/0011-federated-research-organism-ownership.md",
    "docs/architecture/README.md",
    "docs/architecture/federated-research-organism-doctrine-v1.md",
    "docs/architecture/transport.md",
    "docs/integrations/MARKET-CHILD-MISSION.md",
    "docs/integrations/MARKET-INTEGRATION.md",
    "docs/integrations/SECURITY-CHILD-MISSION.md",
    "docs/integrations/SECURITY-INTEGRATION.md",
    "docs/integrations/shared-contracts.md",
    "docs/plans/federated-research-organism-successor-plan-v1.md",
    "src/srl/contracts/schemas/v1/README.md",
)
BOUND_SOURCE_PATHS = (
    ".github/workflows/docs.yml",
    "Makefile",
    "automation/policy.json",
    "automation/state.schema.json",
    "configs/integrations/market-bridge.json",
    "configs/integrations/security-bridge.json",
    "scripts/docs/generate_solo_agent_docs.py",
    "scripts/docs/generate_system_docs.py",
    "src/srl/autonomy/policy.py",
    "src/srl/contracts/schema.py",
    "src/srl/contracts/schemas/v1/evidence-assessment.json",
    "src/srl/contracts/schemas/v1/federation-status.json",
    "src/srl/contracts/schemas/v1/federation-orientation-report.json",
    "src/srl/contracts/schemas/v1/lab-cell-manifest.json",
    "src/srl/contracts/schemas/v1/lab-export-packet.json",
    "src/srl/contracts/schemas/v1/lab-federation-manifest.json",
    "src/srl/contracts/schemas/v1/science-lab-run-receipt.json",
    "src/srl/contracts/schemas/v1/scientific-import-receipt.json",
    "src/srl/contracts/schemas/v1/scientific-object-envelope.json",
    "src/srl/contracts/schemas/v1/scientific-request-envelope.json",
    "src/srl/contracts/schemas/v1/scientific-result-envelope.json",
    "src/srl/contracts/schemas/v1/scientific-run-receipt.json",
    "src/srl/contracts/schemas/v1/spool-ack.json",
    "src/srl/contracts/schemas/v1/spool-message.json",
    "src/srl/contracts/schemas/v1/srf-pulse.json",
    "src/srl/contracts/schemas/v1/transformation-receipt.json",
    "src/srl/cli.py",
    "src/srl/integrations/market/bridge.py",
    "src/srl/integrations/security/bridge.py",
    "src/srl/labctl.py",
    "src/srl/transport/spool.py",
    "tests/contracts/test_srf_federation_schemas.py",
    "tests/unit/test_labctl.py",
)
DOCUMENTATION_REQUIRED_PATHS = (
    "START-HERE.md",
    "SYSTEM-ATLAS.md",
    "SOLO-AGENT-RUNBOOK.md",
    "CELL-MATRIX.md",
    "CAPABILITY-CATALOG.md",
    "CONTRACT-MATRIX.md",
    "AUTHORITY-MATRIX.md",
    "DATA-CLASSIFICATION.md",
    "FAILURE-ROUTING.md",
    "T7-OPERATIONS.md",
    "COMPUTE-NODE.md",
    "MARKET-INTEGRATION.md",
    "SECURITY-INTEGRATION.md",
    "TRADING-EXECUTION-BOUNDARY.md",
    "PACK-AUTHORING.md",
    "PACK-REVOCATION.md",
    "RECOVERY-RUNBOOK.md",
    "RELEASE-RUNBOOK.md",
)
DOCUMENTATION_GENERATED_SOURCE_PATHS = (
    "docs/verification/system-acceptance-receipt.json",
    "policies/federation-ownership-policy-v1.json",
    "scripts/checks/federation-doctrine-consistency.py",
    "scripts/checks/markdown_structure.py",
    "scripts/docs/generate_solo_agent_docs.py",
    "scripts/docs/generate_system_docs.py",
    "tests/adversarial/test_system_acceptance_failure_routes.py",
    "tests/docs/test_documentation_closure.py",
    "tests/docs/test_federation_doctrine.py",
    "tests/e2e/test_system_acceptance_receipt.py",
)


def _policy() -> dict[str, Any]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("federation_doctrine_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(
    policy_path: Path | None = None,
    repo_root: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    command = [sys.executable, str(GATE_PATH)]
    if repo_root is not None:
        command.extend(["--repo-root", str(repo_root)])
    if policy_path is not None:
        command.extend(["--policy", str(policy_path)])
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    report = json.loads(result.stdout)
    assert isinstance(report, dict)
    return result, report


def _git(
    repo_root: Path,
    *args: str,
    capture_output: bool = False,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(repo_root), *args],
        capture_output=capture_output,
        check=True,
        text=text,
    )


def _write_policy(tmp_path: Path, policy: dict[str, Any]) -> Path:
    path = tmp_path / "hostile-policy.json"
    path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _failed_checks(report: dict[str, Any]) -> set[str]:
    checks = report["checks"]
    assert isinstance(checks, list)
    return {
        str(check["check_id"])
        for check in checks
        if isinstance(check, dict) and check.get("status") == "FAIL"
    }


def _canonical_sha256(value: object) -> str:
    encoded = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_policy_digest(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    grouped = "-".join(digest[index : index + 8] for index in range(0, 64, 8))
    return "sha256:" + grouped


def _rebind_policy(repo_root: Path) -> None:
    policy_path = repo_root / POLICY_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["document_bindings"] = {
        relative_path: _file_policy_digest(repo_root / relative_path)
        for relative_path in BOUND_DOCUMENT_PATHS
    }
    policy["source_bindings"] = {
        relative_path: _file_policy_digest(repo_root / relative_path)
        for relative_path in BOUND_SOURCE_PATHS
    }
    policy_path.write_text(
        json.dumps(policy, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _insert_before_eof(path: Path, claim: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.endswith(marker + "\n")
    path.write_text(
        text.removesuffix(marker + "\n") + claim.rstrip() + "\n\n" + marker + "\n",
        encoding="utf-8",
    )


def _synthetic_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "synthetic-repo"
    paths = (
        *BOUND_DOCUMENT_PATHS,
        *BOUND_SOURCE_PATHS,
        *DOCUMENTATION_REQUIRED_PATHS,
        *DOCUMENTATION_GENERATED_SOURCE_PATHS,
        "policies/federation-ownership-policy-v1.json",
        "docs/verification/documentation-closure-receipt-v2.json",
        "docs/verification/documentation-closure-receipt.json",
        "docs/verification/federation-doctrine-independent-review-v1.json",
        "docs/verification/system-acceptance-receipt.json",
        "docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json",
    )
    for relative_path in sorted(set(paths)):
        source = Path(relative_path)
        target = repo_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, target)
        else:
            target.write_text("{}\n", encoding="utf-8")
    _rebind_policy(repo_root)
    return repo_root


def test_federation_doctrine_consistency_gate_passes() -> None:
    result, report = _run()

    assert result.returncode == 0, result.stdout
    assert report["schema_version"] == "FederationDoctrineConsistencyReceipt/v1"
    assert report["result"] == "PASS"
    assert report["canonical_writes"] == 0
    assert report["live_actions"] == 0
    assert report["grants_authority"] is False
    assert report["input_manifest"]["candidate_base_head"] == EXPECTED_CANDIDATE_BASE_HEAD
    assert report["input_manifest"]["current_head"]
    assert report["input_manifest"]["worktree_matches_index"] is True
    assert report["input_manifest"]["candidate_diff_sha256"].startswith("sha256:")
    assert report["input_manifest_sha256"] == _canonical_sha256(report["input_manifest"])
    receipt_body = {key: value for key, value in report.items() if key != "receipt_id"}
    assert report["receipt_id"] == _canonical_sha256(receipt_body)


def test_global_sovereign_writer_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["formal_invariants"]["global_sovereign_writer"] = "scientific-resource-lab"

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-02-formal-invariants" in _failed_checks(report)


def test_global_a2_authority_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["formal_invariants"]["global_a2_authority"] = "security-research-os"
    policy["formal_invariants"]["cross_domain_a2_allowed"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-02-formal-invariants" in _failed_checks(report)


def test_ambiguous_global_brain_field_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["global_brain_owner"] = "scientific-resource-lab"

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-01-policy-metadata" in _failed_checks(report)


def test_unknown_global_authority_field_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["global_authority_granted"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-01-policy-metadata" in _failed_checks(report)


def test_srl_native_market_writer_claim_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["srl"]["owns"].append("market_native_writers")

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-04-srl-boundary" in _failed_checks(report)


def test_unknown_nested_authority_field_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["srl"]["global_authority_granted"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-03-participant-identities" in _failed_checks(report)


def test_dual_scientific_payload_reinterpretation_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["dual"]["payload_reinterpretation_allowed"] = True
    policy["wire_semantic_boundary"]["dual_may_reinterpret_scientific_payload"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert {
        "FDC-05-dual-boundary",
        "FDC-08-wire-semantic-separation",
    }.issubset(_failed_checks(report))


def test_dual_scientific_semantics_claim_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["dual"]["owns"].append("scientific_contract_semantics")

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-05-dual-boundary" in _failed_checks(report)


def test_security_general_scientific_planner_claim_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    security = policy["participants"]["security"]
    security["owns"].append("general_scientific_planning")

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-06-native-truth-and-effects" in _failed_checks(report)


def test_market_security_truth_claim_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["market"]["owns"].append("security_truth")

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-06-native-truth-and-effects" in _failed_checks(report)


def test_crosslab_execution_claim_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    crosslab = policy["participants"]["crosslab"]
    crosslab["does_not_own"].remove("execution")
    crosslab["owns"].append("execution")

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-07-crosslab-pager-only" in _failed_checks(report)


def test_static_policy_cannot_claim_runtime_activation(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["activates_federation"] = True
    policy["runtime_truth"] = True
    policy["current_state"]["role_allocation_is_runtime_evidence"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert {
        "FDC-01-policy-metadata",
        "FDC-09-current-vs-static-truth",
    }.issubset(_failed_checks(report))


def test_unknown_current_state_authority_field_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["current_state"]["authority_granted"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-09-current-vs-static-truth" in _failed_checks(report)


def test_duplicate_participant_ownership_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["srl"]["owns"].append(policy["participants"]["srl"]["owns"][0])

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert {
        "FDC-03-participant-identities",
        "FDC-04-srl-boundary",
    }.issubset(_failed_checks(report))


def test_boolean_canonical_write_count_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["canonical_writes"] = False

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-01-policy-metadata" in _failed_checks(report)


def test_active_dual_target_role_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["dual"]["role_activation"] = "ACTIVE"

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-05-dual-boundary" in _failed_checks(report)


def test_crosslab_cannot_become_srl_endpoint(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["participants"]["crosslab"]["srl_endpoint_allowed"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-07-crosslab-pager-only" in _failed_checks(report)


def test_contradictory_entrypoint_claim_and_hash_drift_are_rejected(
    tmp_path: Path,
) -> None:
    repo_root = _synthetic_repo(tmp_path)
    doctrine = repo_root / "docs/architecture/federated-research-organism-doctrine-v1.md"
    doctrine.write_text(
        doctrine.read_text(encoding="utf-8")
        + "\nACTUAL GOVERNANCE: SRL IS GLOBAL A2 AND DUAL IS ACTIVE\n",
        encoding="utf-8",
    )

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert {
        "FDC-10-mandatory-entrypoints",
        "FDC-11-document-bindings",
    }.issubset(_failed_checks(report))


def test_minimal_fake_release_receipt_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    release = repo_root / "docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json"
    release.write_text(
        json.dumps({"result": "BLOCKED_EXTERNAL_AUTHORITY"}) + "\n",
        encoding="utf-8",
    )

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-09-current-vs-static-truth" in _failed_checks(report)


def test_broken_local_link_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    readme = repo_root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\n[broken](missing-doctrine.md)\n",
        encoding="utf-8",
    )

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-12-local-links" in _failed_checks(report)


def test_duplicate_json_authority_key_is_rejected(tmp_path: Path) -> None:
    text = POLICY_PATH.read_text(encoding="utf-8")
    hostile = text.replace(
        '  "grants_authority": false,',
        '  "grants_authority": true,\n  "grants_authority": false,',
        1,
    )
    policy_path = tmp_path / "duplicate-key-policy.json"
    policy_path.write_text(hostile, encoding="utf-8")

    result, report = _run(policy_path)

    assert result.returncode != 0
    assert "FDC-00-policy-load" in _failed_checks(report)


def test_rebound_inverse_and_modal_authority_claims_are_rejected(
    tmp_path: Path,
) -> None:
    repo_root = _synthetic_repo(tmp_path)
    doctrine_path = repo_root / "docs/architecture/federated-research-organism-doctrine-v1.md"
    _insert_before_eof(
        doctrine_path,
        "The global sovereign controller is SRL.\n"
        + "Dual is deployed and operational.\n"
        + "CrossLab may execute actions.\n"
        + "SRL issues native permits.",
        "<!-- FEDERATION-DOCTRINE-END -->",
    )
    policy_path = repo_root / POLICY_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    relative_path = "docs/architecture/federated-research-organism-doctrine-v1.md"
    policy["document_bindings"][relative_path] = _file_policy_digest(doctrine_path)
    policy_path.write_text(
        json.dumps(policy, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-10-mandatory-entrypoints" in _failed_checks(report)
    assert "FDC-11-document-bindings" not in _failed_checks(report)


def test_semantic_class_collapse_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["semantic_invariants"]["evidence_reclassified_as_proposal"] = True
    policy["semantic_invariants"]["c3_semantic_kinds"].append("receipt")

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-02-formal-invariants" in _failed_checks(report)


def test_d3_reference_or_simultaneous_second_bus_is_rejected(tmp_path: Path) -> None:
    policy = copy.deepcopy(_policy())
    policy["semantic_invariants"]["d3_cross_boundary_hash_reference_identifier_or_log_allowed"] = (
        True
    )
    policy["semantic_invariants"]["simultaneous_srl_spool_and_dual_wire_order_authority"] = True

    result, report = _run(_write_policy(tmp_path, policy))

    assert result.returncode != 0
    assert "FDC-02-formal-invariants" in _failed_checks(report)


def test_machine_claims_fail_even_after_document_rebinding(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    doctrine_path = repo_root / "docs/architecture/federated-research-organism-doctrine-v1.md"
    _insert_before_eof(
        doctrine_path,
        "GLOBAL_SOVEREIGN_WRITER: SCIENTIFIC_RESOURCE_LAB\n"
        + "GLOBAL_A2: ALLOWED\n"
        + "CURRENT_DUAL_RUNTIME: ACTIVE\n"
        + "CROSSLAB_SRL_ENDPOINT: ENABLED\n"
        + "SRL spool and Dual Wire are both active.\n"
        + "D3 may be exported.\n"
        + "Receipts and evidence are C3 proposals.",
        "<!-- FEDERATION-DOCTRINE-END -->",
    )
    policy_path = repo_root / POLICY_PATH
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    relative_path = "docs/architecture/federated-research-organism-doctrine-v1.md"
    policy["document_bindings"][relative_path] = _file_policy_digest(doctrine_path)
    policy_path.write_text(
        json.dumps(policy, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-10-mandatory-entrypoints" in _failed_checks(report)
    assert "FDC-11-document-bindings" not in _failed_checks(report)


def test_source_binding_drift_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    source_path = repo_root / "src/srl/labctl.py"
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\n# semantic drift\n",
        encoding="utf-8",
    )

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-14-source-bindings" in _failed_checks(report)


def test_duplicate_key_in_release_receipt_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    release_path = repo_root / "docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json"
    release_text = release_path.read_text(encoding="utf-8")
    hostile = release_text.replace(
        '"result":"BLOCKED_EXTERNAL_AUTHORITY"',
        '"result":"DONE","result":"BLOCKED_EXTERNAL_AUTHORITY"',
        1,
    )
    assert hostile != release_text
    release_path.write_text(hostile, encoding="utf-8")

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-09-current-vs-static-truth" in _failed_checks(report)


def test_duplicate_nested_dual_activation_key_is_rejected(tmp_path: Path) -> None:
    text = POLICY_PATH.read_text(encoding="utf-8")
    hostile = text.replace(
        '      "role_activation": "TARGET_DECLARED_NOT_RUNTIME_PROVEN",',
        '      "role_activation": "ACTIVE",\n'
        '      "role_activation": "TARGET_DECLARED_NOT_RUNTIME_PROVEN",',
        1,
    )
    assert hostile != text
    policy_path = tmp_path / "duplicate-dual-key-policy.json"
    policy_path.write_text(hostile, encoding="utf-8")

    result, report = _run(policy_path)

    assert result.returncode != 0
    assert "FDC-00-policy-load" in _failed_checks(report)


@pytest.mark.parametrize(
    "claim",
    (
        "SRL is authorized to approve native admission.",
        "Production cross-domain traffic flows over Dual Wire.",
        "CrossLab starts jobs.",
        "SRL receives requests through a CrossLab endpoint.",
        "Raw D2 is sent unchanged.",
        "D3 can be logged.",
        "Validation evidence becomes a C3 proposal.",
        "The adapter imports C3 findings.",
        "v2.0.0 is published.",
        "The federation runtime is operational.",
    ),
)
def test_rebound_semantic_paraphrases_are_rejected(
    tmp_path: Path,
    claim: str,
) -> None:
    repo_root = _synthetic_repo(tmp_path)
    doctrine_path = repo_root / "docs/architecture/federated-research-organism-doctrine-v1.md"
    _insert_before_eof(
        doctrine_path,
        claim,
        "<!-- FEDERATION-DOCTRINE-END -->",
    )
    _rebind_policy(repo_root)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-10-mandatory-entrypoints" in _failed_checks(report), claim
    assert "FDC-11-document-bindings" not in _failed_checks(report), claim


@pytest.mark.parametrize(
    ("relative_path", "marker"),
    (
        (
            "docs/architecture/federated-research-organism-doctrine-v1.md",
            "<!-- FEDERATION-DOCTRINE-END -->",
        ),
        (
            "docs/plans/federated-research-organism-successor-plan-v1.md",
            "<!-- FEDERATION-SUCCESSOR-PLAN-END -->",
        ),
    ),
)
def test_rebound_addendum_after_exact_eof_is_rejected(
    tmp_path: Path,
    relative_path: str,
    marker: str,
) -> None:
    repo_root = _synthetic_repo(tmp_path)
    document = repo_root / relative_path
    text = document.read_text(encoding="utf-8")
    assert text.endswith(marker + "\n")
    document.write_text(text + "UNREVIEWED ADDENDUM\n", encoding="utf-8")
    _rebind_policy(repo_root)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-10-mandatory-entrypoints" in _failed_checks(report)
    assert "FDC-11-document-bindings" not in _failed_checks(report)


def test_candidate_digest_is_identical_before_and_after_commit(tmp_path: Path) -> None:
    gate = _gate_module()
    repo_root = tmp_path / "candidate-repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.name", "Verifier Test")
    _git(repo_root, "config", "user.email", "verifier@example.invalid")
    (repo_root / "AGENTS.md").write_text("base\n", encoding="utf-8")
    _git(repo_root, "add", "AGENTS.md")
    _git(repo_root, "commit", "-qm", "base")
    base_head = _git(
        repo_root,
        "rev-parse",
        "HEAD",
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo_root / "AGENTS.md").write_text("candidate\n", encoding="utf-8")
    _git(repo_root, "add", "AGENTS.md")

    before = gate._git_candidate_diff_sha256(repo_root, base_head)
    _git(repo_root, "commit", "-qm", "candidate")
    after = gate._git_candidate_diff_sha256(repo_root, base_head)

    assert before is not None
    assert after == before

    (repo_root / "unrelated.txt").write_text("later\n", encoding="utf-8")
    _git(repo_root, "add", "unrelated.txt")
    _git(repo_root, "commit", "-qm", "unrelated descendant")
    assert gate._git_candidate_diff_sha256(repo_root, base_head) == before

    (repo_root / "AGENTS.md").write_text("governed descendant\n", encoding="utf-8")
    _git(repo_root, "add", "AGENTS.md")
    _git(repo_root, "commit", "-qm", "governed descendant")
    assert gate._git_candidate_diff_sha256(repo_root, base_head) != before


def test_empty_and_evidence_receipt_only_candidates_are_rejected(tmp_path: Path) -> None:
    gate = _gate_module()
    repo_root = tmp_path / "receipt-only-repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.name", "Verifier Test")
    _git(repo_root, "config", "user.email", "verifier@example.invalid")
    (repo_root / "AGENTS.md").write_text("base\n", encoding="utf-8")
    _git(repo_root, "add", "AGENTS.md")
    _git(repo_root, "commit", "-qm", "base")
    base_head = _git(
        repo_root,
        "rev-parse",
        "HEAD",
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert gate._git_candidate_diff_sha256(repo_root, base_head) is None
    for receipt_path in (
        DOCUMENTATION_CLOSURE_RECEIPT_PATH,
        INDEPENDENT_REVIEW_RECEIPT_PATH,
    ):
        target = repo_root / receipt_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
    _git(
        repo_root,
        "add",
        str(DOCUMENTATION_CLOSURE_RECEIPT_PATH),
        str(INDEPENDENT_REVIEW_RECEIPT_PATH),
    )
    assert gate._git_candidate_diff_sha256(repo_root, base_head) is None

    near_match = repo_root / f"{DOCUMENTATION_CLOSURE_RECEIPT_PATH}.bak"
    near_match.write_text("not evidence\n", encoding="utf-8")
    _git(repo_root, "add", str(near_match.relative_to(repo_root)))
    assert gate._git_candidate_diff_sha256(repo_root, base_head) is None

    (repo_root / "AGENTS.md").write_text("candidate\n", encoding="utf-8")
    _git(repo_root, "add", "AGENTS.md")
    assert gate._git_candidate_diff_sha256(repo_root, base_head) is not None


def test_v37_history_is_byte_immutable_from_frozen_base(tmp_path: Path) -> None:
    gate = _gate_module()
    repo_root = tmp_path / "v37-history-repo"
    plan = repo_root / "docs/plans/scientific-reasoning-fabric-activation-master-plan-v3.7.md"
    receipt = repo_root / "docs/verification/srf-v3-7-a01-receipt.json"
    plan.parent.mkdir(parents=True)
    receipt.parent.mkdir(parents=True)
    plan.write_text("frozen plan\n", encoding="utf-8")
    receipt.write_text('{"receipt_id":"frozen"}\n', encoding="utf-8")
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.name", "Verifier Test")
    _git(repo_root, "config", "user.email", "verifier@example.invalid")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-qm", "frozen v37")
    base_head = _git(
        repo_root,
        "rev-parse",
        "HEAD",
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert gate._v37_history_immutability_check(repo_root, base_head)["status"] == "PASS"

    receipt.write_text('{"receipt_id":"rewritten"}\n', encoding="utf-8")
    assert gate._v37_history_immutability_check(repo_root, base_head)["status"] == "FAIL"


def test_documentation_receipt_duplicate_key_is_rejected(tmp_path: Path) -> None:
    gate = _gate_module()
    repo_root = _synthetic_repo(tmp_path)
    receipt_path = repo_root / DOCUMENTATION_CLOSURE_RECEIPT_PATH
    text = receipt_path.read_text(encoding="utf-8")
    hostile = text.replace(
        '  "grants_authority": false,',
        '  "grants_authority": true,\n  "grants_authority": false,',
        1,
    )
    assert hostile != text
    receipt_path.write_text(hostile, encoding="utf-8")

    check = gate._documentation_closure_check(
        repo_root,
        {
            "candidate_base_head": EXPECTED_CANDIDATE_BASE_HEAD,
            "candidate_diff_sha256": "sha256:" + "1" * 64,
        },
    )

    assert check["status"] == "FAIL"
    assert "duplicate JSON object key" in check["detail"]


def test_documentation_receipt_exact_candidate_binding_is_independent(
    tmp_path: Path,
) -> None:
    gate = _gate_module()
    repo_root = _synthetic_repo(tmp_path)
    receipt_path = repo_root / DOCUMENTATION_CLOSURE_RECEIPT_PATH
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["required_doc_sha256"] = {
        path: _file_policy_digest(repo_root / path) for path in DOCUMENTATION_REQUIRED_PATHS
    }
    receipt["generated_source_sha256"] = {
        path: _file_policy_digest(repo_root / path) for path in DOCUMENTATION_GENERATED_SOURCE_PATHS
    }
    receipt["source_head"] = EXPECTED_CANDIDATE_BASE_HEAD
    receipt["staged_candidate_diff_sha256"] = "sha256:" + "1" * 64
    receipt["receipt_id"] = gate._documentation_receipt_id(receipt)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    matching = gate._documentation_closure_check(
        repo_root,
        {
            "candidate_base_head": EXPECTED_CANDIDATE_BASE_HEAD,
            "candidate_diff_sha256": "sha256:" + "1" * 64,
        },
    )
    mismatched = gate._documentation_closure_check(
        repo_root,
        {
            "candidate_base_head": EXPECTED_CANDIDATE_BASE_HEAD,
            "candidate_diff_sha256": "sha256:" + "2" * 64,
        },
    )

    assert matching["status"] == "PASS", matching
    assert mismatched["status"] == "FAIL"


def test_rebound_active_second_bus_source_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    spool = repo_root / "src/srl/transport/spool.py"
    spool.write_text(
        spool.read_text(encoding="utf-8") + "\nDUAL_WIRE_ACTIVE = True\n",
        encoding="utf-8",
    )
    _rebind_policy(repo_root)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-18-critical-source-semantics" in _failed_checks(report)
    assert "FDC-14-source-bindings" not in _failed_checks(report)


def test_rebound_spool_ack_execution_status_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    ack_path = repo_root / "src/srl/contracts/schemas/v1/spool-ack.json"
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    ack["properties"]["ack_status"]["enum"].append("EXECUTED")
    ack_path.write_text(json.dumps(ack) + "\n", encoding="utf-8")
    _rebind_policy(repo_root)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-18-critical-source-semantics" in _failed_checks(report)
    assert "FDC-14-source-bindings" not in _failed_checks(report)


@pytest.mark.parametrize(
    ("relative_path", "hostile_text", "failure"),
    (
        (
            "Makefile",
            "\t@true",
            "makefile_federation_gate_entrypoint",
        ),
        (
            ".github/workflows/docs.yml",
            "        continue-on-error: true",
            "github_federation_gate_job",
        ),
    ),
)
def test_governance_gate_entrypoint_cannot_be_rebound_to_noop(
    tmp_path: Path,
    relative_path: str,
    hostile_text: str,
    failure: str,
) -> None:
    gate = _gate_module()
    repo_root = _synthetic_repo(tmp_path)
    path = repo_root / relative_path
    text = path.read_text(encoding="utf-8")
    if relative_path == "Makefile":
        text = text.replace(
            "\tuv run python scripts/checks/federation-doctrine-consistency.py",
            hostile_text,
            1,
        )
    else:
        text = text.replace(
            "      - name: Federation doctrine consistency",
            f"{hostile_text}\n      - name: Federation doctrine consistency",
            1,
        )
    path.write_text(text, encoding="utf-8")

    check = gate._critical_source_semantics_check(repo_root)

    assert check["status"] == "FAIL"
    assert failure in check["detail"]


@pytest.mark.parametrize(
    "relative_path",
    (
        "src/srl/contracts/schemas/v1/evidence-assessment.json",
        "src/srl/contracts/schemas/v1/federation-status.json",
        "src/srl/contracts/schemas/v1/lab-cell-manifest.json",
        "src/srl/contracts/schemas/v1/lab-export-packet.json",
        "src/srl/contracts/schemas/v1/lab-federation-manifest.json",
        "src/srl/contracts/schemas/v1/science-lab-run-receipt.json",
        "src/srl/contracts/schemas/v1/scientific-object-envelope.json",
        "src/srl/contracts/schemas/v1/scientific-request-envelope.json",
        "src/srl/contracts/schemas/v1/scientific-result-envelope.json",
        "src/srl/contracts/schemas/v1/scientific-run-receipt.json",
        "src/srl/contracts/schemas/v1/spool-message.json",
        "src/srl/contracts/schemas/v1/srf-pulse.json",
        "src/srl/contracts/schemas/v1/transformation-receipt.json",
    ),
)
def test_rebound_reused_schema_authority_leak_is_rejected(
    tmp_path: Path,
    relative_path: str,
) -> None:
    repo_root = _synthetic_repo(tmp_path)
    path = repo_root / relative_path
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["properties"]["grants_authority"]["const"] = True
    path.write_text(json.dumps(schema) + "\n", encoding="utf-8")
    _rebind_policy(repo_root)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-18-critical-source-semantics" in _failed_checks(report)
    assert "FDC-14-source-bindings" not in _failed_checks(report)


def test_reused_schema_rejects_boolean_canonical_write_and_export_effect(
    tmp_path: Path,
) -> None:
    gate = _gate_module()
    repo_root = _synthetic_repo(tmp_path)
    path = repo_root / "src/srl/contracts/schemas/v1/lab-export-packet.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["properties"]["canonical_writes"]["const"] = False
    schema["properties"]["canonical_effect"]["const"] = "publish"
    path.write_text(json.dumps(schema) + "\n", encoding="utf-8")

    check = gate._critical_source_semantics_check(repo_root)

    assert check["status"] == "FAIL"
    assert "authority_negative_schema" in check["detail"]
    assert "lab_export_packet_safety" in check["detail"]


def test_rebound_autonomy_policy_expansion_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    autonomy_path = repo_root / "automation/policy.json"
    autonomy = json.loads(autonomy_path.read_text(encoding="utf-8"))
    autonomy["deployment_allowed"] = True
    autonomy["max_scientific_execution_wip"] = 2
    autonomy_path.write_text(json.dumps(autonomy) + "\n", encoding="utf-8")
    state_path = repo_root / "automation/state.schema.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["properties"]["scientific_wip"]["maxItems"] = 2
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    _rebind_policy(repo_root)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-18-critical-source-semantics" in _failed_checks(report)
    assert "FDC-14-source-bindings" not in _failed_checks(report)


@pytest.mark.parametrize(
    ("relative_path", "mutate"),
    (
        ("configs/integrations/market-bridge.json", "active_bridge"),
        (
            "src/srl/contracts/schemas/v1/scientific-import-receipt.json",
            "evidence_import",
        ),
    ),
)
def test_rebound_bridge_or_legacy_import_authority_leak_is_rejected(
    tmp_path: Path,
    relative_path: str,
    mutate: str,
) -> None:
    repo_root = _synthetic_repo(tmp_path)
    path = repo_root / relative_path
    value = json.loads(path.read_text(encoding="utf-8"))
    if mutate == "active_bridge":
        value["activation_state"] = "ACTIVE"
        value["runtime_truth"] = True
    else:
        value["properties"]["import_status"]["enum"].append("IMPORTED_AS_EVIDENCE")
        value["properties"]["grants_authority"]["const"] = True
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    _rebind_policy(repo_root)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-18-critical-source-semantics" in _failed_checks(report)
    assert "FDC-14-source-bindings" not in _failed_checks(report)


def test_symlinked_bound_document_is_rejected(tmp_path: Path) -> None:
    repo_root = _synthetic_repo(tmp_path)
    outside = tmp_path / "outside-readme.md"
    outside.write_text((repo_root / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    readme = repo_root / "README.md"
    readme.unlink()
    readme.symlink_to(outside)

    result, report = _run(repo_root=repo_root)

    assert result.returncode != 0
    assert "FDC-17-repository-file-containment" in _failed_checks(report)
