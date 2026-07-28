#!/usr/bin/env python3
"""Schema compatibility check: all schemas meta-valid + loader registry complete.

Verifies the two WP-B11 compatibility properties:

1. Every shipped schema still meta-validates against JSON Schema 2020-12
   (delegated to :func:`srl.contracts.schema.meta_validate_all`).
2. The loader registry is complete: every ``schemas/v1/*.json`` on disk maps to
   a known schema name (no orphan files), every known name resolves to a file,
   every loaded schema carries a unique non-empty ``$id``, and the on-disk file
   count equals the registry count (no drift between the source tree and the
   loader).

Prints a canonical JSON receipt (``SchemaCompatReceipt/v1``) and exits non-zero
on any failure. Runs as ``python3 scripts/checks/schema-compat.py`` (adds
``src/`` to ``sys.path``) or under ``uv run``.
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
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/schema-compat.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402  (path setup must precede import)
from srl.contracts.schema import (  # noqa: E402
    SchemaError,
    list_schemas,
    load_schema,
    meta_validate_all,
    schema_file_map,
)

RECEIPT_SCHEMA: Final[str] = "SchemaCompatReceipt/v1"
_SCHEMA_DIR: Final[Path] = _REPO_ROOT / "src" / "srl" / "contracts" / "schemas" / "v1"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _on_disk_schema_files() -> list[str]:
    """Return sorted basenames of the .json schema files on disk (v1 dir)."""
    if not _SCHEMA_DIR.is_dir():
        return []
    return sorted(p.name for p in _SCHEMA_DIR.glob("*.json"))


def main() -> int:
    """Run the compatibility check and emit the receipt. Non-zero exit on failure."""
    results: list[dict[str, Any]] = []
    overall = "PASS"
    error: str | None = None

    # 1. Every schema meta-validates (loads + meta-validates).
    try:
        meta_validate_all()
    except SchemaError as exc:
        overall = "FAIL"
        error = str(exc)

    # 2. Every known schema loads and carries a non-empty, unique $id.
    name_to_id: dict[str, str] = {}
    for name in list_schemas():
        try:
            schema = load_schema(name)
            sid = schema.get("$id", "")
            if not isinstance(sid, str) or not sid:
                results.append({"name": name, "status": "FAIL", "error": "missing $id"})
                overall = "FAIL"
            else:
                name_to_id[name] = sid
                results.append({"name": name, "status": "PASS", "$id": sid})
        except SchemaError as exc:
            results.append({"name": name, "status": "FAIL", "error": str(exc)})
            overall = "FAIL"

    # 3. $id uniqueness (two schemas must not share an $id).
    seen: dict[str, str] = {}
    for name, sid in name_to_id.items():
        if sid in seen:
            results.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "error": f"$id {sid!r} shared with {seen[sid]!r}",
                }
            )
            overall = "FAIL"
        else:
            seen[sid] = name

    # 4. Registry completeness: no on-disk orphans, counts agree.
    disk_files = _on_disk_schema_files()
    known_files = set(schema_file_map().values())
    orphans = sorted(f for f in disk_files if f not in known_files)
    registry_count = len(list_schemas())
    disk_count = len(disk_files)
    if orphans:
        overall = "FAIL"
    if registry_count != disk_count:
        overall = "FAIL"

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "overall": overall,
        "registry_count": registry_count,
        "disk_count": disk_count,
        "disk_orphans": orphans,
        "schemas": results,
    }
    if error is not None:
        receipt["error"] = error
    _emit(receipt)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
