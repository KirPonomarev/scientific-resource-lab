#!/usr/bin/env python3
"""Governance gate for machine-enforced lane management (GOV-01..GOV-05).

Runs the five governance checks for the active-lane ledger and prints a
single canonical ``GateReceipt/v1`` JSON line to stdout. Exits 0 only if
every check PASSes; any FAIL makes the exit code non-zero so the gate can
be wired into CI and ``make gate-gov``.

The checks
----------
GOV-01 policy cap == schema max_lanes, and the gate enforces that cap
    Reads BOTH ``automation/policy.json`` (the lane cap) and
    ``automation/state.schema.json`` (the ``max_lanes`` const) and proves
    they agree. The cap the gate enforces is *derived* from the policy via
    ``srl.autonomy.lanes.policy_lane_cap``; the gate never hardcodes a lane
    number, so a test fails if the policy says 6 but the gate enforced
    another number.

GOV-02 acquire enforces the cap
    Acquiring the cap number of disjoint lanes succeeds; acquiring one more
    is rejected. Proves the bound the policy declares is the bound
    ``acquire_lane`` actually enforces.

GOV-03 overlapping owned paths rejected
    The disjointness matrix: exact-match, prefix-of (candidate nests under
    an existing owned path), and prefixed-by (candidate encloses an existing
    owned path) all raise ``PathOwnershipError`` naming the conflicting lane.

GOV-04 lease expiry stops the lane
    A lane whose heartbeat is older than its TTL is transitioned to
    ``stopped`` by ``expire_leases`` (fail reason ``ORPHAN_PROCESS_DETECTED``).

GOV-05 ledger write is atomic
    Injecting a failure mid-write (``os.replace`` patched to raise) leaves
    the previously-persisted ledger byte-intact. No partial state, no
    leftover temp.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/gov-lanes-gate.py`` without a prior ``uv run``, and
also works under ``uv run`` (idempotent path insertion).

This is a governance-change WP touching protected paths (``automation/``,
``ci.yml``). Per GOVERNANCE.md the old verifier (full pytest + wp03-gate)
must pass against the new diff before the PR opens; those are run in the
PR gates, not here.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/gov-lanes-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.autonomy.lanes import (  # noqa: E402  (path setup must precede import)
    CONTRACT_INVALID_FAIL_REASON,
    LEDGER_SCHEMA_VERSION,
    Executor,
    LaneEntry,
    LaneError,
    LaneLedger,
    LaneStatus,
    PathOwnershipError,
    acquire_lane,
    expire_leases,
    heartbeat,
    policy_lane_cap,
    save_ledger,
)
from srl.autonomy.policy import load_policy  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-GOV-LANES"

# Canonical paths the gate reads to prove the cap has a single source.
_POLICY_PATH = _REPO_ROOT / "automation" / "policy.json"
_SCHEMA_PATH = _REPO_ROOT / "automation" / "state.schema.json"

# Test timestamp anchors for lease lifecycle checks.
_TS_ACQUIRE: Final[str] = "2026-07-28T08:00:00Z"
_TS_EXPIRED: Final[str] = "2026-07-28T08:30:00Z"  # 30 min later > default 15 min TTL
# Argument count for the single-check CLI form: "--check <id>".
_SINGLE_CHECK_ARGC: Final[int] = 2


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact) to stdout."""
    line = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _schema_max_lanes() -> int | None:
    """Return the ``max_lanes`` const from the state schema, or None if absent."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    prop = schema.get("properties", {}).get("max_lanes", {})
    const = prop.get("const")
    return int(const) if isinstance(const, int) else None


# ---------------------------------------------------------------------------
# GOV-01: policy cap == schema max_lanes, and the gate enforces that cap.
# ---------------------------------------------------------------------------


def _check_gov_01() -> dict[str, Any]:
    """GOV-01: the policy cap and the schema max_lanes agree.

    Reads the cap from the policy via ``policy_lane_cap`` (the same symbol
    ``acquire_lane`` uses) and the ``max_lanes`` const from the schema, and
    asserts they are equal. The cap the gate reports is *derived*, not
    hardcoded: if the policy said 6 but the gate reported any other number,
    this check would FAIL because the two sources would disagree.
    """
    try:
        policy = load_policy(_POLICY_PATH)
    except Exception as exc:  # gate must report any loader failure as evidence
        return {"status": "FAIL", "detail": f"policy load failed: {exc}"}
    cap = policy_lane_cap(policy)
    schema_cap = _schema_max_lanes()
    if schema_cap is None:
        return {"status": "FAIL", "detail": "schema has no max_lanes const"}
    if cap != schema_cap:
        return {
            "status": "FAIL",
            "detail": f"policy cap {cap} != schema max_lanes {schema_cap}",
            "policy_cap": cap,
            "schema_max_lanes": schema_cap,
        }
    return {
        "status": "PASS",
        "detail": "policy cap == schema max_lanes; gate derives cap from policy (no hardcode)",
        "policy_cap": cap,
        "schema_max_lanes": schema_cap,
        "policy_key": "max_parallel_implementation_lanes",
    }


# ---------------------------------------------------------------------------
# GOV-02: acquire enforces the cap.
# ---------------------------------------------------------------------------


def _check_gov_02() -> dict[str, Any]:
    """GOV-02: acquire_lane admits the cap number of lanes and rejects one more.

    The cap is read from the policy (via the same symbol acquire_lane uses),
    so this check tracks the real policy value. Acquiring ``cap`` disjoint
    lanes must succeed; the ``cap + 1`` lane must be rejected with a cap
    error.
    """
    policy = load_policy(_POLICY_PATH)
    cap = policy_lane_cap(policy)
    ledger = LaneLedger()
    for i in range(cap):
        acquire_lane(
            ledger,
            wp_id=f"WP-{i}",
            executor=Executor.GLM_52,
            worktree_path=f"/wt/{i}",
            branch=f"feat/{i}",
            base_sha="0" * 40,
            owned_paths=(f"src/srl/mod{i}/",),
            lane_id=f"lane-{i}",
            now=_TS_ACQUIRE,
            policy=policy,
        )
    active = [e for e in ledger.lanes if e.status == LaneStatus.ACTIVE]
    if len(active) != cap:
        return {
            "status": "FAIL",
            "detail": f"expected {cap} active lanes after {cap} acquires, got {len(active)}",
        }
    # One more exceeds the cap.
    rejected = False
    fail_reason: str | None = None
    try:
        acquire_lane(
            ledger,
            wp_id="WP-extra",
            executor=Executor.GLM_52,
            worktree_path="/wt/extra",
            branch="feat/extra",
            base_sha="0" * 40,
            owned_paths=("src/srl/extra/",),
            lane_id="lane-extra",
            now=_TS_ACQUIRE,
            policy=policy,
        )
    except LaneError as exc:
        rejected = True
        fail_reason = exc.fail_reason
    if not rejected:
        return {"status": "FAIL", "detail": f"acquire_lane admitted lane #{cap + 1} past the cap"}
    return {
        "status": "PASS",
        "detail": f"acquire enforces cap: {cap} admitted, {cap + 1} rejected",
        "cap": cap,
        "active_after_cap_acquires": len(active),
        "reject_fail_reason": fail_reason,
    }


# ---------------------------------------------------------------------------
# GOV-03: overlapping owned paths rejected (exact, prefix-of, prefixed-by).
# ---------------------------------------------------------------------------


def _check_gov_03() -> dict[str, Any]:
    """GOV-03: the disjointness matrix is enforced.

    For each of the three collision classes, acquire a holder lane with an
    owned path, then attempt to acquire a newcomer whose owned path collides.
    Each must raise ``PathOwnershipError`` naming the holder, with fail
    reason ``CONTRACT_INVALID``.
    """
    matrix = [
        ("exact", "src/srl/hold/", "src/srl/hold/"),
        ("prefix_of", "src/srl/hold/", "src/srl/hold/sub.py"),
        ("prefixed_by", "src/srl/hold/sub/", "src/srl/hold/"),
    ]
    results: dict[str, dict[str, Any]] = {}
    for label, holder_owned, newcomer_owned in matrix:
        ledger = LaneLedger()
        acquire_lane(
            ledger,
            wp_id="WP-hold",
            executor=Executor.GLM_52,
            worktree_path="/wt/holder",
            branch="feat/hold",
            base_sha="0" * 40,
            owned_paths=(holder_owned,),
            lane_id="holder",
            now=_TS_ACQUIRE,
            policy=_POLICY_PATH,
        )
        collision_id: str | None = None
        fail_reason: str | None = None
        raised = False
        try:
            acquire_lane(
                ledger,
                wp_id="WP-new",
                executor=Executor.GLM_52,
                worktree_path="/wt/newcomer",
                branch="feat/new",
                base_sha="0" * 40,
                owned_paths=(newcomer_owned,),
                lane_id="newcomer",
                now=_TS_ACQUIRE,
                policy=_POLICY_PATH,
            )
        except PathOwnershipError as exc:
            raised = True
            collision_id = exc.conflicting_lane_id
            fail_reason = exc.fail_reason
        if not raised:
            return {
                "status": "FAIL",
                "detail": f"collision class {label!r} was not rejected",
            }
        if collision_id != "holder":
            return {
                "status": "FAIL",
                "detail": f"collision class {label!r} named wrong lane {collision_id!r}",
            }
        if fail_reason != CONTRACT_INVALID_FAIL_REASON:
            return {
                "status": "FAIL",
                "detail": f"collision class {label!r} had fail_reason {fail_reason!r}",
            }
        results[label] = {"conflicting_lane_id": collision_id, "fail_reason": fail_reason}
    return {
        "status": "PASS",
        "detail": "exact / prefix-of / prefixed-by collisions all rejected",
        "matrix": results,
    }


# ---------------------------------------------------------------------------
# GOV-04: lease expiry stops the lane.
# ---------------------------------------------------------------------------


def _check_gov_04() -> dict[str, Any]:
    """GOV-04: a lane past its TTL is stopped by expire_leases.

    Acquires a lane, advances the clock well past the TTL without a
    heartbeat, and asserts ``expire_leases`` stops it. A heartbeating lane
    in the same ledger must survive.
    """
    ledger = LaneLedger()
    # Stale lane: acquired at _TS_ACQUIRE, never heartbeated.
    acquire_lane(
        ledger,
        wp_id="WP-stale",
        executor=Executor.GLM_52,
        worktree_path="/wt/stale",
        branch="feat/stale",
        base_sha="0" * 40,
        owned_paths=("src/srl/stale/",),
        lane_id="stale",
        now=_TS_ACQUIRE,
        policy=_POLICY_PATH,
    )
    # Fresh lane: acquired and heartbeated at the expiry instant.
    fresh = acquire_lane(
        ledger,
        wp_id="WP-fresh",
        executor=Executor.GLM_52,
        worktree_path="/wt/fresh",
        branch="feat/fresh",
        base_sha="0" * 40,
        owned_paths=("src/srl/fresh/",),
        lane_id="fresh",
        now=_TS_EXPIRED,
        policy=_POLICY_PATH,
    )
    heartbeat(ledger, fresh.lane_id, now=_TS_EXPIRED)
    expired: list[LaneEntry] = expire_leases(ledger, now=_TS_EXPIRED)
    expired_ids = {e.lane_id for e in expired}
    if "stale" not in expired_ids:
        return {"status": "FAIL", "detail": "stale lane was not expired"}
    statuses = {e.lane_id: e.status.value for e in ledger.lanes}
    if statuses.get("stale") != "stopped":
        return {
            "status": "FAIL",
            "detail": f"stale lane status is {statuses.get('stale')!r}, expected 'stopped'",
        }
    if statuses.get("fresh") != "active":
        return {
            "status": "FAIL",
            "detail": f"fresh lane was expired: status {statuses.get('fresh')!r}",
        }
    return {
        "status": "PASS",
        "detail": "stale lane stopped; heartbeating lane survived",
        "expired": sorted(expired_ids),
        "statuses": statuses,
    }


# ---------------------------------------------------------------------------
# GOV-05: ledger write is atomic.
# ---------------------------------------------------------------------------


def _check_gov_05() -> dict[str, Any]:
    """GOV-05: a mid-write failure leaves the old ledger byte-intact.

    Writes a ledger, records its bytes, then attempts a second write whose
    ``os.replace`` is patched to raise. The original file must be
    byte-identical (old state, never partial), and no ``.atomic-`` temp may
    remain in the directory.
    """
    ledger_a = LaneLedger()
    acquire_lane(
        ledger_a,
        wp_id="WP-a",
        executor=Executor.GLM_52,
        worktree_path="/wt/a",
        branch="feat/a",
        base_sha="0" * 40,
        owned_paths=("src/srl/a/",),
        lane_id="a",
        now=_TS_ACQUIRE,
        policy=_POLICY_PATH,
    )
    work_dir = Path(tempfile.mkdtemp(prefix="gov05-"))
    out = work_dir / "lanes.json"
    save_ledger(ledger_a, out)
    old_bytes = out.read_bytes()

    ledger_b = LaneLedger()
    acquire_lane(
        ledger_b,
        wp_id="WP-b",
        executor=Executor.GLM_52,
        worktree_path="/wt/b",
        branch="feat/b",
        base_sha="0" * 40,
        owned_paths=("src/srl/b/",),
        lane_id="b",
        now=_TS_ACQUIRE,
        policy=_POLICY_PATH,
    )

    def boom(_src: Path | str, _dst: Path | str) -> None:
        raise OSError("injected: os.replace failed")

    failed_correctly = False
    with patch("srl.autonomy.lanes.os.replace", side_effect=boom):
        try:
            save_ledger(ledger_b, out)
        except OSError:
            failed_correctly = True

    if not failed_correctly:
        return {"status": "FAIL", "detail": "injected os.replace failure did not surface"}
    new_bytes = out.read_bytes()
    if new_bytes != old_bytes:
        return {
            "status": "FAIL",
            "detail": "ledger file changed despite the atomic-write failure",
        }
    leftovers = [p.name for p in work_dir.iterdir() if p.name.startswith(".atomic-")]
    if leftovers:
        return {"status": "FAIL", "detail": f"leftover temp files: {leftovers}"}
    return {
        "status": "PASS",
        "detail": "mid-write failure left the old ledger byte-intact; no leftover temp",
        "schema_version": LEDGER_SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Evidence + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: policy + schema sources for the cap."""
    policy = load_policy(_POLICY_PATH)
    return {
        "policy": {
            "schema_version": policy["schema_version"],
            "cap": policy_lane_cap(policy),
        },
        "schema_max_lanes": _schema_max_lanes(),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "GOV-01": _check_gov_01(),
        "GOV-02": _check_gov_02(),
        "GOV-03": _check_gov_03(),
        "GOV-04": _check_gov_04(),
        "GOV-05": _check_gov_05(),
    }
    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {"sources": _evidence(), "statuses": statuses},
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode.
    if args and args[0] == "--check" and len(args) == _SINGLE_CHECK_ARGC:
        cid = args[1]
        runners = {
            "GOV-01": _check_gov_01,
            "GOV-02": _check_gov_02,
            "GOV-03": _check_gov_03,
            "GOV-04": _check_gov_04,
            "GOV-05": _check_gov_05,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "error": f"unknown check {cid}"})
            return 2
        result = runner()
        _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "check": cid, **result})
        return 0 if result["status"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior: run from repo root.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
