"""Pytest configuration for tests/catalog.

Shared builders live in :mod:`tests.catalog._helpers`; this conftest exposes the
seed entries and the fixed timestamp as pytest fixtures.
"""

from __future__ import annotations

import pytest

from srl.catalog.registry import CapabilityRegistryEntry, build_default_registry
from tests.catalog._helpers import FIXED_UTC


@pytest.fixture
def fixed_utc() -> str:
    """Return a fixed RFC 3339 UTC timestamp for deterministic snapshots."""
    return FIXED_UTC


@pytest.fixture
def seed_entries() -> tuple[CapabilityRegistryEntry, ...]:
    """Return the 15 packaged seed registry entries."""
    return build_default_registry()
