"""Crash-safe local spool transport.

The transport is deliberately small: it is a file protocol, not a daemon,
broker, SFTP route, or shared database. Messages are canonical JSON files
written through ``tmp`` and committed with atomic ``os.replace``. Receivers
validate schema, classification, detached signature, TTL, and idempotency before
recording an import receipt or terminal state.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from srl.contracts import object_id, validate_object_id
from srl.contracts.canonical import dumps, loads
from srl.contracts.errors import ContractError
from srl.contracts.schema import validate as schema_validate
from srl.contracts.timestamps import normalize as normalize_timestamp

_SIGNATURE_SCHEMA_VERSION = "DetachedSpoolSignature/v1"
_SIGNATURE_ALGORITHM_HMAC_SHA256 = "test-hmac-sha256"
_DEFAULT_ACK_CREATED_UTC = "2026-07-29T00:00:00Z"
_VALID_CLASSIFICATIONS = frozenset({"D0", "D1"})
_MIN_RETRY_SECONDS = 1
_MAX_RETRY_SECONDS = 3600


class SpoolState(StrEnum):
    """File-backed transport states."""

    QUEUED = "queued"
    IN_FLIGHT = "in-flight"
    ACKNOWLEDGED = "acknowledged"
    IMPORTED_AS_C3 = "imported-as-c3"
    REJECTED = "rejected"
    EXPIRED = "expired"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    DEAD_LETTERED = "dead-lettered"


class SpoolError(ContractError):
    """Raised when the local spool protocol is used incorrectly."""


class TransportRefusalError(SpoolError):
    """Raised for a deterministic terminal transport refusal."""


class SignatureVerifier(Protocol):
    """Detached signature verifier interface.

    Native deployments bind this interface to their Ed25519 keyring. The module
    ships a deterministic HMAC fixture implementation for local tests and
    conformance vectors; callers that do not provide a verifier fail closed.
    """

    def verify(self, message: Mapping[str, Any], signature: Mapping[str, Any]) -> bool:
        """Return True when ``signature`` authenticates ``message``."""


class SignatureSigner(Protocol):
    """Detached signature producer interface."""

    def sign(
        self,
        message: Mapping[str, Any],
        *,
        sequence: int,
        previous_signature_ref: str | None,
    ) -> DetachedSignature:
        """Return a detached signature for ``message``."""


@dataclass(frozen=True)
class DetachedSignature:
    """Detached signature and monotonic hash-chain metadata."""

    schema_version: str
    algorithm: str
    signer_cell: str
    message_id: str
    sequence: int
    previous_signature_ref: str | None
    signature_value: str

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON representation."""
        return {
            "schema_version": self.schema_version,
            "algorithm": self.algorithm,
            "signer_cell": self.signer_cell,
            "message_id": self.message_id,
            "sequence": self.sequence,
            "previous_signature_ref": self.previous_signature_ref,
            "signature_value": self.signature_value,
        }


@dataclass(frozen=True)
class HmacSha256Signer:
    """Deterministic fixture signer for local conformance tests.

    This signer is intentionally labelled ``test-hmac-sha256`` so it cannot be
    mistaken for production Ed25519 authority. It still enforces the important
    S05 property: unsigned or tampered messages are never accepted.
    """

    signer_cell: str
    secret: bytes

    def sign(
        self,
        message: Mapping[str, Any],
        *,
        sequence: int,
        previous_signature_ref: str | None,
    ) -> DetachedSignature:
        """Sign a message with deterministic hash-chain metadata."""
        _require_positive_sequence(sequence)
        message_id = _message_id_from_mapping(message)
        body = _signature_body(
            algorithm=_SIGNATURE_ALGORITHM_HMAC_SHA256,
            signer_cell=self.signer_cell,
            message_id=message_id,
            sequence=sequence,
            previous_signature_ref=previous_signature_ref,
        )
        signature_value = hmac.new(self.secret, dumps(body), hashlib.sha256).hexdigest()
        return DetachedSignature(
            schema_version=_SIGNATURE_SCHEMA_VERSION,
            algorithm=_SIGNATURE_ALGORITHM_HMAC_SHA256,
            signer_cell=self.signer_cell,
            message_id=message_id,
            sequence=sequence,
            previous_signature_ref=previous_signature_ref,
            signature_value=signature_value,
        )

    def verify(self, message: Mapping[str, Any], signature: Mapping[str, Any]) -> bool:
        """Verify a deterministic fixture signature."""
        try:
            _validate_detached_signature(signature)
            if signature.get("algorithm") != _SIGNATURE_ALGORITHM_HMAC_SHA256:
                return False
            if signature.get("schema_version") != _SIGNATURE_SCHEMA_VERSION:
                return False
            if signature.get("signer_cell") != self.signer_cell:
                return False
            if signature.get("message_id") != message.get("message_id"):
                return False
            expected = self.sign(
                message,
                sequence=_sequence_from_signature(signature),
                previous_signature_ref=_previous_ref_from_signature(signature),
            )
        except ContractError:
            return False
        return hmac.compare_digest(
            str(signature.get("signature_value", "")),
            expected.signature_value,
        )


class NullSignatureVerifier:
    """Fail-closed verifier used when no native key binding exists."""

    def verify(self, message: Mapping[str, Any], signature: Mapping[str, Any]) -> bool:
        """Always reject."""
        return False


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded deterministic exponential retry policy."""

    max_attempts: int
    base_seconds: int = 1
    max_delay_seconds: int = 300

    def __post_init__(self) -> None:
        """Validate retry bounds."""
        if self.max_attempts < 0:
            msg = "max_attempts must be non-negative"
            raise SpoolError(msg)
        if self.base_seconds < _MIN_RETRY_SECONDS:
            msg = "base_seconds must be at least 1"
            raise SpoolError(msg)
        if self.max_delay_seconds < self.base_seconds:
            msg = "max_delay_seconds must be >= base_seconds"
            raise SpoolError(msg)
        if self.max_delay_seconds > _MAX_RETRY_SECONDS:
            msg = f"max_delay_seconds must be <= {_MAX_RETRY_SECONDS}"
            raise SpoolError(msg)


@dataclass(frozen=True)
class QueuedMessage:
    """Paths and canonical objects produced by queueing a message."""

    message: dict[str, Any]
    signature: dict[str, Any]
    message_path: Path
    signature_path: Path


@dataclass(frozen=True)
class ReplayItem:
    """A deterministic replay item."""

    state: SpoolState
    message_id: str
    path: Path
    payload: dict[str, Any]


@dataclass(frozen=True)
class DeadLetterResult:
    """Dead-letter terminal record."""

    record: dict[str, Any]
    record_path: Path


def build_spool_message(  # noqa: PLR0913 - wire fields intentionally mirror SpoolMessage/v1.
    *,
    source_cell: str,
    target_cell: str,
    payload_ref: str,
    classification: str,
    created_utc: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build and schema-validate a ``SpoolMessage/v1``."""
    payload_ref = validate_object_id(payload_ref)
    if classification not in _VALID_CLASSIFICATIONS:
        allowed = sorted(_VALID_CLASSIFICATIONS)
        msg = f"classification must be one of {allowed}, got {classification!r}"
        raise TransportRefusalError(msg)
    created = normalize_timestamp(created_utc)
    idempotency = idempotency_key or object_id(
        {
            "schema_version": "SpoolIdempotencyKey/v1",
            "source_cell": source_cell,
            "target_cell": target_cell,
            "payload_ref": payload_ref,
            "classification": classification,
        }
    )
    validate_object_id(idempotency)
    without_id: dict[str, Any] = {
        "schema_version": "SpoolMessage/v1",
        "idempotency_key": idempotency,
        "source_cell": _require_non_empty(source_cell, "source_cell"),
        "target_cell": _require_non_empty(target_cell, "target_cell"),
        "payload_ref": payload_ref,
        "classification": classification,
        "created_utc": created,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    message = {"message_id": object_id(without_id), **without_id}
    schema_validate(message, "SpoolMessage")
    return message


def deterministic_retry_delays(message_id: str, policy: RetryPolicy) -> tuple[int, ...]:
    """Return deterministic bounded retry delays in seconds.

    The tiny jitter is derived from the message identity so every agent computes
    the same schedule without a background timer or random source.
    """
    validate_object_id(message_id)
    delays: list[int] = []
    for attempt in range(policy.max_attempts):
        exponential = policy.base_seconds * (2**attempt)
        capped = min(exponential, policy.max_delay_seconds)
        digest = hashlib.sha256(f"{message_id}:{attempt}".encode()).digest()
        jitter = digest[0] % max(policy.base_seconds, 1)
        delays.append(min(capped + jitter, policy.max_delay_seconds))
    return tuple(delays)


@dataclass(frozen=True)
class SpoolRoot:
    """A local filesystem spool root."""

    root: Path

    @classmethod
    def at(cls, root: str | Path) -> SpoolRoot:
        """Create a spool handle at ``root``."""
        return cls(Path(root))

    def initialize(self) -> None:
        """Create the deterministic directory layout."""
        for directory in self._all_directories():
            directory.mkdir(parents=True, exist_ok=True)

    def queue_message(
        self,
        message: Mapping[str, Any],
        *,
        signer: SignatureSigner,
        sequence: int | None = None,
        previous_signature_ref: str | None = None,
    ) -> QueuedMessage:
        """Seal and queue a message through atomic writes."""
        self.initialize()
        canonical_message = dict(message)
        schema_validate(canonical_message, "SpoolMessage")
        if not _message_id_matches_content(canonical_message):
            msg = "message_id does not match canonical message content"
            raise TransportRefusalError(msg)
        message_id = _message_id_from_mapping(canonical_message)
        prior_ref = previous_signature_ref
        prior_sequence = 0
        if prior_ref is None:
            prior = self.latest_signature()
            if prior is not None:
                prior_ref = prior[0]
                prior_sequence = prior[1]
        next_sequence = sequence if sequence is not None else prior_sequence + 1
        signature = signer.sign(
            canonical_message,
            sequence=next_sequence,
            previous_signature_ref=prior_ref,
        ).to_dict()
        message_path = self.queued_dir / _json_filename(message_id)
        signature_path = self.signature_path_for(message_id)
        _atomic_write_json(message_path, canonical_message, tmp_dir=self.tmp_dir)
        _atomic_write_json(signature_path, signature, tmp_dir=self.tmp_dir)
        return QueuedMessage(
            message=canonical_message,
            signature=signature,
            message_path=message_path,
            signature_path=signature_path,
        )

    def receive(  # noqa: PLR0911 - each terminal state writes its own receipt at the boundary.
        self,
        message_path: Path,
        *,
        verifier: SignatureVerifier,
        now_utc: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        """Validate and import a queued message, returning a ``SpoolAck/v1``."""
        self.initialize()
        now = _parse_utc(now_utc)
        if ttl_seconds < 0:
            msg = "ttl_seconds must be non-negative"
            raise SpoolError(msg)
        try:
            message = _read_json_object(message_path)
            schema_validate(message, "SpoolMessage")
            message_id = _message_id_from_mapping(message)
            if not _message_id_matches_content(message):
                raise TransportRefusalError("message_id does not match canonical message content")
        except (ContractError, OSError) as exc:
            raw = _read_bytes_best_effort(message_path)
            synthetic_id = "sha256:" + hashlib.sha256(raw).hexdigest()
            self._quarantine_raw(message_path, reason=f"malformed_message:{exc}")
            return self._write_ack(
                message_id=synthetic_id,
                status="QUARANTINED",
                created_utc=now_utc,
            )
        signature_path = self.signature_path_for(message_id)
        try:
            signature = _read_json_object(signature_path)
            _validate_detached_signature(signature)
        except (ContractError, OSError) as exc:
            self._quarantine_message(message, reason=f"missing_or_bad_signature:{exc}")
            return self._write_ack(
                message_id=message_id,
                status="QUARANTINED",
                created_utc=now_utc,
            )
        if not verifier.verify(message, signature):
            self._quarantine_message(message, reason="signature_verification_failed")
            return self._write_ack(
                message_id=message_id,
                status="QUARANTINED",
                created_utc=now_utc,
            )
        if not self._hash_chain_accepts(signature):
            self._quarantine_message(message, reason="hash_chain_rejected")
            return self._write_ack(
                message_id=message_id,
                status="QUARANTINED",
                created_utc=now_utc,
            )
        if message["classification"] not in _VALID_CLASSIFICATIONS:
            self._quarantine_message(message, reason="classification_rejected")
            return self._write_ack(message_id=message_id, status="REJECTED", created_utc=now_utc)
        created = _parse_utc(str(message["created_utc"]))
        if (now - created).total_seconds() > ttl_seconds:
            self._dead_letter_message(message, reason="ttl_expired", created_utc=now_utc)
            return self._write_ack(message_id=message_id, status="EXPIRED", created_utc=now_utc)
        if self._is_duplicate(message):
            return self._write_ack(message_id=message_id, status="DUPLICATE", created_utc=now_utc)
        imported_path = self.imported_dir / _json_filename(message_id)
        _atomic_write_json(imported_path, message, tmp_dir=self.tmp_dir)
        return self._write_ack(message_id=message_id, status="ACKNOWLEDGED", created_utc=now_utc)

    def dead_letter(
        self,
        message: Mapping[str, Any],
        *,
        reason: str,
        created_utc: str = _DEFAULT_ACK_CREATED_UTC,
    ) -> DeadLetterResult:
        """Write a terminal ``DeadLetterRecord/v1`` for a message."""
        self.initialize()
        record = self._dead_letter_message(dict(message), reason=reason, created_utc=created_utc)
        return DeadLetterResult(
            record=record,
            record_path=self.dlq_dir / _json_filename(str(record["message_id"])),
        )

    def replay(self, state: SpoolState) -> tuple[ReplayItem, ...]:
        """Replay a terminal or queued state deterministically by message id."""
        directory = self._directory_for_state(state)
        if not directory.exists():
            return ()
        items: list[ReplayItem] = []
        for path in sorted(directory.glob("*.json")):
            payload = _read_json_object(path)
            message_id = _message_id_for_replay(payload)
            items.append(ReplayItem(state=state, message_id=message_id, path=path, payload=payload))
        return tuple(sorted(items, key=lambda item: item.message_id))

    def latest_signature(self) -> tuple[str, int] | None:
        """Return the latest accepted signature ref and sequence, if present."""
        signatures: list[tuple[int, str]] = []
        for path in sorted(self.signatures_dir.glob("*.json")):
            try:
                payload = _read_json_object(path)
                sequence = _sequence_from_signature(payload)
            except (ContractError, OSError):
                continue
            signatures.append((sequence, _file_ref(path)))
        if not signatures:
            return None
        sequence, ref = max(signatures, key=lambda item: (item[0], item[1]))
        return ref, sequence

    @property
    def tmp_dir(self) -> Path:
        """Temporary staging directory."""
        return self.root / "tmp"

    @property
    def queued_dir(self) -> Path:
        """Outbound queued message directory."""
        return self.root / "outbox" / "queued"

    @property
    def imported_dir(self) -> Path:
        """Receiver-side imported C3 message directory."""
        return self.root / "inbox" / "imported"

    @property
    def acks_dir(self) -> Path:
        """Acknowledgement directory."""
        return self.root / "acks"

    @property
    def quarantine_dir(self) -> Path:
        """Quarantine directory."""
        return self.root / "quarantine"

    @property
    def dlq_dir(self) -> Path:
        """Dead-letter directory."""
        return self.root / "dlq"

    @property
    def signatures_dir(self) -> Path:
        """Detached signature directory."""
        return self.root / "signatures"

    def signature_path_for(self, message_id: str) -> Path:
        """Return the detached signature path for ``message_id``."""
        validate_object_id(message_id)
        return self.signatures_dir / _json_filename(message_id)

    def _all_directories(self) -> tuple[Path, ...]:
        return (
            self.tmp_dir,
            self.queued_dir,
            self.imported_dir,
            self.acks_dir,
            self.quarantine_dir,
            self.dlq_dir,
            self.signatures_dir,
        )

    def _directory_for_state(self, state: SpoolState) -> Path:
        if state is SpoolState.QUEUED:
            return self.queued_dir
        if state is SpoolState.ACKNOWLEDGED:
            return self.acks_dir
        if state is SpoolState.IMPORTED_AS_C3:
            return self.imported_dir
        if state is SpoolState.QUARANTINED:
            return self.quarantine_dir
        if state is SpoolState.DEAD_LETTERED:
            return self.dlq_dir
        msg = f"state {state.value!r} has no replay directory"
        raise SpoolError(msg)

    def _write_ack(self, *, message_id: str, status: str, created_utc: str) -> dict[str, Any]:
        validate_object_id(message_id)
        ack_without_id = {
            "schema_version": "SpoolAck/v1",
            "message_id": message_id,
            "ack_status": status,
            "created_utc": normalize_timestamp(created_utc),
            "canonical_writes": 0,
            "grants_authority": False,
        }
        ack = {"ack_id": object_id(ack_without_id), **ack_without_id}
        schema_validate(ack, "SpoolAck")
        _atomic_write_json(self.acks_dir / _json_filename(message_id), ack, tmp_dir=self.tmp_dir)
        return ack

    def _dead_letter_message(
        self,
        message: Mapping[str, Any],
        *,
        reason: str,
        created_utc: str,
    ) -> dict[str, Any]:
        message_id = _message_id_from_mapping(message)
        record_without_id = {
            "schema_version": "DeadLetterRecord/v1",
            "message_id": message_id,
            "reason": _require_non_empty(reason, "reason"),
            "created_utc": normalize_timestamp(created_utc),
            "canonical_writes": 0,
            "grants_authority": False,
        }
        record = {"record_id": object_id(record_without_id), **record_without_id}
        schema_validate(record, "DeadLetterRecord")
        _atomic_write_json(self.dlq_dir / _json_filename(message_id), record, tmp_dir=self.tmp_dir)
        return record

    def _quarantine_message(self, message: Mapping[str, Any], *, reason: str) -> None:
        message_id = _message_id_from_mapping(message)
        payload = {
            "schema_version": "SpoolQuarantineRecord/v1",
            "message_id": message_id,
            "reason": reason,
            "message": dict(message),
        }
        _atomic_write_json(
            self.quarantine_dir / _json_filename(message_id),
            payload,
            tmp_dir=self.tmp_dir,
        )

    def _quarantine_raw(self, path: Path, *, reason: str) -> None:
        raw = _read_bytes_best_effort(path)
        raw_id = "sha256:" + hashlib.sha256(raw).hexdigest()
        payload = {
            "schema_version": "SpoolQuarantineRecord/v1",
            "message_id": raw_id,
            "reason": reason,
            "raw_sha256": raw_id,
        }
        _atomic_write_json(
            self.quarantine_dir / _json_filename(raw_id),
            payload,
            tmp_dir=self.tmp_dir,
        )

    def _is_duplicate(self, message: Mapping[str, Any]) -> bool:
        message_id = _message_id_from_mapping(message)
        for path in sorted(self.imported_dir.glob("*.json")):
            imported = _read_json_object(path)
            if imported.get("message_id") == message_id:
                return True
            if imported.get("idempotency_key") == message.get("idempotency_key") and imported.get(
                "payload_ref"
            ) == message.get("payload_ref"):
                return True
        return False

    def _hash_chain_accepts(self, signature: Mapping[str, Any]) -> bool:
        sequence = _sequence_from_signature(signature)
        previous = _previous_ref_from_signature(signature)
        if sequence == 1:
            return previous is None
        if previous is None:
            return False
        known_refs = {_file_ref(path) for path in self.signatures_dir.glob("*.json")}
        return previous in known_refs


def _atomic_write_json(path: Path, payload: Mapping[str, Any], *, tmp_dir: Path) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = dumps(dict(payload))
    tmp_path = tmp_dir / f".{path.name}.{os.getpid()}.tmp"
    with tmp_path.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json_object(path: Path) -> dict[str, Any]:
    value = loads(path.read_bytes())
    if not isinstance(value, dict):
        msg = "spool JSON payload must be an object"
        raise SpoolError(msg)
    return value


def _read_bytes_best_effort(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _json_filename(object_ref: str) -> str:
    validate_object_id(object_ref)
    return f"{object_ref.removeprefix('sha256:')}.json"


def _file_ref(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _message_id_from_mapping(message: Mapping[str, Any]) -> str:
    return validate_object_id(message.get("message_id"))


def _message_id_matches_content(message: Mapping[str, Any]) -> bool:
    if "message_id" not in message:
        return False
    message_without_id = dict(message)
    declared = validate_object_id(message_without_id.pop("message_id"))
    return object_id(message_without_id) == declared


def _message_id_for_replay(payload: Mapping[str, Any]) -> str:
    candidate = payload.get("message_id")
    if isinstance(candidate, str):
        return validate_object_id(candidate)
    candidate = payload.get("record_id")
    if isinstance(candidate, str):
        return validate_object_id(candidate)
    candidate = payload.get("ack_id")
    if isinstance(candidate, str):
        return validate_object_id(candidate)
    msg = "replay payload has no object identity"
    raise SpoolError(msg)


def _require_non_empty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        msg = f"{field} must be a non-empty string"
        raise SpoolError(msg)
    return value


def _require_positive_sequence(sequence: int) -> None:
    if isinstance(sequence, bool) or sequence < 1:
        msg = "signature sequence must be a positive integer"
        raise SpoolError(msg)


def _sequence_from_signature(signature: Mapping[str, Any]) -> int:
    value = signature.get("sequence")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = "signature sequence must be a positive integer"
        raise SpoolError(msg)
    return value


def _previous_ref_from_signature(signature: Mapping[str, Any]) -> str | None:
    value = signature.get("previous_signature_ref")
    if value is None:
        return None
    return validate_object_id(value)


def _validate_detached_signature(signature: Mapping[str, Any]) -> None:
    if signature.get("schema_version") != _SIGNATURE_SCHEMA_VERSION:
        msg = "detached signature schema_version is invalid"
        raise SpoolError(msg)
    if not isinstance(signature.get("algorithm"), str) or not signature["algorithm"]:
        msg = "detached signature algorithm must be a non-empty string"
        raise SpoolError(msg)
    _require_non_empty(str(signature.get("signer_cell", "")), "signer_cell")
    _message_id_from_mapping(signature)
    _sequence_from_signature(signature)
    _previous_ref_from_signature(signature)
    value = signature.get("signature_value")
    if not isinstance(value, str) or not value:
        msg = "detached signature_value must be a non-empty string"
        raise SpoolError(msg)


def _signature_body(
    *,
    algorithm: str,
    signer_cell: str,
    message_id: str,
    sequence: int,
    previous_signature_ref: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": _SIGNATURE_SCHEMA_VERSION,
        "algorithm": algorithm,
        "signer_cell": _require_non_empty(signer_cell, "signer_cell"),
        "message_id": validate_object_id(message_id),
        "sequence": sequence,
        "previous_signature_ref": previous_signature_ref,
    }


def _parse_utc(value: str) -> datetime:
    normalized = normalize_timestamp(value)
    return datetime.strptime(normalized, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
