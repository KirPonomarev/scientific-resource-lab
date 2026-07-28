"""Unit tests for the T7 volume identity guard (srl.cas.t7_identity).

Pins:

1. A mounted volume whose UUID matches the expected identity verifies and yields
   a ``T7IdentityReceipt/v1`` with a redacted mount point.
2. A mounted volume whose UUID differs raises ``WrongVolumeError``
   (``WRONG_T7_VOLUME``, hard stop) carrying the expected and observed UUIDs.
3. An absent/ambiguous provider raises ``T7UnavailableError``
   (``T7_UNAVAILABLE``).
4. ``load_expected_identity`` reads the expected UUID from an out-of-repo config
   file and refuses malformed/missing configs.
5. The default provider parses ``diskutil info`` output and fails closed on
   ambiguous output (exercised via the pure parser, no subprocess).
6. No public output of the guard carries a raw ``/Volumes/`` or ``/Users/`` path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from srl.cas import t7_identity as t7mod
from srl.cas.t7_identity import (
    IDENTITY_RECEIPT_SCHEMA_VERSION,
    T7_UNAVAILABLE_FAIL_REASON,
    WAIT_STORAGE_FAIL_REASON,
    WRONG_T7_VOLUME_FAIL_REASON,
    MountInfo,
    MountInfoProvider,
    T7UnavailableError,
    WrongVolumeError,
    _parse_diskutil_output,
    default_mount_info_provider,
    load_expected_identity,
    verify_t7_identity,
)

# The fake expected/foreign UUIDs (match the storage fixtures).
_EXPECTED_UUID = "00000000-0000-4000-8000-000000000001"
_FOREIGN_UUID = "00000000-0000-4000-8000-000000000099"
_FAKE_MOUNT = "redacted:fake-mount"


def _provider_returning(info: MountInfo | None) -> MountInfoProvider:
    """Build a fake provider returning ``info`` (or raising if None)."""

    def _provider(mount_point: str) -> MountInfo:
        del mount_point
        if info is None:
            raise T7UnavailableError("absent", reason="diskutil_nonzero_exit")
        return dict(info)

    return _provider


def _good_info(uuid: str = _EXPECTED_UUID) -> MountInfo:
    return {"volume_uuid": uuid, "mount_point": _FAKE_MOUNT, "fs_type": "apfs"}


# --- verify_t7_identity ----------------------------------------------------


def test_verify_t7_identity_accepts_matching_uuid() -> None:
    """A matching UUID verifies and returns a receipt with a redacted mount."""
    receipt = verify_t7_identity(
        expected_uuid=_EXPECTED_UUID,
        mount_point="/Volumes/T7-fake",
        provider=_provider_returning(_good_info()),
    )
    assert receipt["schema_version"] == IDENTITY_RECEIPT_SCHEMA_VERSION
    assert receipt["volume_uuid"] == _EXPECTED_UUID
    assert receipt["match"] == "true"
    # The mount point is redacted, never raw.
    assert receipt["mount_point_redacted"].startswith("redacted:")
    assert "/Volumes/" not in receipt["mount_point_redacted"]


def test_verify_t7_identity_rejects_wrong_uuid() -> None:
    """A mismatched UUID raises WrongVolumeError (WRONG_T7_VOLUME)."""
    with pytest.raises(WrongVolumeError) as exc_info:
        verify_t7_identity(
            expected_uuid=_EXPECTED_UUID,
            mount_point=_FAKE_MOUNT,
            provider=_provider_returning(_good_info(_FOREIGN_UUID)),
        )
    assert exc_info.value.fail_reason == WRONG_T7_VOLUME_FAIL_REASON
    assert exc_info.value.expected_uuid == _EXPECTED_UUID
    assert exc_info.value.observed_uuid == _FOREIGN_UUID


def test_verify_t7_identity_unavailable_when_provider_raises() -> None:
    """A provider raising (absent T7) surfaces as T7UnavailableError."""
    with pytest.raises(T7UnavailableError) as exc_info:
        verify_t7_identity(
            expected_uuid=_EXPECTED_UUID,
            mount_point=_FAKE_MOUNT,
            provider=_provider_returning(None),
        )
    assert exc_info.value.fail_reason == T7_UNAVAILABLE_FAIL_REASON


def test_verify_t7_identity_unavailable_on_malformed_provider_output() -> None:
    """Fail closed: a malformed MountInfo (bad keys) is unavailable, not guessed."""
    with pytest.raises(T7UnavailableError):
        verify_t7_identity(
            expected_uuid=_EXPECTED_UUID,
            mount_point=_FAKE_MOUNT,
            provider=lambda mp: {"volume_uuid": _EXPECTED_UUID},  # type: ignore[return-value]
        )


def test_verify_t7_identity_unavailable_on_bad_uuid_shape() -> None:
    """Fail closed: a provider returning a malformed UUID is unavailable."""
    with pytest.raises(T7UnavailableError):
        verify_t7_identity(
            expected_uuid=_EXPECTED_UUID,
            mount_point=_FAKE_MOUNT,
            provider=lambda mp: {  # type: ignore[return-value]
                "volume_uuid": "not-a-uuid",
                "mount_point": _FAKE_MOUNT,
                "fs_type": "apfs",
            },
        )


def test_verify_t7_identity_rejects_bad_expected_uuid() -> None:
    """A malformed expected_uuid is a caller bug (ValueError)."""
    with pytest.raises(ValueError):
        verify_t7_identity(
            expected_uuid="nope",
            mount_point=_FAKE_MOUNT,
            provider=_provider_returning(_good_info()),
        )


def test_verify_t7_identity_normalizes_arbitrary_provider_exception() -> None:
    """Any non-typed provider exception becomes T7UnavailableError."""

    def _raising(_mp: str) -> MountInfo:
        raise RuntimeError("boom")

    with pytest.raises(T7UnavailableError) as exc_info:
        verify_t7_identity(
            expected_uuid=_EXPECTED_UUID,
            mount_point=_FAKE_MOUNT,
            provider=_raising,  # type: ignore[arg-type]
        )
    assert exc_info.value.reason == "provider_raised"


# --- load_expected_identity ------------------------------------------------


def test_load_expected_identity_reads_config(tmp_path: Path) -> None:
    """A well-formed config yields the expected UUID."""
    cfg = tmp_path / "t7-identity.json"
    cfg.write_text(json.dumps({"volume_uuid": _EXPECTED_UUID}), encoding="utf-8")
    assert load_expected_identity(cfg) == _EXPECTED_UUID


@pytest.mark.parametrize(
    "doc,reason",
    [
        ({"volume_uuid": "bad"}, "config_bad_uuid"),
        ({"other": "x"}, "config_missing_uuid"),
        ("not-an-object", "config_not_object"),
    ],
)
def test_load_expected_identity_rejects_malformed(tmp_path: Path, doc: object, reason: str) -> None:
    """Malformed configs are unavailable with the classified reason."""
    cfg = tmp_path / "bad.json"
    cfg.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(T7UnavailableError) as exc_info:
        load_expected_identity(cfg)
    assert exc_info.value.reason == reason


def test_load_expected_identity_rejects_missing_file(tmp_path: Path) -> None:
    """A missing config file is unavailable."""
    with pytest.raises(T7UnavailableError) as exc_info:
        load_expected_identity(tmp_path / "nope.json")
    assert exc_info.value.reason == "config_missing"


def test_load_expected_identity_rejects_bad_json(tmp_path: Path) -> None:
    """A config that is not valid JSON is unavailable."""
    cfg = tmp_path / "broken.json"
    cfg.write_text("{not json", encoding="utf-8")
    with pytest.raises(T7UnavailableError) as exc_info:
        load_expected_identity(cfg)
    assert exc_info.value.reason == "config_bad_json"


# --- diskutil parser -------------------------------------------------------


def test_parse_diskutil_output_extracts_uuid() -> None:
    """The parser extracts the single Volume UUID line."""
    output = (
        "   Device Identifier:         disk2s1\n"
        "   Volume UUID:               00000000-0000-4000-8000-000000000001\n"
        "   File System Personality:   APFS\n"
    )
    assert _parse_diskutil_output(output) == _EXPECTED_UUID


def test_parse_diskutil_output_fails_on_ambiguity() -> None:
    """Zero or multiple Volume UUID lines raise (fail closed)."""
    with pytest.raises(ValueError):
        _parse_diskutil_output("   no uuid here\n")
    with pytest.raises(ValueError):
        _parse_diskutil_output(
            "   Volume UUID:  00000000-0000-4000-8000-000000000001\n"
            "   Volume UUID:  00000000-0000-4000-8000-000000000002\n"
        )


def test_parse_diskutil_output_fails_on_malformed_uuid() -> None:
    """A malformed UUID value raises."""
    with pytest.raises(ValueError):
        _parse_diskutil_output("   Volume UUID:  not-a-uuid\n")


# --- wait-reason export ----------------------------------------------------


def test_wait_storage_fail_reason_constant() -> None:
    """The WAIT_STORAGE constant is the registry value."""
    assert WAIT_STORAGE_FAIL_REASON == "WAIT_STORAGE"


def test_default_mount_info_provider_missing_diskutil(monkeypatch: pytest.MonkeyPatch) -> None:
    """When diskutil is absent (FileNotFoundError) the provider is unavailable."""

    def _raise_no_file(*_a: object, **_k: object) -> None:
        raise FileNotFoundError("diskutil")

    monkeypatch.setattr(t7mod.subprocess, "run", _raise_no_file)
    with pytest.raises(T7UnavailableError) as exc_info:
        default_mount_info_provider("/Volumes/T7-fake")
    assert exc_info.value.reason == "diskutil_missing"
