from __future__ import annotations

import json
import stat
from pathlib import Path

from srl.transport.native_keyring import (
    PRODUCTION_KEY_BINDING_ACTIVE_STATE,
    PRODUCTION_KEY_BINDING_BLOCKED_ABSENT_STATE,
    build_production_key_binding_receipt,
    probe_private_file_keyring,
    production_key_receipt_is_active,
)


def _receipt_from_probe(tmp_path: Path, *, create_missing: bool) -> dict[str, object]:
    probe = probe_private_file_keyring(
        key_dir=tmp_path / "native-keyring",
        create_missing=create_missing,
        authority_directive_present=True,
    )
    return build_production_key_binding_receipt(
        probe=probe,
        authority_directive_id="test-directive",
    )


def test_absent_native_keyring_stays_blocked_without_creating_secret(tmp_path: Path) -> None:
    receipt = _receipt_from_probe(tmp_path, create_missing=False)

    assert receipt["status"] == PRODUCTION_KEY_BINDING_BLOCKED_ABSENT_STATE
    assert production_key_receipt_is_active(receipt) is False
    assert receipt["key_id"] is None
    assert receipt["remaining_external_waits"]
    assert not (tmp_path / "native-keyring").exists()


def test_private_file_keyring_creates_active_secret_free_receipt(tmp_path: Path) -> None:
    key_dir = tmp_path / "native-keyring"
    receipt = _receipt_from_probe(tmp_path, create_missing=True)

    assert receipt["status"] == PRODUCTION_KEY_BINDING_ACTIVE_STATE
    assert production_key_receipt_is_active(receipt) is True
    assert receipt["remaining_external_waits"] == []
    assert str(receipt["key_id"]).startswith("sha256:")
    assert str(receipt["public_key_fingerprint"]).startswith("sha256:")
    assert (key_dir / "production-ed25519.raw").stat().st_size == 32
    assert stat.S_IMODE((key_dir / "production-ed25519.raw").stat().st_mode) == 0o600
    assert stat.S_IMODE((key_dir / "receiver-keyring.json").stat().st_mode) == 0o600

    rendered = json.dumps(receipt, sort_keys=True)
    assert str(tmp_path) not in rendered
    assert "raw_public_key" in rendered
    assert "private_key_hex" not in rendered
    pem_private_marker = "BEGIN " + "PRIVATE KEY"
    assert pem_private_marker not in rendered
    assert all(value is False for value in receipt["public_boundary"].values())


def test_private_file_keyring_reuse_keeps_key_id_stable(tmp_path: Path) -> None:
    first = _receipt_from_probe(tmp_path, create_missing=True)
    second = _receipt_from_probe(tmp_path, create_missing=True)

    assert first["status"] == PRODUCTION_KEY_BINDING_ACTIVE_STATE
    assert second["status"] == PRODUCTION_KEY_BINDING_ACTIVE_STATE
    assert second["key_id"] == first["key_id"]
    assert second["public_key_fingerprint"] == first["public_key_fingerprint"]
