"""Honest P0 core admission bundle.

S11 does not pretend that every named P0 engine is installed. It records each
component independently as ACTIVE, DEGRADED, or WAIT_CAPABILITY, with explicit
method-card and cross-check policy fields. Solver disagreement is preserved:
z3 and cvc5 are separate components and cvc5 cannot inherit z3's evidence.
"""

from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

P0_CORE_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "P0CoreAdmissionBundle/v1"

_ACTIVE_REASON: Final[str] = "importable_and_license_allowed"
_WAIT_REASON: Final[str] = "runtime_or_license_evidence_missing"
_CVC5_REASON: Final[str] = "WAIT_LICENSE: cvc5 wheel license closure not admitted"


class P0AdmissionError(ContractError):
    """Raised when a P0 admission component is structurally invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class P0ComponentStatus(StrEnum):
    """Admission status for a P0 component."""

    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    WAIT_CAPABILITY = "WAIT_CAPABILITY"


@dataclass(frozen=True)
class P0Component:
    """One independently assessed P0 component."""

    component_id: str
    family: str
    status: P0ComponentStatus
    import_names: tuple[str, ...]
    package_names: tuple[str, ...]
    license_spdx: tuple[str, ...]
    capability_profiles: tuple[str, ...]
    method_card: str
    cross_checks: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        for field in (
            "component_id",
            "family",
            "method_card",
            "reason",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise P0AdmissionError(f"{field} must be a non-empty string")
        for field in (
            "import_names",
            "package_names",
            "license_spdx",
            "capability_profiles",
            "cross_checks",
        ):
            values = getattr(self, field)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise P0AdmissionError(f"{field} must be a tuple of non-empty strings")

    def with_status(self, status: P0ComponentStatus, reason: str) -> P0Component:
        """Return this component with a changed admission status."""
        return P0Component(
            component_id=self.component_id,
            family=self.family,
            status=status,
            import_names=self.import_names,
            package_names=self.package_names,
            license_spdx=self.license_spdx,
            capability_profiles=self.capability_profiles,
            method_card=self.method_card,
            cross_checks=self.cross_checks,
            reason=reason,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible component card."""
        return {
            "component_id": self.component_id,
            "family": self.family,
            "status": self.status.value,
            "import_names": list(self.import_names),
            "package_names": list(self.package_names),
            "license_spdx": list(self.license_spdx),
            "capability_profiles": list(self.capability_profiles),
            "method_card": self.method_card,
            "cross_checks": list(self.cross_checks),
            "reason": self.reason,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def default_p0_components() -> tuple[P0Component, ...]:
    """Return the declared P0 component set in deterministic order."""
    active = P0ComponentStatus.ACTIVE
    wait = P0ComponentStatus.WAIT_CAPABILITY
    degraded = P0ComponentStatus.DEGRADED
    return (
        P0Component(
            "numeric.numpy",
            "numeric",
            active,
            ("numpy",),
            ("numpy",),
            ("BSD-3-Clause",),
            ("numeric_array",),
            "NumPy array arithmetic; no scientific truth promotion",
            ("shape_dtype_validation", "exact_input_digest"),
            _ACTIVE_REASON,
        ),
        P0Component(
            "numeric.scipy",
            "numeric",
            active,
            ("scipy",),
            ("scipy",),
            ("BSD-3-Clause",),
            ("numeric_scipy",),
            "SciPy bounded numerical routines",
            ("residual_check", "method_card_scope"),
            _ACTIVE_REASON,
        ),
        P0Component(
            "units.pint",
            "units",
            active,
            ("pint",),
            ("pint",),
            ("BSD-3-Clause",),
            ("algebra_exact", "symbolic_law"),
            "Pint dimensional analysis via isolated units adapter",
            ("exact_decimal_round_trip", "dimension_mismatch_reject"),
            _ACTIVE_REASON,
        ),
        P0Component(
            "smt.z3",
            "smt",
            active,
            ("z3",),
            ("z3-solver",),
            ("MIT",),
            ("nonlinear_continuous_or_hybrid_constraint",),
            "Z3 SAT/UNSAT checks capped at formal_check=checked",
            ("solver_timeout", "malformed_formula_reject", "no_proven_claim"),
            _ACTIVE_REASON,
        ),
        P0Component(
            "smt.cvc5",
            "smt",
            degraded,
            ("cvc5",),
            ("cvc5",),
            ("WAIT_LICENSE",),
            ("nonlinear_continuous_or_hybrid_constraint",),
            "cvc5 held until license closure; disagreement path preserved",
            ("solver_disagreement_preserved", "no_z3_substitution"),
            _CVC5_REASON,
        ),
        P0Component(
            "symbolic.sympy",
            "symbolic",
            wait,
            ("sympy",),
            ("sympy",),
            ("BSD-3-Clause",),
            ("algebra_exact", "symbolic_law"),
            "SymPy symbolic manipulation",
            ("exact_vs_float", "unsupported_operator_reject"),
            _WAIT_REASON,
        ),
        P0Component(
            "numeric.mpmath",
            "numeric",
            wait,
            ("mpmath",),
            ("mpmath",),
            ("BSD-3-Clause",),
            ("numeric_high_precision",),
            "mpmath arbitrary precision numerics",
            ("precision_declared", "interval_or_residual_check"),
            _WAIT_REASON,
        ),
        P0Component(
            "exact.flint",
            "exact",
            wait,
            ("flint",),
            ("python-flint", "FLINT", "Arb", "Calcium"),
            ("WAIT_CAPABILITY",),
            ("algebra_exact",),
            "FLINT/Arb/Calcium exact algebra stack",
            ("exact_rational", "algebraic_number_cross_check"),
            _WAIT_REASON,
        ),
        P0Component(
            "exact.pari",
            "exact",
            wait,
            ("cypari2",),
            ("PARI/GP",),
            ("WAIT_CAPABILITY",),
            ("number_theory_exact",),
            "PARI/GP number theory stack",
            ("number_theory_cross_engine",),
            _WAIT_REASON,
        ),
        P0Component(
            "cas.maxima",
            "symbolic",
            wait,
            ("maxima",),
            ("Maxima",),
            ("WAIT_CAPABILITY",),
            ("symbolic_law",),
            "Maxima CAS subprocess adapter",
            ("subprocess_allowlist", "no_eval_string"),
            _WAIT_REASON,
        ),
        P0Component(
            "cas.gap",
            "exact",
            wait,
            ("gap",),
            ("GAP",),
            ("WAIT_CAPABILITY",),
            ("algebra_exact",),
            "GAP algebra system adapter",
            ("group_theory_fixture", "subprocess_allowlist"),
            _WAIT_REASON,
        ),
        P0Component(
            "cas.singular",
            "exact",
            wait,
            ("singular",),
            ("Singular",),
            ("WAIT_CAPABILITY",),
            ("algebra_exact",),
            "Singular polynomial algebra adapter",
            ("groebner_fixture", "subprocess_allowlist"),
            _WAIT_REASON,
        ),
    )


def build_p0_admission_bundle(
    *,
    components: tuple[P0Component, ...] | None = None,
) -> dict[str, object]:
    """Build a deterministic P0 admission bundle from current runtime probes."""
    assessed = tuple(
        _assess_component(component) for component in (components or default_p0_components())
    )
    body: dict[str, object] = {
        "schema_version": P0_CORE_ADMISSION_BUNDLE_SCHEMA_VERSION,
        "components": [component.to_dict() for component in assessed],
        "active_component_ids": [
            component.component_id
            for component in assessed
            if component.status is P0ComponentStatus.ACTIVE
        ],
        "degraded_component_ids": [
            component.component_id
            for component in assessed
            if component.status is P0ComponentStatus.DEGRADED
        ],
        "wait_component_ids": [
            component.component_id
            for component in assessed
            if component.status is P0ComponentStatus.WAIT_CAPABILITY
        ],
        "solver_disagreement_policy": "preserve_disagreement_never_substitute_z3_for_cvc5",
        "integration_authority": "none",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def _assess_component(component: P0Component) -> P0Component:
    if component.status is not P0ComponentStatus.ACTIVE:
        return component
    missing = [name for name in component.import_names if importlib.util.find_spec(name) is None]
    if missing:
        return component.with_status(
            P0ComponentStatus.WAIT_CAPABILITY,
            f"missing import(s): {', '.join(missing)}",
        )
    return component


__all__ = [
    "P0_CORE_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "P0AdmissionError",
    "P0Component",
    "P0ComponentStatus",
    "build_p0_admission_bundle",
    "default_p0_components",
]
