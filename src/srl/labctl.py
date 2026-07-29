"""Solo-agent entry semantics for Scientific Reasoning Fabric.

The functions in this module are deliberately data-first: they expose the
manifest and access receipt that ``srlab labctl enter`` prints, and the S02
documentation generator renders the same structures. This keeps the CLI and
docs from drifting into separate sources of truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from srl import __version__

PROJECT_ID: Final[str] = "scientific-resource-lab"
PRODUCT_NAME: Final[str] = "Scientific Reasoning Fabric"
PROJECT_FINGERPRINT: Final[str] = "d56e03d0d5e1a9bb9c33a008ab9895102d8e41e8bfd001dfbfc8e1c80b9df0b3"
MISSION_ID: Final[str] = "build-scientific-reasoning-fabric-v1"
PLAN_ID: Final[str] = "SRF-MASTER-2026-07-29-V3.6"

_CELLS: Final[dict[str, dict[str, Any]]] = {
    "standalone": {
        "cell_id": "standalone",
        "display_name": "Standalone SRF session",
        "native_bootstrap": "srlab doctor",
        "allowed_transport": "local_json",
        "status": "READY",
        "proposal_only": False,
    },
    "market": {
        "cell_id": "market",
        "display_name": "Crypto Market Lab bridge",
        "native_bootstrap": "Market native operator bootstrap",
        "allowed_transport": "D0_D1_spool_packet",
        "status": "WAIT_NATIVE_BOOTSTRAP",
        "proposal_only": True,
    },
    "security": {
        "cell_id": "security",
        "display_name": "Security Researcher bridge",
        "native_bootstrap": "Security native bootstrap",
        "allowed_transport": "D0_D1_spool_packet",
        "status": "WAIT_NATIVE_BOOTSTRAP",
        "proposal_only": True,
    },
}


def labctl_manifest() -> dict[str, Any]:
    """Return the deterministic SRF solo-agent manifest."""
    cells = [deepcopy(_CELLS[key]) for key in sorted(_CELLS)]
    return {
        "schema_version": "LabCtlManifest/v1",
        "project_id": PROJECT_ID,
        "product_name": PRODUCT_NAME,
        "project_fingerprint": PROJECT_FINGERPRINT,
        "mission_id": MISSION_ID,
        "plan_id": PLAN_ID,
        "package_version": __version__,
        "entry_command": "srlab labctl enter",
        "cells": cells,
        "authority_invariants": {
            "grants_authority": False,
            "canonical_writes": 0,
            "live_actions": 0,
            "orders_allowed": False,
            "security_actions_allowed": False,
        },
        "next_commands": [
            "srlab doctor",
            "srlab catalog inspect",
            "srlab plan build <bundle-file>",
            "srlab run execute <run-spec-file>",
        ],
    }


def lab_access_receipt(cell_id: str = "standalone") -> dict[str, Any]:
    """Return a ``LabAccessReceipt/v1`` scope projection for ``cell_id``.

    The receipt is authority-negative by construction. Cross-lab cells are
    marked as proposal-only and WAIT until their native bootstrap has produced
    fresh evidence outside SRF.
    """
    if cell_id not in _CELLS:
        valid = ", ".join(sorted(_CELLS))
        msg = f"unknown lab cell {cell_id!r}; expected one of: {valid}"
        raise ValueError(msg)
    cell = deepcopy(_CELLS[cell_id])
    invariants = labctl_manifest()["authority_invariants"]
    return {
        "schema_version": "LabAccessReceipt/v1",
        "project_id": PROJECT_ID,
        "project_fingerprint": PROJECT_FINGERPRINT,
        "mission_id": MISSION_ID,
        "plan_id": PLAN_ID,
        "cell": cell,
        "scope": {
            "proposal_only": bool(cell["proposal_only"]),
            "allowed_transport": cell["allowed_transport"],
            "native_bootstrap_required": True,
            "native_bootstrap": cell["native_bootstrap"],
        },
        **invariants,
    }


def enter_report(cell_id: str = "standalone") -> dict[str, Any]:
    """Build the JSON report emitted by ``srlab labctl enter``."""
    receipt = lab_access_receipt(cell_id)
    return {
        "schema_version": "LabCtlEnterReport/v1",
        "status": receipt["cell"]["status"],
        "manifest": labctl_manifest(),
        "receipt": receipt,
    }
