#!/usr/bin/env python3
"""V3.7 A19 Market native bridge closeout gate.

This gate is truth-led. It passes when SRF preserves the inactive, proposal-only
Market bridge boundary and honestly projects the current native Market state as
``WAIT_SRF`` without claiming global health, trading authority, or a native
child closeout that does not exist.
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
    MARKET_IMPORTED_STATUS,
    MARKET_OFFLINE_WAIT_STATUS,
    MARKET_REJECTED_STATUS,
    MARKET_WAIT_STATUS,
    MarketBridgeStatus,
    MarketCloseoutError,
    build_market_bridge_health_projection,
    build_market_closeout_import_receipt,
    build_market_science_request,
    import_market_observation_packet,
    verify_native_bridge_child_request,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A19"
CHILD_REQUEST_PATH: Final[Path] = (
    REPO_ROOT / "docs" / "child-missions" / "market" / "market-bridge-child-request.json"
)
NATIVE_BOOTSTRAP_EVIDENCE_PATH: Final[Path] = (
    REPO_ROOT / "docs" / "child-missions" / "market" / "market-native-bootstrap-evidence.json"
)
FIXTURE_KEYS: Final[dict[str, bytes]] = {
    "srf-market-child-fixture-key": b"srf-market-child-fixture-key"
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
    env_path = os.environ.get("SRL_A19_NATIVE_CLOSEOUT_PATH")
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
    if child_request.get("target_project") != "crypto-market-lab":
        failures.append("target_project drifted")
    if child_request.get("native_closeout_status") != MARKET_WAIT_STATUS:
        failures.append("child request no longer waits for native closeout")
    if (
        child_request.get("parent_direct_external_writes") != 0
        or child_request.get("canonical_writes") != 0
        or child_request.get("live_actions") != 0
        or child_request.get("grants_authority") is not False
        or child_request.get("activation_state") != "INACTIVE"
    ):
        failures.append("child request is not inactive and authority-negative")
    return {
        "check_id": "A19-01-hash-bound-child-request",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "child request signature, source ancestry, target and authority boundary are valid",
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
    if bootstrap_evidence.get("trading_allowed") is not False:
        failures.append("bootstrap evidence permits trading")
    if bootstrap_evidence.get("canonical_mutation_allowed") is not False:
        failures.append("bootstrap evidence permits canonical mutation")
    return {
        "check_id": "A19-02-native-bootstrap-evidence",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else (
            "Market native bootstrap evidence is preserved as "
            f"{bootstrap_evidence.get('organism_status')}"
        ),
        "native_bootstrap_status": bootstrap_evidence.get("status"),
        "organism_status": bootstrap_evidence.get("organism_status"),
        "next_gate": bootstrap_evidence.get("next_gate"),
    }


def _check_inactive_bridge(
    child_request: dict[str, Any],
    bootstrap_evidence: dict[str, Any],
) -> dict[str, Any]:
    try:
        market_head = _require_str(child_request.get("target_head"), "target_head")
        request = build_market_science_request(
            objective="evaluate public synthetic volatility feature stability",
            market_head=market_head,
            evidence_refs=("sha256:" + "1" * 64,),
        )
        observation_id = "sha256:" + "2" * 64
        result = import_market_observation_packet(
            {
                "schema_version": "MarketScienceObservationPacket/v1",
                "observation_id": observation_id,
                "request_id": request["request_id"],
                "market_head": market_head,
                "payload": {"finding": "synthetic C3 proposal only"},
                "classification": "D0",
                "semantic_class": "C3_PROPOSAL",
                "authority_claimed": False,
                "trading_action": None,
            },
            expected_market_head=market_head,
            seen_observation_ids=frozenset(),
        )
        projection = build_market_bridge_health_projection(
            market_gate=_require_str(bootstrap_evidence.get("organism_status"), "organism_status"),
            market_head=market_head,
        )
    except Exception as exc:
        return {
            "check_id": "A19-03-inactive-bridge-safety",
            "status": "FAIL",
            "detail": str(exc),
        }
    failures: list[str] = []
    if request.get("grants_authority") is not False or result.get("grants_authority") is not False:
        failures.append("request/result grants authority")
    if projection.get("trading_allowed") is not False or projection.get("live_actions") != 0:
        failures.append("health projection permits live Market action")
    if bootstrap_evidence.get("organism_status") != "GREEN":
        if projection.get("status") != MarketBridgeStatus.WAIT_RUNTIME_HEALTH.value:
            failures.append("non-GREEN Market evidence did not project WAIT_RUNTIME_HEALTH")
    return {
        "check_id": "A19-03-inactive-bridge-safety",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "inactive Market bridge rejects authority/trading and projects non-GREEN as WAIT",
        "request_id": request["request_id"],
        "result_id": result["result_id"],
        "bridge_projection_receipt_id": projection["receipt_id"],
        "bridge_projection_status": projection["status"],
    }


def _check_import_projection(
    child_request: dict[str, Any],
    bootstrap_evidence: dict[str, Any],
    native_closeout: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        import_receipt = build_market_closeout_import_receipt(
            child_request=child_request,
            native_closeout=native_closeout,
            key_material_by_id=FIXTURE_KEYS,
            native_bootstrap_evidence=bootstrap_evidence,
        )
    except MarketCloseoutError as exc:
        return {
            "check_id": "A19-04-native-closeout-import",
            "status": "FAIL",
            "detail": str(exc),
            "import_receipt": None,
        }
    expected_status = MARKET_IMPORTED_STATUS if native_closeout is not None else MARKET_WAIT_STATUS
    failures: list[str] = []
    if import_receipt.get("status") != expected_status:
        failures.append(f"import receipt status is {import_receipt.get('status')}")
    if import_receipt.get("srf_offline_status") != MARKET_OFFLINE_WAIT_STATUS:
        failures.append("SRF offline status is not WAIT_SRF")
    if (
        import_receipt.get("parent_direct_external_writes") != 0
        or import_receipt.get("market_writes") != 0
        or import_receipt.get("canonical_writes") != 0
        or import_receipt.get("live_actions") != 0
        or import_receipt.get("trading_allowed") is not False
        or import_receipt.get("grants_authority") is not False
        or import_receipt.get("scientific_authority_granted") is not False
        or import_receipt.get("market_activation_authority_granted") is not False
    ):
        failures.append("import receipt is not authority-negative")
    return {
        "check_id": "A19-04-native-closeout-import",
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
        _check_import_projection(child_request, bootstrap_evidence, native_closeout),
    ]
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    import_receipt = checks[-1].get("import_receipt")
    terminal_state = (
        import_receipt.get("status") if isinstance(import_receipt, dict) else MARKET_REJECTED_STATUS
    )
    waits = []
    if terminal_state != MARKET_IMPORTED_STATUS:
        waits.append("WAIT_NATIVE_CHILD_CLOSEOUT:MARKET_NATIVE_BRIDGE_CLOSEOUT_ABSENT")
    if bootstrap_evidence.get("organism_status") != "GREEN":
        waits.append("WAIT_RUNTIME_HEALTH:MARKET_ORGANISM_NOT_GREEN")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": status,
        "terminal_state": terminal_state,
        "srf_offline_status": MARKET_OFFLINE_WAIT_STATUS,
        "stage_closure": "A19_ACTIVE_NATIVE_CLOSEOUT_IMPORTED"
        if terminal_state == MARKET_IMPORTED_STATUS and status == "PASS"
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
        "market_writes": 0,
        "canonical_writes": 0,
        "live_actions": 0,
        "trading_allowed": False,
        "grants_authority": False,
        "scientific_authority_granted": False,
        "market_activation_authority_granted": False,
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
    parser.add_argument("--out", type=Path, help="optional path for the generated A19 receipt")
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
