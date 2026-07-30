from __future__ import annotations

import json
from pathlib import Path

import pytest

from srl.cas import LocalArtifactStore
from srl.cas.store import StoreIntegrityError
from srl.health import bounded_restore_drill
from srl.health.disaster_recovery import (
    PHYSICAL_RECOVERY_AUTHORITY_WAIT,
    PHYSICAL_T7_RESTORE_WAIT,
    RECOVERY_TARGET_WAIT_STATE,
    build_a21_operator_action,
    run_a21_disaster_recovery_drill,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_a21_drill_restores_chain_and_records_waits(tmp_path: Path) -> None:
    receipt = run_a21_disaster_recovery_drill(repo_root=REPO_ROOT, drill_root=tmp_path)

    assert receipt["result"] == "PASS"
    assert receipt["terminal_state"] == RECOVERY_TARGET_WAIT_STATE
    assert receipt["rpo_rto"]["rpo_seconds_measured"] == 0.0
    assert receipt["rpo_rto"]["restored_artifact_count"] == 3
    assert PHYSICAL_RECOVERY_AUTHORITY_WAIT in receipt["remaining_external_waits"]
    assert PHYSICAL_T7_RESTORE_WAIT in receipt["remaining_external_waits"]
    assert receipt["current_vps_used_as_sole_backup"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["live_actions"] == 0
    assert receipt["grants_authority"] is False


def test_a21_receipt_has_all_required_chaos_routes(tmp_path: Path) -> None:
    receipt = run_a21_disaster_recovery_drill(repo_root=REPO_ROOT, drill_root=tmp_path)
    chaos = receipt["chaos_receipts"]

    assert set(chaos) == {
        "executor_crash",
        "corrupt_objects",
        "revoked_packs",
        "stale_keys",
        "lost_indexes",
    }
    for chaos_id, item in chaos.items():
        assert item["status"] == "PASS", chaos_id
        assert item["canonical_writes"] == 0, chaos_id
        assert item["live_actions"] == 0, chaos_id
        assert item["grants_authority"] is False, chaos_id


def test_a21_receipt_does_not_publish_host_paths(tmp_path: Path) -> None:
    receipt = run_a21_disaster_recovery_drill(repo_root=REPO_ROOT, drill_root=tmp_path)
    rendered = json.dumps(receipt, sort_keys=True)

    assert "/Users/" not in rendered
    assert "/Volumes/" not in rendered
    assert str(tmp_path) not in rendered


def test_a21_operator_action_is_non_authorizing() -> None:
    action = build_a21_operator_action()

    assert action["schema_version"] == "ProtectedOperatorAction/v1"
    assert action["action_id"] == "A21_CONFIGURE_SECOND_ENCRYPTED_RECOVERY_TARGET"
    assert action["authority_required"] is True
    assert action["grants_authority"] is False
    assert "claim_done_or_v2_release" in action["forbidden_without_authority"]
    committed = json.loads(
        (
            REPO_ROOT / "docs" / "target-binding" / "a21-recovery-target-operator-action.json"
        ).read_text(encoding="utf-8")
    )
    assert committed == action


def test_a21_restore_still_fails_closed_on_corrupt_unique_source(tmp_path: Path) -> None:
    source = LocalArtifactStore(tmp_path / "source")
    artifact = source.put(b"unique-small-receipt").digest
    source._object_path(artifact).write_bytes(b"corrupt")

    with pytest.raises(StoreIntegrityError):
        bounded_restore_drill(
            source_store=source,
            restore_root=tmp_path / "restore",
            artifact_ids=(artifact,),
            created_utc="2026-07-30T00:00:00Z",
        )
