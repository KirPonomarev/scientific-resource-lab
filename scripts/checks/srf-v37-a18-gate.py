#!/usr/bin/env python3
"""V3.7 A18 DualContour native child closeout gate.

This gate is truth-led. It passes when SRF correctly preserves the current
``WAIT_NATIVE_CHILD_CLOSEOUT`` state and fails if a stale, mismatched, failed or
authority-granting native closeout is projected as accepted.
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
    DUAL_CONTOUR_IMPORTED_STATUS,
    DUAL_CONTOUR_REJECTED_STATUS,
    DUAL_CONTOUR_WAIT_STATUS,
    DualContourCloseoutError,
    build_dual_contour_closeout_import_receipt,
    build_shared_contract_conformance_receipt,
    verify_shared_contract_child_mission_request,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A18"
CHILD_REQUEST_PATH: Final[Path] = (
    REPO_ROOT
    / "docs"
    / "child-missions"
    / "dual-contour"
    / "shared-contract-child-mission-request.json"
)
NATIVE_STARTUP_EVIDENCE_PATH: Final[Path] = (
    REPO_ROOT
    / "docs"
    / "child-missions"
    / "dual-contour"
    / "dual-contour-native-startup-evidence.json"
)
FIXTURE_KEYS: Final[dict[str, bytes]] = {"fixture-key": b"fixture-secret"}
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
    env_path = os.environ.get("SRL_A18_NATIVE_CLOSEOUT_PATH")
    if env_path:
        return _load_json(Path(env_path))
    return None


def _check_child_request(child_request: dict[str, Any], current_head: str) -> dict[str, Any]:
    failures: list[str] = []
    try:
        verify_shared_contract_child_mission_request(
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
    if child_request.get("target_project") != "dual-contour-research-os":
        failures.append("target_project drifted")
    if child_request.get("native_closeout_status") != DUAL_CONTOUR_WAIT_STATUS:
        failures.append("child request no longer waits for native closeout")
    if (
        child_request.get("parent_direct_external_writes") != 0
        or child_request.get("canonical_writes") != 0
        or child_request.get("grants_authority") is not False
    ):
        failures.append("child request is not authority-negative")
    return {
        "check_id": "A18-01-hash-bound-child-request",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "child request signature, source ancestry, target and authority boundary are valid",
        "child_request_id": child_request.get("request_id"),
        "source_head": child_request.get("source_head"),
        "current_head": current_head,
        "target_head": child_request.get("target_head"),
    }


def _check_producer_suite() -> dict[str, Any]:
    try:
        receipt = build_shared_contract_conformance_receipt()
    except Exception as exc:
        return {
            "check_id": "A18-02-producer-conformance-suite",
            "status": "FAIL",
            "detail": str(exc),
        }
    return {
        "check_id": "A18-02-producer-conformance-suite",
        "status": "PASS",
        "detail": "SRF producer conformance vectors accept/reject as declared",
        "producer_conformance_receipt_id": receipt["receipt_id"],
        "outcomes": receipt["outcomes"],
    }


def _check_native_startup(
    child_request: dict[str, Any],
    startup_evidence: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    if startup_evidence.get("target_project") != child_request.get("target_project"):
        failures.append("native startup target_project mismatch")
    if startup_evidence.get("target_head") != child_request.get("target_head"):
        failures.append("native startup target_head mismatch")
    if startup_evidence.get("parent_direct_external_writes") != 0:
        failures.append("startup evidence records parent external writes")
    if startup_evidence.get("grants_authority") is not False:
        failures.append("startup evidence grants authority")
    status = startup_evidence.get("status")
    return {
        "check_id": "A18-03-native-startup-evidence",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else f"DualContour native startup evidence is preserved as {status}",
        "native_startup_status": status,
        "native_startup_result": startup_evidence.get("result"),
    }


def _check_import_projection(
    child_request: dict[str, Any],
    startup_evidence: dict[str, Any],
    native_closeout: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        import_receipt = build_dual_contour_closeout_import_receipt(
            child_request=child_request,
            native_closeout=native_closeout,
            key_material_by_id=FIXTURE_KEYS,
            native_startup_evidence=startup_evidence,
        )
    except DualContourCloseoutError as exc:
        return {
            "check_id": "A18-04-native-closeout-import",
            "status": "FAIL",
            "detail": str(exc),
            "import_receipt": None,
        }
    expected_status = (
        DUAL_CONTOUR_IMPORTED_STATUS if native_closeout is not None else DUAL_CONTOUR_WAIT_STATUS
    )
    failures: list[str] = []
    if import_receipt.get("status") != expected_status:
        failures.append(f"import receipt status is {import_receipt.get('status')}")
    if (
        import_receipt.get("parent_direct_external_writes") != 0
        or import_receipt.get("canonical_writes") != 0
        or import_receipt.get("live_actions") != 0
        or import_receipt.get("grants_authority") is not False
        or import_receipt.get("scientific_authority_granted") is not False
        or import_receipt.get("domain_authority_granted") is not False
    ):
        failures.append("import receipt is not authority-negative")
    return {
        "check_id": "A18-04-native-closeout-import",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else f"native closeout projection is {import_receipt['status']}",
        "import_receipt": import_receipt,
    }


def _build_stage_receipt(native_closeout_path: Path | None) -> dict[str, Any]:
    child_request = _load_json(CHILD_REQUEST_PATH)
    startup_evidence = _load_json(NATIVE_STARTUP_EVIDENCE_PATH)
    native_closeout = _optional_native_closeout(native_closeout_path)
    checks = [
        _check_child_request(child_request, _current_head()),
        _check_producer_suite(),
        _check_native_startup(child_request, startup_evidence),
        _check_import_projection(child_request, startup_evidence, native_closeout),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    import_receipt = checks[-1].get("import_receipt")
    terminal_state = (
        import_receipt.get("status")
        if isinstance(import_receipt, dict)
        else DUAL_CONTOUR_REJECTED_STATUS
    )
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "terminal_state": terminal_state,
        "stage_closure": "A18_ACTIVE"
        if terminal_state == DUAL_CONTOUR_IMPORTED_STATUS and status == "PASS"
        else "PARKED_WAIT_NATIVE_CHILD_CLOSEOUT",
        "child_request_id": child_request.get("request_id"),
        "native_closeout_receipt_id": import_receipt.get("native_closeout_receipt_id")
        if isinstance(import_receipt, dict)
        else None,
        "import_receipt_id": import_receipt.get("receipt_id")
        if isinstance(import_receipt, dict)
        else None,
        "remaining_external_waits": []
        if terminal_state == DUAL_CONTOUR_IMPORTED_STATUS
        else ["WAIT_NATIVE_CHILD_CLOSEOUT:DUAL_CONTOUR_MAKE_CONTRACTS_FAIL"],
        "checks": checks,
        "parent_direct_external_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "domain_authority_granted": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--native-closeout", type=Path, help="optional native closeout JSON path")
    parser.add_argument("--out", type=Path, help="optional path for the generated A18 receipt")
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
