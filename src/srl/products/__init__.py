"""SRF product surfaces built from governed packs."""

from __future__ import annotations

from srl.products.applied import (
    A13_APPLIED_RECEIPT_SCHEMA_VERSION,
    APPLIED_RESULT_RECEIPT_SCHEMA_VERSION,
    APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION,
    AppliedPackCard,
    AppliedPackStatus,
    AppliedScienceError,
    build_applied_result_receipt,
    build_applied_science_admission_bundle,
    default_applied_pack_cards,
    run_a13_applied_science_smoke,
)
from srl.products.discovery_dynamics import (
    A12_DISCOVERY_RECEIPT_SCHEMA_VERSION,
    A12PackPolicy,
    A12RuntimeContext,
    DiscoveryDynamicsError,
    default_a12_pack_policy,
    prepare_a12_julia_depot,
    resolve_a12_runtime,
    run_a12_discovery_dynamics_smoke,
)
from srl.products.lawminer import (
    LAWMINER_VALIDATION_RECEIPT_SCHEMA_VERSION,
    DiscoveryPackCard,
    DiscoveryPackStatus,
    LawMinerError,
    build_lawminer_admission_bundle,
    default_discovery_pack_cards,
    fit_linear_dynamics,
    fit_linear_law,
)

__all__ = [
    "A12_DISCOVERY_RECEIPT_SCHEMA_VERSION",
    "A13_APPLIED_RECEIPT_SCHEMA_VERSION",
    "APPLIED_RESULT_RECEIPT_SCHEMA_VERSION",
    "APPLIED_SCIENCE_ADMISSION_BUNDLE_SCHEMA_VERSION",
    "LAWMINER_VALIDATION_RECEIPT_SCHEMA_VERSION",
    "A12PackPolicy",
    "A12RuntimeContext",
    "AppliedPackCard",
    "AppliedPackStatus",
    "AppliedScienceError",
    "DiscoveryDynamicsError",
    "DiscoveryPackCard",
    "DiscoveryPackStatus",
    "LawMinerError",
    "build_applied_result_receipt",
    "build_applied_science_admission_bundle",
    "build_lawminer_admission_bundle",
    "default_a12_pack_policy",
    "default_applied_pack_cards",
    "default_discovery_pack_cards",
    "fit_linear_dynamics",
    "fit_linear_law",
    "prepare_a12_julia_depot",
    "resolve_a12_runtime",
    "run_a12_discovery_dynamics_smoke",
    "run_a13_applied_science_smoke",
]
