#!/usr/bin/env python3
"""Receipt-invariants check: every receipt schema pins the two safety consts.

Verifies the governance-level invariant that every SRL *receipt* schema (the
immutable, content-addressed lineage artifacts) pins its two safety consts as
``const`` JSON Schema keywords:

- ``canonical_writes`` is ``const: 0`` (a receipt is immutable once authored);
- ``grants_authority`` is ``const: false`` (a receipt never grants authority on
  its own).

A receipt that admitted a non-zero ``canonical_writes`` or a ``true``
``grants_authority`` would be a governance change, not a schema-compatibility
change (see ``src/srl/contracts/schemas/v1/README.md``). This check makes that
invariant machine-checkable so a schema edit that drops a ``const`` cannot land
silently.

The set of schemas checked is the *receipt* family: schemas whose title carries
the ``Receipt`` suffix (or is the ``GateReceipt``), i.e. the lineage artifacts
that carry the safety consts. Non-receipt schemas (e.g. ``ArtifactRef``,
``MathIR``) are not receipts and do not carry the consts, so they are excluded.

Prints a canonical JSON receipt (``ReceiptInvariantsReceipt/v1``) and exits
non-zero on any failure. Runs as ``python3 scripts/checks/receipt-invariants.py``
(adds ``src/`` to ``sys.path``) or under ``uv run``.
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
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/receipt-invariants.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402  (path setup must precede import)
from srl.contracts.schema import (  # noqa: E402
    list_schemas,
    load_schema,
)

RECEIPT_SCHEMA: Final[str] = "ReceiptInvariantsReceipt/v1"

# The two safety consts every receipt schema must pin. The value is the
# expected ``const`` keyword value; the key is the property name.
_SAFETY_CONSTS: Final[dict[str, object]] = {
    "canonical_writes": 0,
    "grants_authority": False,
}


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _is_receipt_schema(name: str, schema: dict[str, Any]) -> bool:
    """Return True iff the schema is a scientific receipt carrying the safety consts.

    A scientific receipt is a content-addressed lineage artifact that carries
    the two safety consts (``canonical_writes`` and ``grants_authority``): the
    TransformationReceipt and the ScienceLab* receipts. It is identified by its
    title stem ending in ``Receipt`` AND its properties declaring BOTH safety
    consts. The lightweight ``GateReceipt`` (provenance-only, no safety consts)
    and non-receipt schemas (ArtifactRef, MathIR, ScientificClaim, ...) are
    excluded because they do not carry the consts.
    """
    title = schema.get("title", "")
    if not isinstance(title, str):
        return False
    stem = title.removesuffix("/v1")
    if not stem.endswith("Receipt"):
        return False
    # A scientific receipt must declare both safety consts to be in scope; the
    # GateReceipt is provenance-only and does not carry them.
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return False
    return all(prop in properties for prop in _SAFETY_CONSTS)


def main() -> int:
    """Run the check and emit the receipt. Non-zero exit on failure."""
    results: list[dict[str, Any]] = []
    overall = "PASS"

    for name in list_schemas():
        schema = load_schema(name)
        if not _is_receipt_schema(name, schema):
            continue
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            results.append(
                {"name": name, "status": "FAIL", "error": "schema 'properties' is not an object"}
            )
            overall = "FAIL"
            continue
        required = schema.get("required", [])
        required_set = set(required) if isinstance(required, list) else set()
        missing: list[str] = []
        not_const: list[str] = []
        for prop, expected in _SAFETY_CONSTS.items():
            prop_schema = properties.get(prop)
            if not isinstance(prop_schema, dict):
                missing.append(prop)
                continue
            if prop not in required_set:
                missing.append(f"{prop} (not in required)")
                continue
            const_value = prop_schema.get("const")
            if const_value != expected:
                not_const.append(f"{prop} (const={const_value!r}, expected {expected!r})")
        if missing or not_const:
            overall = "FAIL"
            results.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "missing": missing,
                    "not_const": not_const,
                }
            )
        else:
            results.append({"name": name, "status": "PASS"})

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "overall": overall,
        "checked": results,
        "safety_consts": {k: v for k, v in _SAFETY_CONSTS.items()},
    }
    _emit(receipt)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
