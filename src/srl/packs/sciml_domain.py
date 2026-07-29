"""SciML and domain-science pack admission.

S17 records Julia/Python SciML and domain-science capabilities under explicit
environment provenance. Missing runtimes stay in WAIT_CAPABILITY; result
receipts can still validate unit, solver and tolerance metadata without
turning absence into an ACTIVE pack.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

SCIML_DOMAIN_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "SciMLDomainAdmissionBundle/v1"
SCIML_DOMAIN_RESULT_RECEIPT_SCHEMA_VERSION: Final[str] = "SciMLDomainResultReceipt/v1"
CROSS_LANGUAGE_FIXTURE_RECEIPT_SCHEMA_VERSION: Final[str] = "CrossLanguageFixtureReceipt/v1"

_ACTIVE_REASON: Final[str] = "runtime_importable_and_environment_frozen"
_WAIT_REASON: Final[str] = "runtime_or_environment_evidence_missing"
_SHA256_HEX_LENGTH: Final[int] = 64
_MIN_CROSS_LANGUAGE_RECEIPTS: Final[int] = 2


class SciMLDomainError(ContractError):
    """Raised when a SciML/domain admission or result contract is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class SciMLDomainStatus(StrEnum):
    """Admission status for a SciML or domain-science profile."""

    ACTIVE = "ACTIVE"
    WAIT_CAPABILITY = "WAIT_CAPABILITY"


@dataclass(frozen=True)
class SciMLDomainProfile:
    """One reproducible environment profile card."""

    profile_id: str
    family: str
    language: str
    status: SciMLDomainStatus
    import_names: tuple[str, ...]
    executable_names: tuple[str, ...]
    package_names: tuple[str, ...]
    environment_kind: str
    environment_fingerprint: str
    unit_policy: str
    solver_policy: str
    tolerance_policy: str
    reason: str

    def __post_init__(self) -> None:
        for field in (
            "profile_id",
            "family",
            "language",
            "environment_kind",
            "environment_fingerprint",
            "unit_policy",
            "solver_policy",
            "tolerance_policy",
            "reason",
        ):
            _require_non_empty(getattr(self, field), field)
        for field in ("import_names", "executable_names", "package_names"):
            _require_string_tuple(getattr(self, field), field, allow_empty=True)
        if not self.import_names and not self.executable_names:
            raise SciMLDomainError("profile must declare at least one import or executable probe")

    def with_status(self, status: SciMLDomainStatus, reason: str) -> SciMLDomainProfile:
        """Return this profile with a changed status and reason."""
        return SciMLDomainProfile(
            profile_id=self.profile_id,
            family=self.family,
            language=self.language,
            status=status,
            import_names=self.import_names,
            executable_names=self.executable_names,
            package_names=self.package_names,
            environment_kind=self.environment_kind,
            environment_fingerprint=self.environment_fingerprint,
            unit_policy=self.unit_policy,
            solver_policy=self.solver_policy,
            tolerance_policy=self.tolerance_policy,
            reason=reason,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible profile card."""
        return {
            "profile_id": self.profile_id,
            "family": self.family,
            "language": self.language,
            "status": self.status.value,
            "import_names": list(self.import_names),
            "executable_names": list(self.executable_names),
            "package_names": list(self.package_names),
            "environment_kind": self.environment_kind,
            "environment_fingerprint": self.environment_fingerprint,
            "unit_policy": self.unit_policy,
            "solver_policy": self.solver_policy,
            "tolerance_policy": self.tolerance_policy,
            "reason": self.reason,
            "canonical_writes": 0,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class SciMLDomainResultSpec:
    """Unit, solver and tolerance provenance for one bounded domain result."""

    result_id: str
    profile_id: str
    language: str
    solver_name: str
    solver_family: str
    unit_bindings: tuple[str, ...]
    tolerance_abs: float
    tolerance_rel: float
    trace_sha256: str
    assumptions: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in (
            "result_id",
            "profile_id",
            "language",
            "solver_name",
            "solver_family",
            "trace_sha256",
        ):
            _require_non_empty(getattr(self, field), field)
        _require_string_tuple(self.unit_bindings, "unit_bindings", allow_empty=False)
        _require_string_tuple(self.assumptions, "assumptions", allow_empty=False)
        if self.tolerance_abs < 0 or self.tolerance_rel < 0:
            raise SciMLDomainError("tolerances must be non-negative")
        if self.tolerance_abs == 0 and self.tolerance_rel == 0:
            raise SciMLDomainError("at least one tolerance must be positive")
        if len(self.trace_sha256) != _SHA256_HEX_LENGTH:
            raise SciMLDomainError("trace_sha256 must be a 64-character hex digest")
        try:
            int(self.trace_sha256, 16)
        except ValueError as exc:
            raise SciMLDomainError("trace_sha256 must be hexadecimal") from exc


def default_sciml_domain_profiles() -> tuple[SciMLDomainProfile, ...]:
    """Return S17 SciML/domain profile cards in deterministic order."""
    wait = SciMLDomainStatus.WAIT_CAPABILITY
    return (
        _julia_profile("julia.sciml", "sciml", ("SciML",)),
        _julia_profile("julia.modelingtoolkit", "sciml", ("ModelingToolkit",)),
        _julia_profile("julia.datadrivendiffeq", "sciml", ("DataDrivenDiffEq",)),
        _python_profile("python.diffrax", "sciml", wait, ("diffrax",), ("diffrax",)),
        _python_profile("python.qutip", "physics", wait, ("qutip",), ("qutip",)),
        _python_profile("python.cadabra", "symbolic_physics", wait, ("cadabra2",), ("cadabra2",)),
        _python_profile("python.astropy", "astronomy", wait, ("astropy",), ("astropy",)),
        _python_profile("python.cantera", "chemistry", wait, ("cantera",), ("cantera",)),
        _python_profile("python.pybamm", "battery", wait, ("pybamm",), ("pybamm",)),
        _python_profile("python.quimb", "quantum_many_body", wait, ("quimb",), ("quimb",)),
        _python_profile("python.cotengra", "tensor_networks", wait, ("cotengra",), ("cotengra",)),
    )


def build_sciml_domain_admission_bundle(
    *,
    profiles: tuple[SciMLDomainProfile, ...] | None = None,
) -> dict[str, object]:
    """Build deterministic SciML/domain admission status."""
    assessed = tuple(_assess(profile) for profile in (profiles or default_sciml_domain_profiles()))
    body: dict[str, object] = {
        "schema_version": SCIML_DOMAIN_ADMISSION_BUNDLE_SCHEMA_VERSION,
        "profiles": [profile.to_dict() for profile in assessed],
        "active_profile_ids": [
            profile.profile_id for profile in assessed if profile.status is SciMLDomainStatus.ACTIVE
        ],
        "wait_profile_ids": [
            profile.profile_id
            for profile in assessed
            if profile.status is SciMLDomainStatus.WAIT_CAPABILITY
        ],
        "unit_policy": "unit_bindings_required_no_unit_loss",
        "solver_policy": "solver_name_family_and_status_required",
        "tolerance_policy": (
            "absolute_or_relative_tolerance_required_no_bitwise_cross_solver_claims"
        ),
        "shared_mutable_global_depots": 0,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def build_sciml_domain_result_receipt(spec: SciMLDomainResultSpec) -> dict[str, object]:
    """Build one authority-negative domain result receipt."""
    receipt: dict[str, object] = {
        "schema_version": SCIML_DOMAIN_RESULT_RECEIPT_SCHEMA_VERSION,
        "result_id": spec.result_id,
        "profile_id": spec.profile_id,
        "language": spec.language,
        "solver_name": spec.solver_name,
        "solver_family": spec.solver_family,
        "unit_bindings": list(spec.unit_bindings),
        "tolerance_abs": spec.tolerance_abs,
        "tolerance_rel": spec.tolerance_rel,
        "trace_sha256": spec.trace_sha256,
        "assumptions": list(spec.assumptions),
        "comparison_scope": "tolerance_provenance_only",
        "bitwise_identity_claimed": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def build_cross_language_fixture_receipt(
    *,
    receipts: tuple[dict[str, object], ...],
    comparison_label: str,
    tolerance_abs: float,
    tolerance_rel: float,
    bitwise_identity_claimed: bool = False,
) -> dict[str, object]:
    """Build a tolerance-only cross-language fixture receipt."""
    _require_non_empty(comparison_label, "comparison_label")
    if len(receipts) < _MIN_CROSS_LANGUAGE_RECEIPTS:
        raise SciMLDomainError("at least two receipts are required")
    if tolerance_abs < 0 or tolerance_rel < 0:
        raise SciMLDomainError("tolerances must be non-negative")
    if tolerance_abs == 0 and tolerance_rel == 0:
        raise SciMLDomainError("at least one tolerance must be positive")
    languages = {_expect_str(receipt, "language") for receipt in receipts}
    solver_families = {_expect_str(receipt, "solver_family") for receipt in receipts}
    if bitwise_identity_claimed and (len(languages) > 1 or len(solver_families) > 1):
        raise SciMLDomainError("bitwise identity cannot be claimed across runtimes or solvers")
    body: dict[str, object] = {
        "schema_version": CROSS_LANGUAGE_FIXTURE_RECEIPT_SCHEMA_VERSION,
        "comparison_label": comparison_label,
        "receipt_ids": [_expect_str(receipt, "receipt_id") for receipt in receipts],
        "languages": sorted(languages),
        "solver_families": sorted(solver_families),
        "tolerance_abs": tolerance_abs,
        "tolerance_rel": tolerance_rel,
        "comparison_scope": "bounded_fixture_tolerance_only",
        "bitwise_identity_claimed": bitwise_identity_claimed,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["receipt_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def _julia_profile(
    profile_id: str,
    family: str,
    package_names: tuple[str, ...],
) -> SciMLDomainProfile:
    return SciMLDomainProfile(
        profile_id=profile_id,
        family=family,
        language="julia",
        status=SciMLDomainStatus.WAIT_CAPABILITY,
        import_names=(),
        executable_names=("julia",),
        package_names=package_names,
        environment_kind="julia_manifest",
        environment_fingerprint="WAIT_JULIA_MANIFEST",
        unit_policy="unit_bindings_required",
        solver_policy="solver_name_and_algorithm_required",
        tolerance_policy="declared_tolerances_required",
        reason=_WAIT_REASON,
    )


def _python_profile(
    profile_id: str,
    family: str,
    status: SciMLDomainStatus,
    import_names: tuple[str, ...],
    package_names: tuple[str, ...],
) -> SciMLDomainProfile:
    return SciMLDomainProfile(
        profile_id=profile_id,
        family=family,
        language="python",
        status=status,
        import_names=import_names,
        executable_names=(),
        package_names=package_names,
        environment_kind="uv_lock",
        environment_fingerprint="WAIT_PYTHON_LOCK_ADMISSION",
        unit_policy="unit_bindings_required",
        solver_policy="solver_name_and_status_required",
        tolerance_policy="declared_tolerances_required",
        reason=_WAIT_REASON,
    )


def _assess(profile: SciMLDomainProfile) -> SciMLDomainProfile:
    missing_imports = [
        name for name in profile.import_names if importlib.util.find_spec(name) is None
    ]
    missing_executables = [name for name in profile.executable_names if shutil.which(name) is None]
    missing = missing_imports + missing_executables
    if missing:
        return profile.with_status(
            SciMLDomainStatus.WAIT_CAPABILITY,
            f"missing runtime evidence: {', '.join(missing)}",
        )
    if profile.status is SciMLDomainStatus.ACTIVE:
        return profile.with_status(SciMLDomainStatus.ACTIVE, _ACTIVE_REASON)
    return profile


def _expect_str(receipt: dict[str, object], key: str) -> str:
    value = receipt.get(key)
    if not isinstance(value, str) or not value:
        raise SciMLDomainError(f"{key} must be a non-empty string")
    return value


def _require_string_tuple(values: object, field: str, *, allow_empty: bool) -> None:
    if not isinstance(values, tuple):
        raise SciMLDomainError(f"{field} must be a tuple")
    if not allow_empty and not values:
        raise SciMLDomainError(f"{field} must not be empty")
    if any(not isinstance(item, str) or not item for item in values):
        raise SciMLDomainError(f"{field} must contain only non-empty strings")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise SciMLDomainError(f"{field} must be a non-empty string")


__all__ = [
    "CROSS_LANGUAGE_FIXTURE_RECEIPT_SCHEMA_VERSION",
    "SCIML_DOMAIN_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "SCIML_DOMAIN_RESULT_RECEIPT_SCHEMA_VERSION",
    "SciMLDomainError",
    "SciMLDomainProfile",
    "SciMLDomainResultSpec",
    "SciMLDomainStatus",
    "build_cross_language_fixture_receipt",
    "build_sciml_domain_admission_bundle",
    "build_sciml_domain_result_receipt",
    "default_sciml_domain_profiles",
]
