"""Unit tests for the platform probe and preflight (srl.execution.platform_probe).

Pins:

1. A preflight against a provider below the free-disk floor raises
   ``ResourceLimitError`` with ``fail_reason='RESOURCE_LIMIT'``.
2. A provider at or above the floor returns a ``PreflightReceipt`` with
   ``ok=True`` and the observed/required bytes recorded.
3. The injected :class:`StaticPreflightProvider` makes preflight hermetic (no
   filesystem access).
4. The real :class:`DiskProbe` returns a non-negative int from the live volume.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from srl.execution.estimate import ResourceEstimate
from srl.execution.platform_probe import (
    PREFLIGHT_SCHEMA_VERSION,
    RESOURCE_LIMIT_FAIL_REASON,
    DiskProbe,
    PreflightReceipt,
    ResourceLimitError,
    StaticPreflightProvider,
    preflight,
)
from srl.execution.policy import load_policy

_POLICY_PATH = Path("policies/resource-policy-m1.json")
_DEFAULT_FREE_DISK = 21474836480  # 20 GiB


@pytest.fixture(scope="module")
def policy() -> object:
    """The shipped M1 policy, loaded once for the preflight tests."""
    return load_policy(_POLICY_PATH)


@pytest.fixture(scope="module")
def estimate() -> ResourceEstimate:
    """A canonical default-envelope estimate carried for preflight context."""
    return ResourceEstimate(
        wall_seconds=300, rss_bytes=1610612736, scratch_bytes=4294967296, cpu_cores=1
    )


# ---------------------------------------------------------------------------
# Low-disk preflight -> RESOURCE_LIMIT.
# ---------------------------------------------------------------------------


def test_preflight_below_floor_raises_resource_limit(
    policy: object, estimate: ResourceEstimate
) -> None:
    """One byte below the floor raises ResourceLimitError(RESOURCE_LIMIT)."""
    provider = StaticPreflightProvider(free_disk_bytes=_DEFAULT_FREE_DISK - 1)
    with pytest.raises(ResourceLimitError) as exc_info:
        preflight(estimate, policy, provider)  # type: ignore[arg-type]
    assert exc_info.value.fail_reason == RESOURCE_LIMIT_FAIL_REASON
    assert "RESOURCE_LIMIT" in str(exc_info.value)


def test_preflight_zero_disk_raises(policy: object, estimate: ResourceEstimate) -> None:
    """A zero-free-disk provider raises RESOURCE_LIMIT."""
    provider = StaticPreflightProvider(free_disk_bytes=0)
    with pytest.raises(ResourceLimitError) as exc_info:
        preflight(estimate, policy, provider)  # type: ignore[arg-type]
    assert exc_info.value.fail_reason == RESOURCE_LIMIT_FAIL_REASON


# ---------------------------------------------------------------------------
# At/above floor -> ok receipt.
# ---------------------------------------------------------------------------


def test_preflight_at_floor_ok(policy: object, estimate: ResourceEstimate) -> None:
    """Exactly at the floor is ok (boundary inclusive)."""
    provider = StaticPreflightProvider(free_disk_bytes=_DEFAULT_FREE_DISK)
    receipt = preflight(estimate, policy, provider)  # type: ignore[arg-type]
    assert isinstance(receipt, PreflightReceipt)
    assert receipt.ok is True
    assert receipt.observed_free_disk_bytes == _DEFAULT_FREE_DISK
    assert receipt.required_free_disk_bytes == _DEFAULT_FREE_DISK


def test_preflight_above_floor_ok(policy: object, estimate: ResourceEstimate) -> None:
    """Well above the floor is ok."""
    provider = StaticPreflightProvider(free_disk_bytes=_DEFAULT_FREE_DISK * 4)
    receipt = preflight(estimate, policy, provider)  # type: ignore[arg-type]
    assert receipt.ok is True
    assert receipt.observed_free_disk_bytes == _DEFAULT_FREE_DISK * 4


def test_preflight_receipt_schema_version() -> None:
    """The receipt carries the PreflightReceipt/v1 schema version."""
    assert PREFLIGHT_SCHEMA_VERSION == "PreflightReceipt/v1"


def test_preflight_receipt_to_dict_round_trip(policy: object, estimate: ResourceEstimate) -> None:
    """The receipt dict carries the required fields for serialization."""
    provider = StaticPreflightProvider(free_disk_bytes=_DEFAULT_FREE_DISK)
    receipt = preflight(estimate, policy, provider)  # type: ignore[arg-type]
    d = receipt.to_dict()
    assert d["schema_version"] == "PreflightReceipt/v1"
    assert d["ok"] is True
    assert d["required_free_disk_bytes"] == _DEFAULT_FREE_DISK
    assert d["observed_free_disk_bytes"] == _DEFAULT_FREE_DISK


# ---------------------------------------------------------------------------
# Hermeticity: the injected provider avoids the filesystem.
# ---------------------------------------------------------------------------


def test_static_preflight_provider_is_frozen() -> None:
    """The static provider is frozen (immutable) and safe to share."""
    p = StaticPreflightProvider(free_disk_bytes=123)
    assert p.free_disk_bytes == 123
    with pytest.raises(Exception):  # noqa: B017  (frozen dataclass raises FrozenInstanceError)
        p.free_disk_bytes = 456  # type: ignore[misc]


def test_disk_probe_returns_non_negative_int(tmp_path: Path) -> None:
    """The real DiskProbe returns a non-negative int from the live volume."""
    probe = DiskProbe(tmp_path)
    free = probe.free_disk_bytes
    assert isinstance(free, int)
    assert free >= 0
