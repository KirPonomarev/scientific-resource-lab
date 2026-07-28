#!/usr/bin/env python3
"""WP-B10 acceptance gate for canonical JSON and identifiers.

Runs the four WP-B10 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp10``.

The checks
----------
B10-01 key-order determinism
    The same object written in three different key orders canonicalizes to
    identical bytes and therefore an identical SHA-256 identity. Proves the
    canonical form is order-independent, which is the prerequisite for
    content-addressed identity.

B10-02 NaN / Infinity / bool-as-int rejection
    Each of NaN, Infinity, and a bool-as-int is rejected by the appropriate
    typed validator (``CanonicalJSONError`` for the non-finite floats via the
    canonical ``loads`` path, ``NumericContractError`` for the bool-as-int).

B10-03 self-hash rejection
    An object that already carries its own ``object_id`` field is rejected by
    ``object_id`` with ``SelfHashError`` (fail reason ``CONTRACT_INVALID``).

B10-04 portable path rejection
    An absolute path and a ``..`` traversal path are each rejected by the
    portable-path validator with ``ArtifactRefError``
    (fail reason ``CONTRACT_INVALID``).

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp10-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp10-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import (  # noqa: E402  (path setup must precede import)
    ArtifactRefError,
    CanonicalJSONError,
    NumericContractError,
    SelfHashError,
    dumps,
    object_id,
    validate_integer_byte_count,
    validate_portable_path,
)
from srl.contracts.canonical import loads  # noqa: E402
from srl.contracts.schema import meta_validate_all  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-B10"


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    # The gate receipt uses the contracts-layer canonical form (UTF-8 bytes).
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _check_b10_01() -> dict[str, Any]:
    """B10-01: three key orders -> identical bytes and identical sha256."""
    # The canonical content (independent of insertion order).
    content = {
        "schema_version": "Demo/v1",
        "zeta": 26,
        "alpha": 1,
        "middle": [3, 2, 1],
    }
    # Three independent orderings of the *same* content. Each rebuilds the dict
    # with a different key insertion order so the canonicalizer must normalize.
    order_a = dict(sorted(content.items()))
    order_b = {k: content[k] for k in reversed(list(content))}
    order_c = {
        "middle": content["middle"],
        "zeta": content["zeta"],
        "alpha": content["alpha"],
        "schema_version": content["schema_version"],
    }
    bytes_a = dumps(order_a)
    bytes_b = dumps(order_b)
    bytes_c = dumps(order_c)
    if not (bytes_a == bytes_b == bytes_c):
        return {
            "status": "FAIL",
            "detail": "three key orders produced different canonical bytes",
            "bytes_a": bytes_a.decode("utf-8"),
            "bytes_b": bytes_b.decode("utf-8"),
            "bytes_c": bytes_c.decode("utf-8"),
        }
    sha_a = hashlib.sha256(bytes_a).hexdigest()
    sha_b = hashlib.sha256(bytes_b).hexdigest()
    sha_c = hashlib.sha256(bytes_c).hexdigest()
    if not (sha_a == sha_b == sha_c):
        return {
            "status": "FAIL",
            "detail": "identical bytes produced different sha256 (impossible)",
        }
    return {
        "status": "PASS",
        "detail": "three key orders -> identical bytes and identical sha256",
        "canonical": bytes_a.decode("utf-8").rstrip("\n"),
        "sha256": sha_a,
    }


def _check_b10_02() -> dict[str, Any]:
    """B10-02: NaN, Infinity, and bool-as-int are each rejected.

    NaN and Infinity are exercised via the canonical ``loads`` path: a JSON
    document containing the non-standard ``NaN``/``Infinity`` literals must be
    rejected by the ``parse_constant`` hook. bool-as-int is exercised via the
    byte-count validator (a ``True`` must not be accepted as ``1``).
    """
    rejections: list[dict[str, str]] = []

    # NaN: feed the non-standard literal through the canonical parser.
    try:
        loads(b'{"value":NaN}')
        rejections.append({"case": "NaN", "outcome": "NOT rejected (expected CanonicalJSONError)"})
    except CanonicalJSONError as exc:
        rejections.append({"case": "NaN", "outcome": "rejected", "fail_reason": exc.fail_reason})

    # Infinity.
    try:
        loads(b'{"value":Infinity}')
        rejections.append(
            {"case": "Infinity", "outcome": "NOT rejected (expected CanonicalJSONError)"}
        )
    except CanonicalJSONError as exc:
        rejections.append(
            {"case": "Infinity", "outcome": "rejected", "fail_reason": exc.fail_reason}
        )

    # bool-as-int: a byte-count field set to True.
    try:
        validate_integer_byte_count(True, field="size_bytes")
        rejections.append(
            {"case": "bool-as-int", "outcome": "NOT rejected (expected NumericContractError)"}
        )
    except NumericContractError as exc:
        rejections.append(
            {"case": "bool-as-int", "outcome": "rejected", "fail_reason": exc.fail_reason}
        )

    not_rejected = [r for r in rejections if not r["outcome"].startswith("rejected")]
    if not_rejected:
        return {
            "status": "FAIL",
            "detail": "one or more invalid values were not rejected",
            "rejections": rejections,
        }
    return {
        "status": "PASS",
        "detail": "NaN, Infinity, and bool-as-int each rejected by typed error",
        "rejections": rejections,
    }


def _check_b10_03() -> dict[str, Any]:
    """B10-03: a self-referential object is rejected as a self-hash."""
    self_ref = {"object_id": "sha256:deadbeef", "payload": {"x": 1}}
    try:
        object_id(self_ref)
        return {
            "status": "FAIL",
            "detail": "self-referential object was not rejected (expected SelfHashError)",
        }
    except SelfHashError as exc:
        return {
            "status": "PASS",
            "detail": "self-hash rejected with SelfHashError",
            "fail_reason": exc.fail_reason,
        }


def _check_b10_04() -> dict[str, Any]:
    """B10-04: absolute and traversal portable paths are rejected."""
    bad_paths = ["/etc/passwd", "../../secret", "C:\\evil\\path", "legit/../escape"]
    rejections: list[dict[str, str]] = []
    for bad in bad_paths:
        try:
            validate_portable_path(bad, field="path")
            rejections.append({"path": bad, "outcome": "NOT rejected"})
        except ArtifactRefError as exc:
            rejections.append({"path": bad, "outcome": "rejected", "fail_reason": exc.fail_reason})
    not_rejected = [r for r in rejections if not r["outcome"].startswith("rejected")]
    if not_rejected:
        return {
            "status": "FAIL",
            "detail": "one or more non-portable paths were not rejected",
            "rejections": rejections,
        }
    return {
        "status": "PASS",
        "detail": "absolute/traversal/drive/backslash paths rejected",
        "rejections": rejections,
    }


def _evidence() -> dict[str, Any]:
    """Compact evidence summary for the receipt."""
    return {
        "vector_counts": {
            "positive": _count_vectors("positive"),
            "negative": _count_vectors("negative"),
        },
        "schemas": _schema_evidence(),
    }


def _count_vectors(subdir: str) -> int:
    """Count positive/negative vector input files under the conformance dir."""
    vec_dir = _REPO_ROOT / "fixtures" / "conformance" / "canonical_json"
    if subdir == "negative":
        vec_dir = vec_dir / "negative"
    if not vec_dir.is_dir():
        return 0
    return len(list(vec_dir.glob("*.input.json")))


def _schema_evidence() -> dict[str, Any]:
    """Load every shipped schema and report name -> $id (proves meta-validity)."""
    try:
        return {"loaded": True, "schemas": meta_validate_all()}
    except Exception as exc:  # gate must report any loader failure as evidence
        return {"loaded": False, "error": str(exc)}


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "B10-01": _check_b10_01(),
        "B10-02": _check_b10_02(),
        "B10-03": _check_b10_03(),
        "B10-04": _check_b10_04(),
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
            **_evidence(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "B10-01": _check_b10_01,
            "B10-02": _check_b10_02,
            "B10-03": _check_b10_03,
            "B10-04": _check_b10_04,
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
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    # `json` is imported for the manifest evidence path used by some callers;
    # keep the import alive even when unused on this branch.
    _ = json
    raise SystemExit(main())
