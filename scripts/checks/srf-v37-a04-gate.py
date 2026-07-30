#!/usr/bin/env python3
"""V3.7 A04 production signing and reliable transport gate.

This gate proves the software side of A04 with real Ed25519 signatures and
crash-safe file-spool invariants. It uses ephemeral in-memory test keys only:
no production private key is generated, stored, requested, logged or committed.
The native production key binding remains a protected operator action.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps, object_id  # noqa: E402
from srl.transport import (  # noqa: E402
    Ed25519Signer,
    Ed25519Verifier,
    HmacSha256Signer,
    SpoolRoot,
    build_spool_message,
)
from srl.transport import spool as spool_mod  # noqa: E402
from srl.transport.native_keyring import (  # noqa: E402
    PRODUCTION_KEY_BINDING_RECEIPT_SCHEMA_VERSION,
    production_key_receipt_is_active,
)
from srl.transport.spool import SpoolState  # noqa: E402

SCHEMA_VERSION: Final[str] = "StageCompletionReceipt/v1"
STAGE_ID: Final[str] = "A04"
OPERATOR_ACTION = REPO_ROOT / "docs" / "target-binding" / "ed25519-native-key-operator-action.json"
PRODUCTION_KEY_RECEIPT = (
    REPO_ROOT / "docs" / "verification" / "srf-v3-7-a04-production-key-binding-receipt.json"
)


def _payload_ref(name: str) -> str:
    return object_id({"fixture": name})


def _message(name: str, created_utc: str = "2026-07-29T00:00:00Z") -> dict[str, object]:
    return build_spool_message(
        source_cell="standalone",
        target_cell="market",
        payload_ref=_payload_ref(name),
        classification="D1",
        created_utc=created_utc,
    )


def _file_ref(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _check_ed25519_acceptance() -> dict[str, Any]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        spool = SpoolRoot.at(tmp)
        signer = Ed25519Signer.generate(signer_cell="standalone")
        verifier = Ed25519Verifier({signer.resolved_key_id(): signer.public_key_hex})
        queued = spool.queue_message(_message("ed25519-ok"), signer=signer)
        ack = spool.receive(
            queued.message_path,
            verifier=verifier,
            now_utc="2026-07-29T00:00:10Z",
            ttl_seconds=60,
        )
        if ack["ack_status"] != "ACKNOWLEDGED":
            failures.append(f"valid Ed25519 message yielded {ack['ack_status']}")
        tampered = dict(queued.message)
        tampered["target_cell"] = "security"
        queued.message_path.write_text(json.dumps(tampered), encoding="utf-8")
        tamper_ack = spool.receive(
            queued.message_path,
            verifier=verifier,
            now_utc="2026-07-29T00:00:11Z",
            ttl_seconds=60,
        )
        if tamper_ack["ack_status"] != "QUARANTINED":
            failures.append("tampered Ed25519 message was not quarantined")
        wrong_key = Ed25519Signer.generate(signer_cell="standalone")
        wrong_spool = SpoolRoot.at(Path(tmp) / "wrong-key")
        wrong_queued = wrong_spool.queue_message(_message("wrong-key"), signer=signer)
        wrong_ack = wrong_spool.receive(
            wrong_queued.message_path,
            verifier=Ed25519Verifier({signer.resolved_key_id(): wrong_key.public_key_hex}),
            now_utc="2026-07-29T00:00:12Z",
            ttl_seconds=60,
        )
        if wrong_ack["ack_status"] != "QUARANTINED":
            failures.append("wrong Ed25519 public key was not quarantined")
    return {
        "check_id": "A04-01-ed25519-real-signature",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "real Ed25519 signed message accepted; tamper and wrong public key rejected",
    }


def _check_fixture_hmac_rejected_in_production() -> dict[str, Any]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        spool = SpoolRoot.at(tmp)
        ed_signer = Ed25519Signer.generate(signer_cell="standalone")
        queued = spool.queue_message(
            _message("fixture-hmac"),
            signer=HmacSha256Signer(signer_cell="standalone", secret=b"fixture-secret"),
        )
        ack = spool.receive(
            queued.message_path,
            verifier=Ed25519Verifier({ed_signer.resolved_key_id(): ed_signer.public_key_hex}),
            now_utc="2026-07-29T00:00:10Z",
            ttl_seconds=60,
        )
        if queued.signature["algorithm"] != "test-hmac-sha256":
            failures.append("fixture signature algorithm drifted")
        if ack["ack_status"] != "QUARANTINED":
            failures.append("production verifier accepted fixture HMAC")
    return {
        "check_id": "A04-02-fixture-hmac-production-rejected",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "production Ed25519 verifier rejects test-hmac-sha256 signatures",
    }


def _check_revoked_replay_and_sequence_guards() -> dict[str, Any]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        signer = Ed25519Signer.generate(signer_cell="standalone")
        key_id = signer.resolved_key_id()

        revoked_spool = SpoolRoot.at(Path(tmp) / "revoked")
        revoked = revoked_spool.queue_message(_message("revoked"), signer=signer)
        revoked_ack = revoked_spool.receive(
            revoked.message_path,
            verifier=Ed25519Verifier({key_id: signer.public_key_hex}, frozenset({key_id})),
            now_utc="2026-07-29T00:00:10Z",
            ttl_seconds=60,
        )
        if revoked_ack["ack_status"] != "QUARANTINED":
            failures.append("revoked Ed25519 key was not quarantined")

        spool = SpoolRoot.at(Path(tmp) / "sequence")
        verifier = Ed25519Verifier({key_id: signer.public_key_hex})
        first = spool.queue_message(_message("first"), signer=signer)
        second = spool.queue_message(_message("second"), signer=signer)
        second_first_ack = spool.receive(
            second.message_path,
            verifier=verifier,
            now_utc="2026-07-29T00:00:10Z",
            ttl_seconds=60,
        )
        first_ack = spool.receive(
            first.message_path,
            verifier=verifier,
            now_utc="2026-07-29T00:00:11Z",
            ttl_seconds=60,
        )
        second_retry_ack = spool.receive(
            second.message_path,
            verifier=verifier,
            now_utc="2026-07-29T00:00:12Z",
            ttl_seconds=60,
        )
        if second_first_ack["ack_status"] != "QUARANTINED":
            failures.append("out-of-order sequence was not quarantined before predecessor import")
        if (
            first_ack["ack_status"] != "ACKNOWLEDGED"
            or second_retry_ack["ack_status"] != "ACKNOWLEDGED"
        ):
            failures.append("valid predecessor-ordered sequence did not recover")

        rollback = spool.queue_message(_message("rollback"), signer=signer, sequence=1)
        stale = spool.queue_message(
            _message("stale-predecessor"),
            signer=signer,
            sequence=2,
            previous_signature_ref=_file_ref(first.signature_path),
        )
        rollback_ack = spool.receive(
            rollback.message_path,
            verifier=verifier,
            now_utc="2026-07-29T00:00:13Z",
            ttl_seconds=60,
        )
        stale_ack = spool.receive(
            stale.message_path,
            verifier=verifier,
            now_utc="2026-07-29T00:00:14Z",
            ttl_seconds=60,
        )
        if rollback_ack["ack_status"] != "QUARANTINED":
            failures.append("sequence rollback was not quarantined")
        if stale_ack["ack_status"] != "QUARANTINED":
            failures.append("stale predecessor hash chain was not quarantined")
    return {
        "check_id": "A04-03-revoked-replay-sequence-guards",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "revoked keys, out-of-order replay, rollback and stale predecessor are rejected",
    }


def _check_crash_reconciliation() -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    failures: list[str] = []
    original_atomic_write: Callable[..., None] = spool_mod._atomic_write_json
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue_spool = SpoolRoot.at(root / "queue-crash")

            def crash_on_signature(path: Path, payload: Any, *, tmp_dir: Path) -> None:
                if path.parent.name == "signatures":
                    raise RuntimeError("injected crash after queued message write")
                original_atomic_write(path, payload, tmp_dir=tmp_dir)

            spool_mod._atomic_write_json = crash_on_signature
            try:
                queue_spool.queue_message(
                    _message("queue-crash"),
                    signer=Ed25519Signer.generate(signer_cell="standalone"),
                )
            except RuntimeError:
                pass
            finally:
                spool_mod._atomic_write_json = original_atomic_write
            queued_files = list((root / "queue-crash" / "outbox" / "queued").glob("*.json"))
            if not queued_files:
                failures.append("queue crash did not leave a recoverable queued message")
            elif list((root / "queue-crash" / "acks").glob("*.json")):
                failures.append("queue crash created an ack before import")

            import_spool = SpoolRoot.at(root / "import-crash")
            signer = Ed25519Signer.generate(signer_cell="standalone")
            verifier = Ed25519Verifier({signer.resolved_key_id(): signer.public_key_hex})
            queued = import_spool.queue_message(_message("import-crash"), signer=signer)

            def crash_on_import(path: Path, payload: Any, *, tmp_dir: Path) -> None:
                if path.parent.name == "imported":
                    raise RuntimeError("injected crash before imported publish")
                original_atomic_write(path, payload, tmp_dir=tmp_dir)

            spool_mod._atomic_write_json = crash_on_import
            try:
                import_spool.receive(
                    queued.message_path,
                    verifier=verifier,
                    now_utc="2026-07-29T00:00:10Z",
                    ttl_seconds=60,
                )
            except RuntimeError:
                pass
            finally:
                spool_mod._atomic_write_json = original_atomic_write
            if list(import_spool.acks_dir.glob("*.json")):
                failures.append("pre-import crash created an ack")

            ack_spool = SpoolRoot.at(root / "ack-crash")
            signer2 = Ed25519Signer.generate(signer_cell="standalone")
            verifier2 = Ed25519Verifier({signer2.resolved_key_id(): signer2.public_key_hex})
            queued2 = ack_spool.queue_message(_message("ack-crash"), signer=signer2)

            def crash_on_ack(path: Path, payload: Any, *, tmp_dir: Path) -> None:
                if path.parent.name == "acks":
                    raise RuntimeError("injected crash after import before ack")
                original_atomic_write(path, payload, tmp_dir=tmp_dir)

            spool_mod._atomic_write_json = crash_on_ack
            try:
                ack_spool.receive(
                    queued2.message_path,
                    verifier=verifier2,
                    now_utc="2026-07-29T00:00:10Z",
                    ttl_seconds=60,
                )
            except RuntimeError:
                pass
            finally:
                spool_mod._atomic_write_json = original_atomic_write
            if len(ack_spool.replay(SpoolState.IMPORTED_AS_C3)) != 1:
                failures.append("ack crash lost imported message")
            if list(ack_spool.acks_dir.glob("*.json")):
                failures.append("ack crash wrote partial ack")
            repaired = ack_spool.reconcile_acknowledgements(created_utc="2026-07-29T00:00:20Z")
            if len(repaired) != 1 or repaired[0]["ack_status"] != "ACKNOWLEDGED":
                failures.append("restart reconciliation did not rebuild missing acknowledged ack")
    finally:
        spool_mod._atomic_write_json = original_atomic_write
    return {
        "check_id": "A04-04-crash-transition-reconciliation",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "queue/import/ack crash injections preserve no false ack and reconcile imported ACK",
    }


def _check_operator_action() -> dict[str, Any]:
    action = json.loads(OPERATOR_ACTION.read_text(encoding="utf-8"))
    expected_hash = action.get("action_hash_grouped_sha256")
    action_without_hash = dict(action)
    action_without_hash.pop("action_hash_grouped_sha256", None)
    digest = hashlib.sha256(dumps(action_without_hash)).hexdigest()
    grouped = "-".join(digest[index : index + 8] for index in range(0, len(digest), 8))
    failures: list[str] = []
    if grouped != expected_hash:
        failures.append("operator action hash drifted")
    if action.get("grants_authority") is not False:
        failures.append("operator action grants authority")
    if action.get("authority_required") is not True:
        failures.append("operator action does not require authority")
    return {
        "check_id": "A04-05-native-key-operator-action",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "native Ed25519 key binding action is exact and non-authorizing",
        "operator_action_hash": expected_hash,
    }


def _check_production_key_binding_receipt() -> dict[str, Any]:
    failures: list[str] = []
    if not PRODUCTION_KEY_RECEIPT.exists():
        failures.append("production key binding receipt is absent")
        receipt: dict[str, Any] = {}
    else:
        receipt = json.loads(PRODUCTION_KEY_RECEIPT.read_text(encoding="utf-8"))
        if receipt.get("schema_version") != PRODUCTION_KEY_BINDING_RECEIPT_SCHEMA_VERSION:
            failures.append("production key binding receipt schema drifted")
        if not production_key_receipt_is_active(receipt):
            failures.append("production key binding receipt is not ACTIVE")
        rendered = json.dumps(receipt, sort_keys=True)
        if "/Users/" in rendered or "/Volumes/" in rendered:
            failures.append("production key binding receipt publishes a machine path")
        if "PRIVATE KEY" in rendered or "private_key_hex" in rendered:
            failures.append("production key binding receipt publishes private key material marker")
    return {
        "check_id": "A04-06-production-key-binding-receipt",
        "status": "FAIL" if failures else "PASS",
        "detail": "; ".join(failures)
        if failures
        else "native production Ed25519 key binding receipt is ACTIVE and secret-free",
        "production_key_binding_receipt_id": receipt.get("receipt_id"),
    }


def build_gate_receipt() -> dict[str, Any]:
    checks = (
        _check_ed25519_acceptance(),
        _check_fixture_hmac_rejected_in_production(),
        _check_revoked_replay_and_sequence_guards(),
        _check_crash_reconciliation(),
        _check_operator_action(),
        _check_production_key_binding_receipt(),
    )
    failures = [check for check in checks if check["status"] != "PASS"]
    production_receipt_id = next(
        (
            check.get("production_key_binding_receipt_id")
            for check in checks
            if check["check_id"] == "A04-06-production-key-binding-receipt"
        ),
        None,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": STAGE_ID,
        "status": "FAIL" if failures else "PASS",
        "terminal_state": "A04_ACCEPTED" if not failures else "A04_BLOCKED",
        "stage_closure": "A04_ACTIVE" if not failures else "BLOCKED",
        "protected_key_binding": f"ACTIVE:{production_receipt_id}"
        if not failures
        else "WAIT_AUTHORITY:A04_BIND_PRODUCTION_ED25519_KEYRING",
        "checks": list(checks),
        "canonical_writes": 0,
        "grants_authority": False,
    }
    payload["receipt_id"] = object_id(payload)
    return payload


def main() -> int:
    receipt = build_gate_receipt()
    sys.stdout.buffer.write(dumps(receipt))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
