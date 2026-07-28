"""Unit tests for the machine-enforced lane ledger (``srl.autonomy.lanes``).

These tests pin the three acquire-time invariants (cap, disjoint ownership,
worktree uniqueness), the lease lifecycle (heartbeat, expiry, release), and
the persistence contract (atomic, canonical, byte-stable). They also pin
that the ``automation/state.schema.json`` extension is backward compatible.

All tests are hermetic (``tmp_path``). The policy cap is read from the
committed ``automation/policy.json`` (currently 6) so the cap test tracks
the real policy rather than a hardcoded copy.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from srl.autonomy.lanes import (
    CONTRACT_INVALID_FAIL_REASON,
    DEFAULT_LEASE_TTL_SECONDS,
    LEDGER_SCHEMA_VERSION,
    ORPHAN_PROCESS_FAIL_REASON,
    Executor,
    LaneError,
    LaneLedger,
    LaneStatus,
    PathOwnershipError,
    acquire_lane,
    expire_leases,
    heartbeat,
    load_ledger,
    policy_lane_cap,
    release_lane,
    save_ledger,
    worktree_fingerprint,
)
from srl.autonomy.policy import load_policy

_POLICY_PATH = Path("automation/policy.json")
_LEDGER_PATH = Path("automation/lanes.json")
_SCHEMA_PATH = Path("automation/state.schema.json")

_TS0 = "2026-07-28T08:00:00Z"
_TS_LATER = "2026-07-28T08:30:00Z"  # 30 min later > default TTL of 15 min


def _cap() -> int:
    """Read the real policy cap so cap tests track the policy, not a copy."""
    return policy_lane_cap(load_policy(_POLICY_PATH))


def _acquire(  # noqa: PLR0913 (test helper; kw-only mirrors acquire_lane's contract)
    ledger: LaneLedger,
    *,
    lane_id: str,
    owned: tuple[str, ...],
    worktree: str = "/wt/a",
    branch: str = "feat/a",
    now: str = _TS0,
) -> object:
    """Thin wrapper over acquire_lane with defaults for the test matrix."""
    return acquire_lane(
        ledger,
        wp_id=f"WP-{lane_id}",
        executor=Executor.GLM_52,
        worktree_path=worktree,
        branch=branch,
        base_sha="0" * 40,
        owned_paths=owned,
        lane_id=lane_id,
        now=now,
        policy=_POLICY_PATH,
    )


# ---------------------------------------------------------------------------
# Cap enforcement (invariant 1).
# ---------------------------------------------------------------------------


def test_policy_lane_cap_reads_committed_policy() -> None:
    """policy_lane_cap returns the policy's value (6), not a hardcoded copy."""
    cap = _cap()
    assert cap == 6


def test_acquire_up_to_cap_then_reject(tmp_path: Path) -> None:
    """Acquiring the cap number of lanes succeeds; one more is rejected."""
    cap = _cap()
    ledger = LaneLedger()
    for i in range(cap):
        entry = _acquire(
            ledger,
            lane_id=f"lane-{i}",
            owned=(f"src/srl/mod{i}/",),
            worktree=f"/wt/{i}",
        )
        assert entry.status == LaneStatus.ACTIVE
    assert len([e for e in ledger.lanes if e.status == LaneStatus.ACTIVE]) == cap
    # One more exceeds the cap.
    with pytest.raises(LaneError) as exc_info:
        _acquire(ledger, lane_id="lane-extra", owned=("src/srl/extra/",), worktree="/wt/extra")
    assert "cap" in str(exc_info.value).lower()


def test_cap_takes_effect_from_real_policy(tmp_path: Path) -> None:
    """The cap is enforced from the loaded policy dict, not a constant."""
    ledger = LaneLedger()
    # Use a policy dict with cap=2 to prove the bound follows the policy.
    small_policy = {"max_parallel_implementation_lanes": 2}
    acquire_lane(
        ledger,
        wp_id="WP-a",
        executor=Executor.GLM_52,
        worktree_path="/wt/a",
        branch="b",
        base_sha="0" * 40,
        owned_paths=("src/srl/a/",),
        lane_id="a",
        now=_TS0,
        policy=small_policy,
    )
    acquire_lane(
        ledger,
        wp_id="WP-b",
        executor=Executor.GLM_52,
        worktree_path="/wt/b",
        branch="b",
        base_sha="0" * 40,
        owned_paths=("src/srl/b/",),
        lane_id="b",
        now=_TS0,
        policy=small_policy,
    )
    with pytest.raises(LaneError):
        acquire_lane(
            ledger,
            wp_id="WP-c",
            executor=Executor.GLM_52,
            worktree_path="/wt/c",
            branch="b",
            base_sha="0" * 40,
            owned_paths=("src/srl/c/",),
            lane_id="c",
            now=_TS0,
            policy=small_policy,
        )


# ---------------------------------------------------------------------------
# Disjoint ownership matrix (invariant 2).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("existing", "candidate", "label"),
    [
        ("src/srl/foo/", "src/srl/foo/", "exact match"),
        ("src/srl/foo/", "src/srl/foo/sub.py", "candidate nests under existing"),
        ("src/srl/foo/sub/", "src/srl/foo/", "candidate encloses existing"),
        ("src/srl/foo", "src/srl/foo/bar", "no trailing slash, prefix-of"),
        ("src/srl/foo/bar", "src/srl/foo", "no trailing slash, prefixed-by"),
    ],
)
def test_overlapping_owned_paths_rejected(existing: str, candidate: str, label: str) -> None:
    """Exact, prefix-of, and prefixed-by ownership collisions are rejected."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="holder", owned=(existing,), worktree="/wt/holder")
    with pytest.raises(PathOwnershipError) as exc_info:
        _acquire(ledger, lane_id="newcomer", owned=(candidate,), worktree="/wt/newcomer")
    assert exc_info.value.conflicting_lane_id == "holder"
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON
    assert label  # parametrize label surfaced on failure


def test_sibling_owned_paths_are_disjoint() -> None:
    """Sibling directories do not collide and both acquire successfully."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a")
    _acquire(ledger, lane_id="b", owned=("src/srl/b/",), worktree="/wt/b")
    active = [e for e in ledger.lanes if e.status == LaneStatus.ACTIVE]
    assert {e.lane_id for e in active} == {"a", "b"}


def test_disjointness_checks_all_owned_paths_of_new_lane() -> None:
    """A collision on any one of the new lane's owned paths rejects the lane."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="holder", owned=("src/srl/hold/",), worktree="/wt/h")
    # The new lane owns one disjoint path and one that nests under the holder.
    with pytest.raises(PathOwnershipError) as exc_info:
        _acquire(
            ledger,
            lane_id="newcomer",
            owned=("src/srl/fresh/", "src/srl/hold/inside.py"),
            worktree="/wt/n",
        )
    assert exc_info.value.conflicting_lane_id == "holder"


def test_released_lane_releases_ownership() -> None:
    """A parked/completed lane no longer blocks ownership for a new lane."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="first", owned=("src/srl/x/",), worktree="/wt/first")
    release_lane(ledger, "first", LaneStatus.COMPLETED)
    # The same path is now acquirable by a new lane.
    entry = _acquire(ledger, lane_id="second", owned=("src/srl/x/",), worktree="/wt/second")
    assert entry.status == LaneStatus.ACTIVE


# ---------------------------------------------------------------------------
# Worktree uniqueness (invariant 3).
# ---------------------------------------------------------------------------


def test_duplicate_worktree_fingerprint_rejected() -> None:
    """One worktree, one lane: a duplicate fingerprint is rejected."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/same")
    with pytest.raises(LaneError) as exc_info:
        _acquire(ledger, lane_id="b", owned=("src/srl/b/",), worktree="/wt/same")
    assert "worktree" in str(exc_info.value).lower()


def test_duplicate_lane_id_rejected() -> None:
    """A duplicate lane_id among active lanes is rejected."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="dup", owned=("src/srl/a/",), worktree="/wt/a")
    with pytest.raises(LaneError):
        _acquire(ledger, lane_id="dup", owned=("src/srl/b/",), worktree="/wt/b")


def test_worktree_fingerprint_never_persists_raw_path(tmp_path: Path) -> None:
    """The raw absolute worktree path is never written to the ledger file."""
    ledger = LaneLedger()
    secret_path = "/srv/srl-lane/worktree"  # noqa: S105 (a synthetic path, not a secret)
    _acquire(
        ledger,
        lane_id="a",
        owned=("src/srl/a/",),
        worktree=secret_path,
    )
    out = tmp_path / "lanes.json"
    save_ledger(ledger, out)
    raw = out.read_text(encoding="utf-8")
    assert secret_path not in raw
    assert worktree_fingerprint(secret_path) in raw


# ---------------------------------------------------------------------------
# Lease lifecycle: heartbeat, expiry, release.
# ---------------------------------------------------------------------------


def test_heartbeat_refreshes_timestamp() -> None:
    """heartbeat updates heartbeat_utc without changing ownership or status."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a", now=_TS0)
    updated = heartbeat(ledger, "a", now=_TS_LATER)
    assert updated.lease.heartbeat_utc == _TS_LATER
    assert updated.lease.acquired_utc == _TS0
    assert updated.status == LaneStatus.ACTIVE


def test_heartbeat_unknown_lane_raises() -> None:
    """heartbeating an unknown or non-active lane raises."""
    ledger = LaneLedger()
    with pytest.raises(LaneError):
        heartbeat(ledger, "nope", now=_TS_LATER)


def test_lease_expiry_stops_stale_lane() -> None:
    """A lane whose heartbeat is older than its TTL is stopped on expire."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a", now=_TS0)
    # No heartbeat; advancing well past the TTL expires the lane.
    expired = expire_leases(ledger, now=_TS_LATER)
    assert len(expired) == 1
    assert expired[0].lane_id == "a"
    assert expired[0].status == LaneStatus.STOPPED


def test_lease_expiry_keeps_heartbeating_lane_alive() -> None:
    """A lane that heartbeated within the TTL survives expiry."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a", now=_TS0)
    heartbeat(ledger, "a", now=_TS_LATER)
    # Expiry at the same instant as the last heartbeat keeps it alive.
    expired = expire_leases(ledger, now=_TS_LATER)
    assert expired == []
    active = [e for e in ledger.lanes if e.status == LaneStatus.ACTIVE]
    assert len(active) == 1


def test_expired_lane_releases_cap_slot() -> None:
    """After expiry, the freed cap slot allows a new lane to be acquired."""
    cap = _cap()
    ledger = LaneLedger()
    for i in range(cap):
        _acquire(
            ledger,
            lane_id=f"lane-{i}",
            owned=(f"src/srl/m{i}/",),
            worktree=f"/wt/{i}",
        )
    # Cap is full.
    with pytest.raises(LaneError):
        _acquire(ledger, lane_id="extra", owned=("src/srl/z/",), worktree="/wt/z")
    # Expire them all, freeing the cap.
    expire_leases(ledger, now=_TS_LATER)
    # Now a brand-new disjoint lane acquires successfully.
    entry = _acquire(ledger, lane_id="fresh", owned=("src/srl/fresh/",), worktree="/wt/fresh")
    assert entry.status == LaneStatus.ACTIVE


def test_expire_leases_fail_reason_is_orphan() -> None:
    """Expiry records the ORPHAN_PROCESS_DETECTED fail reason in the docstring contract.

    The fail reason is a module constant; this test pins that the constant
    matches the documented registry entry.
    """
    assert ORPHAN_PROCESS_FAIL_REASON == "ORPHAN_PROCESS_DETECTED"


# ---------------------------------------------------------------------------
# Release: idempotency and status validation.
# ---------------------------------------------------------------------------


def test_release_is_idempotent() -> None:
    """Releasing an already-released lane with the same status is a no-op."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a")
    first = release_lane(ledger, "a", LaneStatus.PARKED)
    # Releasing again into the same status must not raise and must not add a
    # second entry: the lane record is unchanged.
    second = release_lane(ledger, "a", LaneStatus.PARKED)
    assert first.status == LaneStatus.PARKED
    assert second.status == LaneStatus.PARKED
    entries = [e for e in ledger.lanes if e.lane_id == "a"]
    assert len(entries) == 1
    assert entries[0].status == LaneStatus.PARKED


def test_release_then_re_release_to_different_status() -> None:
    """Releasing a parked lane to completed updates the status."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a")
    release_lane(ledger, "a", LaneStatus.PARKED)
    updated = release_lane(ledger, "a", LaneStatus.COMPLETED)
    assert updated.status == LaneStatus.COMPLETED


def test_release_rejects_active_status() -> None:
    """active is not an admissible release status (use heartbeat)."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a")
    with pytest.raises(LaneError):
        release_lane(ledger, "a", LaneStatus.ACTIVE)


def test_release_unknown_lane_raises() -> None:
    """Releasing an unknown lane raises."""
    ledger = LaneLedger()
    with pytest.raises(LaneError):
        release_lane(ledger, "nope", LaneStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Persistence: canonical, atomic, byte-stable, round-trip.
# ---------------------------------------------------------------------------


def test_committed_ledger_loads_and_is_empty() -> None:
    """The committed automation/lanes.json loads as an empty ActiveLaneLedger/v1."""
    ledger = load_ledger(_LEDGER_PATH)
    assert ledger.schema_version == LEDGER_SCHEMA_VERSION
    assert ledger.lanes == []


def test_committed_ledger_is_canonical_json() -> None:
    """The committed ledger is sorted-key, compact, ASCII, with trailing newline."""
    raw = _LEDGER_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert raw == canonical + "\n"


def test_save_load_round_trip(tmp_path: Path) -> None:
    """A saved ledger round-trips through load with no loss."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="b", owned=("src/srl/b/",), worktree="/wt/b")
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a")
    out = tmp_path / "lanes.json"
    save_ledger(ledger, out)
    reloaded = load_ledger(out)
    assert [e.lane_id for e in reloaded.lanes] == ["a", "b"]  # canonical sort
    assert reloaded.lanes[0].executor == Executor.GLM_52
    assert reloaded.lanes[0].lease.ttl_seconds == DEFAULT_LEASE_TTL_SECONDS


def test_save_is_byte_stable(tmp_path: Path) -> None:
    """Saving the same ledger twice yields byte-identical files."""
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a")
    _acquire(ledger, lane_id="b", owned=("src/srl/b/",), worktree="/wt/b")
    out1 = tmp_path / "lanes1.json"
    out2 = tmp_path / "lanes2.json"
    save_ledger(ledger, out1)
    save_ledger(ledger, out2)
    assert out1.read_bytes() == out2.read_bytes()


def test_save_is_atomic_on_mid_write_failure(tmp_path: Path) -> None:
    """A crash during the atomic write leaves the old ledger intact.

    Injects a failure at os.replace (the publish step). The temp is cleaned
    up and the previously-persisted ledger is untouched (old state, not
    partial). This mirrors the CAS engine crash-safety contract.
    """
    ledger = LaneLedger()
    _acquire(ledger, lane_id="a", owned=("src/srl/a/",), worktree="/wt/a")
    out = tmp_path / "lanes.json"
    save_ledger(ledger, out)
    old_bytes = out.read_bytes()

    # Mutate the ledger and attempt a save whose os.replace fails.
    ledger2 = LaneLedger()
    _acquire(ledger2, lane_id="b", owned=("src/srl/b/",), worktree="/wt/b")

    def boom(src: Path | str, dst: Path | str) -> None:
        raise OSError("injected: os.replace failed")

    with patch("srl.autonomy.lanes.os.replace", side_effect=boom):
        with pytest.raises(OSError):
            save_ledger(ledger2, out)

    # The original ledger is byte-intact (atomic: old-or-new, never partial).
    assert out.read_bytes() == old_bytes
    # No leftover temp file in the directory.
    leftovers = [p.name for p in out.parent.iterdir() if p.name.startswith(".atomic-")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# state.schema.json extension: backward compatibility.
# ---------------------------------------------------------------------------


def test_state_schema_extension_is_backward_compatible() -> None:
    """Documents without the new fields still validate: the new fields are
    optional (not in 'required'), and the minimal AutomationState keys are
    still the only required ones.
    """
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    # The new fields exist and are optional.
    assert "active_lanes" in schema["properties"]
    assert "max_lanes" in schema["properties"]
    assert "active_lanes" not in schema["required"]
    assert "max_lanes" not in schema["required"]
    # The original required set is unchanged.
    assert schema["required"] == ["mission_digest", "current_wp", "terminal_status"]


def test_state_schema_max_lanes_matches_policy_cap() -> None:
    """The max_lanes const in the schema equals the policy cap (single source)."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    max_lanes_const = schema["properties"]["max_lanes"]["const"]
    assert max_lanes_const == _cap()


def test_state_schema_active_lanes_shape_mirrors_ledger_entry() -> None:
    """The active_lanes item shape carries the full lane-entry contract."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    item_props = schema["properties"]["active_lanes"]["items"]["properties"]
    for field in (
        "lane_id",
        "wp_id",
        "executor",
        "worktree_fingerprint",
        "branch",
        "base_sha",
        "owned_paths",
        "lease",
        "status",
    ):
        assert field in item_props, f"active_lanes item missing {field}"
    # executor and status enums are closed.
    assert set(item_props["executor"]["enum"]) == {e.value for e in Executor}
    assert set(item_props["status"]["enum"]) == {s.value for s in LaneStatus}
