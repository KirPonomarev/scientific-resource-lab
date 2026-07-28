"""Pack stage receipts for the WP-C23 admission pipeline.

Every transition through the eight-stage admission machine emits an explicit
:class:`PackStageReceipt` in ``PackStageReceipt/v1`` shape. No stage is ever
inferred: a receipt is the evidence that a transition happened, and a stage
without a receipt was never reached.

Receipt identity
----------------
The ``receipt_id`` is ``sha256:<64 hex>`` over the canonical encoding of the
receipt *without* its own ``receipt_id`` field. This makes the id a pure
function of the receipt content: two independent builders that emit the same
stage, pack, evidence, and timestamp produce the same id.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from typing import Any, Final

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Schema identity. Bumped only on a contract change to the receipt shape.
RECEIPT_SCHEMA_VERSION: Final[str] = "PackStageReceipt/v1"

# The canonical stages of the pack admission pipeline, in legal order.
# A stage name is arbitrary except for its position in this tuple.
STAGES: Final[tuple[str, ...]] = (
    "DISCOVERED",
    "SOURCE_VERIFIED",
    "LICENSE_CLEARED",
    "LOCKED",
    "BUILT",
    "BYTE_VERIFIED",
    "RUNTIME_PROBED",
    "ACTUAL_COMPUTE_PROBED",
    "EXPERIMENTAL_ACCEPTED",
)


class ReceiptError(ContractError):
    """Raised when a pack stage receipt violates its structural contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class PackStageReceipt:
    """PackStageReceipt/v1: evidence of one admission stage transition.

    Attributes
    ----------
    schema_version:
        Always ``PackStageReceipt/v1``.
    receipt_id:
        ``sha256:<64 hex>`` content-addressed identity of this receipt.
    pack_id:
        The pack that transitioned.
    stage:
        The stage reached (one of :data:`STAGES`).
    from_stage:
        The previous stage, or ``None`` for the initial ``DISCOVERED`` receipt
        (which records the starting point rather than a transition).
    evidence:
        A JSON-serializable dict describing the evidence that justified the
        transition. The ``kind`` key is required and names the gate that was
        satisfied (e.g. ``"license_clearance"``).
    created_utc:
        RFC 3339 UTC timestamp (seconds precision) when the receipt was issued.
    canonical_writes:
        Always ``0`` (a receipt is a read-only record; it does not mutate state).
    grants_authority:
        Always ``False`` (admission receipts do not grant scientific authority).
    """

    schema_version: str
    receipt_id: str
    pack_id: str
    stage: str
    from_stage: str | None
    evidence: dict[str, Any]
    created_utc: str
    canonical_writes: int
    grants_authority: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the receipt as a plain JSON-serializable dict."""
        return asdict(self)

    def canonical_dumps(self) -> bytes:
        """Return canonical JSON bytes (sorted keys, compact, trailing newline)."""
        return dumps(self.to_dict())


def _utc_now() -> str:
    """Return an RFC 3339 UTC timestamp string with a trailing ``Z``."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _validate_stage(stage: str) -> str:
    """Return ``stage`` if it is a known stage name, else raise ReceiptError."""
    if stage not in STAGES:
        msg = f"stage {stage!r} must be one of {STAGES!r}"
        raise ReceiptError(msg)
    return stage


def _require_non_empty_str(value: Any, field: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise ReceiptError."""
    if not isinstance(value, str) or value == "":
        msg = f"{field} must be a non-empty string, got {value!r}"
        raise ReceiptError(msg)
    return value


def _canonical_receipt_id(seed: dict[str, Any]) -> str:
    """Compute the content-addressed receipt id for a receipt seed.

    The seed is the receipt body *without* the ``receipt_id`` field. Hashing it
    gives a deterministic id that is a pure function of the receipt content.
    """
    return "sha256:" + hashlib.sha256(dumps(seed)).hexdigest()


def build_pack_stage_receipt(
    pack_id: str,
    stage: str,
    from_stage: str | None,
    evidence: Any,
    created_utc: str | None = None,
) -> PackStageReceipt:
    """Build a :class:`PackStageReceipt` and compute its content-addressed id.

    Parameters
    ----------
    pack_id:
        Non-empty identifier of the pack.
    stage:
        Stage reached (one of :data:`STAGES`).
    from_stage:
        Previous stage, or ``None`` for the initial ``DISCOVERED`` receipt.
    evidence:
        JSON-serializable dict with at least a ``kind`` string describing the
        gate satisfied by this transition.
    created_utc:
        Optional RFC 3339 UTC timestamp. If ``None``, the current UTC time is
        used.

    Returns
    -------
    PackStageReceipt
        A validated, immutable receipt with its ``receipt_id`` populated.

    Raises
    ------
    ReceiptError
        If any field violates the structural contract.
    """
    pack_id = _require_non_empty_str(pack_id, "pack_id")
    stage = _validate_stage(stage)
    if from_stage is not None:
        from_stage = _validate_stage(from_stage)
        if from_stage == stage:
            msg = f"from_stage and stage must differ, got {stage!r}"
            raise ReceiptError(msg)
    if not isinstance(evidence, dict):
        msg = f"evidence must be a dict, got {type(evidence).__name__}"
        raise ReceiptError(msg)
    if not isinstance(evidence.get("kind"), str):
        msg = f"evidence must contain a string 'kind', got {evidence.get('kind')!r}"
        raise ReceiptError(msg)
    if created_utc is None:
        created_utc = _utc_now()
    created_utc = _require_non_empty_str(created_utc, "created_utc")

    canonical_writes = 0
    grants_authority = False

    seed: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "pack_id": pack_id,
        "stage": stage,
        "from_stage": from_stage,
        "evidence": evidence,
        "created_utc": created_utc,
        "canonical_writes": canonical_writes,
        "grants_authority": grants_authority,
    }
    receipt_id = _canonical_receipt_id(seed)
    return PackStageReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        receipt_id=receipt_id,
        pack_id=pack_id,
        stage=stage,
        from_stage=from_stage,
        evidence=evidence,
        created_utc=created_utc,
        canonical_writes=canonical_writes,
        grants_authority=grants_authority,
    )


__all__ = [
    "RECEIPT_SCHEMA_VERSION",
    "STAGES",
    "PackStageReceipt",
    "ReceiptError",
    "build_pack_stage_receipt",
]
