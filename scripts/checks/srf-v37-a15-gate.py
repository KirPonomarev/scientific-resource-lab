#!/usr/bin/env python3
"""V3.7 A15 heavy compute target readiness gate.

This gate deliberately does not launch, provision or mutate a compute node.
It proves the SRF-side contract is fail-closed while the protected external
target remains absent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.contracts.ids import object_id  # noqa: E402
from srl.runtime import (  # noqa: E402
    A15_REQUIRED_PROFILE_IDS,
    ComputeNodeManifest,
    HeavyCapabilityStatus,
    HeavyRemoteJobSpec,
    build_heavy_capability_routing_bundle,
    default_heavy_profiles,
    route_heavy_job,
)

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A15"
CHECKPOINT_INTERVAL_STEPS: Final[int] = 25
OPERATOR_ACTION_PATH: Final[Path] = (
    REPO_ROOT / "docs" / "target-binding" / "a15-heavy-compute-operator-action.json"
)


def _profiles_by_id() -> dict[str, Any]:
    return {profile.profile_id: profile for profile in default_heavy_profiles()}


def _required_images() -> tuple[str, ...]:
    profiles = _profiles_by_id()
    return tuple(profiles[profile_id].image_digest for profile_id in A15_REQUIRED_PROFILE_IDS)


def _required_capabilities() -> tuple[str, ...]:
    capabilities: list[str] = []
    profiles = _profiles_by_id()
    for profile_id in A15_REQUIRED_PROFILE_IDS:
        capabilities.extend(profiles[profile_id].remote_capabilities)
    return tuple(dict.fromkeys(capabilities))


def _job(profile_id: str) -> HeavyRemoteJobSpec:
    profile = _profiles_by_id()[profile_id]
    capability = profile.remote_capabilities[0]
    return HeavyRemoteJobSpec(
        job_id=f"a15-{profile_id.replace('.', '-').replace('_', '-')}",
        profile_id=profile_id,
        required_capability=capability,
        image_digest=profile.image_digest,
        architecture=profile.architecture,
        budget_units=0,
        checkpoint_interval_steps=CHECKPOINT_INTERVAL_STEPS,
        input_digest="sha256:" + "15" * 32,
    )


def _compatible_fixture_node() -> ComputeNodeManifest:
    return ComputeNodeManifest(
        node_id="a15-fixture-node-no-launch",
        architecture="linux-x86_64",
        capabilities=_required_capabilities(),
        image_digests=_required_images(),
        online=True,
    )


def _check_absent_target_wait() -> dict[str, Any]:
    bundle = build_heavy_capability_routing_bundle()
    profiles = {
        cast(dict[str, Any], item)["profile_id"]: cast(dict[str, Any], item)
        for item in cast(list[Any], bundle["profiles"])
    }
    failures: list[str] = []
    for profile_id in A15_REQUIRED_PROFILE_IDS:
        profile = profiles.get(profile_id)
        if not isinstance(profile, dict):
            failures.append(f"{profile_id} missing from bundle")
            continue
        if profile.get("status") != HeavyCapabilityStatus.WAIT_COMPUTE_NODE.value:
            failures.append(f"{profile_id} did not wait for compute node")
        if profile.get("requires_compute_target") is not True:
            failures.append(f"{profile_id} is not compute-target-bound")
    if bundle.get("active_local_profile_ids") != []:
        failures.append("heavy profiles became ACTIVE_LOCAL without compute target")
    if bundle.get("routable_remote_profile_ids") != []:
        failures.append("heavy profiles became routable without compute target")
    if bundle.get("canonical_writes") != 0 or bundle.get("grants_authority") is not False:
        failures.append("routing bundle is not authority-negative")
    return {
        "check_id": "A15-01-absent-compute-target-fail-closed",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "mandatory heavy profiles remain WAIT_COMPUTE_NODE with no local fallback",
        "bundle_id": bundle.get("bundle_id"),
        "required_profiles": list(A15_REQUIRED_PROFILE_IDS),
    }


def _check_fixture_remote_routing_no_launch() -> dict[str, Any]:
    node = _compatible_fixture_node()
    decisions = [
        route_heavy_job(_job(profile_id), node_manifest=node, budget_receipt=None)
        for profile_id in A15_REQUIRED_PROFILE_IDS
    ]
    failures: list[str] = []
    for decision in decisions:
        if decision.get("status") != HeavyCapabilityStatus.ROUTABLE_REMOTE.value:
            failures.append(f"{decision.get('profile_id')} did not route on fixture node")
        if decision.get("checkpoint_interval_steps") != CHECKPOINT_INTERVAL_STEPS:
            failures.append(f"{decision.get('profile_id')} checkpoint interval drifted")
        if (
            decision.get("implicit_spend") != 0
            or decision.get("unbounded_local_runs") != 0
            or decision.get("canonical_writes") != 0
            or decision.get("grants_authority") is not False
        ):
            failures.append(f"{decision.get('profile_id')} routing decision is not inert")
    return {
        "check_id": "A15-02-compatible-fixture-node-routes-without-launch",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "fixture node proves routing contract only; no jobs launched",
        "node_manifest": node.to_dict(),
        "decision_ids": [decision.get("decision_id") for decision in decisions],
    }


def _check_negative_routing_guards() -> dict[str, Any]:
    profile_id = A15_REQUIRED_PROFILE_IDS[0]
    image = _profiles_by_id()[profile_id].image_digest
    base = _compatible_fixture_node()
    cases = {
        "offline": ComputeNodeManifest(
            node_id="a15-offline",
            architecture=base.architecture,
            capabilities=base.capabilities,
            image_digests=base.image_digests,
            online=False,
        ),
        "architecture_mismatch": ComputeNodeManifest(
            node_id="a15-arm",
            architecture="linux-aarch64",
            capabilities=base.capabilities,
            image_digests=base.image_digests,
        ),
        "capability_missing": ComputeNodeManifest(
            node_id="a15-missing-cap",
            architecture=base.architecture,
            capabilities=tuple(cap for cap in base.capabilities if cap != "petsc"),
            image_digests=base.image_digests,
        ),
        "image_missing": ComputeNodeManifest(
            node_id="a15-missing-image",
            architecture=base.architecture,
            capabilities=base.capabilities,
            image_digests=tuple(digest for digest in base.image_digests if digest != image),
        ),
        "revoked_image": ComputeNodeManifest(
            node_id="a15-revoked",
            architecture=base.architecture,
            capabilities=base.capabilities,
            image_digests=base.image_digests,
            revoked_image_digests=(image,),
        ),
    }
    expected = {
        "offline": HeavyCapabilityStatus.WAIT_COMPUTE_NODE.value,
        "architecture_mismatch": HeavyCapabilityStatus.WAIT_COMPUTE_NODE.value,
        "capability_missing": HeavyCapabilityStatus.WAIT_COMPUTE_NODE.value,
        "image_missing": HeavyCapabilityStatus.WAIT_COMPUTE_NODE.value,
        "revoked_image": HeavyCapabilityStatus.REJECTED.value,
    }
    decisions = {
        name: route_heavy_job(_job(profile_id), node_manifest=node, budget_receipt=None)
        for name, node in cases.items()
    }
    failures = [
        f"{name} yielded {decision.get('status')}"
        for name, decision in decisions.items()
        if decision.get("status") != expected[name]
    ]
    return {
        "check_id": "A15-03-negative-node-and-image-guards",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "offline, architecture, capability, image and revocation guards fail closed",
        "decisions": decisions,
    }


def _check_operator_action() -> dict[str, Any]:
    failures: list[str] = []
    if not OPERATOR_ACTION_PATH.exists():
        failures.append("operator action file missing")
        action: dict[str, Any] = {}
    else:
        action = json.loads(OPERATOR_ACTION_PATH.read_text(encoding="utf-8"))
        if not isinstance(action, dict):
            failures.append("operator action is not a JSON object")
            action = {}
    if action.get("schema_version") != "ProtectedOperatorAction/v1":
        failures.append("operator action schema mismatch")
    if action.get("action_id") != "A15_PROVISION_HEAVY_COMPUTE_TARGET":
        failures.append("operator action id mismatch")
    if action.get("authority_required") is not True or action.get("grants_authority") is not False:
        failures.append("operator action authority fields drifted")
    if action.get("required_profiles") != list(A15_REQUIRED_PROFILE_IDS):
        failures.append("operator action required profiles drifted")
    return {
        "check_id": "A15-04-protected-operator-action-recorded",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "operator action records exact protected work needed for real A15 activation",
        "operator_action_path": str(OPERATOR_ACTION_PATH.relative_to(REPO_ROOT)),
        "operator_action_hash": object_id(action) if action else None,
    }


def _build_stage_receipt() -> dict[str, Any]:
    checks = [
        _check_absent_target_wait(),
        _check_fixture_remote_routing_no_launch(),
        _check_negative_routing_guards(),
        _check_operator_action(),
    ]
    failures = [check for check in checks if check["status"] != "PASS"]
    result = "FAIL" if failures else "PASS"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "result": result,
        "stage_closure": "A15_WAIT_COMPUTE_NODE" if result == "PASS" else "A15_OPEN",
        "active_packs": [],
        "routable_fixture_profiles": list(A15_REQUIRED_PROFILE_IDS) if result == "PASS" else [],
        "remaining_internal_waits": [],
        "remaining_external_waits": ["WAIT_COMPUTE_NODE:A15_PROVISION_HEAVY_COMPUTE_TARGET"],
        "checks": checks,
        "live_actions": 0,
        "remote_launches": 0,
        "implicit_spend": 0,
        "unbounded_local_runs": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["routing_contract_sha256"] = (
        "sha256:" + hashlib.sha256(dumps({"checks": checks})).hexdigest()
    )
    receipt["receipt_id"] = object_id(receipt)
    return receipt


def main() -> int:
    receipt = _build_stage_receipt()
    sys.stdout.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
