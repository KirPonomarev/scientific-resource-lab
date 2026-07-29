"""Deterministic environment profile factory for scientific resource packs.

The factory is a control-plane contract. It plans isolated Python, native,
Julia and prover environments from lock/SBOM/dependency evidence and decides
whether a profile may be scheduled. It does not install packages, mutate global
depots, grant authority, or close toolchain acceptance by declaration.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from srl.contracts.artifact_refs import validate_digest
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id
from srl.packs.governance import PackRevocationRegistry
from srl.packs.manifest import LICENSE_ALLOWLIST, LICENSE_INCOMPATIBLE_PREFIXES

ENVIRONMENT_PROFILE_SCHEMA_VERSION: Final[str] = "EnvironmentProfile/v1"
ENVIRONMENT_FACTORY_RECEIPT_SCHEMA_VERSION: Final[str] = "EnvironmentFactoryReceipt/v1"

UNKNOWN_LICENSE_REASON: Final[str] = "license_unknown"
INCOMPATIBLE_LICENSE_REASON: Final[str] = "license_incompatible"
REVOKED_DEPENDENCY_REASON: Final[str] = "revoked_dependency"
GLOBAL_MUTABLE_DEPOT_REASON: Final[str] = "global_mutable_depot"
DEPENDENCY_DAG_INVALID_REASON: Final[str] = "dependency_dag_invalid"

_PROFILE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,96}$")
_DEPENDENCY_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
_FORBIDDEN_ROOT_TOKENS: Final[tuple[str, ...]] = (
    "~",
    "$HOME",
    "${HOME}",
    "/",
    ".venv",
    "site-packages",
    ".julia",
    "julia/depot/global",
    "global-depot",
)
_MIN_PROFILE_ROOT_PARTS: Final[int] = 3


class EnvironmentFactoryError(ContractError):
    """Raised when an environment profile violates the factory contract."""

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


class EnvironmentKind(StrEnum):
    """Supported isolated environment profile kinds."""

    PYTHON_UV = "python_uv"
    NATIVE_BINARY = "native_binary"
    JULIA_DEPOT = "julia_depot"
    LEAN_PROVER = "lean_prover"


class EnvironmentStatus(StrEnum):
    """Scheduling status for one deterministic environment profile."""

    ACTIVE = "ACTIVE"
    WAIT_LICENSE = "WAIT_LICENSE"
    REVOKED = "REVOKED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class EnvironmentDependency:
    """One dependency in an environment lock/SBOM DAG."""

    dependency_id: str
    version: str
    license_spdx: str
    artifact_sha256: str
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_dependency_id(self.dependency_id, "dependency_id")
        _require_non_empty(self.version, "version")
        _require_non_empty(self.license_spdx, "license_spdx")
        validate_digest(self.artifact_sha256, field="artifact_sha256")
        for dependency_id in self.depends_on:
            _validate_dependency_id(dependency_id, "depends_on")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible dependency record."""
        return {
            "dependency_id": self.dependency_id,
            "version": self.version,
            "license_spdx": self.license_spdx,
            "artifact_sha256": self.artifact_sha256,
            "depends_on": sorted(self.depends_on),
        }


@dataclass(frozen=True, slots=True)
class EnvironmentProfileSpec:
    """Input spec for an isolated deterministic environment profile."""

    profile_id: str
    kind: EnvironmentKind
    lock_sha256: str
    sbom_sha256: str
    dependencies: tuple[EnvironmentDependency, ...]
    mutable_roots: tuple[str, ...]
    native_tools: tuple[str, ...] = ()
    canonical_writes: int = 0
    grants_authority: bool = False

    def __post_init__(self) -> None:
        _validate_profile_id(self.profile_id)
        validate_digest(self.lock_sha256, field="lock_sha256")
        validate_digest(self.sbom_sha256, field="sbom_sha256")
        if not self.dependencies:
            msg = "environment profile must declare at least one dependency"
            raise EnvironmentFactoryError(msg)
        if len({dep.dependency_id for dep in self.dependencies}) != len(self.dependencies):
            msg = "environment dependency ids must be unique"
            raise EnvironmentFactoryError(msg)
        if len(set(self.mutable_roots)) != len(self.mutable_roots):
            msg = "mutable_roots must be unique"
            raise EnvironmentFactoryError(msg)
        for root in self.mutable_roots:
            validate_isolated_mutable_root(root)
        for tool in self.native_tools:
            _validate_dependency_id(tool, "native_tools")
        if self.canonical_writes != 0 or self.grants_authority:
            msg = "environment factory specs must not grant authority or canonical writes"
            raise EnvironmentFactoryError(msg)

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible profile spec."""
        data = asdict(self)
        data["kind"] = self.kind.value
        data["dependencies"] = [dep.to_dict() for dep in self.dependencies]
        data["mutable_roots"] = sorted(self.mutable_roots)
        data["native_tools"] = sorted(self.native_tools)
        return data


@dataclass(frozen=True, slots=True)
class EnvironmentProfileRecord:
    """Scheduling assessment result for one environment profile."""

    profile_id: str
    kind: EnvironmentKind
    status: EnvironmentStatus
    reasons: tuple[str, ...]
    manifest: dict[str, object]
    canonical_writes: int = 0
    grants_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible environment profile record."""
        return {
            "schema_version": ENVIRONMENT_PROFILE_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "manifest": self.manifest,
            "canonical_writes": self.canonical_writes,
            "grants_authority": self.grants_authority,
        }

    def canonical_digest(self) -> str:
        """Return the digest of this record's canonical encoding."""
        return "sha256:" + hashlib.sha256(dumps(self.to_dict())).hexdigest()


def default_mutable_roots(profile_id: str) -> tuple[str, ...]:
    """Return isolated SRF work namespace roots for a profile id."""
    _validate_profile_id(profile_id)
    return (
        f"work/envs/{profile_id}",
        f"work/caches/{profile_id}",
        f"work/scratch/{profile_id}",
        f"work/spool/{profile_id}",
    )


def validate_isolated_mutable_root(root: str) -> str:
    """Validate that a mutable root is profile-scoped and portable."""
    _require_non_empty(root, "mutable_root")
    if root.startswith("/") or root.startswith("~") or "\\" in root or ":" in root:
        msg = f"mutable root {root!r} is not an isolated repo-relative POSIX path"
        raise EnvironmentFactoryError(msg, fail_reason=GLOBAL_MUTABLE_DEPOT_REASON)
    path = PurePosixPath(root)
    if path.is_absolute() or ".." in path.parts or len(path.parts) < _MIN_PROFILE_ROOT_PARTS:
        msg = f"mutable root {root!r} must stay inside a profile work namespace"
        raise EnvironmentFactoryError(msg, fail_reason=GLOBAL_MUTABLE_DEPOT_REASON)
    if path.parts[0] != "work":
        msg = f"mutable root {root!r} must start with work/"
        raise EnvironmentFactoryError(msg, fail_reason=GLOBAL_MUTABLE_DEPOT_REASON)
    lowered = root.lower()
    if any(token in lowered for token in _FORBIDDEN_ROOT_TOKENS if token not in {"/"}):
        msg = f"mutable root {root!r} names a forbidden global depot"
        raise EnvironmentFactoryError(msg, fail_reason=GLOBAL_MUTABLE_DEPOT_REASON)
    return root


def build_environment_profile(
    spec: EnvironmentProfileSpec,
    revocations: PackRevocationRegistry,
) -> EnvironmentProfileRecord:
    """Build a deterministic environment manifest and scheduling assessment."""
    dependency_order = _topological_dependency_order(spec.dependencies)
    status, reasons = _status_for(spec, dependency_order, revocations)
    manifest: dict[str, object] = {
        "schema_version": ENVIRONMENT_PROFILE_SCHEMA_VERSION,
        "profile_id": spec.profile_id,
        "kind": spec.kind.value,
        "lock_sha256": spec.lock_sha256,
        "sbom_sha256": spec.sbom_sha256,
        "dependencies": [dep.to_dict() for dep in dependency_order],
        "dependency_graph": {dep.dependency_id: sorted(dep.depends_on) for dep in dependency_order},
        "mutable_roots": sorted(spec.mutable_roots),
        "native_tools": sorted(spec.native_tools),
        "canonical_writes": 0,
        "grants_authority": False,
        "factory_executes_install": False,
    }
    manifest["manifest_id"] = object_id(manifest)
    return EnvironmentProfileRecord(
        profile_id=spec.profile_id,
        kind=spec.kind,
        status=status,
        reasons=reasons,
        manifest=manifest,
    )


def build_environment_factory_receipt(
    records: tuple[EnvironmentProfileRecord, ...],
) -> dict[str, object]:
    """Build the deterministic A03 environment factory receipt payload."""
    if not records:
        msg = "environment factory receipt requires at least one record"
        raise EnvironmentFactoryError(msg)
    active_unknown = [
        record.profile_id
        for record in records
        if record.status is EnvironmentStatus.ACTIVE
        and any(str(reason).startswith(UNKNOWN_LICENSE_REASON) for reason in record.reasons)
    ]
    if active_unknown:
        msg = f"ACTIVE profile(s) carry unknown license reason: {active_unknown}"
        raise EnvironmentFactoryError(msg)
    kinds = sorted({record.kind.value for record in records})
    payload: dict[str, object] = {
        "schema_version": ENVIRONMENT_FACTORY_RECEIPT_SCHEMA_VERSION,
        "record_count": len(records),
        "profile_kinds": kinds,
        "active_profile_ids": sorted(
            record.profile_id for record in records if record.status is EnvironmentStatus.ACTIVE
        ),
        "wait_profile_ids": sorted(
            record.profile_id for record in records if record.status is not EnvironmentStatus.ACTIVE
        ),
        "record_digests": sorted(record.canonical_digest() for record in records),
        "canonical_writes": 0,
        "grants_authority": False,
    }
    payload["receipt_id"] = object_id(payload)
    return payload


def _status_for(
    spec: EnvironmentProfileSpec,
    dependency_order: tuple[EnvironmentDependency, ...],
    revocations: PackRevocationRegistry,
) -> tuple[EnvironmentStatus, tuple[str, ...]]:
    revoked = sorted(
        dep.dependency_id
        for dep in dependency_order
        if dep.dependency_id in revocations.revoked_dependency_ids
    )
    if revoked:
        return EnvironmentStatus.REVOKED, tuple(
            f"{REVOKED_DEPENDENCY_REASON}:{dep}" for dep in revoked
        )
    unknown = sorted(
        dep.dependency_id
        for dep in dependency_order
        if dep.license_spdx not in LICENSE_ALLOWLIST
        and not dep.license_spdx.startswith(LICENSE_INCOMPATIBLE_PREFIXES)
    )
    if unknown:
        return EnvironmentStatus.WAIT_LICENSE, tuple(
            f"{UNKNOWN_LICENSE_REASON}:{dep}" for dep in unknown
        )
    incompatible = sorted(
        dep.dependency_id
        for dep in dependency_order
        if dep.license_spdx.startswith(LICENSE_INCOMPATIBLE_PREFIXES)
    )
    if incompatible:
        return EnvironmentStatus.WAIT_LICENSE, tuple(
            f"{INCOMPATIBLE_LICENSE_REASON}:{dep}" for dep in incompatible
        )
    return EnvironmentStatus.ACTIVE, ("complete_environment_profile_evidence",)


def _topological_dependency_order(
    dependencies: tuple[EnvironmentDependency, ...],
) -> tuple[EnvironmentDependency, ...]:
    by_id = {dep.dependency_id: dep for dep in dependencies}
    visiting: set[str] = set()
    visited: set[str] = set()
    ordered: list[EnvironmentDependency] = []

    def visit(dependency_id: str) -> None:
        if dependency_id in visited:
            return
        if dependency_id in visiting:
            msg = f"dependency graph contains a cycle at {dependency_id!r}"
            raise EnvironmentFactoryError(msg, fail_reason=DEPENDENCY_DAG_INVALID_REASON)
        dep = by_id.get(dependency_id)
        if dep is None:
            msg = f"dependency {dependency_id!r} referenced but not declared"
            raise EnvironmentFactoryError(msg, fail_reason=DEPENDENCY_DAG_INVALID_REASON)
        visiting.add(dependency_id)
        for child in sorted(dep.depends_on):
            visit(child)
        visiting.remove(dependency_id)
        visited.add(dependency_id)
        ordered.append(dep)

    for dependency_id in sorted(by_id):
        visit(dependency_id)
    return tuple(ordered)


def _validate_profile_id(profile_id: str) -> str:
    if not isinstance(profile_id, str) or not _PROFILE_ID_RE.fullmatch(profile_id):
        msg = f"profile_id {profile_id!r} must match {_PROFILE_ID_RE.pattern}"
        raise EnvironmentFactoryError(msg)
    return profile_id


def _validate_dependency_id(dependency_id: str, field: str) -> str:
    if not isinstance(dependency_id, str) or not _DEPENDENCY_ID_RE.fullmatch(dependency_id):
        msg = f"{field} {dependency_id!r} must match {_DEPENDENCY_ID_RE.pattern}"
        raise EnvironmentFactoryError(msg)
    return dependency_id


def _require_non_empty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        msg = f"{field} must be a non-empty string"
        raise EnvironmentFactoryError(msg)
    return value


__all__ = [
    "DEPENDENCY_DAG_INVALID_REASON",
    "ENVIRONMENT_FACTORY_RECEIPT_SCHEMA_VERSION",
    "ENVIRONMENT_PROFILE_SCHEMA_VERSION",
    "GLOBAL_MUTABLE_DEPOT_REASON",
    "INCOMPATIBLE_LICENSE_REASON",
    "REVOKED_DEPENDENCY_REASON",
    "UNKNOWN_LICENSE_REASON",
    "EnvironmentDependency",
    "EnvironmentFactoryError",
    "EnvironmentKind",
    "EnvironmentProfileRecord",
    "EnvironmentProfileSpec",
    "EnvironmentStatus",
    "build_environment_factory_receipt",
    "build_environment_profile",
    "default_mutable_roots",
    "validate_isolated_mutable_root",
]
