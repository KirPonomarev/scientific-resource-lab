#!/usr/bin/env python3
"""V3.7 A20 Security native bridge closeout gate.

This gate is truth-led. It passes when SRF preserves the inactive,
proposal-only Security bridge boundary, imports no missing native closeout as a
success, and proves that D2/D3 material, targets, credentials, scanner control
and Security actions cannot cross the SRF bridge.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402
from srl.integrations import (  # noqa: E402
    SECURITY_IMPORTED_STATUS,
    SECURITY_OFFLINE_WAIT_STATUS,
    SECURITY_REJECTED_STATUS,
    SECURITY_WAIT_STATUS,
    SecurityBridgeError,
    SecurityBridgeStatus,
    SecurityCloseoutError,
    build_security_bridge_health_projection,
    build_security_closeout_import_receipt,
    build_security_science_request,
    import_security_observation_packet,
    verify_native_bridge_child_request,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A20"
CHILD_REQUEST_PATH: Final[Path] = (
    REPO_ROOT / "docs" / "child-missions" / "security" / "security-bridge-child-request.json"
)
NATIVE_BOOTSTRAP_EVIDENCE_PATH: Final[Path] = (
    REPO_ROOT / "docs" / "child-missions" / "security" / "security-native-bootstrap-evidence.json"
)
FIXTURE_KEYS: Final[dict[str, bytes]] = {
    "srf-security-child-fixture-key": b"srf-security-child-fixture-key"
}
GIT: Final[str] = "/usr/bin/git"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _current_head() -> str:
    return subprocess.check_output(  # noqa: S603
        [GIT, "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(  # noqa: S603
            [GIT, "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=REPO_ROOT,
            check=False,
        ).returncode
        == 0
    )


def _optional_native_closeout(path_arg: Path | None) -> dict[str, Any] | None:
    if path_arg is not None:
        return _load_json(path_arg)
    env_path = os.environ.get("SRL_A20_NATIVE_CLOSEOUT_PATH")
    if env_path:
        return _load_json(Path(env_path))
    return None


def _check_child_request(child_request: dict[str, Any], current_head: str) -> dict[str, Any]:
    failures: list[str] = []
    try:
        verify_native_bridge_child_request(
            child_request,
            key_material_by_id=FIXTURE_KEYS,
        )
    except Exception as exc:
        failures.append(f"signature verification failed: {exc}")
    source_head = child_request.get("source_head")
    if not isinstance(source_head, str) or not source_head:
        failures.append("source_head missing")
    elif not _is_ancestor(source_head, current_head):
        failures.append("source_head is not an ancestor of current HEAD")
    if child_request.get("target_project") != "security-research-os":
        failures.append("target_project drifted")
    if child_request.get("native_closeout_status") != SECURITY_WAIT_STATUS:
        failures.append("child request no longer waits for native closeout")
    if (
        child_request.get("parent_direct_external_writes") != 0
        or child_request.get("canonical_writes") != 0
        or child_request.get("live_actions") != 0
        or child_request.get("grants_authority") is not False
        or child_request.get("activation_state") != "INACTIVE"
    ):
        failures.append("child request is not inactive and authority-negative")
    requested_action = child_request.get("requested_action")
    if not isinstance(requested_action, str) or "ebashim" not in requested_action:
        failures.append("child request does not preserve ebashim boundary")
    return {
        "check_id": "A20-01-hash-bound-child-request",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "child request signature, source ancestry, target and ebashim boundary are valid",
        "child_request_id": child_request.get("request_id"),
        "source_head": child_request.get("source_head"),
        "current_head": current_head,
        "target_head": child_request.get("target_head"),
    }


def _check_native_bootstrap(
    child_request: dict[str, Any],
    bootstrap_evidence: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    if bootstrap_evidence.get("target_project") != child_request.get("target_project"):
        failures.append("native bootstrap target_project mismatch")
    if bootstrap_evidence.get("runtime_head") != child_request.get("target_head"):
        failures.append("native bootstrap runtime_head mismatch")
    if bootstrap_evidence.get("parent_direct_external_writes") != 0:
        failures.append("bootstrap evidence records parent external writes")
    if bootstrap_evidence.get("grants_authority") is not False:
        failures.append("bootstrap evidence grants authority")
    if bootstrap_evidence.get("no_live_authority") is not True:
        failures.append("bootstrap evidence does not prove no live authority")
    if bootstrap_evidence.get("security_actions_allowed") is not False:
        failures.append("bootstrap evidence permits Security actions")
    if bootstrap_evidence.get("target_actions_allowed") is not False:
        failures.append("bootstrap evidence permits target actions")
    if bootstrap_evidence.get("direct_scanner_control") is not False:
        failures.append("bootstrap evidence permits direct scanner control")
    if bootstrap_evidence.get("D2_D3_transfers") != 0:
        failures.append("bootstrap evidence records D2/D3 transfer")
    return {
        "check_id": "A20-02-native-bootstrap-evidence",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "Security native bootstrap evidence is preserved as "
            f"{bootstrap_evidence.get('organism_status')}"
        ),
        "native_bootstrap_status": bootstrap_evidence.get("status"),
        "organism_status": bootstrap_evidence.get("organism_status"),
        "technical_health": bootstrap_evidence.get("technical_health"),
        "next_gate": bootstrap_evidence.get("next_gate"),
        "root_reason_code": bootstrap_evidence.get("root_reason_code"),
    }


def _check_inactive_bridge(
    child_request: dict[str, Any],
    bootstrap_evidence: dict[str, Any],
) -> dict[str, Any]:
    try:
        security_head = _require_str(child_request.get("target_head"), "target_head")
        request = build_security_science_request(
            objective="summarize public sanitized method evidence for defensive review",
            security_head=security_head,
            evidence_refs=("sha256:" + "3" * 64,),
        )
        observation_id = "sha256:" + "4" * 64
        result = import_security_observation_packet(
            {
                "schema_version": "SecurityObservationPacket/v1",
                "observation_id": observation_id,
                "request_id": request["request_id"],
                "security_head": security_head,
                "payload": {"finding": "sanitized C3 defensive-method proposal"},
                "classification": "D1",
                "semantic_class": "C3_PROPOSAL",
                "executor": "ebashim",
                "authority_claimed": False,
                "target_action": None,
            },
            expected_security_head=security_head,
            seen_observation_ids=frozenset(),
        )
        projection = build_security_bridge_health_projection(
            security_gate=_require_str(
                bootstrap_evidence.get("organism_status"),
                "organism_status",
            ),
            security_head=security_head,
        )
    except Exception as exc:
        return {
            "check_id": "A20-03-inactive-bridge-safety",
            "status": "FAIL",
            "detail": str(exc),
        }
    failures: list[str] = []
    if request.get("grants_authority") is not False or result.get("grants_authority") is not False:
        failures.append("request/result grants authority")
    payload = result.get("payload")
    if not isinstance(payload, dict) or payload.get("native_executor_boundary") != "ebashim":
        failures.append("result did not preserve ebashim")
    if projection.get("security_actions") != 0 or projection.get("target_actions") != 0:
        failures.append("health projection permits Security or target action")
    if projection.get("D2_D3_transfers") != 0:
        failures.append("health projection permits D2/D3 transfer")
    if bootstrap_evidence.get("organism_status") != "GREEN":
        if projection.get("status") != SecurityBridgeStatus.WAIT_SECURITY_HEALTH.value:
            failures.append("non-GREEN Security evidence did not project WAIT_SECURITY_HEALTH")
    return {
        "check_id": "A20-03-inactive-bridge-safety",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "inactive Security bridge preserves ebashim and rejects authority/action",
        "request_id": request["request_id"],
        "result_id": result["result_id"],
        "bridge_projection_receipt_id": projection["receipt_id"],
        "bridge_projection_status": projection["status"],
    }


def _check_containment(child_request: dict[str, Any]) -> dict[str, Any]:
    security_head = _require_str(child_request.get("target_head"), "target_head")
    failures: list[str] = []
    reject_cases = (
        (
            "D2-classification",
            lambda: build_security_science_request(
                objective="summarize public sanitized method evidence",
                security_head=security_head,
                classification="D2",
            ),
        ),
        (
            "target-material",
            lambda: build_security_science_request(
                objective="scan target host 192.0.2.1",
                security_head=security_head,
            ),
        ),
        (
            "non-ebashim-executor",
            lambda: import_security_observation_packet(
                {
                    "schema_version": "SecurityObservationPacket/v1",
                    "observation_id": "sha256:" + "5" * 64,
                    "request_id": "sha256:" + "6" * 64,
                    "security_head": security_head,
                    "payload": {"finding": "sanitized"},
                    "classification": "D0",
                    "semantic_class": "C3_PROPOSAL",
                    "executor": "direct-scanner",
                    "authority_claimed": False,
                    "target_action": None,
                },
                expected_security_head=security_head,
            ),
        ),
        (
            "target-action",
            lambda: import_security_observation_packet(
                {
                    "schema_version": "SecurityObservationPacket/v1",
                    "observation_id": "sha256:" + "7" * 64,
                    "request_id": "sha256:" + "8" * 64,
                    "security_head": security_head,
                    "payload": {"finding": "sanitized"},
                    "classification": "D0",
                    "semantic_class": "C3_PROPOSAL",
                    "executor": "ebashim",
                    "authority_claimed": False,
                    "target_action": "scan",
                },
                expected_security_head=security_head,
            ),
        ),
    )
    for name, call in reject_cases:
        try:
            call()
        except SecurityBridgeError:
            continue
        failures.append(f"{name} was accepted")
    return {
        "check_id": "A20-04-d0-d1-containment",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "D2/D3, target material, non-ebashim executor and target actions are rejected",
    }


def _check_import_projection(
    child_request: dict[str, Any],
    bootstrap_evidence: dict[str, Any],
    native_closeout: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        import_receipt = build_security_closeout_import_receipt(
            child_request=child_request,
            native_closeout=native_closeout,
            key_material_by_id=FIXTURE_KEYS,
            native_bootstrap_evidence=bootstrap_evidence,
        )
    except SecurityCloseoutError as exc:
        return {
            "check_id": "A20-05-native-closeout-import",
            "status": "FAIL",
            "detail": str(exc),
            "import_receipt": None,
        }
    expected_status = (
        SECURITY_IMPORTED_STATUS if native_closeout is not None else SECURITY_WAIT_STATUS
    )
    failures: list[str] = []
    if import_receipt.get("status") != expected_status:
        failures.append(f"import receipt status is {import_receipt.get('status')}")
    if import_receipt.get("srf_offline_status") != SECURITY_OFFLINE_WAIT_STATUS:
        failures.append("SRF offline status is not WAIT_SRF")
    if (
        import_receipt.get("parent_direct_external_writes") != 0
        or import_receipt.get("security_writes") != 0
        or import_receipt.get("canonical_writes") != 0
        or import_receipt.get("live_actions") != 0
        or import_receipt.get("security_actions") != 0
        or import_receipt.get("target_actions") != 0
        or import_receipt.get("D2_D3_transfers") != 0
        or import_receipt.get("direct_scanner_control") is not False
        or import_receipt.get("grants_authority") is not False
        or import_receipt.get("scientific_authority_granted") is not False
        or import_receipt.get("security_activation_authority_granted") is not False
    ):
        failures.append("import receipt is not authority/action-negative")
    return {
        "check_id": "A20-05-native-closeout-import",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else f"native closeout projection is {import_receipt['status']} with WAIT_SRF",
        "import_receipt": import_receipt,
    }


def _build_stage_receipt(native_closeout_path: Path | None) -> dict[str, Any]:
    child_request = _load_json(CHILD_REQUEST_PATH)
    bootstrap_evidence = _load_json(NATIVE_BOOTSTRAP_EVIDENCE_PATH)
    native_closeout = _optional_native_closeout(native_closeout_path)
    checks = [
        _check_child_request(child_request, _current_head()),
        _check_native_bootstrap(child_request, bootstrap_evidence),
        _check_inactive_bridge(child_request, bootstrap_evidence),
        _check_containment(child_request),
        _check_import_projection(child_request, bootstrap_evidence, native_closeout),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    import_receipt = checks[-1].get("import_receipt")
    terminal_state = (
        import_receipt.get("status")
        if isinstance(import_receipt, dict)
        else SECURITY_REJECTED_STATUS
    )
    waits = []
    if terminal_state != SECURITY_IMPORTED_STATUS:
        waits.append("WAIT_NATIVE_CHILD_CLOSEOUT:SECURITY_NATIVE_BRIDGE_CLOSEOUT_ABSENT")
    if bootstrap_evidence.get("organism_status") != "GREEN":
        waits.append("WAIT_SECURITY_HEALTH:SECURITY_ORGANISM_NOT_GREEN")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "terminal_state": terminal_state,
        "srf_offline_status": SECURITY_OFFLINE_WAIT_STATUS,
        "stage_closure": "A20_ACTIVE_NATIVE_CLOSEOUT_IMPORTED"
        if terminal_state == SECURITY_IMPORTED_STATUS and status == "PASS"
        else "PARKED_WAIT_NATIVE_CHILD_CLOSEOUT",
        "child_request_id": child_request.get("request_id"),
        "native_closeout_receipt_id": import_receipt.get("native_closeout_receipt_id")
        if isinstance(import_receipt, dict)
        else None,
        "import_receipt_id": import_receipt.get("receipt_id")
        if isinstance(import_receipt, dict)
        else None,
        "remaining_external_waits": waits,
        "checks": checks,
        "parent_direct_external_writes": 0,
        "security_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "security_actions": 0,
        "target_actions": 0,
        "D2_D3_transfers": 0,
        "direct_scanner_control": False,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "security_activation_authority_granted": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--native-closeout", type=Path, help="optional native closeout JSON path")
    parser.add_argument("--out", type=Path, help="optional path for the generated A20 receipt")
    args = parser.parse_args()
    receipt = _build_stage_receipt(args.native_closeout)
    rendered = dumps(receipt)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(rendered)
    sys.stdout.buffer.write(rendered)
    sys.stdout.buffer.flush()
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
