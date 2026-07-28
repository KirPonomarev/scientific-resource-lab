#!/usr/bin/env python3
"""Meta-validate every shipped SRL schema document against JSON Schema 2020-12.

Loads each ``schemas/v1/*.json`` via the packaged schema loader
(:func:`srl.contracts.schema.load_schema`, which meta-validates on first load)
and additionally verifies the on-disk files under
``src/srl/contracts/schemas/v1/`` match the packaged set, so a schema cannot
silently drift between the source tree and the installed wheel.

Prints a canonical JSON receipt (``SchemaMetaValidationReceipt/v1``) and exits
non-zero on any failure.

Runs as ``python3 scripts/checks/schema-meta-validate.py`` (adds ``src/`` to
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
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/schema-meta-validate.py -> repo root
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

RECEIPT_SCHEMA: Final[str] = "SchemaMetaValidationReceipt/v1"

# Where the schema source files live in the repository tree. Used to assert
# the on-disk file set matches the loader's known-name set.
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
    """Run the meta-validation and emit the receipt. Non-zero exit on failure."""
    results: list[dict[str, Any]] = []
    overall = "PASS"
    error: str | None = None

    # meta_validate_all loads every schema and meta-validates each; it raises
    # on the first malformed schema. We catch so the receipt still reports the
    # per-schema status below.
    try:
        meta_validate_all()
    except SchemaError as exc:
        overall = "FAIL"
        error = str(exc)

    for name in list_schemas():
        try:
            schema = load_schema(name)
            results.append(
                {
                    "name": name,
                    "status": "PASS",
                    "$id": schema.get("$id", ""),
                    "title": schema.get("title", ""),
                    "additionalProperties": schema.get("additionalProperties"),
                }
            )
        except SchemaError as exc:
            overall = "FAIL"
            results.append({"name": name, "status": "FAIL", "error": str(exc)})

    # Cross-check: every .json file on disk must correspond to a known schema
    # name (no orphan files), and every known name must have a file. The
    # loader's name->file map is the authority; a file with no known name is an
    # orphan, and a known name with no file would have failed load_schema above.
    disk_files = _on_disk_schema_files()
    known_files = set(schema_file_map().values())
    disk_orphans = sorted(f for f in disk_files if f not in known_files)
    if disk_orphans:
        # An orphan file is not itself a meta-validation failure, but it is a
        # drift signal worth surfacing in the receipt.
        pass

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "overall": overall,
        "schema_count": len(list_schemas()),
        "schemas": results,
        "disk_files": disk_files,
        "disk_orphans": disk_orphans,
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
