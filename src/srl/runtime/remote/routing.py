"""WAIT-safe routing for heavy, remote and budgeted oracle capabilities."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import shutil
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

HEAVY_CAPABILITY_ROUTING_BUNDLE_SCHEMA_VERSION: Final[str] = "HeavyCapabilityRoutingBundle/v1"
HEAVY_REMOTE_JOB_PACKET_SCHEMA_VERSION: Final[str] = "HeavyRemoteJobPacket/v1"
HEAVY_REMOTE_ROUTING_DECISION_SCHEMA_VERSION: Final[str] = "HeavyRemoteRoutingDecision/v1"

_TEST_HMAC_SHA256: Final[str] = "test-hmac-sha256"
_WAIT_RUNTIME: Final[str] = "runtime_or_node_capability_missing"
_WAIT_AUTHORITY: Final[str] = "credential_or_budget_authority_missing"
A15_REQUIRED_PROFILE_IDS: Final[tuple[str, ...]] = (
    "heavy.petsc",
    "heavy.fenicsx",
    "heavy.pymor",
    "heavy.scikit_fem",
    "heavy.dedalus",
    "heavy.sage",
)


class RemoteRoutingError(ContractError):
    """Raised when heavy routing inputs violate the S18 contract."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class HeavyCapabilityStatus(StrEnum):
    """Heavy capability routing status."""

    ACTIVE_LOCAL = "ACTIVE_LOCAL"
    ROUTABLE_REMOTE = "ROUTABLE_REMOTE"
    WAIT_CAPABILITY = "WAIT_CAPABILITY"
    WAIT_COMPUTE_NODE = "WAIT_COMPUTE_NODE"
    WAIT_AUTHORITY = "WAIT_AUTHORITY"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class HeavyProfile:
    """One PDE/HPC/Sage/oracle capability profile."""

    profile_id: str
    family: str
    import_names: tuple[str, ...]
    executable_names: tuple[str, ...]
    remote_capabilities: tuple[str, ...]
    image_digest: str
    architecture: str
    tiny_local_allowed: bool
    paid_oracle: bool
    checkpoint_policy: str
    requires_compute_target: bool = True
    status: HeavyCapabilityStatus = HeavyCapabilityStatus.WAIT_COMPUTE_NODE
    reason: str = _WAIT_RUNTIME

    def __post_init__(self) -> None:
        for field in ("profile_id", "family", "image_digest", "architecture", "checkpoint_policy"):
            _require_non_empty(getattr(self, field), field)
        for field in ("import_names", "executable_names", "remote_capabilities"):
            _require_tuple(getattr(self, field), field, allow_empty=True)
        if not self.import_names and not self.executable_names and not self.remote_capabilities:
            raise RemoteRoutingError(
                "profile must declare an import, executable or remote capability"
            )
        if isinstance(self.tiny_local_allowed, bool) is False:
            raise RemoteRoutingError("tiny_local_allowed must be a bool")
        if isinstance(self.paid_oracle, bool) is False:
            raise RemoteRoutingError("paid_oracle must be a bool")
        if isinstance(self.requires_compute_target, bool) is False:
            raise RemoteRoutingError("requires_compute_target must be a bool")

    def with_status(self, status: HeavyCapabilityStatus, reason: str) -> HeavyProfile:
        """Return this profile with changed routing status."""
        return HeavyProfile(
            profile_id=self.profile_id,
            family=self.family,
            import_names=self.import_names,
            executable_names=self.executable_names,
            remote_capabilities=self.remote_capabilities,
            image_digest=self.image_digest,
            architecture=self.architecture,
            tiny_local_allowed=self.tiny_local_allowed,
            paid_oracle=self.paid_oracle,
            checkpoint_policy=self.checkpoint_policy,
            requires_compute_target=self.requires_compute_target,
            status=status,
            reason=reason,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible profile card."""
        return {
            "profile_id": self.profile_id,
            "family": self.family,
            "import_names": list(self.import_names),
            "executable_names": list(self.executable_names),
            "remote_capabilities": list(self.remote_capabilities),
            "image_digest": self.image_digest,
            "architecture": self.architecture,
            "tiny_local_allowed": self.tiny_local_allowed,
            "paid_oracle": self.paid_oracle,
            "checkpoint_policy": self.checkpoint_policy,
            "requires_compute_target": self.requires_compute_target,
            "status": self.status.value,
            "reason": self.reason,
            "canonical_writes": 0,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class ComputeNodeManifest:
    """A bounded fixture compute-node capability manifest."""

    node_id: str
    architecture: str
    capabilities: tuple[str, ...]
    image_digests: tuple[str, ...]
    revoked_image_digests: tuple[str, ...] = ()
    online: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.node_id, "node_id")
        _require_non_empty(self.architecture, "architecture")
        _require_tuple(self.capabilities, "capabilities", allow_empty=False)
        _require_tuple(self.image_digests, "image_digests", allow_empty=False)
        _require_tuple(self.revoked_image_digests, "revoked_image_digests", allow_empty=True)
        if isinstance(self.online, bool) is False:
            raise RemoteRoutingError("online must be a bool")

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible node data."""
        return {
            "node_id": self.node_id,
            "architecture": self.architecture,
            "capabilities": list(self.capabilities),
            "image_digests": list(self.image_digests),
            "revoked_image_digests": list(self.revoked_image_digests),
            "online": self.online,
        }


@dataclass(frozen=True)
class BudgetReceipt:
    """Budget and credential authority evidence for remote execution."""

    receipt_id: str
    remaining_units: int
    credential_scope: str

    def __post_init__(self) -> None:
        _require_non_empty(self.receipt_id, "receipt_id")
        _require_non_empty(self.credential_scope, "credential_scope")
        if self.remaining_units < 0:
            raise RemoteRoutingError("remaining_units must be non-negative")


@dataclass(frozen=True)
class HeavyRemoteJobSpec:
    """One signed remote job request before native executor intake."""

    job_id: str
    profile_id: str
    required_capability: str
    image_digest: str
    architecture: str
    budget_units: int
    checkpoint_interval_steps: int
    input_digest: str

    def __post_init__(self) -> None:
        for field in (
            "job_id",
            "profile_id",
            "required_capability",
            "image_digest",
            "architecture",
            "input_digest",
        ):
            _require_non_empty(getattr(self, field), field)
        if self.budget_units < 0:
            raise RemoteRoutingError("budget_units must be non-negative")
        if self.checkpoint_interval_steps <= 0:
            raise RemoteRoutingError("checkpoint_interval_steps must be positive")

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-compatible job data."""
        return {
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "required_capability": self.required_capability,
            "image_digest": self.image_digest,
            "architecture": self.architecture,
            "budget_units": self.budget_units,
            "checkpoint_interval_steps": self.checkpoint_interval_steps,
            "input_digest": self.input_digest,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def default_heavy_profiles() -> tuple[HeavyProfile, ...]:
    """Return S18 heavy capability profiles in deterministic order."""
    return (
        _profile("heavy.petsc", "pde_hpc", ("petsc4py",), (), ("petsc",), True),
        _profile("heavy.fenicsx", "pde_hpc", ("dolfinx",), (), ("fenicsx",), True),
        _profile("heavy.pymor", "model_reduction", ("pymor",), (), ("pymor",), True),
        _profile("heavy.scikit_fem", "finite_elements", ("skfem",), (), ("scikit_fem",), True),
        _profile("heavy.dedalus", "spectral_pde", ("dedalus",), (), ("dedalus",), True),
        _profile("heavy.modulus", "neural_operator", ("modulus",), (), ("accelerator",), False),
        _profile("heavy.neuralop", "neural_operator", ("neuralop",), (), ("accelerator",), False),
        _profile("heavy.sage", "exact_math", ("sageall",), ("sage",), ("sage",), True),
        _profile(
            "oracle.wolfram",
            "paid_oracle",
            ("wolframclient",),
            ("wolframscript",),
            ("wolfram",),
            False,
            paid_oracle=True,
        ),
    )


def build_heavy_capability_routing_bundle(
    *,
    profiles: tuple[HeavyProfile, ...] | None = None,
    node_manifest: ComputeNodeManifest | None = None,
    budget_receipt: BudgetReceipt | None = None,
) -> dict[str, object]:
    """Build deterministic S18 heavy capability routing status."""
    assessed = tuple(
        _assess_profile(profile, node_manifest=node_manifest, budget_receipt=budget_receipt)
        for profile in (profiles or default_heavy_profiles())
    )
    body: dict[str, object] = {
        "schema_version": HEAVY_CAPABILITY_ROUTING_BUNDLE_SCHEMA_VERSION,
        "profiles": [profile.to_dict() for profile in assessed],
        "active_local_profile_ids": [
            profile.profile_id
            for profile in assessed
            if profile.status is HeavyCapabilityStatus.ACTIVE_LOCAL
        ],
        "routable_remote_profile_ids": [
            profile.profile_id
            for profile in assessed
            if profile.status is HeavyCapabilityStatus.ROUTABLE_REMOTE
        ],
        "wait_profile_ids": [
            profile.profile_id
            for profile in assessed
            if profile.status
            in {
                HeavyCapabilityStatus.WAIT_CAPABILITY,
                HeavyCapabilityStatus.WAIT_COMPUTE_NODE,
                HeavyCapabilityStatus.WAIT_AUTHORITY,
            }
        ],
        "node_manifest": node_manifest.to_dict() if node_manifest is not None else None,
        "implicit_spend": 0,
        "unbounded_local_runs": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def route_heavy_job(  # noqa: PLR0911
    job: HeavyRemoteJobSpec,
    *,
    profiles: tuple[HeavyProfile, ...] | None = None,
    node_manifest: ComputeNodeManifest | None,
    budget_receipt: BudgetReceipt | None,
) -> dict[str, object]:
    """Return a WAIT-safe routing decision for one heavy remote job."""
    profile_map = {
        profile.profile_id: profile for profile in (profiles or default_heavy_profiles())
    }
    profile = profile_map.get(job.profile_id)
    if profile is None:
        return _decision(job, HeavyCapabilityStatus.WAIT_CAPABILITY, "unknown profile")
    if profile.paid_oracle and budget_receipt is None:
        return _decision(job, HeavyCapabilityStatus.WAIT_AUTHORITY, _WAIT_AUTHORITY)
    if job.budget_units > 0 and budget_receipt is None:
        return _decision(job, HeavyCapabilityStatus.WAIT_AUTHORITY, _WAIT_AUTHORITY)
    if budget_receipt is not None and job.budget_units > budget_receipt.remaining_units:
        return _decision(job, HeavyCapabilityStatus.WAIT_AUTHORITY, "budget exhausted")
    if node_manifest is None or not node_manifest.online:
        return _decision(job, HeavyCapabilityStatus.WAIT_COMPUTE_NODE, "node absent or offline")
    if job.image_digest in node_manifest.revoked_image_digests:
        return _decision(job, HeavyCapabilityStatus.REJECTED, "revoked image")
    if job.architecture != node_manifest.architecture:
        return _decision(job, HeavyCapabilityStatus.WAIT_COMPUTE_NODE, "architecture mismatch")
    if job.required_capability not in node_manifest.capabilities:
        return _decision(job, HeavyCapabilityStatus.WAIT_COMPUTE_NODE, "capability missing")
    if job.image_digest not in node_manifest.image_digests:
        return _decision(job, HeavyCapabilityStatus.WAIT_COMPUTE_NODE, "image unavailable")
    return _decision(job, HeavyCapabilityStatus.ROUTABLE_REMOTE, "compatible remote route")


def build_signed_remote_job_packet(
    job: HeavyRemoteJobSpec,
    *,
    signer_key_id: str,
    key_material: bytes,
) -> dict[str, object]:
    """Build a deterministic test-HMAC signed remote job packet."""
    _require_non_empty(signer_key_id, "signer_key_id")
    if not key_material:
        raise RemoteRoutingError("key_material must not be empty")
    job_bytes = dumps(job.to_dict())
    signature = hmac.new(key_material, job_bytes, hashlib.sha256).hexdigest()
    packet: dict[str, object] = {
        "schema_version": HEAVY_REMOTE_JOB_PACKET_SCHEMA_VERSION,
        "job": job.to_dict(),
        "signer_key_id": signer_key_id,
        "signature_algorithm": _TEST_HMAC_SHA256,
        "signature": signature,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    packet["packet_id"] = "sha256:" + hashlib.sha256(dumps(packet)).hexdigest()
    return packet


def verify_remote_job_packet(
    packet: dict[str, object],
    *,
    key_material_by_id: dict[str, bytes],
) -> dict[str, object]:
    """Verify a deterministic test-HMAC packet and return its job."""
    if packet.get("schema_version") != HEAVY_REMOTE_JOB_PACKET_SCHEMA_VERSION:
        raise RemoteRoutingError("unexpected packet schema_version")
    if packet.get("signature_algorithm") != _TEST_HMAC_SHA256:
        raise RemoteRoutingError("unsupported signature algorithm")
    signer_key_id = packet.get("signer_key_id")
    signature = packet.get("signature")
    job = packet.get("job")
    if not isinstance(signer_key_id, str) or not signer_key_id:
        raise RemoteRoutingError("signer_key_id must be a non-empty string")
    if not isinstance(signature, str) or not signature:
        raise RemoteRoutingError("signature must be a non-empty string")
    if not isinstance(job, dict):
        raise RemoteRoutingError("job must be an object")
    key_material = key_material_by_id.get(signer_key_id)
    if key_material is None:
        raise RemoteRoutingError("unknown signer key")
    expected = hmac.new(key_material, dumps(job), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise RemoteRoutingError("signature verification failed")
    return job


def _profile(  # noqa: PLR0913, PLR0917
    profile_id: str,
    family: str,
    import_names: tuple[str, ...],
    executable_names: tuple[str, ...],
    remote_capabilities: tuple[str, ...],
    tiny_local_allowed: bool,
    *,
    paid_oracle: bool = False,
    requires_compute_target: bool = True,
) -> HeavyProfile:
    return HeavyProfile(
        profile_id=profile_id,
        family=family,
        import_names=import_names,
        executable_names=executable_names,
        remote_capabilities=remote_capabilities,
        image_digest=f"sha256:{hashlib.sha256(profile_id.encode()).hexdigest()}",
        architecture="linux-x86_64",
        tiny_local_allowed=tiny_local_allowed,
        paid_oracle=paid_oracle,
        checkpoint_policy="checkpoint_by_deterministic_step_count",
        requires_compute_target=requires_compute_target,
    )


def _assess_profile(  # noqa: PLR0911
    profile: HeavyProfile,
    *,
    node_manifest: ComputeNodeManifest | None,
    budget_receipt: BudgetReceipt | None,
) -> HeavyProfile:
    if profile.paid_oracle and budget_receipt is None:
        return profile.with_status(HeavyCapabilityStatus.WAIT_AUTHORITY, _WAIT_AUTHORITY)
    missing_imports = [
        name for name in profile.import_names if importlib.util.find_spec(name) is None
    ]
    missing_executables = [name for name in profile.executable_names if shutil.which(name) is None]
    if (
        not profile.requires_compute_target
        and not missing_imports
        and not missing_executables
        and profile.tiny_local_allowed
    ):
        return profile.with_status(
            HeavyCapabilityStatus.ACTIVE_LOCAL,
            "tiny local runtime importable under bounded profile",
        )
    if node_manifest is None or not node_manifest.online:
        return profile.with_status(
            HeavyCapabilityStatus.WAIT_COMPUTE_NODE,
            "node absent or offline",
        )
    if profile.image_digest in node_manifest.revoked_image_digests:
        return profile.with_status(HeavyCapabilityStatus.REJECTED, "revoked image")
    if profile.architecture != node_manifest.architecture:
        return profile.with_status(HeavyCapabilityStatus.WAIT_COMPUTE_NODE, "architecture mismatch")
    if any(
        capability not in node_manifest.capabilities for capability in profile.remote_capabilities
    ):
        return profile.with_status(HeavyCapabilityStatus.WAIT_COMPUTE_NODE, "capability missing")
    if profile.image_digest not in node_manifest.image_digests:
        return profile.with_status(HeavyCapabilityStatus.WAIT_COMPUTE_NODE, "image unavailable")
    return profile.with_status(HeavyCapabilityStatus.ROUTABLE_REMOTE, "compatible remote route")


def _decision(
    job: HeavyRemoteJobSpec,
    status: HeavyCapabilityStatus,
    reason: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": HEAVY_REMOTE_ROUTING_DECISION_SCHEMA_VERSION,
        "job_id": job.job_id,
        "profile_id": job.profile_id,
        "status": status.value,
        "reason": reason,
        "checkpoint_interval_steps": job.checkpoint_interval_steps,
        "implicit_spend": 0,
        "unbounded_local_runs": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["decision_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def _require_tuple(values: object, field: str, *, allow_empty: bool) -> None:
    if not isinstance(values, tuple):
        raise RemoteRoutingError(f"{field} must be a tuple")
    if not allow_empty and not values:
        raise RemoteRoutingError(f"{field} must not be empty")
    if any(not isinstance(item, str) or not item for item in values):
        raise RemoteRoutingError(f"{field} must contain only non-empty strings")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise RemoteRoutingError(f"{field} must be a non-empty string")


__all__ = [
    "A15_REQUIRED_PROFILE_IDS",
    "HEAVY_CAPABILITY_ROUTING_BUNDLE_SCHEMA_VERSION",
    "HEAVY_REMOTE_JOB_PACKET_SCHEMA_VERSION",
    "HEAVY_REMOTE_ROUTING_DECISION_SCHEMA_VERSION",
    "BudgetReceipt",
    "ComputeNodeManifest",
    "HeavyCapabilityStatus",
    "HeavyProfile",
    "HeavyRemoteJobSpec",
    "RemoteRoutingError",
    "build_heavy_capability_routing_bundle",
    "build_signed_remote_job_packet",
    "default_heavy_profiles",
    "route_heavy_job",
    "verify_remote_job_packet",
]
