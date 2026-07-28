"""Unit tests for the M1 resource policy and admission (srl.execution.policy).

Pins:

1. The shipped M1 policy loads with the exact default caps and safety consts.
2. The exception envelope is bounded: every over-cap value is rejected at load
   with ``fail_reason='CONTRACT_INVALID'``.
3. The admission matrix has no silent downgrade: an over-default estimate parks
   without the exception flag; an over-exception estimate parks even with it.
4. Estimate validation rejects bool/float/negative quantities.
5. The estimate canonical serialization and digest are stable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from srl.execution.estimate import ESTIMATE_FAIL_REASON, ResourceEstimate, ResourceEstimateError
from srl.execution.policy import (
    OVERFLOW_ACTION,
    POLICY_FAIL_REASON,
    RESOURCE_POLICY_SCHEMA_VERSION,
    AdmissionDecision,
    PolicyError,
    ResourcePolicy,
    admit,
    load_policy,
)

# The shipped M1 policy, resolved relative to the repo root (tests run from the
# repo root under pytest).
_GIB = 1024**3
_POLICY_PATH = Path("policies/resource-policy-m1.json")

# Exact default caps pinned by the spec.
_DEFAULT_CPU = 1
_DEFAULT_RSS = 1610612736  # 1.5 GiB
_DEFAULT_WALL = 300
_DEFAULT_SCRATCH = 4294967296  # 4 GiB
_DEFAULT_FREE_DISK = 21474836480  # 20 GiB


# ---------------------------------------------------------------------------
# Loading and exact caps.
# ---------------------------------------------------------------------------


def test_load_policy_exact_default_caps() -> None:
    """The M1 policy loads with the exact six pinned default integers."""
    policy = load_policy(_POLICY_PATH)
    assert policy.name == "m1-default"
    assert policy.concurrency == 1
    assert policy.default.cpu_cores == _DEFAULT_CPU
    assert policy.default.rss_bytes == _DEFAULT_RSS
    assert policy.default.wall_seconds == _DEFAULT_WALL
    assert policy.default.scratch_bytes == _DEFAULT_SCRATCH
    assert policy.required_free_disk_bytes == _DEFAULT_FREE_DISK


def test_load_policy_safety_consts_and_overflow() -> None:
    """canonical_writes=0, grants_authority=False, overflow=WAIT_REMOTE_EXECUTOR."""
    policy = load_policy(_POLICY_PATH)
    assert policy.canonical_writes == 0
    assert policy.grants_authority is False
    assert policy.overflow_action == OVERFLOW_ACTION
    assert policy.overflow_action == "WAIT_REMOTE_EXECUTOR"


def test_load_policy_exception_envelope_values() -> None:
    """The shipped exception envelope is cpu=2, rss=2GiB, wall=900, scratch=4GiB."""
    policy = load_policy(_POLICY_PATH)
    assert policy.exception.cpu_cores == 2
    assert policy.exception.rss_bytes == 2 * _GIB
    assert policy.exception.wall_seconds == 900
    assert policy.exception.scratch_bytes == _DEFAULT_SCRATCH


def test_load_policy_missing_file() -> None:
    """A missing policy file raises PolicyError(CONTRACT_INVALID)."""
    with pytest.raises(PolicyError) as exc_info:
        load_policy("policies/does-not-exist.json")
    assert exc_info.value.fail_reason == POLICY_FAIL_REASON


def test_load_policy_bad_schema_version(tmp_path: Path) -> None:
    """A wrong schema_version is rejected."""
    p = tmp_path / "bad.json"
    p.write_text('{"schema_version":"ResourcePolicy/v0"}', encoding="utf-8")
    with pytest.raises(PolicyError) as exc_info:
        load_policy(p)
    assert exc_info.value.fail_reason == POLICY_FAIL_REASON


# ---------------------------------------------------------------------------
# Exception envelope bounds (each field rejected one step over its cap).
# ---------------------------------------------------------------------------


def _write_policy(tmp_path: Path, exception: dict[str, int]) -> Path:
    """Write an M1 policy doc with the given exception sub-object."""
    doc = {
        "schema_version": RESOURCE_POLICY_SCHEMA_VERSION,
        "name": "m1-default",
        "concurrency": 1,
        "cpu_cores": _DEFAULT_CPU,
        "rss_bytes": _DEFAULT_RSS,
        "wall_seconds": _DEFAULT_WALL,
        "scratch_bytes": _DEFAULT_SCRATCH,
        "required_free_disk_bytes": _DEFAULT_FREE_DISK,
        "exception": exception,
        "overflow_action": "WAIT_REMOTE_EXECUTOR",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    p = tmp_path / "policy.json"
    p.write_text(__import__("json").dumps(doc), encoding="utf-8")
    return p


def _valid_exception() -> dict[str, int]:
    """The canonical valid exception envelope."""
    return {
        "cpu_cores": 2,
        "rss_bytes": 2 * _GIB,
        "wall_seconds": 900,
        "scratch_bytes": _DEFAULT_SCRATCH,
    }


@pytest.mark.parametrize(
    ("field", "over_value"),
    [
        ("cpu_cores", 3),
        ("rss_bytes", 2 * _GIB + 1),
        ("wall_seconds", 901),
        ("scratch_bytes", _DEFAULT_SCRATCH + 1),
    ],
)
def test_exception_over_cap_rejected(tmp_path: Path, field: str, over_value: int) -> None:
    """An exception value beyond its absolute cap is rejected at load."""
    exception = {**_valid_exception(), field: over_value}
    p = _write_policy(tmp_path, exception)
    with pytest.raises(PolicyError) as exc_info:
        load_policy(p)
    assert exc_info.value.fail_reason == POLICY_FAIL_REASON


def test_exception_missing_key_rejected(tmp_path: Path) -> None:
    """An exception missing a key is rejected."""
    exception = _valid_exception()
    del exception["wall_seconds"]
    p = _write_policy(tmp_path, exception)
    with pytest.raises(PolicyError):
        load_policy(p)


def test_exception_extra_key_rejected(tmp_path: Path) -> None:
    """An exception with an extra key is rejected."""
    exception = {**_valid_exception(), "gpu_cores": 1}
    p = _write_policy(tmp_path, exception)
    with pytest.raises(PolicyError):
        load_policy(p)


def test_exception_valid_loads(tmp_path: Path) -> None:
    """The canonical valid exception loads cleanly (boundary values accepted)."""
    p = _write_policy(tmp_path, _valid_exception())
    policy = load_policy(p)
    assert policy.exception.cpu_cores == 2


def test_grants_authority_true_rejected(tmp_path: Path) -> None:
    """grants_authority=true is rejected (safety const)."""
    doc = {
        "schema_version": RESOURCE_POLICY_SCHEMA_VERSION,
        "name": "m1-default",
        "concurrency": 1,
        "cpu_cores": _DEFAULT_CPU,
        "rss_bytes": _DEFAULT_RSS,
        "wall_seconds": _DEFAULT_WALL,
        "scratch_bytes": _DEFAULT_SCRATCH,
        "required_free_disk_bytes": _DEFAULT_FREE_DISK,
        "exception": _valid_exception(),
        "overflow_action": "WAIT_REMOTE_EXECUTOR",
        "canonical_writes": 0,
        "grants_authority": True,
    }
    p = tmp_path / "policy.json"
    p.write_text(__import__("json").dumps(doc), encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(p)


# ---------------------------------------------------------------------------
# Admission matrix (no silent downgrade).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def policy() -> ResourcePolicy:
    """The shipped M1 policy, loaded once for the admission matrix."""
    return load_policy(_POLICY_PATH)


def test_admit_within_default(policy: ResourcePolicy) -> None:
    """An estimate at the default caps is ADMITTED_DEFAULT."""
    e = ResourceEstimate(
        wall_seconds=_DEFAULT_WALL,
        rss_bytes=_DEFAULT_RSS,
        scratch_bytes=_DEFAULT_SCRATCH,
        cpu_cores=_DEFAULT_CPU,
    )
    assert admit(e, policy) is AdmissionDecision.ADMITTED_DEFAULT


def test_admit_over_default_no_flag_parks(policy: ResourcePolicy) -> None:
    """Over default, within exception, no flag -> WAIT (no silent downgrade)."""
    e = ResourceEstimate(
        wall_seconds=900, rss_bytes=2 * _GIB, scratch_bytes=_DEFAULT_SCRATCH, cpu_cores=2
    )
    assert admit(e, policy, use_exception=False) is AdmissionDecision.WAIT_REMOTE_EXECUTOR


def test_admit_over_default_with_flag_admits_exception(policy: ResourcePolicy) -> None:
    """Over default, within exception, with flag -> ADMITTED_EXCEPTION."""
    e = ResourceEstimate(
        wall_seconds=900, rss_bytes=2 * _GIB, scratch_bytes=_DEFAULT_SCRATCH, cpu_cores=2
    )
    assert admit(e, policy, use_exception=True) is AdmissionDecision.ADMITTED_EXCEPTION


def test_admit_over_exception_with_flag_parks(policy: ResourcePolicy) -> None:
    """Over the exception caps, even with the flag -> WAIT."""
    e = ResourceEstimate(
        wall_seconds=901, rss_bytes=2 * _GIB, scratch_bytes=_DEFAULT_SCRATCH, cpu_cores=2
    )
    assert admit(e, policy, use_exception=True) is AdmissionDecision.WAIT_REMOTE_EXECUTOR


def test_admit_single_axis_over_default_parks(policy: ResourcePolicy) -> None:
    """Over default on a single axis (rss) parks without the flag."""
    e = ResourceEstimate(
        wall_seconds=_DEFAULT_WALL,
        rss_bytes=_DEFAULT_RSS + 1,
        scratch_bytes=_DEFAULT_SCRATCH,
        cpu_cores=_DEFAULT_CPU,
    )
    assert admit(e, policy, use_exception=False) is AdmissionDecision.WAIT_REMOTE_EXECUTOR


# ---------------------------------------------------------------------------
# Estimate validation and serialization.
# ---------------------------------------------------------------------------


def test_estimate_rejects_bool() -> None:
    """A bool field is rejected (a flag is not a quantity)."""
    with pytest.raises(ResourceEstimateError) as exc_info:
        ResourceEstimate(wall_seconds=True, rss_bytes=0, scratch_bytes=0, cpu_cores=0)  # type: ignore[arg-type]
    assert exc_info.value.fail_reason == ESTIMATE_FAIL_REASON


def test_estimate_rejects_negative() -> None:
    """A negative field is rejected."""
    with pytest.raises(ResourceEstimateError):
        ResourceEstimate(wall_seconds=-1, rss_bytes=0, scratch_bytes=0, cpu_cores=0)


def test_estimate_rejects_float() -> None:
    """A float field is rejected even when integral."""
    with pytest.raises(ResourceEstimateError):
        ResourceEstimate(wall_seconds=1.0, rss_bytes=0, scratch_bytes=0, cpu_cores=0)  # type: ignore[arg-type]


def test_estimate_digest_is_stable_and_prefixed() -> None:
    """Two equal estimates produce the same sha256: digest."""
    a = ResourceEstimate(wall_seconds=10, rss_bytes=20, scratch_bytes=30, cpu_cores=1)
    b = ResourceEstimate(wall_seconds=10, rss_bytes=20, scratch_bytes=30, cpu_cores=1)
    assert a.digest() == b.digest()
    assert a.digest().startswith("sha256:")
    assert len(a.digest()) == len("sha256:") + 64


def test_estimate_digest_differs_on_content() -> None:
    """Different estimates produce different digests."""
    a = ResourceEstimate(wall_seconds=10, rss_bytes=20, scratch_bytes=30, cpu_cores=1)
    b = ResourceEstimate(wall_seconds=11, rss_bytes=20, scratch_bytes=30, cpu_cores=1)
    assert a.digest() != b.digest()


def test_estimate_canonical_bytes_endwith_newline() -> None:
    """Canonical bytes end with a single trailing newline."""
    e = ResourceEstimate(wall_seconds=1, rss_bytes=1, scratch_bytes=1, cpu_cores=1)
    blob = e.canonical_bytes()
    assert blob.endswith(b"\n")
    assert blob.count(b"\n") == 1
