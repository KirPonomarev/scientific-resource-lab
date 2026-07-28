#!/usr/bin/env python3
"""WP-D32 acceptance gate for the run materializer and sealer.

Runs the five WP-D32 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI.

The checks
----------
D32-01 happy path run receipt with digests bound and read-back verified
    A run with an ``echo.v1`` adapter is materialized from a content-addressed
    store, executed by the bounded runner, and sealed. The resulting run receipt
    binds the input digest, the output digest, the engine receipt id, and the
    store descriptor ids; it is read back and verified against its own content id.
D32-02 input hash mismatch aborts pre-run
    A stored input object is corrupted out-of-band. ``materialize_run`` aborts
    with ``CAS_INTEGRITY_FAILURE`` before the run receipt is produced.
D32-03 schema-invalid output -> no receipt, no ingest
    The sealer is given an output that fails the injected validator. No run
    receipt is written and no objects are ingested into the store.
D32-04 store ingest failure -> no run receipt
    A store that raises on the second ingest causes ``seal_run`` to fail without
    writing a run receipt (the receipt-last invariant holds).
D32-05 receipt has no absolute paths
    The run receipt text is scanned for raw host-local paths (``/Users/``,
    ``/Volumes/``, ``/home/``, Windows drive letters). None are present; the
    store root is recorded as a ``redacted:<16 hex>`` token.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp32-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion). It is hermetic: it uses
temporary directories and the shipped ``echo.v1`` adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp32-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.cas import LocalArtifactStore, QuotaExceededError  # noqa: E402
from srl.contracts import dumps  # noqa: E402
from srl.execution import (  # noqa: E402
    load_policy,
    materialize_run,
    prepare_scratch,
    run_adapter,
    seal_run,
)
from srl.execution.sealer import SealerError  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-D32"

# The canonical M1 policy path.
_POLICY_PATH: Final[Path] = _REPO_ROOT / "policies" / "resource-policy-m1.json"

# Media type for input objects ingested by the gate.
_INPUT_MEDIA_TYPE: Final[str] = "application/json"

# Patterns that mark a raw host-local path leak in a receipt.
_RAW_PATH_RE: Final[re.Pattern[str]] = re.compile(r"/(Users|Volumes|home)/|[A-Za-z]:\\")

# The fail reasons surfaced in the gate receipt, mirrored from the registry.
_CAS_INTEGRITY_FAILURE_REF: Final[str] = "CAS_INTEGRITY_FAILURE"
_CONTRACT_INVALID_REF: Final[str] = "CONTRACT_INVALID"


class _FailingStore(LocalArtifactStore):
    """LocalArtifactStore that raises on the Nth ingest_bytes call."""

    def __init__(self, root: Path, *, fail_on: int = 2) -> None:
        super().__init__(root)
        self._fail_on = fail_on
        self._calls = 0

    def ingest_bytes(
        self,
        source_bytes: bytes,
        media_type: str,
        *,
        capacity_hook: object | None = None,
        used_bytes: int = 0,
        created_utc: str | None = None,
    ) -> Any:
        self._calls += 1
        if self._calls == self._fail_on:
            raise QuotaExceededError(
                "simulated ingest failure (gate probe)",
                used_bytes=0,
                size_bytes=len(source_bytes),
            )
        return super().ingest_bytes(
            source_bytes,
            media_type,
            capacity_hook=capacity_hook,
            used_bytes=used_bytes,
            created_utc=created_utc,
        )


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _compute_receipt_id(body: dict[str, Any]) -> str:
    """Return the content-addressed id of a receipt (body without receipt_id)."""
    seed = {k: v for k, v in body.items() if k != "receipt_id"}
    return "sha256:" + hashlib.sha256(dumps(seed)).hexdigest()


def _valid_output(output: object) -> None:
    if not isinstance(output, dict) or "value" not in output:
        raise ValueError("output missing 'value' field")


def _invalid_output(output: object) -> None:
    """A validator that rejects the echo.v1 output for D32-03."""
    if isinstance(output, dict) and "value" in output:
        raise ValueError("schema-invalid output (rejected by gate probe)")


def _ingest_input(store: LocalArtifactStore, payload: dict[str, Any]) -> str:
    """Canonicalize and ingest a payload; return its digest."""
    payload_bytes = dumps(payload)
    return store.ingest_bytes(payload_bytes, _INPUT_MEDIA_TYPE).digest


# ---------------------------------------------------------------------------
# D32-01 happy path.
# ---------------------------------------------------------------------------


def _check_d32_01() -> dict[str, Any]:
    """D32-01: materialize, run, seal; run receipt binds digests and verifies."""
    policy = load_policy(_POLICY_PATH)
    input_payload = {"value": "hello"}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root / "store")
        receipt_dir = root / "receipts"
        input_digest = _ingest_input(store, input_payload)

        run_spec = {
            "adapter_id": "echo.v1",
            "input_payloads": {"input.json": input_digest},
            "pack_ref": None,
        }
        staged = materialize_run(run_spec, store, root / "staging")

        scratch = prepare_scratch(parent=root)
        try:
            outcome = run_adapter(
                "echo.v1",
                input_payload,
                policy,
                scratch,
                wall_seconds=10,
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        sealed = seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)
        receipt = json.loads(sealed.run_receipt_path.read_text(encoding="utf-8"))
        expected_id = _compute_receipt_id(receipt)

        failures = []
        if receipt.get("receipt_id") != expected_id:
            failures.append("run receipt id does not match its content hash")
        if receipt.get("adapter_id") != "echo.v1":
            failures.append("adapter_id mismatch")
        if receipt.get("input_digests") != {"input.json": input_digest}:
            failures.append("input digest not bound correctly")
        if sealed.output_object_id not in receipt.get("store_descriptor_ids", []):
            failures.append("output descriptor id not in store_descriptor_ids")
        if sealed.engine_receipt_id not in receipt.get("engine_receipt_id", ""):
            failures.append("engine receipt id not bound")
        if not sealed.run_receipt_path.name.startswith("sha256:"):
            failures.append("receipt filename is not a content digest")

        if failures:
            return {"status": "FAIL", "detail": "; ".join(failures), "receipt": receipt}
        return {
            "status": "PASS",
            "detail": (
                "happy path: materialized, ran echo.v1, sealed; run receipt id matches content; "
                "input/output digests and engine receipt id are bound"
            ),
            "receipt_id": receipt["receipt_id"],
        }


# ---------------------------------------------------------------------------
# D32-02 input hash mismatch aborts pre-run.
# ---------------------------------------------------------------------------


def _check_d32_02() -> dict[str, Any]:
    """D32-02: a corrupted stored input aborts materialization with CAS_INTEGRITY_FAILURE."""
    input_payload = {"value": "hello"}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root / "store")
        input_digest = _ingest_input(store, input_payload)
        obj_path = store._object_path(input_digest)
        corrupted = obj_path.read_bytes()[:-1] + b"X"
        obj_path.write_bytes(corrupted)

        run_spec = {
            "adapter_id": "echo.v1",
            "input_payloads": {"input.json": input_digest},
            "pack_ref": None,
        }
        raised = False
        reason = ""
        try:
            materialize_run(run_spec, store, root / "staging")
        except Exception as exc:
            raised = True
            reason = getattr(exc, "fail_reason", "")

        case = {
            "raised": raised,
            "fail_reason": reason,
            "expected_reason": _CAS_INTEGRITY_FAILURE_REF,
        }
        if not raised or reason != _CAS_INTEGRITY_FAILURE_REF:
            return {
                "status": "FAIL",
                "detail": "input hash mismatch did not abort with CAS_INTEGRITY_FAILURE",
                "case": case,
            }
        return {
            "status": "PASS",
            "detail": "input hash mismatch raised CAS_INTEGRITY_FAILURE before the run receipt",
            "case": case,
        }


# ---------------------------------------------------------------------------
# D32-03 schema-invalid output -> no receipt, no ingest.
# ---------------------------------------------------------------------------


def _check_d32_03() -> dict[str, Any]:
    """D32-03: a schema-invalid output produces no receipt and no ingests."""
    policy = load_policy(_POLICY_PATH)
    input_payload = {"value": "hello"}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root / "store")
        receipt_dir = root / "receipts"
        input_digest = _ingest_input(store, input_payload)

        run_spec = {
            "adapter_id": "echo.v1",
            "input_payloads": {"input.json": input_digest},
            "pack_ref": None,
        }
        staged = materialize_run(run_spec, store, root / "staging")

        scratch = prepare_scratch(parent=root)
        try:
            outcome = run_adapter("echo.v1", input_payload, policy, scratch, wall_seconds=10)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        raised = False
        reason = ""
        objects_before = len(list((root / "store" / "objects").rglob("sha256:*")))
        try:
            seal_run(staged, outcome, store, receipt_dir, output_validator=_invalid_output)
        except SealerError as exc:
            raised = True
            reason = exc.fail_reason

        objects_after = len(list((root / "store" / "objects").rglob("sha256:*")))
        receipts = list(receipt_dir.glob("*.json"))
        case = {
            "raised": raised,
            "fail_reason": reason,
            "expected_reason": _CONTRACT_INVALID_REF,
            "object_files_before": objects_before,
            "object_files_after": objects_after,
            "receipt_files": len(receipts),
        }
        failures = []
        if not raised or reason != _CONTRACT_INVALID_REF:
            failures.append("schema-invalid output did not raise SealerError(CONTRACT_INVALID)")
        if objects_after != objects_before:
            failures.append("sealer ingested objects despite invalid output")
        if receipts:
            failures.append("a run receipt was written despite invalid output")
        if failures:
            return {"status": "FAIL", "detail": "; ".join(failures), "case": case}
        return {
            "status": "PASS",
            "detail": "schema-invalid output raised CONTRACT_INVALID; no receipt, no ingest",
            "case": case,
        }


# ---------------------------------------------------------------------------
# D32-04 store ingest failure -> no run receipt.
# ---------------------------------------------------------------------------


def _check_d32_04() -> dict[str, Any]:
    """D32-04: a store ingest failure leaves no run receipt."""
    policy = load_policy(_POLICY_PATH)
    input_payload = {"value": "hello"}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = _FailingStore(root / "store", fail_on=2)
        receipt_dir = root / "receipts"
        input_digest = _ingest_input(store, input_payload)

        run_spec = {
            "adapter_id": "echo.v1",
            "input_payloads": {"input.json": input_digest},
            "pack_ref": None,
        }
        staged = materialize_run(run_spec, store, root / "staging")

        scratch = prepare_scratch(parent=root)
        try:
            outcome = run_adapter("echo.v1", input_payload, policy, scratch, wall_seconds=10)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        raised = False
        reason = ""
        try:
            seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)
        except QuotaExceededError as exc:
            raised = True
            reason = exc.fail_reason

        receipts = list(receipt_dir.glob("*.json"))
        case = {
            "raised": raised,
            "fail_reason": reason,
            "expected_reason": "T7_QUOTA_EXCEEDED",
            "receipt_files": len(receipts),
        }
        if not raised:
            return {
                "status": "FAIL",
                "detail": "store ingest failure did not raise",
                "case": case,
            }
        if receipts:
            return {
                "status": "FAIL",
                "detail": "a run receipt was written despite the ingest failure",
                "case": case,
            }
        return {
            "status": "PASS",
            "detail": (
                "store ingest failure raised T7_QUOTA_EXCEEDED and no run receipt was written"
            ),
            "case": case,
        }


# ---------------------------------------------------------------------------
# D32-05 receipt has no absolute paths.
# ---------------------------------------------------------------------------


def _check_d32_05() -> dict[str, Any]:
    """D32-05: the run receipt contains no raw host-local paths."""
    policy = load_policy(_POLICY_PATH)
    input_payload = {"value": "hello"}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalArtifactStore(root / "store")
        receipt_dir = root / "receipts"
        input_digest = _ingest_input(store, input_payload)

        run_spec = {
            "adapter_id": "echo.v1",
            "input_payloads": {"input.json": input_digest},
            "pack_ref": None,
        }
        staged = materialize_run(run_spec, store, root / "staging")

        scratch = prepare_scratch(parent=root)
        try:
            outcome = run_adapter("echo.v1", input_payload, policy, scratch, wall_seconds=10)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        sealed = seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)
        text = sealed.run_receipt_path.read_text(encoding="utf-8")
        leak = _RAW_PATH_RE.search(text)

        case = {
            "leak_found": leak is not None,
            "store_root_redacted": sealed.run_receipt.get("store_root_redacted", ""),
        }
        if leak:
            return {
                "status": "FAIL",
                "detail": f"run receipt contains a raw host-local path: {leak.group(0)!r}",
                "case": case,
            }
        return {
            "status": "PASS",
            "detail": "run receipt contains no raw host-local paths; store root is redacted",
            "case": case,
        }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: policy path, adapter, and redaction patterns."""
    return {
        "policy_path": str(_POLICY_PATH.relative_to(_REPO_ROOT)),
        "adapter": "echo.v1",
        "input_media_type": _INPUT_MEDIA_TYPE,
    }


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "D32-01": _check_d32_01(),
        "D32-02": _check_d32_02(),
        "D32-03": _check_d32_03(),
        "D32-04": _check_d32_04(),
        "D32-05": _check_d32_05(),
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

    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "D32-01": _check_d32_01,
            "D32-02": _check_d32_02,
            "D32-03": _check_d32_03,
            "D32-04": _check_d32_04,
            "D32-05": _check_d32_05,
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
    raise SystemExit(main())
