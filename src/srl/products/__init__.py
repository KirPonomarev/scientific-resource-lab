"""SRF product surfaces built from governed packs."""

from __future__ import annotations

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
    "LAWMINER_VALIDATION_RECEIPT_SCHEMA_VERSION",
    "DiscoveryPackCard",
    "DiscoveryPackStatus",
    "LawMinerError",
    "build_lawminer_admission_bundle",
    "default_discovery_pack_cards",
    "fit_linear_dynamics",
    "fit_linear_law",
]
