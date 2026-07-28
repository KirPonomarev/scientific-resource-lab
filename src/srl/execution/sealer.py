"""Run sealer: validate output, ingest artifacts, and write the run receipt (WP-D32).

The sealer is the receipt-last step of a bounded scientific run. It takes a
staged run, validates the runner's output against an injected schema validator,
ingests the output and the engine receipt into the content-addressed store, and
writes the final run receipt to a receipt directory. Any failure before the run
receipt is written produces **no run receipt**; partial CAS ingests are not
rolled back (they are explicit evidence of how far the run progressed).

The engine receipt is execution evidence, not validation: it records whether the
engine reported ``completed`` or ``failed``, the observed wall seconds and RSS,
and the content-addressed ids of the output objects. The run receipt then binds
the input digests, output digests, engine receipt id, and the ids of the store
descriptors that were published by the seal. No absolute filesystem paths are
written to the receipt; the store root is recorded via
:func:`~srl.cas.privacy.redact_store_path`.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from srl.cas.store import LocalArtifactStore
from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.execution.materialize import StagedRun
from srl.execution.runner import RunOutcome, RunStatus

# Schema identity anchors for the two receipts produced by the sealer.
ENGINE_RECEIPT_SCHEMA_VERSION: Final[str] = "ScienceLabEngineReceipt/v1"
RUN_RECEIPT_SCHEMA_VERSION: Final[str] = "ScienceLabRunReceipt/v1"

# The exercise level recorded on every sealed run (local bounded execution).
_EXERCISE_LEVEL: Final[str] = "actual_compute"

# Media types for the objects ingested by the sealer.
_OUTPUT_MEDIA_TYPE: Final[str] = "application/json"
_ENGINE_RECEIPT_MEDIA_TYPE: Final[str] = "application/srl.engine-receipt.v1+json"

# The output name used when a run produces a single validated handler dict.
_OUTPUT_NAME: Final[str] = "output.json"


class SealerError(ContractError):
    """Raised when a sealer contract (e.g. output schema validation) fails.

    Carries the typed fail reason ``CONTRACT_INVALID``. Store-level failures are
    allowed to propagate unchanged so their own typed reasons (e.g.
    ``T7_QUOTA_EXCEEDED``) are preserved.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


@dataclass(frozen=True)
class SealedRun:
    """The result of sealing a run: the receipt path and the ids it binds.

    Attributes
    ----------
    run_receipt_path:
        Path to the written ``ScienceLabRunReceipt/v1`` JSON file.
    run_receipt:
        The run receipt dict (including its ``receipt_id``).
    engine_receipt_id:
        The self-reported ``receipt_id`` of the engine receipt (the content
        digest of the engine receipt *without* its own ``receipt_id`` field).
    engine_receipt_object_id:
        The content-addressed object id of the engine receipt as published in the
        store (the digest of the canonical bytes *with* the ``receipt_id``
        field).
    output_object_id:
        The content-addressed object id of the runner output, or ``None`` if the
        run produced no validated output.
    """

    run_receipt_path: Path
    run_receipt: dict[str, Any]
    engine_receipt_id: str
    engine_receipt_object_id: str
    output_object_id: str | None


def _utc_now() -> str:
    """Return an ISO 8601 UTC timestamp string with a trailing ``Z``."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _compute_receipt_id(body: dict[str, Any]) -> str:
    """Return the content-addressed receipt id for ``body``.

    The id is the SHA-256 of the canonical JSON encoding of ``body`` with any
    ``receipt_id`` field removed. This matches the self-hash pattern in
    :mod:`srl.cas.descriptors`.
    """
    seed = {k: v for k, v in body.items() if k != "receipt_id"}
    return "sha256:" + hashlib.sha256(dumps(seed)).hexdigest()


def _engine_execution_status(outcome: RunOutcome) -> str:
    """Map the runner outcome to the engine receipt's binary execution status."""
    return "completed" if outcome.status is RunStatus.COMPLETED else "failed"


def _ingest_output(
    store: LocalArtifactStore,
    output: Any,
) -> str:
    """Canonicalize ``output`` and ingest it into ``store``; return its object id."""
    payload = dumps(output)
    outcome = store.ingest_bytes(payload, _OUTPUT_MEDIA_TYPE)
    return outcome.digest


def _ingest_engine_receipt(body: dict[str, Any], store: LocalArtifactStore) -> tuple[str, str]:
    """Canonicalize and ingest the engine receipt; return (receipt_id, object_id).

    The receipt id is the content digest of the body *without* its own
    ``receipt_id`` field; the object id is the digest of the published bytes
    *with* the ``receipt_id`` field. Both are returned so the run receipt can
    bind the engine receipt id and the store descriptor list.
    """
    receipt_id = _compute_receipt_id(body)
    published = dict(body)
    published["receipt_id"] = receipt_id
    payload = dumps(published)
    outcome = store.ingest_bytes(payload, _ENGINE_RECEIPT_MEDIA_TYPE)
    return receipt_id, outcome.digest


def seal_run(
    staged: StagedRun,
    outcome: RunOutcome,
    store: LocalArtifactStore,
    receipt_dir: str | Path,
    *,
    output_validator: Callable[[object], None] | None = None,
) -> SealedRun:
    """Seal a completed/failed run: validate output, ingest artifacts, write receipt.

    The run receipt is written **last**, after the output and engine receipt have
    been ingested. If any step before the run receipt fails, no run receipt is
    produced. The caller can distinguish a completed run from a failed run by the
    ``engine_execution`` field in the engine receipt; the sealer itself runs for
    both, because execution evidence is valuable regardless of success.

    Parameters
    ----------
    staged:
        The staged run produced by :func:`~srl.execution.materialize.materialize_run`.
    outcome:
        The runner outcome produced by :func:`~srl.execution.runner.run_adapter`.
    store:
        The content-addressed store where the output and engine receipt are
        published.
    receipt_dir:
        Directory where the final ``ScienceLabRunReceipt/v1`` JSON file is
        written. Created if it does not exist.
    output_validator:
        Optional callable ``(output) -> None`` that raises if the output dict is
        schema-invalid. If supplied and ``outcome.output`` is not ``None``, it
        is invoked before any ingest. A validation failure produces **no** run
        receipt and **no** ingest.

    Returns
    -------
    SealedRun
        The path, the receipt dict, and the published object ids.

    Raises
    ------
    SealerError
        If the output fails schema validation (``CONTRACT_INVALID``).
    StoreError / QuotaExceededError / CasIntegrityError
        If the store refuses an ingest; no run receipt is written in that case.
    """
    # 1. Schema validation, if an output exists and a validator was supplied.
    output_object_id: str | None = None
    if outcome.output is not None and output_validator is not None:
        try:
            output_validator(outcome.output)
        except Exception as exc:
            raise SealerError(f"output schema validation failed: {exc}") from exc
        output_object_id = _ingest_output(store, outcome.output)

    # 2. Build the engine receipt. Output is ingested first so its object id is
    #    available for the engine receipt's output_object_ids list.
    engine_receipt_body: dict[str, Any] = {
        "schema_version": ENGINE_RECEIPT_SCHEMA_VERSION,
        "adapter_id": staged.adapter_id,
        "exercise_level": _EXERCISE_LEVEL,
        "engine_execution": _engine_execution_status(outcome),
        "wall_seconds": outcome.usage.wall_seconds,
        "rss_bytes": outcome.usage.rss_bytes,
        "output_object_ids": [output_object_id] if output_object_id else [],
        "created_utc": _utc_now(),
    }
    engine_receipt_id, engine_receipt_object_id = _ingest_engine_receipt(engine_receipt_body, store)

    # 3. Build and write the run receipt LAST. It binds the digests the engine
    #    used and the store descriptors published by this seal.
    output_digests: dict[str, str] = {}
    if output_object_id:
        output_digests[_OUTPUT_NAME] = output_object_id
    store_descriptor_ids: list[str] = [engine_receipt_object_id]
    if output_object_id:
        store_descriptor_ids.insert(0, output_object_id)

    run_receipt_body: dict[str, Any] = {
        "schema_version": RUN_RECEIPT_SCHEMA_VERSION,
        "adapter_id": staged.adapter_id,
        "exercise_level": _EXERCISE_LEVEL,
        "engine_receipt_id": engine_receipt_id,
        "input_digests": dict(staged.input_digests),
        "output_digests": output_digests,
        "store_descriptor_ids": store_descriptor_ids,
        "store_root_redacted": store.store_root_redacted,
        "created_utc": _utc_now(),
    }
    run_receipt_id = _compute_receipt_id(run_receipt_body)
    run_receipt_body["receipt_id"] = run_receipt_id
    run_receipt_bytes = dumps(run_receipt_body)

    receipt_path = Path(receipt_dir)
    receipt_path.mkdir(parents=True, exist_ok=True)
    receipt_file = receipt_path / f"{run_receipt_id}.json"
    receipt_file.write_bytes(run_receipt_bytes)

    return SealedRun(
        run_receipt_path=receipt_file,
        run_receipt=run_receipt_body,
        engine_receipt_id=engine_receipt_id,
        engine_receipt_object_id=engine_receipt_object_id,
        output_object_id=output_object_id,
    )


__all__ = [
    "ENGINE_RECEIPT_SCHEMA_VERSION",
    "RUN_RECEIPT_SCHEMA_VERSION",
    "SealedRun",
    "SealerError",
    "seal_run",
]
