"""Solo-agent entry semantics for Scientific Reasoning Fabric.

The functions in this module are deliberately data-first: they expose the
manifest and access receipt that ``srlab labctl enter`` prints, and the S02
documentation generator renders the same structures. This keeps the CLI and
docs from drifting into separate sources of truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Final

from srl import __version__
from srl.contracts.schema import ContractValidationError, SchemaError, validate

PROJECT_ID: Final[str] = "scientific-resource-lab"
PRODUCT_NAME: Final[str] = "Scientific Reasoning Fabric"
PROJECT_FINGERPRINT: Final[str] = "d56e03d0d5e1a9bb9c33a008ab9895102d8e41e8bfd001dfbfc8e1c80b9df0b3"
MISSION_ID: Final[str] = "build-scientific-reasoning-fabric-v1"
PLAN_ID: Final[str] = "SRF-MASTER-2026-07-29-V3.7"
FEDERATION_POLICY_PATH: Final[str] = "policies/federation-ownership-policy-v1.json"
FEDERATION_SUCCESSOR_PLAN_PATH: Final[str] = (
    "docs/plans/federated-research-organism-successor-plan-v1.md"
)
FEDERATION_RELEASE_RECEIPT_PATH: Final[str] = (
    "docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json"
)
FEDERATION_DOCTRINE_GATE_PATH: Final[str] = "scripts/checks/federation-doctrine-consistency.py"
FEDERATION_ORIENTATION_SCHEMA_PATH: Final[str] = (
    "src/srl/contracts/schemas/v1/federation-orientation-report.json"
)
FEDERATION_STAGE_RECEIPTS: Final[dict[str, str]] = {
    "dual": "docs/verification/srf-v3-7-a18-dual-contour-closeout-receipt.json",
    "market": "docs/verification/srf-v3-7-a19-market-native-bridge-receipt.json",
    "security": "docs/verification/srf-v3-7-a20-security-native-bridge-receipt.json",
}
GIT_HEAD_LENGTH: Final[int] = 40
_SUBPROCESS_TIMEOUT_SECONDS: Final[float] = 15.0
_MAX_GATE_OUTPUT_BYTES: Final[int] = 1_000_000
_MAX_WRITE_SCOPE_LENGTH: Final[int] = 256
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"sha256:[0-9a-f]{64}")
_HEAD_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
_WRITE_SCOPE_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:-]*(?:/[A-Za-z0-9][A-Za-z0-9._:-]*)*"
)

_EXPECTED_RELEASE_RECEIPT_ID: Final[str] = (
    "sha256:a1876671c4e039285e366ae047c56bde9f565e2e9d52083a4063c6cf7bf58dcd"
)
_EXPECTED_RELEASE_HEAD: Final[str] = "418aa9673b814871405e92a4a1ea13290efb3fae"
_EXPECTED_STAGE_RECEIPTS: Final[dict[str, tuple[str, str]]] = {
    "dual": (
        "A18",
        "sha256:d60e2fe35a732cbb29107b549ca4b6c89a280a0e5128b432a2b5cb1743896b50",
    ),
    "market": (
        "A19",
        "sha256:f2e1638e40150c2929f8bc27ae4de4e6d6919bf3eb85e1a24668f1b9bb73391a",
    ),
    "security": (
        "A20",
        "sha256:327881c83976f1b600b0b7ec3b15ba3f1e8aa661695705e3f340bc7631827cfd",
    ),
}

_EXPECTED_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "activates_federation",
        "canonical_writes",
        "current_state",
        "document_bindings",
        "formal_invariants",
        "grants_authority",
        "human_metaphor",
        "participants",
        "policy_id",
        "runtime_truth",
        "schema_version",
        "semantic_invariants",
        "source_bindings",
        "status",
        "transport_transition",
        "wire_semantic_boundary",
    }
)
_EXPECTED_CURRENT_STATE: Final[dict[str, object]] = {
    "accepted_release_head": _EXPECTED_RELEASE_HEAD,
    "federation_state_source": "exact_current_native_receipts_only",
    "federation_runtime_state": "NOT_CHARACTERIZED_BY_THIS_POLICY",
    "release_truth_path": FEDERATION_RELEASE_RECEIPT_PATH,
    "release_truth_receipt_id": _EXPECTED_RELEASE_RECEIPT_ID,
    "release_truth_result": "BLOCKED_EXTERNAL_AUTHORITY",
    "role_allocation_is_runtime_evidence": False,
    "target_release": "v2.0.0",
    "target_release_published": False,
}
_EXPECTED_FORMAL_INVARIANTS: Final[dict[str, object]] = {
    "cross_domain_a2_allowed": False,
    "cross_domain_effect_owner": "target_native_domain_only",
    "global_a2": "FORBIDDEN",
    "global_a2_authority": None,
    "global_sovereign_controller": None,
    "global_sovereign_writer": None,
    "primary_scientific_cortex": "scientific-resource-lab",
    "shared_srl_scientific_contract_semantics_owner": "scientific-resource-lab",
    "target_wire_order_owner": "dual-contour-research-os",
}
_EXPECTED_PARTICIPANT_IDENTITIES: Final[dict[str, tuple[str, str]]] = {
    "crosslab": ("crosslab-shadow-link-v0", "PAGER_ONLY"),
    "dual": ("dual-contour-research-os", "MECHANICAL_TRANSPORT_ORDER_FABRIC"),
    "market": ("crypto-market-lab", "NATIVE_MARKET_TRUTH_AND_EFFECT_OWNER"),
    "security": (
        "security-research-os",
        "NATIVE_SECURITY_TRUTH_SAFETY_AND_EFFECT_OWNER",
    ),
    "srl": ("scientific-resource-lab", "SCIENTIFIC_REASONING_COMPUTE_FABRIC"),
}

_EXPECTED_RELEASE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "accepted_release_head",
        "canonical_writes",
        "decision_packet",
        "forbidden_terminal_states",
        "generator_head",
        "git_head",
        "git_head_semantics",
        "grants_authority",
        "head_provenance",
        "live_actions",
        "mandatory_nonactive_components",
        "mission_id",
        "observed_main_head",
        "protected_activation_attempts",
        "receipt_id",
        "release",
        "release_truth_decision",
        "remaining_external_waits",
        "result",
        "schema_version",
        "source_git_head",
        "stage_id",
        "stage_receipt_count",
        "target_release",
        "target_result",
    }
)

_EXPECTED_GATE_REPORT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "canonical_writes",
        "checks",
        "grants_authority",
        "input_manifest",
        "input_manifest_sha256",
        "live_actions",
        "policy_id",
        "receipt_id",
        "result",
        "schema_version",
    }
)
_EXPECTED_GATE_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "checked_document_sha256",
        "checked_source_sha256",
        "candidate_base_head",
        "candidate_diff_sha256",
        "current_head",
        "policy_sha256",
        "release_receipt_sha256",
        "verifier_sha256",
        "worktree_matches_index",
    }
)
_EXPECTED_GATE_CHECK_IDS: Final[frozenset[str]] = frozenset(
    {
        "FDC-00-policy-load",
        "FDC-01-policy-metadata",
        "FDC-02-formal-invariants",
        "FDC-03-participant-identities",
        "FDC-04-srl-boundary",
        "FDC-05-dual-boundary",
        "FDC-06-native-truth-and-effects",
        "FDC-07-crosslab-pager-only",
        "FDC-08-wire-semantic-separation",
        "FDC-09-current-vs-static-truth",
        "FDC-10-mandatory-entrypoints",
        "FDC-11-document-bindings",
        "FDC-12-local-links",
        "FDC-13-input-manifest",
        "FDC-14-source-bindings",
        "FDC-15-independent-review",
        "FDC-16-documentation-closure-binding",
        "FDC-17-repository-file-containment",
        "FDC-18-critical-source-semantics",
        "FDC-19-v37-history-immutability",
    }
)

_CELLS: Final[dict[str, dict[str, Any]]] = {
    "standalone": {
        "cell_id": "standalone",
        "display_name": "Standalone SRF session",
        "native_bootstrap": "srlab doctor",
        "allowed_transport": "local_json",
        "status": "READY",
        "proposal_only": False,
    },
    "market": {
        "cell_id": "market",
        "display_name": "Crypto Market Lab bridge",
        "native_bootstrap": "Market native operator bootstrap",
        "allowed_transport": "D0_D1_spool_packet",
        "status": "WAIT_NATIVE_BOOTSTRAP",
        "proposal_only": True,
    },
    "security": {
        "cell_id": "security",
        "display_name": "Security Researcher bridge",
        "native_bootstrap": "Security native bootstrap",
        "allowed_transport": "D0_D1_spool_packet",
        "status": "WAIT_NATIVE_BOOTSTRAP",
        "proposal_only": True,
    },
}


def labctl_manifest() -> dict[str, Any]:
    """Return the deterministic SRF solo-agent manifest."""
    cells = [deepcopy(_CELLS[key]) for key in sorted(_CELLS)]
    return {
        "schema_version": "LabCtlManifest/v1",
        "project_id": PROJECT_ID,
        "product_name": PRODUCT_NAME,
        "project_fingerprint": PROJECT_FINGERPRINT,
        "mission_id": MISSION_ID,
        "plan_id": PLAN_ID,
        "package_version": __version__,
        "entry_command": "srlab labctl enter",
        "cells": cells,
        "authority_invariants": {
            "grants_authority": False,
            "canonical_writes": 0,
            "live_actions": 0,
            "orders_allowed": False,
            "security_actions_allowed": False,
        },
        "next_commands": [
            "srlab labctl doctor",
            "srlab labctl federation-orient [write-scope]",
            "srlab labctl submit <session-dir>",
            "srlab labctl status <session-dir>",
            "srlab labctl result <session-dir>",
            "srlab labctl export <session-dir>",
            "srlab labctl replay <session-dir>",
            "srlab catalog inspect",
            "srlab plan build <bundle-file>",
            "srlab run execute <run-spec-file>",
        ],
    }


def lab_access_receipt(cell_id: str = "standalone") -> dict[str, Any]:
    """Return a ``LabAccessReceipt/v1`` scope projection for ``cell_id``.

    The receipt is authority-negative by construction. Cross-lab cells are
    marked as proposal-only and WAIT until their native bootstrap has produced
    fresh evidence outside SRF.
    """
    if cell_id not in _CELLS:
        valid = ", ".join(sorted(_CELLS))
        msg = f"unknown lab cell {cell_id!r}; expected one of: {valid}"
        raise ValueError(msg)
    cell = deepcopy(_CELLS[cell_id])
    invariants = labctl_manifest()["authority_invariants"]
    return {
        "schema_version": "LabAccessReceipt/v1",
        "project_id": PROJECT_ID,
        "project_fingerprint": PROJECT_FINGERPRINT,
        "mission_id": MISSION_ID,
        "plan_id": PLAN_ID,
        "cell": cell,
        "scope": {
            "proposal_only": bool(cell["proposal_only"]),
            "allowed_transport": cell["allowed_transport"],
            "native_bootstrap_required": True,
            "native_bootstrap": cell["native_bootstrap"],
        },
        **invariants,
    }


def enter_report(cell_id: str = "standalone") -> dict[str, Any]:
    """Build the JSON report emitted by ``srlab labctl enter``."""
    receipt = lab_access_receipt(cell_id)
    return {
        "schema_version": "LabCtlEnterReport/v1",
        "status": receipt["cell"]["status"],
        "manifest": labctl_manifest(),
        "receipt": receipt,
    }


class FederationOrientationError(ValueError):
    """Raised when checkout evidence cannot produce a fail-closed orientation."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_nonstandard_json_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")


def _parse_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FederationOrientationError(f"{label} is not valid strict JSON") from exc
    if not isinstance(value, dict):
        raise FederationOrientationError(f"{label} is not a JSON object")
    return value


def _canonical_sha256(value: object) -> str:
    try:
        encoded = (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FederationOrientationError("federation evidence is not canonical JSON") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _canonical_receipt_id(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "receipt_id"}
    return _canonical_sha256(body)


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _strict_equal(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return False
        return all(_strict_equal(actual[key], item) for key, item in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all(_strict_equal(left, right) for left, right in zip(actual, expected, strict=True))
    return actual == expected


def _is_exact_zero(value: object) -> bool:
    return type(value) is int and value == 0


def _sanitized_subprocess_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def _run_bounded(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FederationOrientationError("bounded repository verification is unavailable") from exc


def _exact_repo_root(repo_root: Path | None) -> tuple[Path, dict[str, str]]:
    requested = Path.cwd() if repo_root is None else Path(repo_root)
    try:
        root = requested.resolve(strict=True)
    except OSError as exc:
        raise FederationOrientationError("exact repository root is unavailable") from exc
    if not root.is_dir():
        raise FederationOrientationError("exact repository root is not a directory")
    environment = _sanitized_subprocess_environment()
    process = _run_bounded(
        ["/usr/bin/git", "-C", str(root), "rev-parse", "--show-toplevel"],
        cwd=root,
        environment=environment,
    )
    try:
        observed_root = Path(process.stdout.decode("utf-8").strip()).resolve(strict=True)
    except (OSError, UnicodeError) as exc:
        raise FederationOrientationError("exact repository identity is unavailable") from exc
    if process.returncode != 0 or observed_root != root:
        raise FederationOrientationError("federation orientation requires the exact Git root")
    return root, environment


def _resolve_repo_input(root: Path, relative_path: str, *, label: str) -> Path:
    if type(relative_path) is not str or not relative_path or "\\" in relative_path:
        raise FederationOrientationError(f"{label} path is not a canonical repository path")
    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or pure.as_posix() != relative_path
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise FederationOrientationError(f"{label} path escapes the repository")

    candidate = root
    for part in pure.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise FederationOrientationError(f"{label} path contains a symbolic link")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise FederationOrientationError(f"{label} is unavailable") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise FederationOrientationError(f"{label} is not a contained repository file")
    return resolved


def _read_stable_bytes(path: Path, *, label: str) -> tuple[bytes, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FederationOrientationError(f"{label} is unreadable") from exc
    digest = _sha256_bytes(raw)
    try:
        observed_digest = _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise FederationOrientationError(f"{label} changed while being read") from exc
    if observed_digest != digest:
        raise FederationOrientationError(f"{label} changed while being read")
    return raw, digest


def _load_stable_json(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    raw, digest = _read_stable_bytes(path, label=label)
    value = _parse_json_object(raw, label=label)
    try:
        observed_digest = _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise FederationOrientationError(f"{label} changed after parsing") from exc
    if observed_digest != digest:
        raise FederationOrientationError(f"{label} changed after parsing")
    return value, digest


def _expect_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise FederationOrientationError(f"{label} digest is invalid")
    return value


def _validate_gate_checks(checks: object) -> None:
    if not isinstance(checks, list):
        raise FederationOrientationError("repository doctrine gate checks are invalid")
    check_ids: set[str] = set()
    for item in checks:
        if (
            not isinstance(item, dict)
            or set(item) != {"check_id", "detail", "status"}
            or type(item.get("check_id")) is not str
            or type(item.get("detail")) is not str
            or item.get("status") != "PASS"
        ):
            raise FederationOrientationError("repository doctrine gate checks are invalid")
        check_ids.add(item["check_id"])
    if check_ids != _EXPECTED_GATE_CHECK_IDS or len(checks) != len(_EXPECTED_GATE_CHECK_IDS):
        raise FederationOrientationError("repository doctrine gate check set is incomplete")


def _validate_gate_manifest(manifest: object) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != _EXPECTED_GATE_INPUT_KEYS:
        raise FederationOrientationError("repository doctrine gate input manifest is invalid")
    document_hashes = manifest.get("checked_document_sha256")
    source_hashes = manifest.get("checked_source_sha256")
    if not isinstance(document_hashes, dict) or not isinstance(source_hashes, dict):
        raise FederationOrientationError("repository doctrine gate bindings are invalid")
    for mapping in (document_hashes, source_hashes):
        if not all(
            type(path) is str and _SHA256_RE.fullmatch(str(value))
            for path, value in mapping.items()
        ):
            raise FederationOrientationError("repository doctrine gate bindings are invalid")
    for key in (
        "candidate_diff_sha256",
        "policy_sha256",
        "release_receipt_sha256",
        "verifier_sha256",
    ):
        _expect_sha256(manifest.get(key), label="repository doctrine gate")
    for key in ("candidate_base_head", "current_head"):
        value = manifest.get(key)
        if type(value) is not str or _HEAD_RE.fullmatch(value) is None:
            raise FederationOrientationError("repository doctrine gate source identity is invalid")
    if manifest.get("worktree_matches_index") is not True:
        raise FederationOrientationError("repository doctrine gate source identity is invalid")
    return manifest


def _validate_gate_report(report: dict[str, Any]) -> dict[str, Any]:
    if set(report) != _EXPECTED_GATE_REPORT_KEYS:
        raise FederationOrientationError("repository doctrine gate report shape is invalid")
    if (
        report.get("schema_version") != "FederationDoctrineConsistencyReceipt/v1"
        or report.get("policy_id") != "FEDERATION_OWNERSHIP_POLICY_V1"
        or report.get("result") != "PASS"
        or not _is_exact_zero(report.get("canonical_writes"))
        or not _is_exact_zero(report.get("live_actions"))
        or report.get("grants_authority") is not False
    ):
        raise FederationOrientationError("repository doctrine gate did not PASS")

    _validate_gate_checks(report.get("checks"))
    manifest = _validate_gate_manifest(report.get("input_manifest"))
    if report.get("input_manifest_sha256") != _canonical_sha256(manifest):
        raise FederationOrientationError("repository doctrine gate manifest binding is invalid")
    if report.get("receipt_id") != _canonical_receipt_id(report):
        raise FederationOrientationError("repository doctrine gate receipt binding is invalid")
    return report


def _run_doctrine_gate(root: Path, environment: dict[str, str]) -> dict[str, Any]:
    script = _resolve_repo_input(root, FEDERATION_DOCTRINE_GATE_PATH, label="doctrine gate")
    _, verifier_sha256 = _read_stable_bytes(script, label="doctrine gate")
    process = _run_bounded(
        [sys.executable, str(script), "--repo-root", str(root)],
        cwd=root,
        environment=environment,
    )
    if (
        process.returncode != 0
        or len(process.stdout) > _MAX_GATE_OUTPUT_BYTES
        or len(process.stderr) > _MAX_GATE_OUTPUT_BYTES
    ):
        raise FederationOrientationError("repository doctrine gate did not PASS")
    report = _parse_json_object(process.stdout, label="repository doctrine gate report")
    validated = _validate_gate_report(report)
    manifest = validated["input_manifest"]
    if not isinstance(manifest, dict) or manifest.get("verifier_sha256") != verifier_sha256:
        raise FederationOrientationError("repository doctrine gate verifier binding is invalid")
    _, observed_verifier_sha256 = _read_stable_bytes(script, label="doctrine gate")
    if observed_verifier_sha256 != verifier_sha256:
        raise FederationOrientationError("doctrine gate changed after verification")
    return validated


def _validate_policy(policy: dict[str, Any]) -> None:
    if set(policy) != _EXPECTED_POLICY_KEYS:
        raise FederationOrientationError("federation ownership policy shape is invalid")
    if (
        policy.get("schema_version") != "FederationOwnershipPolicy/v1"
        or policy.get("policy_id") != "FEDERATION_OWNERSHIP_POLICY_V1"
        or policy.get("status") != "DRAFT_PROPOSED"
        or policy.get("activates_federation") is not False
        or policy.get("runtime_truth") is not False
        or policy.get("grants_authority") is not False
        or not _is_exact_zero(policy.get("canonical_writes"))
        or not _strict_equal(policy.get("current_state"), _EXPECTED_CURRENT_STATE)
        or not _strict_equal(policy.get("formal_invariants"), _EXPECTED_FORMAL_INVARIANTS)
        or not isinstance(policy.get("document_bindings"), dict)
        or not isinstance(policy.get("source_bindings"), dict)
    ):
        raise FederationOrientationError("federation ownership policy is not the safe draft")
    participants = policy.get("participants")
    if not isinstance(participants, dict) or set(participants) != set(
        _EXPECTED_PARTICIPANT_IDENTITIES
    ):
        raise FederationOrientationError("federation participant identities are invalid")
    for name, (repository_id, role_code) in _EXPECTED_PARTICIPANT_IDENTITIES.items():
        item = participants.get(name)
        if (
            not isinstance(item, dict)
            or item.get("repository_id") != repository_id
            or item.get("role_code") != role_code
        ):
            raise FederationOrientationError("federation participant identities are invalid")
    dual = participants["dual"]
    crosslab = participants["crosslab"]
    if (
        dual.get("role_activation") != "TARGET_DECLARED_NOT_RUNTIME_PROVEN"
        or dual.get("payload_reinterpretation_allowed") is not False
        or crosslab.get("srl_endpoint_allowed") is not False
        or not _strict_equal(
            crosslab.get("registered_peer_scope"), ["bridge", "market", "security"]
        )
    ):
        raise FederationOrientationError("federation target role activation is invalid")


def _validate_release(release: dict[str, Any]) -> None:
    if set(release) != _EXPECTED_RELEASE_KEYS:
        raise FederationOrientationError("V3.7 release receipt shape is invalid")
    release_state = release.get("release")
    decision = release.get("release_truth_decision")
    provenance = release.get("head_provenance")
    waits = release.get("remaining_external_waits")
    if (
        release.get("schema_version") != "MissionCloseoutReceipt/v2"
        or release.get("mission_id") != "activate-scientific-reasoning-fabric-v3.7"
        or release.get("stage_id") != "A22"
        or release.get("result") != "BLOCKED_EXTERNAL_AUTHORITY"
        or release.get("target_release") != "v2.0.0"
        or release.get("target_result") != "DONE"
        or release.get("accepted_release_head") != _EXPECTED_RELEASE_HEAD
        or release.get("receipt_id") != _EXPECTED_RELEASE_RECEIPT_ID
        or release.get("receipt_id") != _canonical_receipt_id(release)
        or not _is_exact_zero(release.get("canonical_writes"))
        or not _is_exact_zero(release.get("live_actions"))
        or release.get("grants_authority") is not False
        or not _strict_equal(
            release.get("forbidden_terminal_states"),
            ["DONE", "RELEASED_WITH_DECLARED_WAITS"],
        )
        or not isinstance(waits, list)
        or not waits
        or not all(type(item) is str for item in waits)
        or not isinstance(release_state, dict)
        or set(release_state) != {"published", "reason", "tag"}
        or release_state.get("published") is not False
        or release_state.get("tag") is not None
        or type(release_state.get("reason")) is not str
        or not isinstance(decision, dict)
        or decision.get("schema_version") != "ReleaseTruthDecision/v1"
        or decision.get("verdict") != "REJECT"
        or decision.get("target_release") != "v2.0.0"
        or decision.get("target_result") != "DONE"
        or not isinstance(decision.get("blockers"), list)
        or not decision.get("blockers")
        or not isinstance(provenance, dict)
        or provenance.get("accepted_release_head") != _EXPECTED_RELEASE_HEAD
        or provenance.get("self_referential_commit_claimed") is not False
    ):
        raise FederationOrientationError("V3.7 release receipt is not exact blocked evidence")


def _validate_stage_receipt(participant: str, stage: dict[str, Any]) -> dict[str, str]:
    expected_stage_id, expected_receipt_id = _EXPECTED_STAGE_RECEIPTS[participant]
    waits = stage.get("remaining_external_waits")
    if (
        stage.get("schema_version") != "StageCompletionReceipt/v1"
        or stage.get("stage_id") != expected_stage_id
        or stage.get("receipt_id") != expected_receipt_id
        or stage.get("receipt_id") != _canonical_receipt_id(stage)
        or stage.get("result") != "PASS"
        or stage.get("terminal_state") != "WAIT_NATIVE_CHILD_CLOSEOUT"
        or stage.get("stage_closure") != "PARKED_WAIT_NATIVE_CHILD_CLOSEOUT"
        or not _is_exact_zero(stage.get("canonical_writes"))
        or not _is_exact_zero(stage.get("live_actions"))
        or stage.get("grants_authority") is not False
        or not isinstance(waits, list)
        or not waits
        or not all(type(item) is str for item in waits)
    ):
        raise FederationOrientationError(
            f"recorded V3.7 {participant} stage receipt is not exact parked evidence"
        )
    return {
        "receipt_id": expected_receipt_id,
        "stage_id": expected_stage_id,
        "terminal_state": "WAIT_NATIVE_CHILD_CLOSEOUT",
        "evidence_role": "RECORDED_V3_7_NOT_CURRENT_HEALTH",
    }


def _gate_hash(mapping: object, relative_path: str, *, label: str) -> str:
    if not isinstance(mapping, dict):
        raise FederationOrientationError(f"{label} gate binding is invalid")
    return _expect_sha256(mapping.get(relative_path), label=label)


def _assert_loaded_checkout_sources(
    root: Path,
    gate_manifest: dict[str, Any],
) -> None:
    expected_labctl = _resolve_repo_input(root, "src/srl/labctl.py", label="labctl source")
    expected_cli = _resolve_repo_input(root, "src/srl/cli.py", label="CLI source")
    expected_contracts = _resolve_repo_input(
        root,
        "src/srl/contracts/schema.py",
        label="contract registry source",
    )
    expected_orientation_schema = _resolve_repo_input(
        root,
        FEDERATION_ORIENTATION_SCHEMA_PATH,
        label="orientation schema source",
    )
    loaded_labctl = Path(__file__).resolve()
    loaded_cli = Path(__file__).with_name("cli.py").resolve()
    contract_module = sys.modules.get(validate.__module__)
    contract_file = getattr(contract_module, "__file__", None)
    if type(contract_file) is not str:
        raise FederationOrientationError("contract registry source identity is unavailable")
    loaded_contracts = Path(contract_file).resolve()
    if (
        expected_labctl != loaded_labctl
        or expected_cli != loaded_cli
        or expected_contracts != loaded_contracts
    ):
        raise FederationOrientationError("federation orientation must execute from this checkout")
    source_hashes = gate_manifest.get("checked_source_sha256")
    for relative_path, path, label in (
        ("src/srl/labctl.py", expected_labctl, "labctl source"),
        ("src/srl/cli.py", expected_cli, "CLI source"),
        ("src/srl/contracts/schema.py", expected_contracts, "contract registry source"),
        (
            FEDERATION_ORIENTATION_SCHEMA_PATH,
            expected_orientation_schema,
            "orientation schema source",
        ),
    ):
        _, digest = _read_stable_bytes(path, label=label)
        if digest != _gate_hash(source_hashes, relative_path, label=label):
            raise FederationOrientationError(f"{label} changed after doctrine verification")


def federation_orientation_report(
    *,
    repo_root: Path | None = None,
    write_scope: str = "NONE",
) -> dict[str, Any]:
    """Return a checkout-bound, authority-negative historical orientation.

    The repository doctrine gate must PASS first.  V3.7 receipts are labelled
    as recorded evidence and never characterize current peer or federation
    runtime health.
    """
    if (
        type(write_scope) is not str
        or len(write_scope) > _MAX_WRITE_SCOPE_LENGTH
        or _WRITE_SCOPE_RE.fullmatch(write_scope) is None
    ):
        raise FederationOrientationError("write scope must use 1-256 safe ASCII characters")

    root, environment = _exact_repo_root(repo_root)
    gate = _run_doctrine_gate(root, environment)
    gate_manifest = gate["input_manifest"]
    if not isinstance(gate_manifest, dict):
        raise FederationOrientationError("repository doctrine gate input manifest is invalid")
    _assert_loaded_checkout_sources(root, gate_manifest)

    policy_path = _resolve_repo_input(root, FEDERATION_POLICY_PATH, label="ownership policy")
    policy, policy_sha256 = _load_stable_json(policy_path, label="ownership policy")
    if policy_sha256 != _expect_sha256(gate_manifest.get("policy_sha256"), label="policy"):
        raise FederationOrientationError("ownership policy changed after doctrine verification")
    _validate_policy(policy)

    release_path = _resolve_repo_input(
        root,
        FEDERATION_RELEASE_RECEIPT_PATH,
        label="V3.7 release receipt",
    )
    release, release_sha256 = _load_stable_json(release_path, label="V3.7 release receipt")
    if release_sha256 != _expect_sha256(
        gate_manifest.get("release_receipt_sha256"), label="release receipt"
    ):
        raise FederationOrientationError("V3.7 release receipt changed after doctrine verification")
    _validate_release(release)

    plan_path = _resolve_repo_input(
        root,
        FEDERATION_SUCCESSOR_PLAN_PATH,
        label="successor plan",
    )
    plan_raw, plan_sha256 = _read_stable_bytes(plan_path, label="successor plan")
    try:
        plan_text = plan_raw.decode("utf-8")
    except UnicodeError as exc:
        raise FederationOrientationError("successor plan is not UTF-8") from exc
    document_hashes = gate_manifest.get("checked_document_sha256")
    if (
        plan_sha256
        != _gate_hash(document_hashes, FEDERATION_SUCCESSOR_PLAN_PATH, label="successor plan")
        or "STATUS: DRAFT_PROPOSED" not in plan_text
        or "WAIT_GOVERNANCE_ADMISSION" not in plan_text
        or "ACTIVATES_FEDERATION: false" not in plan_text
        or "GLOBAL_A2: FORBIDDEN" not in plan_text
    ):
        raise FederationOrientationError("successor plan is not the safe draft")
    _, observed_plan_sha256 = _read_stable_bytes(plan_path, label="successor plan")
    if observed_plan_sha256 != plan_sha256:
        raise FederationOrientationError("successor plan changed after parsing")

    recorded_stages: dict[str, dict[str, str]] = {}
    for participant, relative_path in FEDERATION_STAGE_RECEIPTS.items():
        stage_path = _resolve_repo_input(
            root,
            relative_path,
            label=f"recorded V3.7 {participant} stage receipt",
        )
        stage, _ = _load_stable_json(
            stage_path,
            label=f"recorded V3.7 {participant} stage receipt",
        )
        recorded_stages[participant] = _validate_stage_receipt(participant, stage)

    orientation: dict[str, str | bool] = {
        "PRIMARY_SCIENTIFIC_CORTEX": "SCIENTIFIC_RESOURCE_LAB",
        "SRL_FORMAL_ROLE": "SCIENTIFIC_REASONING_COMPUTE_FABRIC",
        "TARGET_WIRE_ORDER_OWNER": "DUAL_CONTOUR",
        "TARGET_WIRE_ORDER_ROLE_STATE": "TARGET_DECLARED_NOT_RUNTIME_PROVEN",
        "SAFETY_CORTEX": "SECURITY_RESEARCH_OS",
        "MARKET_TRUTH_OWNER": "CRYPTO_MARKET_LAB",
        "SECURITY_TRUTH_OWNER": "SECURITY_RESEARCH_OS",
        "GLOBAL_SOVEREIGN_CONTROLLER": "NONE",
        "GLOBAL_SOVEREIGN_WRITER": "NONE",
        "GLOBAL_A2": "FORBIDDEN",
        "CROSS_DOMAIN_EFFECT_OWNER": "TARGET_NATIVE_DOMAIN_ONLY",
        "CROSSLAB_ROLE": "PAGER_ONLY",
        "CROSSLAB_SRL_ENDPOINT": "NONE",
        "CURRENT_SRL_RELEASE_TRUTH": "BLOCKED_EXTERNAL_AUTHORITY",
        "CURRENT_FEDERATION_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_SRL_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_MARKET_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_SECURITY_RUNTIME": "NOT_CHARACTERIZED",
        "CURRENT_DUAL_RUNTIME": "NOT_CHARACTERIZED",
        "FEDERATION_RUNTIME_STATE_SOURCE": "EXACT_CURRENT_NATIVE_RECEIPTS_ONLY",
        "DECLARED_WRITE_SCOPE": write_scope,
        "DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY": False,
    }
    orientation_block = "\n".join(
        f"{key}: {'FALSE' if value is False else value}" for key, value in orientation.items()
    )
    candidate_base_head = gate_manifest["candidate_base_head"]
    current_head = gate_manifest["current_head"]
    candidate_diff = gate_manifest["candidate_diff_sha256"]
    report: dict[str, Any] = {
        "schema_version": "FederationOrientationReport/v1",
        "status": "ORIENTED_READ_ONLY",
        "policy_status": "DRAFT_PROPOSED",
        "admission_state": "WAIT_GOVERNANCE_ADMISSION",
        "orientation": orientation,
        "orientation_block": orientation_block,
        "target_role_activation": {
            "dual_wire_order": "TARGET_DECLARED_NOT_RUNTIME_PROVEN",
        },
        "recorded_v37_evidence": {
            "evidence_role": "RECORDED_V3_7_NOT_CURRENT_RUNTIME_HEALTH",
            "release": {
                "accepted_release_head": _EXPECTED_RELEASE_HEAD,
                "receipt_id": _EXPECTED_RELEASE_RECEIPT_ID,
                "result": "BLOCKED_EXTERNAL_AUTHORITY",
                "target_release": "v2.0.0",
                "target_release_published": False,
            },
            "stages": recorded_stages,
        },
        "bindings": {
            "policy": {
                "path": FEDERATION_POLICY_PATH,
                "sha256": policy_sha256,
            },
            "successor_plan": {
                "path": FEDERATION_SUCCESSOR_PLAN_PATH,
                "sha256": plan_sha256,
            },
            "release_receipt": {
                "path": FEDERATION_RELEASE_RECEIPT_PATH,
                "sha256": release_sha256,
            },
            "doctrine_gate": {
                "input_manifest_sha256": gate["input_manifest_sha256"],
                "receipt_id": gate["receipt_id"],
                "verifier_sha256": gate_manifest["verifier_sha256"],
            },
        },
        "source_identity": {
            "candidate_base_head": candidate_base_head,
            "current_head": current_head,
            "candidate_diff_sha256": candidate_diff,
            "worktree_matches_index": True,
        },
        "runtime_truth": False,
        "activates_federation": False,
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
        "declared_scope_grants_authority": False,
    }
    try:
        validate(report, "FederationOrientationReport")
    except (ContractValidationError, SchemaError) as exc:
        raise FederationOrientationError("orientation report failed its closed schema") from exc
    return report
