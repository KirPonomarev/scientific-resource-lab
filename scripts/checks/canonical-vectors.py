#!/usr/bin/env python3
"""Verify the canonical-JSON conformance vectors under fixtures/.

For every **positive** vector: load ``<name>.input.json`` (a JSON value in a
deliberately non-canonical form), canonicalize it with
:func:`srl.contracts.canonical.dumps`, and assert the result is byte-equal to
``<name>.expected.json``.

For every **negative** vector: load ``<name>.input.json``, run the validator
named in ``<name>.expected_error.json``, and assert it raises the named typed
exception with the named fail reason.

Prints a canonical JSON receipt (``ConformanceVectorsReceipt/v1``) and exits
non-zero on any mismatch.

Runs as ``python3 scripts/checks/canonical-vectors.py`` (adds ``src/`` to
``sys.path``) or under ``uv run``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/canonical-vectors.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import (  # noqa: E402  (path setup must precede import)
    ArtifactRefError,
    CanonicalJSONError,
    ContractError,
    NumericContractError,
    SelfHashError,
    TimestampError,
    dumps,
    object_id,
    validate_integer_byte_count,
    validate_portable_path,
    validate_timestamp,
)
from srl.contracts.canonical import loads  # noqa: E402

RECEIPT_SCHEMA: Final[str] = "ConformanceVectorsReceipt/v1"
_VECTORS_DIR: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "canonical_json"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _read_json(path: Path) -> Any:
    """Read and parse a JSON file (UTF-8). Allows the non-standard NaN/Infinity."""
    text = path.read_text(encoding="utf-8")
    # Use a permissive parser for input files so NaN/Infinity literals reach the
    # contract validator rather than tripping the standard parser here.
    return json.loads(text)


def _read_raw(path: Path) -> bytes:
    """Read a file as raw bytes (for byte-exact expected comparison)."""
    return path.read_bytes()


# Map the validator name in an expected_error file to the callable + the
# exception class it must raise. Kept as a table so the dispatch is auditable.
_EXC_CLASSES: Final[dict[str, type[ContractError]]] = {
    "CanonicalJSONError": CanonicalJSONError,
    "NumericContractError": NumericContractError,
    "SelfHashError": SelfHashError,
    "ArtifactRefError": ArtifactRefError,
    "TimestampError": TimestampError,
}


def _run_negative(vec_dir: Path, name: str) -> dict[str, Any]:
    """Run one negative vector; return a result dict with a status."""
    input_path = vec_dir / f"{name}.input.json"
    expected_path = vec_dir / f"{name}.expected_error.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    validator = expected["validator"]
    exc_name = expected["exception"]
    expected_reason = expected["fail_reason"]
    exc_cls = _EXC_CLASSES.get(exc_name)
    if exc_cls is None:
        return {
            "name": name,
            "status": "FAIL",
            "detail": f"unknown expected exception {exc_name!r}",
        }

    # Each validator extracts its target value from the input doc differently.
    doc = _read_json(input_path)
    try:
        if validator == "loads":
            # The whole input doc (as text) is fed to the canonical parser,
            # which must reject NaN/Infinity via parse_constant.
            loads(input_path.read_bytes())
        elif validator == "integer_byte_count":
            value = doc["size_bytes"] if isinstance(doc, dict) else doc
            validate_integer_byte_count(value, field="size_bytes")
        elif validator == "object_id":
            object_id(doc)
        elif validator == "portable_path":
            value = doc["path"] if isinstance(doc, dict) else doc
            validate_portable_path(value, field="path")
        elif validator == "timestamp":
            value = doc["created_utc"] if isinstance(doc, dict) else doc
            validate_timestamp(value)
        else:
            return {
                "name": name,
                "status": "FAIL",
                "detail": f"unknown validator {validator!r}",
            }
        return {
            "name": name,
            "status": "FAIL",
            "detail": f"input was not rejected (expected {exc_name})",
        }
    except exc_cls as exc:
        if exc.fail_reason != expected_reason:
            return {
                "name": name,
                "status": "FAIL",
                "detail": (
                    f"wrong fail_reason: got {exc.fail_reason!r}, expected {expected_reason!r}"
                ),
            }
        return {
            "name": name,
            "status": "PASS",
            "validator": validator,
            "exception": exc_name,
            "fail_reason": exc.fail_reason,
        }
    except ContractError as exc:
        return {
            "name": name,
            "status": "FAIL",
            "detail": (f"wrong exception type: got {type(exc).__name__}, expected {exc_name}"),
        }


def main() -> int:
    """Run all vectors and emit the receipt. Non-zero exit on any failure."""
    positive_results: list[dict[str, Any]] = []
    negative_results: list[dict[str, Any]] = []
    overall = "PASS"

    # Positive vectors: every <name>.input.json -> canonicalize -> compare.
    for input_path in sorted((_VECTORS_DIR).glob("*.input.json")):
        name = input_path.name.removesuffix(".input.json")
        expected_path = _VECTORS_DIR / f"{name}.expected.json"
        if not expected_path.is_file():
            positive_results.append(
                {"name": name, "status": "FAIL", "detail": "missing expected file"}
            )
            overall = "FAIL"
            continue
        try:
            value = _read_json(input_path)
            actual = dumps(value)
        except Exception as exc:  # report any failure as a FAIL detail
            # Intentionally broad: any failure to canonicalize a positive
            # vector is a FAIL with the exception text as the detail.
            positive_results.append(
                {"name": name, "status": "FAIL", "detail": f"canonicalize failed: {exc}"}
            )
            overall = "FAIL"
            continue
        expected = _read_raw(expected_path)
        if actual != expected:
            positive_results.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "detail": "canonical bytes differ from expected",
                    "actual": actual.decode("utf-8", errors="replace"),
                    "expected": expected.decode("utf-8", errors="replace"),
                }
            )
            overall = "FAIL"
        else:
            positive_results.append({"name": name, "status": "PASS", "bytes": len(actual)})

    # Negative vectors: under negative/, each input must be rejected.
    neg_dir = _VECTORS_DIR / "negative"
    if neg_dir.is_dir():
        for input_path in sorted(neg_dir.glob("*.input.json")):
            name = input_path.name.removesuffix(".input.json")
            result = _run_negative(neg_dir, name)
            negative_results.append(result)
            if result["status"] != "PASS":
                overall = "FAIL"

    pass_pos = sum(1 for r in positive_results if r["status"] == "PASS")
    pass_neg = sum(1 for r in negative_results if r["status"] == "PASS")

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "overall": overall,
        "positive": {"total": len(positive_results), "passed": pass_pos},
        "negative": {"total": len(negative_results), "passed": pass_neg},
        "results": {"positive": positive_results, "negative": negative_results},
    }
    _emit(receipt)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
