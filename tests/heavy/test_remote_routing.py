from __future__ import annotations

from typing import cast

import pytest

from srl.runtime import (
    BudgetReceipt,
    ComputeNodeManifest,
    HeavyCapabilityStatus,
    HeavyRemoteJobSpec,
    RemoteRoutingError,
    build_heavy_capability_routing_bundle,
    build_signed_remote_job_packet,
    default_heavy_profiles,
    route_heavy_job,
    verify_remote_job_packet,
)


def _profile_image(profile_id: str) -> str:
    profile = next(
        profile for profile in default_heavy_profiles() if profile.profile_id == profile_id
    )
    return profile.image_digest


def _job(
    *,
    profile_id: str = "heavy.petsc",
    capability: str = "petsc",
    architecture: str = "linux-x86_64",
    budget_units: int = 0,
    image_digest: str | None = None,
) -> HeavyRemoteJobSpec:
    return HeavyRemoteJobSpec(
        job_id="job-1",
        profile_id=profile_id,
        required_capability=capability,
        image_digest=image_digest or _profile_image(profile_id),
        architecture=architecture,
        budget_units=budget_units,
        checkpoint_interval_steps=10,
        input_digest="sha256:" + "0" * 64,
    )


def _node(
    *,
    capabilities: tuple[str, ...] = ("petsc",),
    architecture: str = "linux-x86_64",
    image_digests: tuple[str, ...] | None = None,
    revoked: tuple[str, ...] = (),
    online: bool = True,
) -> ComputeNodeManifest:
    return ComputeNodeManifest(
        node_id="fixture-node",
        architecture=architecture,
        capabilities=capabilities,
        image_digests=image_digests or (_profile_image("heavy.petsc"),),
        revoked_image_digests=revoked,
        online=online,
    )


def test_heavy_bundle_parks_absent_local_and_remote_capabilities() -> None:
    bundle = build_heavy_capability_routing_bundle()
    waits = set(cast(list[str], bundle["wait_profile_ids"]))

    assert {"heavy.petsc", "heavy.fenicsx", "heavy.sage", "oracle.wolfram"} <= waits
    assert bundle["active_local_profile_ids"] == []
    assert bundle["routable_remote_profile_ids"] == []
    assert bundle["implicit_spend"] == 0
    assert bundle["unbounded_local_runs"] == 0
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


def test_compatible_fixture_node_routes_job_without_launching() -> None:
    decision = route_heavy_job(
        _job(),
        node_manifest=_node(),
        budget_receipt=None,
    )

    assert decision["status"] == HeavyCapabilityStatus.ROUTABLE_REMOTE.value
    assert decision["checkpoint_interval_steps"] == 10
    assert decision["implicit_spend"] == 0
    assert decision["unbounded_local_runs"] == 0
    assert decision["canonical_writes"] == 0
    assert decision["grants_authority"] is False


def test_absent_node_returns_wait_compute_node() -> None:
    decision = route_heavy_job(_job(), node_manifest=None, budget_receipt=None)

    assert decision["status"] == HeavyCapabilityStatus.WAIT_COMPUTE_NODE.value
    assert decision["reason"] == "node absent or offline"


def test_architecture_mismatch_waits_for_compute_node() -> None:
    decision = route_heavy_job(
        _job(architecture="linux-aarch64"),
        node_manifest=_node(),
        budget_receipt=None,
    )

    assert decision["status"] == HeavyCapabilityStatus.WAIT_COMPUTE_NODE.value
    assert decision["reason"] == "architecture mismatch"


def test_revoked_image_is_rejected() -> None:
    image = _profile_image("heavy.petsc")
    decision = route_heavy_job(
        _job(image_digest=image),
        node_manifest=_node(revoked=(image,)),
        budget_receipt=None,
    )

    assert decision["status"] == HeavyCapabilityStatus.REJECTED.value
    assert decision["reason"] == "revoked image"


def test_budget_zero_rejects_paid_oracle() -> None:
    decision = route_heavy_job(
        _job(
            profile_id="oracle.wolfram",
            capability="wolfram",
            budget_units=1,
            image_digest=_profile_image("oracle.wolfram"),
        ),
        node_manifest=_node(
            capabilities=("wolfram",),
            image_digests=(_profile_image("oracle.wolfram"),),
        ),
        budget_receipt=BudgetReceipt(
            receipt_id="budget-1",
            remaining_units=0,
            credential_scope="wolfram-fixture",
        ),
    )

    assert decision["status"] == HeavyCapabilityStatus.WAIT_AUTHORITY.value
    assert decision["reason"] == "budget exhausted"


def test_signed_remote_job_packet_verifies_and_detects_tamper() -> None:
    packet = build_signed_remote_job_packet(
        _job(),
        signer_key_id="fixture-key",
        key_material=b"fixture-secret",
    )

    job = verify_remote_job_packet(packet, key_material_by_id={"fixture-key": b"fixture-secret"})
    assert job["job_id"] == "job-1"

    tampered = dict(packet)
    tampered["job"] = {**cast(dict[str, object], packet["job"]), "job_id": "changed"}
    with pytest.raises(RemoteRoutingError, match="signature"):
        verify_remote_job_packet(tampered, key_material_by_id={"fixture-key": b"fixture-secret"})


def test_remote_job_requires_positive_checkpoint_interval() -> None:
    with pytest.raises(RemoteRoutingError, match="checkpoint"):
        HeavyRemoteJobSpec(
            job_id="job-1",
            profile_id="heavy.petsc",
            required_capability="petsc",
            image_digest=_profile_image("heavy.petsc"),
            architecture="linux-x86_64",
            budget_units=0,
            checkpoint_interval_steps=0,
            input_digest="sha256:" + "0" * 64,
        )
