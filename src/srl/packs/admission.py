"""Eight-stage admission pipeline for SRL resource packs.

The admission machine moves a pack linearly through nine stages connected by
eight explicit transitions:

    DISCOVERED -> SOURCE_VERIFIED -> LICENSE_CLEARED -> LOCKED -> BUILT
    -> BYTE_VERIFIED -> RUNTIME_PROBED -> ACTUAL_COMPUTE_PROBED
    -> EXPERIMENTAL_ACCEPTED

Each transition emits a :class:`~srl.packs.receipts.PackStageReceipt`. No stage
is ever inferred: a pack is at the stage of its most recent receipt, and a
stage with no receipt was never reached.

Typed terminal rejections
-------------------------
A transition can be rejected for a typed reason from the SRL fail-reason
registry (``automation/fail-reasons.json``):

- ``UPSTREAM_SOURCE_UNVERIFIED`` — source verification evidence did not pass.
- ``LICENSE_UNKNOWN`` — the license could not be identified.
- ``LICENSE_INCOMPATIBLE`` — the license is identified but barred by policy.
- ``DEPENDENCY_LOCK_DRIFT`` — the resolved dependency lock drifted from the
  recorded manifest.
- ``PACK_INTEGRITY_FAILURE`` — the manifest or byte tree failed structural or
  hash checks.
- ``PACK_PROBE_ONLY`` — a request reached ``EXPERIMENTAL_ACCEPTED`` from
  ``RUNTIME_PROBED`` without the actual-compute probe stage.
- ``ACTUAL_COMPUTE_FAILED`` — a runtime or actual-compute probe did not pass.

Honesty note
------------
``EXPERIMENTAL_ACCEPTED`` is an *admission* decision: the pack is admitted to
the experimental fabric with its provenance and integrity checks recorded. It
is **not** a scientific validation of the pack's claims; that is the role of the
science-lab evidence model (WP-B13) and the actual-compute probes that feed it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.packs.manifest import (
    LICENSE_INCOMPATIBLE_REASON,
    LICENSE_UNKNOWN_REASON,
    PACK_INTEGRITY_FAILURE_REASON,
)
from srl.packs.receipts import (
    STAGES,
    PackStageReceipt,
    build_pack_stage_receipt,
)

# Typed fail reasons from the SRL registry (see automation/fail-reasons.json).
UPSTREAM_SOURCE_UNVERIFIED_REASON: Final[str] = "UPSTREAM_SOURCE_UNVERIFIED"
DEPENDENCY_LOCK_DRIFT_REASON: Final[str] = "DEPENDENCY_LOCK_DRIFT"
PACK_PROBE_ONLY_REASON: Final[str] = "PACK_PROBE_ONLY"
ACTUAL_COMPUTE_FAILED_REASON: Final[str] = "ACTUAL_COMPUTE_FAILED"


class AdmissionError(ContractError):
    """Raised when a pack admission transition is illegal or fails a gate.

    Carries the typed fail reason from the fail-reason registry. The default is
    ``CONTRACT_INVALID`` for structural/order violations; gate failures use the
    specific typed reason for that gate.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class AdmissionState:
    """The state of a pack in the admission pipeline.

    Attributes
    ----------
    pack_id:
        The pack identifier.
    current_stage:
        The latest reached stage (one of :data:`STAGES`).
    receipts:
        Tuple of receipts emitted so far, in order of emission. The last receipt
        corresponds to ``current_stage``.
    """

    pack_id: str
    current_stage: str
    receipts: tuple[PackStageReceipt, ...]

    def __post_init__(self) -> None:
        if self.current_stage not in STAGES:
            msg = f"invalid current_stage {self.current_stage!r}; must be one of {STAGES!r}"
            raise AdmissionError(msg)
        if self.receipts:
            last_stage = self.receipts[-1].stage
            if last_stage != self.current_stage:
                msg = (
                    f"last receipt stage {last_stage!r} does not match "
                    f"current_stage {self.current_stage!r}"
                )
                raise AdmissionError(msg)
        for i, receipt in enumerate(self.receipts[1:], start=1):
            prev = self.receipts[i - 1]
            if receipt.from_stage != prev.stage:
                msg = (
                    f"receipt chain broken at index {i}: "
                    f"{receipt.stage!r} claims from {receipt.from_stage!r}, "
                    f"but previous stage is {prev.stage!r}"
                )
                raise AdmissionError(msg)


def initial_state(pack_id: str) -> AdmissionState:
    """Return the initial admission state for ``pack_id`` (``DISCOVERED``)."""
    if not isinstance(pack_id, str) or pack_id == "":
        msg = f"pack_id must be a non-empty string, got {pack_id!r}"
        raise AdmissionError(msg)
    return AdmissionState(pack_id=pack_id, current_stage="DISCOVERED", receipts=())


def advance(
    state: AdmissionState,
    stage: str,
    evidence: dict[str, Any],
    *,
    created_utc: str | None = None,
) -> tuple[AdmissionState, PackStageReceipt]:
    """Advance ``state`` to ``stage`` with ``evidence``.

    Returns a new :class:`AdmissionState` carrying the emitted receipt. The
    transition is legal only if ``stage`` is the immediate next stage in the
    linear pipeline. Skipping a stage is a structural contract error.

    Parameters
    ----------
    state:
        Current admission state.
    stage:
        Target stage to reach.
    evidence:
        JSON-serializable dict with a ``kind`` string naming the gate evidence
        for the transition. The required shape depends on ``stage`` (see
        :func:`_validate_gate`).
    created_utc:
        Optional timestamp for the new receipt. If ``None``, the current UTC
        time is used.

    Returns
    -------
    tuple[AdmissionState, PackStageReceipt]
        The new state and the transition receipt.

    Raises
    ------
    AdmissionError
        With a typed fail reason if the order is illegal, the evidence is
        malformed, or the gate for the transition fails.
    """
    if stage not in STAGES:
        msg = f"unknown stage {stage!r}; must be one of {STAGES!r}"
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)

    current_idx = STAGES.index(state.current_stage)
    target_idx = STAGES.index(stage)

    # Idempotent resume: re-advancing an already-reached stage returns the
    # existing receipt with no duplicate.
    if target_idx == current_idx:
        for receipt in reversed(state.receipts):
            if receipt.stage == stage:
                return state, receipt
        # The initial DISCOVERED stage has no receipt; re-advancing it is a
        # structural misuse, not a transition.
        msg = f"no receipt for idempotent re-advance of {stage!r}"
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)

    if target_idx < current_idx:
        msg = (
            f"cannot regress admission for {state.pack_id!r} from "
            f"{state.current_stage!r} to {stage!r}"
        )
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)

    # The only non-immediate forward move that is checked semantically is
    # RUNTIME_PROBED -> EXPERIMENTAL_ACCEPTED: it means the actual-compute
    # probe stage was skipped. Every other skip is a structural contract error.
    if state.current_stage == "RUNTIME_PROBED" and stage == "EXPERIMENTAL_ACCEPTED":
        msg = (
            f"cannot accept {state.pack_id!r} as EXPERIMENTAL_ACCEPTED from "
            "RUNTIME_PROBED: actual-compute probe never ran"
        )
        raise AdmissionError(msg, fail_reason=PACK_PROBE_ONLY_REASON)

    if target_idx != current_idx + 1:
        missing = STAGES[current_idx + 1]
        msg = (
            f"skip from {state.current_stage!r} to {stage!r} for "
            f"{state.pack_id!r} missing required stage {missing!r}"
        )
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)

    from_stage = state.current_stage
    _validate_gate(from_stage, stage, evidence)

    receipt = build_pack_stage_receipt(
        pack_id=state.pack_id,
        stage=stage,
        from_stage=from_stage,
        evidence=evidence,
        created_utc=created_utc,
    )
    new_state = AdmissionState(
        pack_id=state.pack_id,
        current_stage=stage,
        receipts=(*state.receipts, receipt),
    )
    return new_state, receipt


def _validate_gate(_from_stage: str, stage: str, evidence: Any) -> None:
    """Validate the gate evidence for ``stage``.

    Each gate expects a specific ``kind`` and pass/fail flags. A failed gate
    raises :class:`AdmissionError` with the typed fail reason for that gate.
    """
    if not isinstance(evidence, dict):
        msg = f"evidence must be a dict, got {type(evidence).__name__}"
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)

    kind = evidence.get("kind")
    if not isinstance(kind, str):
        msg = f"evidence must contain a string 'kind', got {kind!r}"
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)

    expected_kind = _GATE_KINDS.get(stage)
    if expected_kind is None:
        msg = f"no admission gate defined for stage {stage!r}"
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)
    _expect_kind(kind, expected_kind)
    _GATE_VALIDATORS[stage](evidence)


def _expect_kind(kind: str, expected: str) -> None:
    """Raise CONTRACT_INVALID if ``kind`` does not match ``expected``."""
    if kind != expected:
        msg = f"expected evidence kind {expected!r}, got {kind!r}"
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def _check_source_verified(evidence: dict[str, Any]) -> None:
    if not evidence.get("verified"):
        raise AdmissionError(
            "upstream source verification failed",
            fail_reason=UPSTREAM_SOURCE_UNVERIFIED_REASON,
        )


def _check_license_cleared(evidence: dict[str, Any]) -> None:
    status = evidence.get("status")
    if status == "unknown":
        spdx = evidence.get("spdx", "unknown")
        raise AdmissionError(f"license {spdx!r} is unknown", fail_reason=LICENSE_UNKNOWN_REASON)
    if status == "incompatible":
        spdx = evidence.get("spdx", "unknown")
        raise AdmissionError(
            f"license {spdx!r} is incompatible",
            fail_reason=LICENSE_INCOMPATIBLE_REASON,
        )
    if status != "allowed":
        msg = f"license clearance status must be 'allowed', got {status!r}"
        raise AdmissionError(msg, fail_reason=CONTRACT_INVALID_FAIL_REASON)


def _check_locked(evidence: dict[str, Any]) -> None:
    if evidence.get("drift"):
        raise AdmissionError(
            "dependency lock drifted from the recorded manifest",
            fail_reason=DEPENDENCY_LOCK_DRIFT_REASON,
        )


def _check_built(evidence: dict[str, Any]) -> None:
    if not evidence.get("valid"):
        raise AdmissionError(
            "manifest build failed structural or integrity checks",
            fail_reason=PACK_INTEGRITY_FAILURE_REASON,
        )


def _check_byte_verified(evidence: dict[str, Any]) -> None:
    if not evidence.get("matched"):
        raise AdmissionError(
            "byte tree verification failed",
            fail_reason=PACK_INTEGRITY_FAILURE_REASON,
        )


def _check_runtime_probed(evidence: dict[str, Any]) -> None:
    if not evidence.get("passed"):
        raise AdmissionError("runtime probe failed", fail_reason=ACTUAL_COMPUTE_FAILED_REASON)


def _check_actual_compute_probed(evidence: dict[str, Any]) -> None:
    if not evidence.get("passed"):
        raise AdmissionError(
            "actual compute probe failed",
            fail_reason=ACTUAL_COMPUTE_FAILED_REASON,
        )


def _check_experimental_accepted(_evidence: dict[str, Any]) -> None:
    # Acceptance is terminal and succeeds with valid evidence; the prior
    # ACTUAL_COMPUTE_PROBED stage already proved the compute gate.
    return


_GATE_KINDS: Final[dict[str, str]] = {
    "SOURCE_VERIFIED": "source_verification",
    "LICENSE_CLEARED": "license_clearance",
    "LOCKED": "lock_digest",
    "BUILT": "build_manifest",
    "BYTE_VERIFIED": "tree_hash",
    "RUNTIME_PROBED": "runtime_probe",
    "ACTUAL_COMPUTE_PROBED": "actual_compute_probe",
    "EXPERIMENTAL_ACCEPTED": "experimental_accept",
}

_GATE_VALIDATORS: Final[dict[str, Callable[[dict[str, Any]], None]]] = {
    "SOURCE_VERIFIED": _check_source_verified,
    "LICENSE_CLEARED": _check_license_cleared,
    "LOCKED": _check_locked,
    "BUILT": _check_built,
    "BYTE_VERIFIED": _check_byte_verified,
    "RUNTIME_PROBED": _check_runtime_probed,
    "ACTUAL_COMPUTE_PROBED": _check_actual_compute_probed,
    "EXPERIMENTAL_ACCEPTED": _check_experimental_accepted,
}


__all__ = [
    "ACTUAL_COMPUTE_FAILED_REASON",
    "DEPENDENCY_LOCK_DRIFT_REASON",
    "LICENSE_INCOMPATIBLE_REASON",
    "LICENSE_UNKNOWN_REASON",
    "PACK_INTEGRITY_FAILURE_REASON",
    "PACK_PROBE_ONLY_REASON",
    "UPSTREAM_SOURCE_UNVERIFIED_REASON",
    "AdmissionError",
    "AdmissionState",
    "advance",
    "initial_state",
]
