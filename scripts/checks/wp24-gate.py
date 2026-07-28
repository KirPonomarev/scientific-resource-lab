#!/usr/bin/env python3
"""WP-C24 acceptance gate for the deterministic capability catalog snapshot.

Runs the four WP-C24 checks, prints a single canonical ``GateReceipt/v1`` JSON
line to stdout, and exits 0 only if every check PASSes. The gate exercises the
catalog snapshot's identity invariants, the identity/dynamic split, the
store-absent query path, and tamper detection.

Checks
------
C24-01 shuffled entries -> same bytes + merkle
    Building a snapshot over the same entries in a different input order yields
    byte-identical canonical bytes, an equal ``merkle_root``, and an equal
    ``snapshot_id``. Identity is a pure function of the entry set, not the order.

C24-02 location mutation changes location_state_ref only
    Mutating the dynamic location map changes ``location_state_ref`` but leaves
    ``snapshot_id``, ``merkle_root``, and the canonical entry bytes unchanged.
    Location is dynamic and never part of identity.

C24-03 queryable with the artifact store absent
    The local cache lists and inspects capabilities when the artifact store is
    absent; every capability reports ``{"state": "unknown"}`` (registry presence
    never implies readiness), and the identity fields are still surfaced.

C24-04 tampered entry detected
    Mutating a single entry field (e.g. ``adapter_id``) so the recorded
    ``merkle_root`` no longer matches the recomputed one raises
    ``SnapshotMismatchError`` with fail reason ``CONTRACT_INVALID``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp24-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.catalog import (  # noqa: E402
    SnapshotCache,
    SnapshotMismatchError,
    build_default_registry,
    build_snapshot,
    verify_snapshot,
)
from srl.contracts import dumps  # noqa: E402
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-C24"

# Short aliases for the fail reasons used in assertions below.
CONTRACT_INVALID: Final[str] = CONTRACT_INVALID_FAIL_REASON

# A fixed UTC timestamp so the gate is hermetic (no wall-clock dependence).
_FIXED_UTC: Final[str] = "2026-07-28T00:00:00Z"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# C24-01: shuffled entries -> same bytes + merkle + id.
# ---------------------------------------------------------------------------


def _check_c24_01() -> dict[str, Any]:
    """C24-01: input order does not affect bytes, merkle_root, or snapshot_id."""
    entries = list(build_default_registry())
    forward = build_snapshot(entries, created_utc=_FIXED_UTC)

    shuffled = list(entries)
    # Reverse and swap two interior entries to defeat any accidental ordering.
    shuffled.reverse()
    shuffled[0], shuffled[7] = shuffled[7], shuffled[0]
    backward = build_snapshot(shuffled, created_utc=_FIXED_UTC)

    same_bytes = forward.canonical_dumps() == backward.canonical_dumps()
    same_merkle = forward.merkle_root == backward.merkle_root
    same_id = forward.snapshot_id == backward.snapshot_id

    if same_bytes and same_merkle and same_id:
        return {
            "status": "PASS",
            "detail": (
                "shuffled entries produce identical canonical bytes, merkle_root, and snapshot_id"
            ),
            "evidence": {
                "forward_id": forward.snapshot_id,
                "backward_id": backward.snapshot_id,
                "merkle_root": forward.merkle_root,
                "entry_count": len(entries),
            },
        }
    return {
        "status": "FAIL",
        "detail": (
            f"order-dependence detected: same_bytes={same_bytes}, "
            f"same_merkle={same_merkle}, same_id={same_id}"
        ),
        "evidence": {
            "forward_id": forward.snapshot_id,
            "backward_id": backward.snapshot_id,
            "forward_merkle": forward.merkle_root,
            "backward_merkle": backward.merkle_root,
        },
    }


# ---------------------------------------------------------------------------
# C24-02: location mutation changes location_state_ref only.
# ---------------------------------------------------------------------------


def _check_c24_02() -> dict[str, Any]:
    """C24-02: a location change alters location_state_ref but never identity."""
    entries = list(build_default_registry())
    base = build_snapshot(entries, created_utc=_FIXED_UTC)
    alt = build_snapshot(
        entries,
        {"cap.algebra_exact": {"state": "available"}},
        created_utc=_FIXED_UTC,
    )

    # Identity is snapshot_id + merkle_root + the entry set. The full canonical
    # record bytes legitimately differ here because ``location_state_ref`` is a
    # field of the record (but never of the identity), so we do NOT compare
    # canonical_dumps() across a location mutation.
    identity_stable = (
        alt.snapshot_id == base.snapshot_id
        and alt.merkle_root == base.merkle_root
        and alt.entries == base.entries
    )
    # The dynamic field MUST differ for the check to be meaningful.
    dynamic_changed = alt.location_state_ref != base.location_state_ref

    if identity_stable and dynamic_changed:
        return {
            "status": "PASS",
            "detail": (
                "location mutation changed location_state_ref only; snapshot_id, "
                "merkle_root, and the entry set unchanged"
            ),
            "evidence": {
                "snapshot_id": base.snapshot_id,
                "merkle_root": base.merkle_root,
                "base_location_ref": base.location_state_ref,
                "alt_location_ref": alt.location_state_ref,
            },
        }
    return {
        "status": "FAIL",
        "detail": (
            f"identity/dynamic split violated: identity_stable={identity_stable}, "
            f"dynamic_changed={dynamic_changed}"
        ),
        "evidence": {
            "base_id": base.snapshot_id,
            "alt_id": alt.snapshot_id,
            "base_loc": base.location_state_ref,
            "alt_loc": alt.location_state_ref,
        },
    }


# ---------------------------------------------------------------------------
# C24-03: queryable with the artifact store absent.
# ---------------------------------------------------------------------------


def _check_c24_03() -> dict[str, Any]:
    """C24-03: the cache lists/inspects capabilities when the store is absent."""
    with tempfile.TemporaryDirectory(prefix="wp24_gate_") as tmpdir:
        cache_path = Path(tmpdir) / "catalog.json"
        cache = SnapshotCache(cache_path)
        entries = build_default_registry()
        snap = build_snapshot(entries, created_utc=_FIXED_UTC)
        cache.write(snap)

        # The store is absent -> list_capabilities must still work and every
        # capability must honestly report state=unknown.
        caps = cache.list_capabilities(store_present=False)
        all_unknown = all(c["location_state"] == {"state": "unknown"} for c in caps)
        right_count = len(caps) == len(entries)

        # Inspect one entry; identity fields must still be surfaced.
        inspected = cache.inspect("cap.geometry_tda", store_present=False)
        inspect_ok = (
            inspected is not None
            and inspected["adapter_id"] == "ripser"
            and inspected["location_state"] == {"state": "unknown"}
        )

        cache_bytes = cache_path.stat().st_size

    if right_count and all_unknown and inspect_ok:
        return {
            "status": "PASS",
            "detail": (
                "cache lists and inspects capabilities with the store absent; "
                "every capability reports state=unknown"
            ),
            "evidence": {
                "capability_count": len(entries),
                "all_unknown": all_unknown,
                "cache_bytes": cache_bytes,
                "inspected_adapter": "ripser",
            },
        }
    return {
        "status": "FAIL",
        "detail": (
            f"store-absent query failed: right_count={right_count}, "
            f"all_unknown={all_unknown}, inspect_ok={inspect_ok}"
        ),
        "evidence": {
            "capability_count": len(caps),
            "all_unknown": all_unknown,
            "inspect_ok": inspect_ok,
        },
    }


# ---------------------------------------------------------------------------
# C24-04: tampered entry detected.
# ---------------------------------------------------------------------------


def _check_c24_04() -> dict[str, Any]:
    """C24-04: a tampered entry field is detected by verify_snapshot."""
    entries = list(build_default_registry())
    snap = build_snapshot(entries, created_utc=_FIXED_UTC)

    # Tamper one entry's adapter_id. The stored merkle_root is unchanged, so the
    # recomputed merkle (over the tampered entry) will not match.
    tampered_entry = replace(snap.entries[0], adapter_id="bogus_adapter")
    tampered_entries = (tampered_entry, *snap.entries[1:])
    bad = replace(snap, entries=tampered_entries)

    try:
        verify_snapshot(bad)
    except SnapshotMismatchError as exc:
        if exc.fail_reason == CONTRACT_INVALID and exc.field == "merkle_root":
            return {
                "status": "PASS",
                "detail": (
                    "tampered adapter_id detected via merkle_root mismatch with "
                    "fail_reason CONTRACT_INVALID"
                ),
                "evidence": {
                    "field": exc.field,
                    "fail_reason": exc.fail_reason,
                    "recorded_merkle": str(exc.recorded),
                    "recomputed_merkle": str(exc.recomputed),
                },
            }
        return {
            "status": "FAIL",
            "detail": (
                f"tamper raised SnapshotMismatchError but with field={exc.field!r}, "
                f"fail_reason={exc.fail_reason!r}"
            ),
            "evidence": {"field": exc.field, "fail_reason": exc.fail_reason},
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }
    return {
        "status": "FAIL",
        "detail": "tampered entry was NOT detected (verify_snapshot returned normally)",
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the receipt."""
    checks = {
        "C24-01": _check_c24_01(),
        "C24-02": _check_c24_02(),
        "C24-03": _check_c24_03(),
        "C24-04": _check_c24_04(),
    }

    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            "seed_entry_count": len(build_default_registry()),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    if args and args[0] == "--check":
        # WP-C24 has no single-check mode that is cheaper than the whole
        # receipt; re-run the whole receipt for any --check argument.
        receipt = _build_receipt()
        _emit(receipt)
        return 0 if receipt["overall"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
