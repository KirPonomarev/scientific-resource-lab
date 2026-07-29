"""Applied geometry, topology, probability, causal and optimization admission."""

from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "AppliedScienceAdmissionBundle/v1"
APPLIED_RESULT_RECEIPT_SCHEMA_VERSION: Final[str] = "AppliedResultReceipt/v1"


class AppliedScienceError(ContractError):
    """Raised when applied-science admission or result contracts are invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class AppliedPackStatus(StrEnum):
    """Applied pack status."""

    ACTIVE = "ACTIVE"
    WAIT_CAPABILITY = "WAIT_CAPABILITY"


@dataclass(frozen=True)
class AppliedPackCard:
    """One applied pack admission card."""

    pack_id: str
    family: str
    status: AppliedPackStatus
    import_names: tuple[str, ...]
    capability: str
    diagnostic_policy: str
    reason: str

    def __post_init__(self) -> None:
        for field in ("pack_id", "family", "capability", "diagnostic_policy", "reason"):
            _require_non_empty(getattr(self, field), field)
        if not isinstance(self.import_names, tuple) or any(
            not isinstance(name, str) or not name for name in self.import_names
        ):
            raise AppliedScienceError("import_names must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible pack card."""
        return {
            "pack_id": self.pack_id,
            "family": self.family,
            "status": self.status.value,
            "import_names": list(self.import_names),
            "capability": self.capability,
            "diagnostic_policy": self.diagnostic_policy,
            "reason": self.reason,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def default_applied_pack_cards() -> tuple[AppliedPackCard, ...]:
    """Return S16 applied pack cards."""
    active = AppliedPackStatus.ACTIVE
    wait = AppliedPackStatus.WAIT_CAPABILITY
    return (
        AppliedPackCard(
            pack_id="ripser",
            family="topology",
            status=active,
            import_names=("ripser",),
            capability="persistent_homology",
            diagnostic_policy="null controls required",
            reason="existing bounded adapter",
        ),
        AppliedPackCard(
            pack_id="pyriemann",
            family="geometry",
            status=active,
            import_names=("pyriemann",),
            capability="spd_geometry",
            diagnostic_policy="cross-validation diagnostics required",
            reason="existing bounded adapter",
        ),
        AppliedPackCard(
            pack_id="cvxpy",
            family="optimization",
            status=active,
            import_names=("cvxpy",),
            capability="convex_optimization",
            diagnostic_policy="solver status required",
            reason="existing bounded adapter",
        ),
        AppliedPackCard(
            pack_id="gudhi",
            family="topology",
            status=wait,
            import_names=("gudhi",),
            capability="topological_data_analysis",
            diagnostic_policy="null controls required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="geomstats",
            family="geometry",
            status=wait,
            import_names=("geomstats",),
            capability="riemannian_geometry",
            diagnostic_policy="metric diagnostics required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="pot",
            family="optimization",
            status=wait,
            import_names=("ot",),
            capability="optimal_transport",
            diagnostic_policy="solver status required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="pymanopt",
            family="optimization",
            status=wait,
            import_names=("pymanopt",),
            capability="manifold_optimization",
            diagnostic_policy="solver status required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="keplermapper",
            family="topology",
            status=wait,
            import_names=("kmapper",),
            capability="mapper_graphs",
            diagnostic_policy="null controls required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="toponetx",
            family="topology",
            status=wait,
            import_names=("toponetx",),
            capability="higher_order_topology",
            diagnostic_policy="null controls required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="regina",
            family="topology",
            status=wait,
            import_names=("regina",),
            capability="3_manifold_topology",
            diagnostic_policy="exact certificate required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="pymc",
            family="probability",
            status=wait,
            import_names=("pymc",),
            capability="bayesian_modeling",
            diagnostic_policy="mcmc diagnostics required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="arviz",
            family="probability",
            status=wait,
            import_names=("arviz",),
            capability="mcmc_diagnostics",
            diagnostic_policy="rhat_ess required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="dowhy",
            family="causal",
            status=wait,
            import_names=("dowhy",),
            capability="causal_identification",
            diagnostic_policy="identification required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="tigramite",
            family="causal",
            status=wait,
            import_names=("tigramite",),
            capability="time_series_causal_discovery",
            diagnostic_policy="falsification required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="econml",
            family="causal",
            status=wait,
            import_names=("econml",),
            capability="heterogeneous_treatment_effects",
            diagnostic_policy="identification required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="jaxopt",
            family="optimization",
            status=wait,
            import_names=("jaxopt",),
            capability="differentiable_optimization",
            diagnostic_policy="solver status required",
            reason="missing import",
        ),
        AppliedPackCard(
            pack_id="botorch",
            family="optimization",
            status=wait,
            import_names=("botorch",),
            capability="bayesian_optimization",
            diagnostic_policy="uncertainty diagnostics required",
            reason="missing import",
        ),
    )


def build_applied_science_admission_bundle(
    *,
    cards: tuple[AppliedPackCard, ...] | None = None,
) -> dict[str, object]:
    """Build deterministic applied-science admission status."""
    assessed = tuple(_assess(card) for card in (cards or default_applied_pack_cards()))
    body: dict[str, object] = {
        "schema_version": APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION,
        "pack_cards": [card.to_dict() for card in assessed],
        "active_pack_ids": [
            card.pack_id for card in assessed if card.status is AppliedPackStatus.ACTIVE
        ],
        "wait_pack_ids": [
            card.pack_id for card in assessed if card.status is AppliedPackStatus.WAIT_CAPABILITY
        ],
        "diagnostic_policy": "assumptions_diagnostics_uncertainty_and_solver_status_required",
        "causal_policy": "unidentified_effect_must_not_be_estimated",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def build_applied_result_receipt(  # noqa: PLR0913
    *,
    product: str,
    assumptions: tuple[str, ...],
    diagnostics: tuple[str, ...],
    solver_status: str,
    causal_identification: str = "not_applicable",
    effect_estimate: float | None = None,
) -> dict[str, object]:
    """Build an authority-negative applied result receipt."""
    _require_non_empty(product, "product")
    _require_tuple(assumptions, "assumptions")
    _require_tuple(diagnostics, "diagnostics")
    _require_non_empty(solver_status, "solver_status")
    _require_non_empty(causal_identification, "causal_identification")
    if causal_identification != "identified" and effect_estimate is not None:
        raise AppliedScienceError("unidentified causal effect must not carry an estimate")
    receipt: dict[str, object] = {
        "schema_version": APPLIED_RESULT_RECEIPT_SCHEMA_VERSION,
        "product": product,
        "assumptions": list(assumptions),
        "diagnostics": list(diagnostics),
        "solver_status": solver_status,
        "causal_identification": causal_identification,
        "effect_estimate": effect_estimate,
        "status": "inconclusive" if solver_status != "optimal" else "checked",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def _assess(card: AppliedPackCard) -> AppliedPackCard:
    missing = [name for name in card.import_names if importlib.util.find_spec(name) is None]
    if card.status is AppliedPackStatus.ACTIVE and missing:
        return AppliedPackCard(
            pack_id=card.pack_id,
            family=card.family,
            status=AppliedPackStatus.WAIT_CAPABILITY,
            import_names=card.import_names,
            capability=card.capability,
            diagnostic_policy=card.diagnostic_policy,
            reason=f"missing import(s): {', '.join(missing)}",
        )
    return card


def _require_tuple(values: object, field: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise AppliedScienceError(f"{field} must be a tuple of non-empty strings")


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise AppliedScienceError(f"{field} must be a non-empty string")


__all__ = [
    "APPLIED_RESULT_RECEIPT_SCHEMA_VERSION",
    "APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "AppliedPackCard",
    "AppliedPackStatus",
    "AppliedScienceError",
    "build_applied_result_receipt",
    "build_applied_science_admission_bundle",
    "default_applied_pack_cards",
]
