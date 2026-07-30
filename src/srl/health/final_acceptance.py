"""V3.7 A22 final acceptance and false-release closure checks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

from srl.capabilities.truth import build_truth_ledger, evaluate_release_candidate
from srl.contracts import dumps

A22_FINAL_ACCEPTANCE_RECEIPT_SCHEMA_VERSION: Final[str] = "A22FinalAcceptanceReceipt/v1"
A22_MISSION_CLOSEOUT_RECEIPT_SCHEMA_VERSION: Final[str] = "MissionCloseoutReceipt/v2"
A22_TARGET_RELEASE: Final[str] = "v2.0.0"
A22_TARGET_RESULT: Final[str] = "DONE"
A22_TERMINAL_STATE: Final[str] = "BLOCKED_EXTERNAL_AUTHORITY"
A22_STAGE_CLOSURE: Final[str] = "A22_FINAL_ACCEPTANCE_BLOCKED_EXTERNAL_AUTHORITY"
A22_OPERATOR_ACTION_ID: Final[str] = "A22_RESOLVE_V2_0_0_RELEASE_BLOCKERS"
_GIT_SHA_LENGTH: Final[int] = 40

_STAGE_RECEIPTS: Final[tuple[tuple[str, str], ...]] = (
    ("A00", "docs/verification/srf-v3-7-a00-freeze-receipt.json"),
    ("A01", "docs/verification/srf-v3-7-a01-truth-ledger-receipt.json"),
    ("A02", "docs/verification/srf-v3-7-a02-t7-binding-wait-receipt.json"),
    ("A03", "docs/verification/srf-v3-7-a03-env-factory-receipt.json"),
    ("A04", "docs/verification/srf-v3-7-a04-signing-transport-receipt.json"),
    ("A05", "docs/verification/srf-v3-7-a05-enforced-sandbox-receipt.json"),
    ("A06", "docs/verification/srf-v3-7-a06-durable-executor-receipt.json"),
    ("A07", "docs/verification/srf-v3-7-a07-p0-python-core-receipt.json"),
    ("A08", "docs/verification/srf-v3-7-a08-native-algebra-smt-receipt.json"),
    ("A09", "docs/verification/srf-v3-7-a09-lean-corpora-receipt.json"),
    ("A10", "docs/verification/srf-v3-7-a10-independent-provers-receipt.json"),
    ("A11", "docs/verification/srf-v3-7-a11-knowledge-graph-receipt.json"),
    ("A12", "docs/verification/srf-v3-7-a12-discovery-dynamics-receipt.json"),
    ("A13", "docs/verification/srf-v3-7-a13-applied-science-receipt.json"),
    ("A14", "docs/verification/srf-v3-7-a14-sciml-domain-receipt.json"),
    ("A15", "docs/verification/srf-v3-7-a15-heavy-compute-wait-receipt.json"),
    ("A16", "docs/verification/srf-v3-7-a16-scientific-products-receipt.json"),
    ("A17", "docs/verification/srf-v3-7-a17-solo-agent-receipt.json"),
    ("A18", "docs/verification/srf-v3-7-a18-dual-contour-closeout-receipt.json"),
    ("A19", "docs/verification/srf-v3-7-a19-market-native-bridge-receipt.json"),
    ("A20", "docs/verification/srf-v3-7-a20-security-native-bridge-receipt.json"),
    ("A21", "docs/verification/srf-v3-7-a21-dr-chaos-receipt.json"),
)

_ACTIVATION_ATTEMPT_RECEIPTS: Final[tuple[tuple[str, str], ...]] = (
    ("A02", "docs/verification/srf-v3-7-a02-t7-native-activation-attempt-receipt.json"),
)

_BLOCKED_OPERATOR_ACTIONS: Final[tuple[str, ...]] = (
    "WAIT_AUTHORITY:A02_BIND_T7_NATIVE_TARGET",
    "WAIT_AUTHORITY:A04_BIND_PRODUCTION_ED25519_KEYRING",
    "WAIT_COMPUTE_TARGET:A05_BIND_NATIVE_SANDBOX_COMPUTE_TARGET",
    "WAIT_LICENSE:A07_PYTHON_FLINT_LGPL_CLOSURE",
    "WAIT_AUTHORITY:A09_BIND_PINNED_LEAN_MATHLIB_PROJECT_TO_T7",
    "WAIT_COMPUTE_NODE:A15_PROVISION_HEAVY_COMPUTE_TARGET",
    "WAIT_NATIVE_CHILD_CLOSEOUT:DUAL_CONTOUR_MAKE_CONTRACTS_FAIL",
    "WAIT_NATIVE_CHILD_CLOSEOUT:MARKET_NATIVE_BRIDGE_CLOSEOUT_ABSENT",
    "WAIT_RUNTIME_HEALTH:MARKET_ORGANISM_NOT_GREEN",
    "WAIT_NATIVE_CHILD_CLOSEOUT:SECURITY_NATIVE_BRIDGE_CLOSEOUT_ABSENT",
    "WAIT_SECURITY_HEALTH:SECURITY_ORGANISM_NOT_GREEN",
    "WAIT_AUTHORITY:A21_CONFIGURE_SECOND_ENCRYPTED_RECOVERY_TARGET",
    "WAIT_T7_BINDING:A21_EXECUTE_NATIVE_T7_RESTORE_DRILL",
)


def build_a22_operator_action() -> dict[str, Any]:
    """Build the single decision packet required before v2.0.0 can close."""

    action: dict[str, Any] = {
        "schema_version": "ProtectedOperatorAction/v1",
        "action_id": A22_OPERATOR_ACTION_ID,
        "target": "v2.0.0 DONE release closure",
        "authority_required": True,
        "blocked_until": list(_BLOCKED_OPERATOR_ACTIONS),
        "allowed_actions_after_authority": [
            "bind native T7 target and T7-backed persistence receipts",
            "bind production Ed25519 keyring and reject fixture signer in production",
            "bind native T2/T3 compute sandbox and heavy Linux compute target",
            "resolve python-flint license closure or formally replace it",
            "import passing DualContour, Market and Security native child closeouts",
            "execute native encrypted recovery-target restore drill",
            "rerun A22, make verify, independent audit and release workflow from accepted SHA",
        ],
        "forbidden_without_authority": [
            "publish_v2_0_0",
            "claim_DONE",
            "emit_MissionCloseoutReceipt_DONE",
            "retag_release",
            "hide_or_relabel_wait_states",
            "treat_fixture_signer_as_production",
            "treat_policy_sandbox_as_t2_t3_enforcement",
            "treat_synthetic_restore_as_native_recovery_target",
        ],
        "grants_authority": False,
    }
    action["action_hash_grouped_sha256"] = _grouped_sha256(dumps(action))
    return action


def build_a22_final_acceptance_receipt(
    *,
    repo_root: Path,
    git_head: str | None = None,
) -> dict[str, Any]:
    """Evaluate final V3.7 closure against current committed evidence."""

    head_provenance = resolve_a22_head_provenance(repo_root=repo_root, git_head=git_head)
    ledger = build_truth_ledger()
    release_decision = evaluate_release_candidate(
        {
            "target_release": A22_TARGET_RELEASE,
            "target_result": A22_TARGET_RESULT,
            "production_signer": "WAIT_AUTHORITY:A04_BIND_PRODUCTION_ED25519_KEYRING",
            "sandbox": "t0_t1_enforced_t2_t3_wait",
            "t7_binding": "WAIT_T7_BINDING",
            "ledger": ledger,
        }
    )
    stage_receipts = _stage_receipt_index(repo_root)
    activation_attempts = _activation_attempt_receipt_index(repo_root)
    evidence_receipts = {
        "stage_receipts": stage_receipts,
        "activation_attempts": activation_attempts,
    }
    mandatory_waits = _mandatory_nonactive_components(ledger)
    mandatory_wait_capability_or_toolchain = [
        item for item in mandatory_waits if item["state"] in {"WAIT_CAPABILITY", "WAIT_TOOLCHAIN"}
    ]
    operator_action = build_a22_operator_action()
    mission_closeout = _build_blocked_mission_closeout(
        head_provenance=head_provenance,
        release_decision=release_decision,
        operator_action=operator_action,
        mandatory_waits=mandatory_waits,
        evidence_receipts=evidence_receipts,
    )
    checks = [
        _check(
            "A22-01-a00-a21-receipts-present",
            not any(item["status"] != "PASS" for item in stage_receipts),
            "A00-A21 public stage receipts exist and report PASS",
        ),
        _check(
            "A22-02-mandatory-waits-preserved-as-release-blockers",
            _mandatory_waits_are_release_blockers(
                release_decision=release_decision,
                mandatory_waits=mandatory_waits,
            ),
            "mandatory non-ACTIVE components are preserved as release blockers",
        ),
        _check(
            "A22-03-done-v2-release-rejected",
            release_decision["verdict"] == "REJECT",
            "DONE/v2.0.0 candidate is rejected by release truth gate",
        ),
        _check(
            "A22-04-single-decision-packet",
            operator_action["action_id"] == A22_OPERATOR_ACTION_ID
            and operator_action["grants_authority"] is False,
            "single non-authorizing decision packet names all remaining protected blockers",
        ),
        _check(
            "A22-05-mission-closeout-blocked-not-released",
            mission_closeout["result"] == A22_TERMINAL_STATE
            and mission_closeout["release"]["published"] is False,
            "mission closeout is blocked, not DONE and not RELEASED_WITH_DECLARED_WAITS",
        ),
        _check(
            "A22-06-head-provenance-resolved",
            head_provenance["source_git_head"] != "UNKNOWN"
            and head_provenance["generator_head"] != "UNKNOWN"
            and head_provenance["observed_main_head"] != "UNKNOWN"
            and head_provenance["accepted_release_head"] != "UNKNOWN",
            "A22 provenance resolves explicit/env/local git heads and never masks UNKNOWN",
        ),
        _check(
            "A22-07-activation-attempts-do-not-mask-release-blockers",
            _activation_attempts_preserve_release_blockers(
                activation_attempts=activation_attempts,
                release_decision=release_decision,
            ),
            "partial native activation attempts are recorded but cannot hide release blockers",
        ),
    ]
    result = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    receipt: dict[str, Any] = {
        "schema_version": A22_FINAL_ACCEPTANCE_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A22",
        "target_release": A22_TARGET_RELEASE,
        "target_result": A22_TARGET_RESULT,
        "result": result,
        "stage_closure": A22_STAGE_CLOSURE if result == "PASS" else "A22_OPEN",
        "terminal_state": A22_TERMINAL_STATE if result == "PASS" else "FAIL",
        "release_truth_decision": release_decision,
        "mandatory_nonactive_components": mandatory_waits,
        "mandatory_wait_capability_or_toolchain": mandatory_wait_capability_or_toolchain,
        "remaining_external_waits": list(_BLOCKED_OPERATOR_ACTIONS),
        "remaining_internal_waits": [],
        "protected_actions_performed": [],
        "protected_activation_attempts": activation_attempts,
        "operator_action": operator_action,
        "head_provenance": head_provenance,
        "stage_receipts": stage_receipts,
        "mission_closeout_receipt": mission_closeout,
        "checks": checks,
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
        "release_published": False,
    }
    receipt["receipt_id"] = _object_id(receipt)
    return receipt


def resolve_a22_head_provenance(
    *,
    repo_root: Path,
    git_head: str | None = None,
) -> dict[str, Any]:
    """Resolve A22 head semantics without requiring an impossible self-reference.

    ``source_git_head`` and ``generator_head`` name the checkout that generated
    the receipt. ``accepted_release_head`` names the accepted mainline being
    evaluated for the v2.0.0 release decision.
    """

    explicit_head = _normalized_head(git_head)
    github_head = _normalized_head(os.environ.get("GITHUB_SHA"))
    if explicit_head is not None:
        source_git_head = explicit_head
        source = "explicit_git_head"
    elif github_head is not None:
        source_git_head = github_head
        source = "GITHUB_SHA"
    else:
        local_head = _git_rev_parse(repo_root, "HEAD")
        source_git_head = local_head if local_head is not None else "UNKNOWN"
        source = "git_rev_parse_HEAD" if local_head is not None else "unresolved"

    observed_main_head = (
        _git_rev_parse(repo_root, "origin/main")
        or _git_rev_parse(repo_root, "main")
        or source_git_head
    )
    return {
        "schema_version": "A22HeadProvenance/v1",
        "source_git_head": source_git_head,
        "source_git_head_source": source,
        "generator_head": source_git_head,
        "observed_main_head": observed_main_head,
        "accepted_release_head": observed_main_head,
        "legacy_git_head_semantics": (
            "legacy git_head aliases source_git_head; use accepted_release_head "
            "for accepted-main release truth"
        ),
        "self_referential_commit_claimed": False,
    }


def _build_blocked_mission_closeout(
    *,
    head_provenance: dict[str, Any],
    release_decision: dict[str, Any],
    operator_action: dict[str, Any],
    mandatory_waits: list[dict[str, str]],
    evidence_receipts: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    stage_receipts = evidence_receipts["stage_receipts"]
    activation_attempts = evidence_receipts["activation_attempts"]
    closeout: dict[str, Any] = {
        "schema_version": A22_MISSION_CLOSEOUT_RECEIPT_SCHEMA_VERSION,
        "mission_id": "activate-scientific-reasoning-fabric-v3.7",
        "stage_id": "A22",
        "result": A22_TERMINAL_STATE,
        "target_release": A22_TARGET_RELEASE,
        "target_result": A22_TARGET_RESULT,
        "git_head": head_provenance["source_git_head"],
        "git_head_semantics": head_provenance["legacy_git_head_semantics"],
        "source_git_head": head_provenance["source_git_head"],
        "generator_head": head_provenance["generator_head"],
        "observed_main_head": head_provenance["observed_main_head"],
        "accepted_release_head": head_provenance["accepted_release_head"],
        "head_provenance": head_provenance,
        "release": {
            "published": False,
            "tag": None,
            "reason": "DONE/v2.0.0 rejected while mandatory protected blockers remain",
        },
        "release_truth_decision": release_decision,
        "decision_packet": {
            "action_id": operator_action["action_id"],
            "action_hash_grouped_sha256": operator_action["action_hash_grouped_sha256"],
        },
        "remaining_external_waits": list(_BLOCKED_OPERATOR_ACTIONS),
        "protected_activation_attempts": activation_attempts,
        "mandatory_nonactive_components": mandatory_waits,
        "stage_receipt_count": len(stage_receipts),
        "forbidden_terminal_states": ["DONE", "RELEASED_WITH_DECLARED_WAITS"],
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }
    closeout["receipt_id"] = _object_id(closeout)
    return closeout


def _activation_attempt_receipt_index(repo_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for stage_id, path_text in _ACTIVATION_ATTEMPT_RECEIPTS:
        path = repo_root / path_text
        exists = path.exists()
        data: dict[str, Any] = {}
        if exists:
            data = json.loads(path.read_text(encoding="utf-8"))
        accepted = (
            exists
            and data.get("canonical_writes") == 0
            and data.get("grants_authority") is False
            and data.get("status") in {"PARTIAL_NATIVE_EVIDENCE", "BLOCKED_NATIVE_BRIDGE_ABSENT"}
            and isinstance(data.get("remaining_external_waits"), list)
            and bool(data.get("remaining_external_waits"))
        )
        records.append(
            {
                "stage_id": stage_id,
                "path": path_text,
                "status": "PASS" if accepted else "FAIL",
                "attempt_status": data.get("status") if exists else None,
                "receipt_id": data.get("receipt_id") if exists else None,
                "remaining_external_waits": data.get("remaining_external_waits")
                if exists
                else None,
                "sha256": "sha256:" + _file_sha256(path) if exists else None,
            }
        )
    return records


def _stage_receipt_index(repo_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for stage_id, path_text in _STAGE_RECEIPTS:
        path = repo_root / path_text
        exists = path.exists()
        data: dict[str, Any] = {}
        if exists:
            data = json.loads(path.read_text(encoding="utf-8"))
        accepted = exists and _is_stage_receipt_accepted(data)
        records.append(
            {
                "stage_id": stage_id,
                "path": path_text,
                "status": "PASS" if accepted else "FAIL",
                "result": data.get("result") if exists else None,
                "stage_closure": data.get("stage_closure") if exists else None,
                "terminal_state": data.get("terminal_state") if exists else None,
                "receipt_id": data.get("receipt_id") if exists else None,
                "sha256": "sha256:" + _file_sha256(path) if exists else None,
            }
        )
    return records


def _mandatory_nonactive_components(ledger: dict[str, Any]) -> list[dict[str, str]]:
    waits: list[dict[str, str]] = []
    for item in ledger["components"]:
        if not item.get("mandatory_for_v2", True):
            continue
        state = str(item.get("state"))
        if state == "ACTIVE":
            continue
        waits.append(
            {
                "component_id": str(item["component_id"]),
                "activation_stage": str(item["activation_stage"]),
                "state": state,
                "evidence_axis": str(item["evidence_axis"]),
            }
        )
    return waits


def _mandatory_waits_are_release_blockers(
    *,
    release_decision: dict[str, Any],
    mandatory_waits: list[dict[str, str]],
) -> bool:
    blockers = set(release_decision.get("blockers", []))
    for item in mandatory_waits:
        component_id = item["component_id"]
        state = item["state"]
        expected = f"MANDATORY_NOT_ACTIVE:{component_id}:{state}"
        license_expected = f"MANDATORY_WAIT_LICENSE:{component_id}"
        if expected not in blockers and (
            state != "WAIT_LICENSE" or license_expected not in blockers
        ):
            return False
    return True


def _activation_attempts_preserve_release_blockers(
    *,
    activation_attempts: list[dict[str, Any]],
    release_decision: dict[str, Any],
) -> bool:
    if not activation_attempts:
        return False
    if any(item["status"] != "PASS" for item in activation_attempts):
        return False
    blockers = set(release_decision.get("blockers", []))
    return "T7_NOT_ACTIVE" in blockers and any(
        item.get("attempt_status") == "PARTIAL_NATIVE_EVIDENCE" for item in activation_attempts
    )


def _is_stage_receipt_accepted(data: dict[str, Any]) -> bool:
    if data.get("result") in {"PASS", "ACCEPTED"}:
        return True
    closure = data.get("stage_closure")
    if not isinstance(closure, str) or closure.endswith("_OPEN"):
        return False
    if data.get("canonical_writes") != 0 or data.get("grants_authority") is not False:
        return False
    checks = data.get("checks")
    if checks is None:
        return True
    if not isinstance(checks, list) or not checks:
        return False
    return all(isinstance(item, dict) and item.get("status") == "PASS" for item in checks)


def _check(check_id: str, passed: bool, detail: str) -> dict[str, str]:
    return {"check_id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _grouped_sha256(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


def _normalized_head(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) == _GIT_SHA_LENGTH and all(char in "0123456789abcdef" for char in stripped):
        return stripped
    return None


def _git_rev_parse(repo_root: Path, ref: str) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    proc = subprocess.run(  # noqa: S603
        [git, "-C", str(repo_root), "rev-parse", "--verify", ref],
        capture_output=True,
        check=False,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return _normalized_head(proc.stdout)


def _object_id(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(dumps(payload)).hexdigest()


__all__ = [
    "A22_FINAL_ACCEPTANCE_RECEIPT_SCHEMA_VERSION",
    "A22_MISSION_CLOSEOUT_RECEIPT_SCHEMA_VERSION",
    "A22_OPERATOR_ACTION_ID",
    "A22_STAGE_CLOSURE",
    "A22_TARGET_RELEASE",
    "A22_TARGET_RESULT",
    "A22_TERMINAL_STATE",
    "build_a22_final_acceptance_receipt",
    "build_a22_operator_action",
    "resolve_a22_head_provenance",
]
