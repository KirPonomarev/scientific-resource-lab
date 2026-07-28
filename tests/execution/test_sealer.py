"""Unit tests for run sealing (srl.execution.sealer).

The sealer validates the runner output, ingests the output and the engine receipt
into the content-addressed store, and writes the final run receipt last. Any
failure before the run receipt (output validation failure or store ingest failure)
produces no run receipt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from srl.cas import LocalArtifactStore
from srl.cas.engine import QuotaExceededError
from srl.execution.materialize import StagedRun
from srl.execution.runner import RunOutcome, RunStatus, RunUsage
from srl.execution.sealer import (
    ENGINE_RECEIPT_SCHEMA_VERSION,
    RUN_RECEIPT_SCHEMA_VERSION,
    SealedRun,
    SealerError,
    seal_run,
)


def _valid_output(output: object) -> None:
    if not isinstance(output, dict) or "value" not in output:
        raise ValueError("output missing 'value' field")


def _make_staged(tmp_path: Path) -> StagedRun:
    return StagedRun(
        adapter_id="echo.v1",
        staging_path=tmp_path / "staging" / "srl-run-123",
        input_digests={"input.json": "sha256:" + "a" * 64},
        pack_digest=None,
    )


def _make_completed_outcome(output: dict[str, Any] | None) -> RunOutcome:
    return RunOutcome(
        adapter_id="echo.v1",
        status=RunStatus.COMPLETED if output is not None else RunStatus.FAILED,
        output=output,
        usage=RunUsage(wall_seconds=0.123, rss_bytes=4096, output_bytes=0),
        receipt_written=False,
        fail_reason=None,
        detail="test",
    )


# ---------------------------------------------------------------------------
# Happy paths.
# ---------------------------------------------------------------------------


def test_seal_happy_path_writes_receipt_and_ingests_output(tmp_path: Path) -> None:
    """A completed run is sealed with a run receipt, output, and engine receipt."""
    store = LocalArtifactStore(tmp_path / "store")
    receipt_dir = tmp_path / "receipts"
    staged = _make_staged(tmp_path)
    outcome = _make_completed_outcome({"value": "hello"})

    sealed = seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)

    assert isinstance(sealed, SealedRun)
    assert sealed.run_receipt_path.exists()
    assert sealed.run_receipt["schema_version"] == RUN_RECEIPT_SCHEMA_VERSION
    assert sealed.run_receipt["adapter_id"] == "echo.v1"
    assert sealed.run_receipt["engine_receipt_id"] == sealed.engine_receipt_id
    assert sealed.run_receipt["input_digests"] == staged.input_digests
    assert sealed.run_receipt["output_digests"] == {"output.json": sealed.output_object_id}
    assert sealed.output_object_id in sealed.run_receipt["store_descriptor_ids"]
    assert sealed.engine_receipt_object_id in sealed.run_receipt["store_descriptor_ids"]
    assert sealed.run_receipt["store_root_redacted"].startswith("redacted:")

    # Read-back verify the receipt.
    receipt = json.loads(sealed.run_receipt_path.read_text(encoding="utf-8"))
    assert receipt["receipt_id"] == sealed.run_receipt["receipt_id"]

    # Engine receipt is also ingested.
    assert sealed.output_object_id is not None
    assert store.has(sealed.engine_receipt_object_id)
    assert store.has(sealed.output_object_id)


def test_seal_failed_run_still_writes_receipt_no_output(tmp_path: Path) -> None:
    """A failed run (no output) gets a receipt with empty output bindings."""
    store = LocalArtifactStore(tmp_path / "store")
    receipt_dir = tmp_path / "receipts"
    staged = _make_staged(tmp_path)
    outcome = _make_completed_outcome(None)

    sealed = seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)

    assert sealed.run_receipt_path.exists()
    assert sealed.run_receipt["output_digests"] == {}
    assert sealed.output_object_id is None
    assert sealed.run_receipt["store_descriptor_ids"] == [sealed.engine_receipt_object_id]

    engine_receipt = json.loads(store.get(sealed.engine_receipt_object_id))
    assert engine_receipt["engine_execution"] == "failed"


# ---------------------------------------------------------------------------
# Output validation failure.
# ---------------------------------------------------------------------------


def test_seal_invalid_output_no_receipt_no_ingest(tmp_path: Path) -> None:
    """A schema-invalid output produces no receipt and no store objects."""
    store = LocalArtifactStore(tmp_path / "store")
    receipt_dir = tmp_path / "receipts"
    staged = _make_staged(tmp_path)
    outcome = _make_completed_outcome({"bad": 1})

    with pytest.raises(SealerError) as exc_info:
        seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)
    assert exc_info.value.fail_reason == "CONTRACT_INVALID"
    assert not list(receipt_dir.glob("*.json"))
    # No objects ingested.
    assert not list((tmp_path / "store" / "objects").rglob("sha256:*"))


# ---------------------------------------------------------------------------
# Store ingest failure.
# ---------------------------------------------------------------------------


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
            raise QuotaExceededError("simulated ingest failure")
        return super().ingest_bytes(
            source_bytes,
            media_type,
            capacity_hook=capacity_hook,
            used_bytes=used_bytes,
            created_utc=created_utc,
        )


def test_seal_store_failure_no_run_receipt(tmp_path: Path) -> None:
    """A store ingest failure after the output ingest leaves no run receipt."""
    store = _FailingStore(tmp_path / "store", fail_on=2)
    receipt_dir = tmp_path / "receipts"
    staged = _make_staged(tmp_path)
    outcome = _make_completed_outcome({"value": "hello"})

    with pytest.raises(QuotaExceededError):
        seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)

    # No run receipt.
    assert not list(receipt_dir.glob("*.json"))
    # Output may have been ingested before the failure, but no engine receipt.
    assert store._calls == 2


# ---------------------------------------------------------------------------
# Path redaction in the receipt.
# ---------------------------------------------------------------------------


def test_seal_receipt_contains_no_absolute_paths(tmp_path: Path) -> None:
    """The run receipt never contains an absolute host-local path."""
    store = LocalArtifactStore(tmp_path / "store")
    receipt_dir = tmp_path / "receipts"
    staged = _make_staged(tmp_path)
    outcome = _make_completed_outcome({"value": "hello"})

    sealed = seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)
    text = sealed.run_receipt_path.read_text(encoding="utf-8")

    # No raw Unix / macOS home or volume paths.
    assert re.search(r"/(Users|Volumes|home)/", text) is None
    assert re.search(r"[A-Za-z]:\\", text) is None
    assert "redacted:" in text


# ---------------------------------------------------------------------------
# Engine receipt shape.
# ---------------------------------------------------------------------------


def test_seal_engine_receipt_shape(tmp_path: Path) -> None:
    """The engine receipt carries the expected schema and execution evidence."""
    store = LocalArtifactStore(tmp_path / "store")
    receipt_dir = tmp_path / "receipts"
    staged = _make_staged(tmp_path)
    outcome = _make_completed_outcome({"value": "hello"})

    sealed = seal_run(staged, outcome, store, receipt_dir, output_validator=_valid_output)
    engine_bytes = store.get(sealed.engine_receipt_object_id)
    engine = json.loads(engine_bytes.decode("utf-8"))

    assert engine["schema_version"] == ENGINE_RECEIPT_SCHEMA_VERSION
    assert engine["receipt_id"] == sealed.engine_receipt_id
    assert engine["adapter_id"] == "echo.v1"
    assert engine["exercise_level"] == "actual_compute"
    assert engine["engine_execution"] == "completed"
    assert engine["wall_seconds"] == 0.123
    assert engine["rss_bytes"] == 4096
    assert engine["output_object_ids"] == [sealed.output_object_id]
