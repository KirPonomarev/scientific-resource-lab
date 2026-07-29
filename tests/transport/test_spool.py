from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from srl.contracts import object_id
from srl.transport import (
    Ed25519Signer,
    Ed25519Verifier,
    HmacSha256Signer,
    NullSignatureVerifier,
    RetryPolicy,
    SpoolRoot,
    TransportRefusalError,
    build_spool_message,
    deterministic_retry_delays,
)
from srl.transport.spool import SpoolState


def _payload_ref(name: str = "payload") -> str:
    return object_id({"fixture": name})


def _message(
    name: str = "payload",
    *,
    created_utc: str = "2026-07-29T00:00:00Z",
) -> dict[str, object]:
    return build_spool_message(
        source_cell="standalone",
        target_cell="market",
        payload_ref=_payload_ref(name),
        classification="D1",
        created_utc=created_utc,
    )


def _signer() -> HmacSha256Signer:
    return HmacSha256Signer(signer_cell="standalone", secret=b"fixture-secret")


def test_queue_message_uses_atomic_layout_and_detached_signature(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    message = _message()

    queued = spool.queue_message(message, signer=_signer())

    assert queued.message_path.exists()
    assert queued.signature_path.exists()
    assert not list((tmp_path / "tmp").glob("*.tmp"))
    assert json.loads(queued.message_path.read_text()) == queued.message
    assert queued.signature["schema_version"] == "DetachedSpoolSignature/v1"
    assert queued.signature["key_id"] == "fixture-hmac:standalone"
    assert queued.signature["previous_signature_ref"] is None
    assert queued.signature["sequence"] == 1


def test_ed25519_signed_message_is_accepted_in_production_mode(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    signer = Ed25519Signer.generate(signer_cell="standalone")
    verifier = Ed25519Verifier({signer.resolved_key_id(): signer.public_key_hex})
    queued = spool.queue_message(_message(), signer=signer)

    ack = spool.receive(
        queued.message_path,
        verifier=verifier,
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert queued.signature["algorithm"] == "ed25519"
    assert ack["ack_status"] == "ACKNOWLEDGED"
    assert [item.message_id for item in spool.replay(SpoolState.IMPORTED_AS_C3)] == [
        queued.message["message_id"]
    ]


def test_production_verifier_rejects_fixture_hmac_signature(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    ed_signer = Ed25519Signer.generate(signer_cell="standalone")
    verifier = Ed25519Verifier({ed_signer.resolved_key_id(): ed_signer.public_key_hex})
    queued = spool.queue_message(_message(), signer=_signer())

    ack = spool.receive(
        queued.message_path,
        verifier=verifier,
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert queued.signature["algorithm"] == "test-hmac-sha256"
    assert ack["ack_status"] == "QUARANTINED"
    assert spool.replay(SpoolState.IMPORTED_AS_C3) == ()


def test_revoked_ed25519_key_is_rejected(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    signer = Ed25519Signer.generate(signer_cell="standalone")
    key_id = signer.resolved_key_id()
    queued = spool.queue_message(_message(), signer=signer)

    ack = spool.receive(
        queued.message_path,
        verifier=Ed25519Verifier({key_id: signer.public_key_hex}, frozenset({key_id})),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert ack["ack_status"] == "QUARANTINED"
    assert spool.replay(SpoolState.IMPORTED_AS_C3) == ()


def test_receive_acknowledges_signed_nonexpired_message(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    message = _message()
    queued = spool.queue_message(message, signer=_signer())

    ack = spool.receive(
        queued.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert ack["schema_version"] == "SpoolAck/v1"
    assert ack["ack_status"] == "ACKNOWLEDGED"
    assert ack["canonical_writes"] == 0
    assert ack["grants_authority"] is False
    imported = spool.replay(SpoolState.IMPORTED_AS_C3)
    assert [item.message_id for item in imported] == [message["message_id"]]


def test_receive_rejects_unsigned_message_fail_closed(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    message = _message()
    queued = spool.queue_message(message, signer=_signer())

    ack = spool.receive(
        queued.message_path,
        verifier=NullSignatureVerifier(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert ack["ack_status"] == "QUARANTINED"
    assert len(spool.replay(SpoolState.QUARANTINED)) == 1
    assert spool.replay(SpoolState.IMPORTED_AS_C3) == ()


def test_receive_quarantines_tampered_message_content(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    queued = spool.queue_message(_message(), signer=_signer())
    tampered = dict(queued.message)
    tampered["target_cell"] = "security"
    queued.message_path.write_text(json.dumps(tampered), encoding="utf-8")

    ack = spool.receive(
        queued.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert ack["ack_status"] == "QUARANTINED"
    assert len(spool.replay(SpoolState.QUARANTINED)) == 1


def test_receive_quarantines_tampered_signature(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    queued = spool.queue_message(_message(), signer=_signer())
    signature = dict(queued.signature)
    signature["algorithm"] = "Ed25519"
    queued.signature_path.write_text(json.dumps(signature), encoding="utf-8")

    ack = spool.receive(
        queued.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert ack["ack_status"] == "QUARANTINED"
    assert spool.replay(SpoolState.IMPORTED_AS_C3) == ()


def test_duplicate_delivery_is_idempotent(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    message = _message()
    queued = spool.queue_message(message, signer=_signer())

    first = spool.receive(
        queued.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )
    second = spool.receive(
        queued.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:11Z",
        ttl_seconds=60,
    )

    assert first["ack_status"] == "ACKNOWLEDGED"
    assert second["ack_status"] == "DUPLICATE"
    assert len(spool.replay(SpoolState.IMPORTED_AS_C3)) == 1
    persisted_ack = json.loads((tmp_path / "acks" / queued.message_path.name).read_text())
    assert persisted_ack["ack_status"] == "ACKNOWLEDGED"


def test_distinct_message_with_same_idempotency_key_is_duplicate(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    first_message = _message("shared")
    second_message = build_spool_message(
        source_cell="standalone",
        target_cell="market",
        payload_ref=str(first_message["payload_ref"]),
        classification="D1",
        created_utc="2026-07-29T00:00:01Z",
        idempotency_key=str(first_message["idempotency_key"]),
    )
    first = spool.queue_message(first_message, signer=_signer())
    spool.receive(
        first.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )
    second = spool.queue_message(second_message, signer=_signer())

    ack = spool.receive(
        second.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:11Z",
        ttl_seconds=60,
    )

    assert ack["ack_status"] == "DUPLICATE"
    assert len(spool.replay(SpoolState.IMPORTED_AS_C3)) == 1


def test_expired_message_goes_to_dlq(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    queued = spool.queue_message(_message(created_utc="2026-07-29T00:00:00Z"), signer=_signer())

    ack = spool.receive(
        queued.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:02:00Z",
        ttl_seconds=60,
    )

    assert ack["ack_status"] == "EXPIRED"
    assert len(spool.replay(SpoolState.DEAD_LETTERED)) == 1
    assert spool.replay(SpoolState.IMPORTED_AS_C3) == ()


def test_corrupt_partial_message_is_quarantined(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    spool.initialize()
    corrupt = tmp_path / "outbox" / "queued" / f"{'0' * 64}.json"
    corrupt.write_text('{"schema_version":', encoding="utf-8")

    ack = spool.receive(
        corrupt,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )

    assert ack["ack_status"] == "QUARANTINED"
    assert len(spool.replay(SpoolState.QUARANTINED)) == 1


def test_replay_is_deterministic_by_message_identity(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    late = spool.queue_message(_message("z"), signer=_signer())
    early = spool.queue_message(_message("a"), signer=_signer())

    replay_ids = [item.message_id for item in spool.replay(SpoolState.QUEUED)]

    assert replay_ids == sorted([str(late.message["message_id"]), str(early.message["message_id"])])


def test_reordered_delivery_rejects_until_predecessor_is_imported(
    tmp_path: Path,
) -> None:
    spool = SpoolRoot.at(tmp_path)
    first = spool.queue_message(_message("first"), signer=_signer())
    second = spool.queue_message(_message("second"), signer=_signer())

    second_ack = spool.receive(
        second.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )
    first_ack = spool.receive(
        first.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:11Z",
        ttl_seconds=60,
    )

    assert second_ack["ack_status"] == "QUARANTINED"
    assert first_ack["ack_status"] == "ACKNOWLEDGED"
    retried_second_ack = spool.receive(
        second.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:12Z",
        ttl_seconds=60,
    )
    assert retried_second_ack["ack_status"] == "ACKNOWLEDGED"
    assert len(spool.replay(SpoolState.IMPORTED_AS_C3)) == 2


def test_sequence_rollback_is_rejected_after_latest_import(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    signer = Ed25519Signer.generate(signer_cell="standalone")
    verifier = Ed25519Verifier({signer.resolved_key_id(): signer.public_key_hex})
    first = spool.queue_message(_message("first"), signer=signer)
    second = spool.queue_message(_message("second"), signer=signer)
    spool.receive(
        first.message_path,
        verifier=verifier,
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )
    spool.receive(
        second.message_path,
        verifier=verifier,
        now_utc="2026-07-29T00:00:11Z",
        ttl_seconds=60,
    )

    rollback = spool.queue_message(_message("rollback"), signer=signer, sequence=1)
    older_predecessor = spool.queue_message(
        _message("older-predecessor"),
        signer=signer,
        sequence=2,
        previous_signature_ref="sha256:"
        + hashlib.sha256(first.signature_path.read_bytes()).hexdigest(),
    )

    rollback_ack = spool.receive(
        rollback.message_path,
        verifier=verifier,
        now_utc="2026-07-29T00:00:12Z",
        ttl_seconds=60,
    )
    older_predecessor_ack = spool.receive(
        older_predecessor.message_path,
        verifier=verifier,
        now_utc="2026-07-29T00:00:13Z",
        ttl_seconds=60,
    )

    assert rollback_ack["ack_status"] == "QUARANTINED"
    assert older_predecessor_ack["ack_status"] == "QUARANTINED"
    assert len(spool.replay(SpoolState.IMPORTED_AS_C3)) == 2


def test_missing_ack_after_import_is_reconciled_on_restart(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    queued = spool.queue_message(_message(), signer=_signer())
    ack = spool.receive(
        queued.message_path,
        verifier=_signer(),
        now_utc="2026-07-29T00:00:10Z",
        ttl_seconds=60,
    )
    ack_path = tmp_path / "acks" / queued.message_path.name
    ack_path.unlink()

    repaired = spool.reconcile_acknowledgements(created_utc="2026-07-29T00:00:20Z")

    assert ack["ack_status"] == "ACKNOWLEDGED"
    assert len(repaired) == 1
    assert repaired[0]["ack_status"] == "ACKNOWLEDGED"
    assert ack_path.exists()


def test_retry_delays_are_deterministic_and_bounded() -> None:
    message_id = str(_message()["message_id"])
    policy = RetryPolicy(max_attempts=5, base_seconds=2, max_delay_seconds=9)

    first = deterministic_retry_delays(message_id, policy)
    second = deterministic_retry_delays(message_id, policy)

    assert first == second
    assert len(first) == 5
    assert all(2 <= delay <= 9 for delay in first)


def test_d2_payload_is_refused_before_queue() -> None:
    with pytest.raises(TransportRefusalError):
        build_spool_message(
            source_cell="standalone",
            target_cell="market",
            payload_ref=_payload_ref(),
            classification="D2",
            created_utc="2026-07-29T00:00:00Z",
        )


def test_manual_dead_letter_record_is_schema_valid(tmp_path: Path) -> None:
    spool = SpoolRoot.at(tmp_path)
    message = _message()

    result = spool.dead_letter(message, reason="terminal_delivery_failure")

    assert result.record_path.exists()
    assert result.record["schema_version"] == "DeadLetterRecord/v1"
    assert result.record["message_id"] == message["message_id"]
