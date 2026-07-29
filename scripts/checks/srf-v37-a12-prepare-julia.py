#!/usr/bin/env python3
"""Prepare the cacheable Julia depot used by the V3.7 A12 gate."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from srl.products.discovery_dynamics import (  # noqa: E402
    DiscoveryDynamicsError,
    prepare_a12_julia_depot,
)


def main() -> int:
    depot = os.environ.get("JULIA_DEPOT_PATH")
    try:
        receipt = prepare_a12_julia_depot(julia_depot_path=depot)
    except DiscoveryDynamicsError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "A12JuliaDepotPrepareReceipt/v1",
                    "stage_id": "A12",
                    "prepared": False,
                    "fail_reason": exc.fail_reason,
                    "error": str(exc),
                    "promotion_allowed": False,
                    "canonical_writes": 0,
                    "grants_authority": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
