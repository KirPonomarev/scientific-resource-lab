#!/usr/bin/env python3
"""Prepare the isolated Julia project used by the V3.7 A14 gate."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from srl.products.sciml_domain import (  # noqa: E402
    SciMLDomainActivationError,
    prepare_a14_julia_project,
)


def main() -> int:
    project = os.environ.get("SRL_A14_JULIA_PROJECT_DIR")
    depot = os.environ.get("JULIA_DEPOT_PATH")
    try:
        receipt = prepare_a14_julia_project(
            julia_project_dir=project,
            julia_depot_path=depot,
        )
    except SciMLDomainActivationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "A14JuliaProjectPrepareReceipt/v1",
                    "stage_id": "A14",
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
