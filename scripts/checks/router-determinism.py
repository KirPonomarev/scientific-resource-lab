#!/usr/bin/env python3
"""Router/planner determinism check: rebuild the golden plan twice, compare bytes.

Verifies the load-bearing determinism property of the science-lab router and
planner (WP-B14): the same ``(request, claim, catalog, policy)`` yields a
byte-identical ``ScienceLabPlan/v1``. This script rebuilds the golden plan
fixture TWICE (from the same inputs) and asserts the two canonical byte strings
are identical, and that both match the ``plan_id`` recorded the first time.

This is a stronger, narrower check than ``wp14-gate.py``'s ``B14-01``: it is
the CI job (``router_determinism``) that fails closed the moment the planner's
output becomes input-order-dependent — a regression that would break
content-addressed identity and reproducible comparison.

Prints a canonical JSON receipt (``RouterDeterminismReceipt/v1``) and exits
non-zero on any failure. Runs as
``python3 scripts/checks/router-determinism.py`` (adds ``src/`` to
``sys.path``) or under ``uv run``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/router-determinism.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402  (path setup must precede import)
from srl.planning import (  # noqa: E402
    build_plan,
    build_request,
    default_policy,
    load_default_catalog,
    route,
)

RECEIPT_SCHEMA: Final[str] = "RouterDeterminismReceipt/v1"

# A canonical sha256 digest used for object ids in the inline proof.
_DIGEST: Final[str] = "sha256:" + "a" * 64


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _build_golden_plan() -> dict[str, Any]:
    """Build the golden plan from fixed inputs (the determinism reference)."""
    cat = load_default_catalog()
    pol = default_policy()
    claim = {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": "We compute persistent homology and the Betti numbers of the point cloud.",
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    req = build_request(claim_id=_DIGEST, requested_profiles=[], resource_class="default")
    dec = route(req, claim, cat, pol)
    return build_plan(req, dec, cat, pol)


def main() -> int:
    """Run the determinism check and emit the receipt. Non-zero exit on failure."""
    plan1 = _build_golden_plan()
    plan2 = _build_golden_plan()
    bytes1 = dumps(plan1)
    bytes2 = dumps(plan2)

    byte_identical = bytes1 == bytes2
    plan_id_stable = plan1["plan_id"] == plan2["plan_id"]
    digest_stable = plan1["plan_digest"] == plan2["plan_digest"]
    overall = "PASS" if (byte_identical and plan_id_stable and digest_stable) else "FAIL"

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "overall": overall,
        "byte_identical": byte_identical,
        "plan_id_stable": plan_id_stable,
        "digest_stable": digest_stable,
        "plan_id": plan1["plan_id"],
        "plan_digest": plan1["plan_digest"],
        "byte_count": len(bytes1),
    }
    _emit(receipt)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
