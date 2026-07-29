"""Bounded LawMiner and dynamical discovery validation layer."""

from __future__ import annotations

import hashlib
import importlib.util
import math
import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

LAWMINER_VALIDATION_RECEIPT_SCHEMA_VERSION: Final[str] = "LawMinerValidationReceipt/v1"
LAWMINER_ADMISSION_BUNDLE_SCHEMA_VERSION: Final[str] = "LawMinerAdmissionBundle/v1"
_MIN_DYNAMICS_POINTS: Final[int] = 3
_MIN_LINEAR_FIT_POINTS: Final[int] = 2


class LawMinerError(ContractError):
    """Raised when a LawMiner spec or validation violates honesty constraints."""

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class DiscoveryPackStatus(StrEnum):
    """Status of a discovery/dynamical pack."""

    ACTIVE = "ACTIVE"
    WAIT_CAPABILITY = "WAIT_CAPABILITY"


@dataclass(frozen=True)
class DiscoveryPackCard:
    """Admission card for one discovery or dynamical pack."""

    pack_id: str
    family: str
    status: DiscoveryPackStatus
    import_names: tuple[str, ...]
    capability: str
    reason: str

    def __post_init__(self) -> None:
        for field in ("pack_id", "family", "capability", "reason"):
            _require_non_empty(getattr(self, field), field)
        if not isinstance(self.import_names, tuple) or any(
            not isinstance(name, str) or not name for name in self.import_names
        ):
            raise LawMinerError("import_names must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible pack card."""
        return {
            "pack_id": self.pack_id,
            "family": self.family,
            "status": self.status.value,
            "import_names": list(self.import_names),
            "capability": self.capability,
            "reason": self.reason,
            "canonical_writes": 0,
            "grants_authority": False,
        }


def default_discovery_pack_cards() -> tuple[DiscoveryPackCard, ...]:
    """Return S15 discovery/dynamics pack cards."""
    active = DiscoveryPackStatus.ACTIVE
    wait = DiscoveryPackStatus.WAIT_CAPABILITY
    return (
        DiscoveryPackCard(
            "lawminer.linear_baseline",
            "law_discovery",
            active,
            ("math",),
            "deterministic_linear_law_fixture",
            "stdlib bounded baseline for null/leakage validation",
        ),
        DiscoveryPackCard(
            "pysr", "law_discovery", wait, ("pysr",), "symbolic_regression", "missing import"
        ),
        DiscoveryPackCard(
            "sr4mdl", "law_discovery", wait, ("sr4mdl",), "symbolic_regression", "missing import"
        ),
        DiscoveryPackCard(
            "operon",
            "law_discovery",
            wait,
            ("pyoperon",),
            "symbolic_regression",
            "missing import",
        ),
        DiscoveryPackCard(
            "gplearn",
            "law_discovery",
            wait,
            ("gplearn",),
            "genetic_programming",
            "missing import",
        ),
        DiscoveryPackCard(
            "ai_feynman",
            "law_discovery",
            wait,
            ("aifeynman",),
            "symbolic_regression",
            "missing import",
        ),
        DiscoveryPackCard(
            "pysindy", "dynamical", wait, ("pysindy",), "sparse_dynamics", "missing import"
        ),
        DiscoveryPackCard(
            "pydmd",
            "dynamical",
            wait,
            ("pydmd",),
            "dynamic_mode_decomposition",
            "missing import",
        ),
        DiscoveryPackCard(
            "pykoopman",
            "dynamical",
            wait,
            ("pykoopman",),
            "koopman_learning",
            "missing import",
        ),
        DiscoveryPackCard(
            "dysts",
            "dynamical",
            wait,
            ("dysts",),
            "dynamical_systems_corpus",
            "missing import",
        ),
    )


def build_lawminer_admission_bundle(
    *,
    cards: tuple[DiscoveryPackCard, ...] | None = None,
) -> dict[str, object]:
    """Build deterministic S15 admission status for discovery packs."""
    assessed = tuple(_assess_card(card) for card in (cards or default_discovery_pack_cards()))
    body: dict[str, object] = {
        "schema_version": LAWMINER_ADMISSION_BUNDLE_SCHEMA_VERSION,
        "pack_cards": [card.to_dict() for card in assessed],
        "active_pack_ids": [
            card.pack_id for card in assessed if card.status is DiscoveryPackStatus.ACTIVE
        ],
        "wait_pack_ids": [
            card.pack_id for card in assessed if card.status is DiscoveryPackStatus.WAIT_CAPABILITY
        ],
        "promotion_policy": "candidate_only_no_automatic_law_promotion",
        "holdout_policy": "retrospective_validation_indices_only_no_prospective_materialization",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    body["bundle_id"] = "sha256:" + hashlib.sha256(dumps(body)).hexdigest()
    return body


def fit_linear_law(
    x_values: tuple[float, ...],
    y_values: tuple[float, ...],
    *,
    train_indices: tuple[int, ...],
    validation_indices: tuple[int, ...],
    null_seed: int,
) -> dict[str, object]:
    """Fit ``y = slope*x + intercept`` under leakage/null controls."""
    _validate_split(len(x_values), len(y_values), train_indices, validation_indices)
    train_x = [x_values[i] for i in train_indices]
    train_y = [y_values[i] for i in train_indices]
    slope, intercept = _linear_fit(train_x, train_y)
    validation_rmse = _rmse(
        [slope * x_values[i] + intercept for i in validation_indices],
        [y_values[i] for i in validation_indices],
    )
    shuffled = list(train_y)
    random.Random(null_seed).shuffle(shuffled)  # noqa: S311 - deterministic null fixture.
    null_slope, null_intercept = _linear_fit(train_x, shuffled)
    null_rmse = _rmse(
        [null_slope * x_values[i] + null_intercept for i in validation_indices],
        [y_values[i] for i in validation_indices],
    )
    return _validation_receipt(
        product="lawminer.linear_baseline",
        candidate={"form": "y = slope*x + intercept", "slope": slope, "intercept": intercept},
        validation_metric={"name": "rmse", "value": validation_rmse},
        null_metric={"name": "permuted_train_rmse", "value": null_rmse, "seed": null_seed},
        observed_above_null=validation_rmse < null_rmse,
    )


def fit_linear_dynamics(
    series: tuple[float, ...],
    *,
    train_indices: tuple[int, ...],
    validation_indices: tuple[int, ...],
    null_seed: int,
) -> dict[str, object]:
    """Fit one-step ``x[t+1] = multiplier*x[t]`` with split/null controls."""
    if len(series) < _MIN_DYNAMICS_POINTS:
        raise LawMinerError("series must contain at least three points")
    x_values = tuple(series[i] for i in range(len(series) - 1))
    y_values = tuple(series[i + 1] for i in range(len(series) - 1))
    receipt = fit_linear_law(
        x_values,
        y_values,
        train_indices=train_indices,
        validation_indices=validation_indices,
        null_seed=null_seed,
    )
    candidate = dict(cast(dict[str, object], receipt["candidate"]))
    candidate["form"] = "x_next = multiplier*x + intercept"
    receipt["product"] = "lawminer.linear_dynamics_baseline"
    receipt["candidate"] = candidate
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def _validation_receipt(
    *,
    product: str,
    candidate: dict[str, object],
    validation_metric: dict[str, object],
    null_metric: dict[str, object],
    observed_above_null: bool,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": LAWMINER_VALIDATION_RECEIPT_SCHEMA_VERSION,
        "product": product,
        "candidate": candidate,
        "validation_metric": validation_metric,
        "null_metric": null_metric,
        "observed_above_null": observed_above_null,
        "status": "candidate_observation" if observed_above_null else "null_or_inconclusive",
        "promotion_allowed": False,
        "prospective_holdout_materialization_allowed": False,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = "sha256:" + hashlib.sha256(dumps(receipt)).hexdigest()
    return receipt


def _assess_card(card: DiscoveryPackCard) -> DiscoveryPackCard:
    if card.status is not DiscoveryPackStatus.ACTIVE:
        missing = [name for name in card.import_names if importlib.util.find_spec(name) is None]
        if missing:
            return card
        return DiscoveryPackCard(
            card.pack_id,
            card.family,
            DiscoveryPackStatus.ACTIVE,
            card.import_names,
            card.capability,
            "importable_but_not_promoted_without_pack_governance",
        )
    return card


def _validate_split(
    x_len: int,
    y_len: int,
    train_indices: tuple[int, ...],
    validation_indices: tuple[int, ...],
) -> None:
    if x_len != y_len or x_len == 0:
        raise LawMinerError("x_values and y_values must have equal non-zero length")
    if not train_indices or not validation_indices:
        raise LawMinerError("train and validation indices must be non-empty")
    all_indices = set(train_indices) | set(validation_indices)
    if min(all_indices) < 0 or max(all_indices) >= x_len:
        raise LawMinerError("split index out of range")
    if set(train_indices) & set(validation_indices):
        raise LawMinerError("train and validation splits must not overlap")


def _linear_fit(x_values: list[float], y_values: list[float]) -> tuple[float, float]:
    if len(x_values) != len(y_values) or len(x_values) < _MIN_LINEAR_FIT_POINTS:
        raise LawMinerError("linear fit requires at least two paired training points")
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denom = sum((x - x_mean) ** 2 for x in x_values)
    if denom == 0:
        raise LawMinerError("linear fit requires non-constant x values")
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values, strict=True))
    slope = numerator / denom
    intercept = y_mean - slope * x_mean
    return slope, intercept


def _rmse(predicted: list[float], observed: list[float]) -> float:
    return math.sqrt(
        sum((pred - obs) ** 2 for pred, obs in zip(predicted, observed, strict=True))
        / len(observed)
    )


def _require_non_empty(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise LawMinerError(f"{field} must be a non-empty string")


__all__ = [
    "LAWMINER_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "LAWMINER_VALIDATION_RECEIPT_SCHEMA_VERSION",
    "DiscoveryPackCard",
    "DiscoveryPackStatus",
    "LawMinerError",
    "build_lawminer_admission_bundle",
    "default_discovery_pack_cards",
    "fit_linear_dynamics",
    "fit_linear_law",
]
