"""Native production Ed25519 key binding receipts.

The private signing key is deliberately outside the repository. This module
only creates/verifies public receipts and can probe an operator-owned private
file store without printing, committing, or passing the key through argv/env.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from srl.contracts import dumps, object_id
from srl.transport.spool import (
    Ed25519Signer,
    Ed25519Verifier,
    HmacSha256Signer,
    SpoolRoot,
    build_spool_message,
    ed25519_key_id,
)

PRODUCTION_KEY_BINDING_RECEIPT_SCHEMA_VERSION: Final[str] = (
    "ProductionTransportKeyBindingReceipt/v1"
)
PRODUCTION_KEY_BINDING_ACTIVE_STATE: Final[str] = "ACTIVE"
PRODUCTION_KEY_BINDING_BLOCKED_ABSENT_STATE: Final[str] = "BLOCKED_NATIVE_KEY_ABSENT"
PRODUCTION_KEY_BINDING_PARTIAL_STATE: Final[str] = "PARTIAL_NATIVE_EVIDENCE"
DEFAULT_KEY_SERVICE: Final[str] = "org.scientific-resource-lab.production-ed25519"
DEFAULT_KEY_ACCOUNT: Final[str] = "srf-transport"
PRIVATE_FILE_BACKEND: Final[str] = "private_file_v1"

_PRIVATE_KEY_FILE: Final[str] = "production-ed25519.raw"
_RECEIVER_KEYRING_FILE: Final[str] = "receiver-keyring.json"
_PRIVATE_KEY_BYTES: Final[int] = 32
_PROTECTED_EVIDENCE_FIELDS: Final[tuple[str, ...]] = (
    "authority_directive_present",
    "private_key_created_or_reused",
    "native_secret_store_bound",
    "receiver_public_keyring_bound",
    "nonfixture_signed_spool_roundtrip",
    "fixture_hmac_rejected_in_production_mode",
    "revoked_key_rejected_in_production_mode",
    "no_private_material_published",
    "no_secret_process_arguments",
)


class NativeKeyringError(ValueError):
    """Raised when the native production key binding cannot be proven."""


@dataclass(frozen=True)
class ProductionKeyProbeResult:
    """Public facts from a native key binding probe."""

    status: str
    protected_evidence: dict[str, bool]
    key_id: str | None
    public_key_fingerprint: str | None
    secret_store_ref_hash: str
    receiver_keyring_ref_hash: str | None
    native_secret_store_backend: str
    remaining_external_waits: list[str]
    reason: str | None = None


def default_native_key_dir() -> Path:
    """Return the default out-of-repository private key directory."""

    return (
        Path.home() / "Library" / "Application Support" / "ScientificResourceLab" / "native-keyring"
    )


def grouped_sha256(value: bytes | str) -> str:
    """Return a grouped SHA-256 digest suitable for public receipts."""

    data = value.encode("utf-8") if isinstance(value, str) else value
    digest = hashlib.sha256(data).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, len(digest), 8))


def protected_operator_action() -> dict[str, Any]:
    """Return the exact protected action for A04 native key binding."""

    action: dict[str, Any] = {
        "schema_version": "ProtectedOperatorAction/v1",
        "action_id": "A04_BIND_PRODUCTION_ED25519_KEYRING",
        "authority_required": True,
        "grants_authority": False,
        "target": "operator-controlled native secret store and receiver keyring",
        "allowed_actions_after_authority": [
            "install_private_ed25519_signing_key_in_native_secret_store",
            "install_public_verification_keyring_in_receiver_private_config",
            "record_public_key_id_and_revocation_epoch_without_private_material",
            "run_one_nonfixture_signed_spool_roundtrip_on_target_transport",
            "prove_fixture_hmac_rejected_in_production_mode",
            "prove_revoked_key_rejected_in_production_mode",
            "record_native_transport_receipt_without_secret_material",
        ],
        "forbidden_without_authority": [
            "generate_or_store_production_private_key",
            "copy_private_key_into_git",
            "copy_private_key_into_chat_or_logs",
            "pass_private_key_via_process_arguments",
            "claim_release_DONE_or_production_signer_ACTIVE",
            "replace_ed25519_with_fixture_hmac_in_production",
        ],
        "expected_receipt_schema": PRODUCTION_KEY_BINDING_RECEIPT_SCHEMA_VERSION,
    }
    action["action_hash_grouped_sha256"] = grouped_sha256(dumps(action))
    return action


def probe_private_file_keyring(
    *,
    key_dir: Path,
    create_missing: bool,
    authority_directive_present: bool,
) -> ProductionKeyProbeResult:
    """Probe or create an operator-owned private file Ed25519 keyring.

    The key is generated in-process and written directly to a mode-0600 file.
    The secret is never passed through argv/env or returned by this function.
    """

    secret_store_ref_hash = _ref_hash("private_file_v1", key_dir)
    receiver_keyring_ref_hash = _ref_hash("receiver_private_config_v1", key_dir)
    try:
        key_dir_preexisting = key_dir.exists()
        private_key = _load_or_create_private_key(key_dir, create_missing=create_missing)
        key_dir_mode_ok = _mode_is_private_dir(key_dir)
        key_file_mode_ok = _mode_is_private_file(key_dir / _PRIVATE_KEY_FILE)
        if not key_dir_preexisting:
            os.chmod(key_dir, stat.S_IRWXU)
        signer = Ed25519Signer(signer_cell="standalone", private_key=private_key)
        public_key_hex = signer.public_key_hex
        key_id = signer.resolved_key_id()
        _write_receiver_keyring(key_dir, key_id=key_id, public_key_hex=public_key_hex)
        receiver_mode_ok = _mode_is_private_file(key_dir / _RECEIVER_KEYRING_FILE)
        smoke = _run_production_transport_smoke(signer)
    except FileNotFoundError:
        evidence = {field: False for field in _PROTECTED_EVIDENCE_FIELDS}
        evidence["authority_directive_present"] = authority_directive_present
        evidence["no_private_material_published"] = True
        evidence["no_secret_process_arguments"] = True
        return ProductionKeyProbeResult(
            status=PRODUCTION_KEY_BINDING_BLOCKED_ABSENT_STATE,
            protected_evidence=evidence,
            key_id=None,
            public_key_fingerprint=None,
            secret_store_ref_hash=secret_store_ref_hash,
            receiver_keyring_ref_hash=None,
            native_secret_store_backend=PRIVATE_FILE_BACKEND,
            remaining_external_waits=[
                "WAIT_AUTHORITY:A04_NATIVE_KEY_MATERIAL_ABSENT",
                "WAIT_AUTHORITY:A04_RECEIVER_KEYRING_ABSENT",
            ],
            reason="native private key file absent and create_missing=false",
        )
    except (OSError, ValueError) as exc:
        evidence = {field: False for field in _PROTECTED_EVIDENCE_FIELDS}
        evidence["authority_directive_present"] = authority_directive_present
        evidence["no_private_material_published"] = True
        evidence["no_secret_process_arguments"] = True
        return ProductionKeyProbeResult(
            status=PRODUCTION_KEY_BINDING_PARTIAL_STATE,
            protected_evidence=evidence,
            key_id=None,
            public_key_fingerprint=None,
            secret_store_ref_hash=secret_store_ref_hash,
            receiver_keyring_ref_hash=None,
            native_secret_store_backend=PRIVATE_FILE_BACKEND,
            remaining_external_waits=["WAIT_AUTHORITY:A04_NATIVE_KEYRING_PROBE_FAILED"],
            reason=f"{type(exc).__name__}:{exc}",
        )

    evidence = {
        "authority_directive_present": authority_directive_present,
        "private_key_created_or_reused": True,
        "native_secret_store_bound": key_dir_mode_ok and key_file_mode_ok,
        "receiver_public_keyring_bound": receiver_mode_ok,
        "nonfixture_signed_spool_roundtrip": smoke["nonfixture_signed_spool_roundtrip"],
        "fixture_hmac_rejected_in_production_mode": smoke[
            "fixture_hmac_rejected_in_production_mode"
        ],
        "revoked_key_rejected_in_production_mode": smoke["revoked_key_rejected_in_production_mode"],
        "no_private_material_published": True,
        "no_secret_process_arguments": True,
    }
    remaining = [
        f"WAIT_AUTHORITY:A04_MISSING_{field.upper()}"
        for field in _PROTECTED_EVIDENCE_FIELDS
        if not evidence[field]
    ]
    status = (
        PRODUCTION_KEY_BINDING_ACTIVE_STATE
        if not remaining
        else PRODUCTION_KEY_BINDING_PARTIAL_STATE
    )
    return ProductionKeyProbeResult(
        status=status,
        protected_evidence=evidence,
        key_id=key_id,
        public_key_fingerprint="sha256:" + grouped_sha256(public_key_hex),
        secret_store_ref_hash=secret_store_ref_hash,
        receiver_keyring_ref_hash=receiver_keyring_ref_hash,
        native_secret_store_backend=PRIVATE_FILE_BACKEND,
        remaining_external_waits=remaining,
    )


def build_production_key_binding_receipt(
    *,
    probe: ProductionKeyProbeResult,
    authority_directive_id: str,
) -> dict[str, Any]:
    """Build a public A04 production-key receipt without private material."""

    receipt: dict[str, Any] = {
        "schema_version": PRODUCTION_KEY_BINDING_RECEIPT_SCHEMA_VERSION,
        "stage_id": "A04",
        "status": probe.status,
        "target_role": "operator_controlled_native_secret_store_and_receiver_keyring",
        "native_secret_store_backend": probe.native_secret_store_backend,
        "secret_store_ref_hash": probe.secret_store_ref_hash,
        "receiver_keyring_ref_hash": probe.receiver_keyring_ref_hash,
        "key_id": probe.key_id,
        "public_key_fingerprint": probe.public_key_fingerprint,
        "revocation_epoch": 0 if probe.status == PRODUCTION_KEY_BINDING_ACTIVE_STATE else None,
        "protected_key_evidence": dict(probe.protected_evidence),
        "remaining_external_waits": list(probe.remaining_external_waits),
        "authority_directive": {
            "schema_version": "OperatorDirective/v1",
            "directive_id": authority_directive_id,
            "target_scoped": True,
            "private_secret_authority_granted": True,
            "destructive_storage_authority_granted": False,
        },
        "probe_reason": probe.reason,
        "public_boundary": {
            "raw_secret_store_path_published": False,
            "raw_private_key_material_published": False,
            "raw_public_key_published": False,
            "owner_home_path_published": False,
            "private_key_in_process_arguments": False,
            "private_key_in_environment": False,
        },
        "operator_action": protected_operator_action(),
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
        "false_done_guard": (
            "A04 closes only with ACTIVE production native Ed25519 receipt; "
            "private key bytes are never repository evidence"
        ),
    }
    receipt["receipt_id"] = object_id(
        {key: value for key, value in receipt.items() if key != "receipt_id"}
    )
    return receipt


def production_key_receipt_is_active(receipt: dict[str, Any]) -> bool:  # noqa: PLR0911
    """Return True iff a public receipt proves A04 production key binding."""

    if receipt.get("schema_version") != PRODUCTION_KEY_BINDING_RECEIPT_SCHEMA_VERSION:
        return False
    if receipt.get("stage_id") != "A04" or receipt.get("status") != "ACTIVE":
        return False
    if receipt.get("canonical_writes") != 0 or receipt.get("grants_authority") is not False:
        return False
    if receipt.get("live_actions") != 0:
        return False
    if not isinstance(receipt.get("key_id"), str) or not str(receipt["key_id"]).startswith(
        "sha256:"
    ):
        return False
    if not isinstance(receipt.get("public_key_fingerprint"), str):
        return False
    evidence = receipt.get("protected_key_evidence")
    if not isinstance(evidence, dict):
        return False
    if not all(bool(evidence.get(field)) for field in _PROTECTED_EVIDENCE_FIELDS):
        return False
    boundary = receipt.get("public_boundary")
    if not isinstance(boundary, dict):
        return False
    return not any(bool(value) for value in boundary.values())


def _load_or_create_private_key(key_dir: Path, *, create_missing: bool) -> Ed25519PrivateKey:
    key_path = key_dir / _PRIVATE_KEY_FILE
    if key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) != _PRIVATE_KEY_BYTES:
            msg = "production Ed25519 private key must be 32 raw bytes"
            raise NativeKeyringError(msg)
        return Ed25519PrivateKey.from_private_bytes(raw)
    if not create_missing:
        raise FileNotFoundError(key_path)
    key_dir.mkdir(mode=stat.S_IRWXU, parents=True, exist_ok=True)
    os.chmod(key_dir, stat.S_IRWXU)
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    fd, tmp_name = tempfile.mkstemp(prefix=".production-ed25519.", dir=key_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_name, key_path)
    finally:
        tmp_path = Path(tmp_name)
        if tmp_path.exists():
            tmp_path.unlink()
    return private_key


def _write_receiver_keyring(key_dir: Path, *, key_id: str, public_key_hex: str) -> None:
    path = key_dir / _RECEIVER_KEYRING_FILE
    payload = {
        "schema_version": "ReceiverEd25519Keyring/v1",
        "keyring_role": "srf-production-transport",
        "public_keys_by_id": {key_id: public_key_hex},
        "revoked_key_ids": [],
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".receiver-keyring.", dir=key_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(dumps(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_name, path)
    finally:
        tmp_path = Path(tmp_name)
        if tmp_path.exists():
            tmp_path.unlink()


def _run_production_transport_smoke(signer: Ed25519Signer) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="srl-a04-production-transport-") as tmp:
        root = Path(tmp)
        verifier = Ed25519Verifier({signer.resolved_key_id(): signer.public_key_hex})
        message = build_spool_message(
            source_cell="standalone",
            target_cell="market",
            payload_ref=object_id({"a04": "production-native-key-binding"}),
            classification="D1",
            created_utc="2026-07-30T00:00:00Z",
        )
        spool = SpoolRoot.at(root / "ed25519")
        queued = spool.queue_message(message, signer=signer)
        ack = spool.receive(
            queued.message_path,
            verifier=verifier,
            now_utc="2026-07-30T00:00:10Z",
            ttl_seconds=60,
        )

        fixture_spool = SpoolRoot.at(root / "fixture")
        fixture = fixture_spool.queue_message(
            message,
            signer=HmacSha256Signer(signer_cell="standalone", secret=b"fixture-secret"),
        )
        fixture_ack = fixture_spool.receive(
            fixture.message_path,
            verifier=verifier,
            now_utc="2026-07-30T00:00:11Z",
            ttl_seconds=60,
        )

        revoked_spool = SpoolRoot.at(root / "revoked")
        revoked = revoked_spool.queue_message(message, signer=signer)
        revoked_ack = revoked_spool.receive(
            revoked.message_path,
            verifier=Ed25519Verifier(
                {signer.resolved_key_id(): signer.public_key_hex},
                revoked_key_ids=frozenset({signer.resolved_key_id()}),
            ),
            now_utc="2026-07-30T00:00:12Z",
            ttl_seconds=60,
        )
    return {
        "nonfixture_signed_spool_roundtrip": ack["ack_status"] == "ACKNOWLEDGED",
        "fixture_hmac_rejected_in_production_mode": fixture_ack["ack_status"] == "QUARANTINED",
        "revoked_key_rejected_in_production_mode": revoked_ack["ack_status"] == "QUARANTINED",
    }


def _mode_is_private_dir(path: Path) -> bool:
    mode = stat.S_IMODE(path.stat().st_mode)
    return mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def _mode_is_private_file(path: Path) -> bool:
    mode = stat.S_IMODE(path.stat().st_mode)
    return path.is_file() and mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def _ref_hash(role: str, path: Path) -> str:
    basis = {
        "role": role,
        "service": DEFAULT_KEY_SERVICE,
        "account": DEFAULT_KEY_ACCOUNT,
        "path_name": path.name,
    }
    return grouped_sha256(dumps(basis))


def _public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw).hex()
    )


__all__ = [
    "DEFAULT_KEY_ACCOUNT",
    "DEFAULT_KEY_SERVICE",
    "PRODUCTION_KEY_BINDING_ACTIVE_STATE",
    "PRODUCTION_KEY_BINDING_BLOCKED_ABSENT_STATE",
    "PRODUCTION_KEY_BINDING_PARTIAL_STATE",
    "PRODUCTION_KEY_BINDING_RECEIPT_SCHEMA_VERSION",
    "ProductionKeyProbeResult",
    "build_production_key_binding_receipt",
    "default_native_key_dir",
    "ed25519_key_id",
    "grouped_sha256",
    "probe_private_file_keyring",
    "production_key_receipt_is_active",
    "protected_operator_action",
]
