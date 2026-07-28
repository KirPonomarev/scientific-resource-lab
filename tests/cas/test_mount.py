"""Unit tests for the T7 mount-state probe (srl.cas.mount_state).

Pins the four mount states and the exit directive each maps to:

- MOUNTED_EXPECTED -> proceed
- MOUNTED_FOREIGN  -> fail_closed
- ABSENT           -> wait_storage
- AMBIGUOUS        -> wait_storage
"""

from __future__ import annotations

import pytest

from srl.cas.mount_state import WAIT_STORAGE_EXIT, MountState, probe_mount
from srl.cas.t7_identity import MountInfo, MountInfoProvider, T7UnavailableError

_EXPECTED_UUID = "00000000-0000-4000-8000-000000000001"
_FOREIGN_UUID = "00000000-0000-4000-8000-000000000099"
_FAKE_MOUNT = "redacted:fake-mount"


def _provider_returning(info: MountInfo | None, *, reason: str = "") -> MountInfoProvider:
    def _provider(mount_point: str) -> MountInfo:
        del mount_point
        if info is None:
            raise T7UnavailableError("absent", reason=reason or "diskutil_nonzero_exit")
        return dict(info)

    return _provider


def _good_info(uuid: str = _EXPECTED_UUID) -> MountInfo:
    return {"volume_uuid": uuid, "mount_point": _FAKE_MOUNT, "fs_type": "apfs"}


def test_probe_mount_expected_proceeds() -> None:
    """A matching volume yields MOUNTED_EXPECTED + proceed."""
    state, directive = probe_mount(
        expected_uuid=_EXPECTED_UUID,
        mount_point=_FAKE_MOUNT,
        provider=_provider_returning(_good_info()),
    )
    assert state is MountState.MOUNTED_EXPECTED
    assert directive == "proceed"


def test_probe_mount_foreign_fails_closed() -> None:
    """A foreign volume yields MOUNTED_FOREIGN + fail_closed."""
    state, directive = probe_mount(
        expected_uuid=_EXPECTED_UUID,
        mount_point=_FAKE_MOUNT,
        provider=_provider_returning(_good_info(_FOREIGN_UUID)),
    )
    assert state is MountState.MOUNTED_FOREIGN
    assert directive == "fail_closed"


@pytest.mark.parametrize("reason", ["diskutil_nonzero_exit", "diskutil_missing", "provider_raised"])
def test_probe_mount_absent_waits(reason: str) -> None:
    """A provider failing with a volume-absent reason yields ABSENT + wait."""
    state, directive = probe_mount(
        expected_uuid=_EXPECTED_UUID,
        mount_point=_FAKE_MOUNT,
        provider=_provider_returning(None, reason=reason),
    )
    assert state is MountState.ABSENT
    assert directive == WAIT_STORAGE_EXIT


def test_probe_mount_ambiguous_waits() -> None:
    """A provider returning malformed output yields AMBIGUOUS + wait."""
    state, directive = probe_mount(
        expected_uuid=_EXPECTED_UUID,
        mount_point=_FAKE_MOUNT,
        provider=lambda mp: {"volume_uuid": _EXPECTED_UUID},  # type: ignore[return-value]
    )
    assert state is MountState.AMBIGUOUS
    assert directive == WAIT_STORAGE_EXIT


def test_wait_storage_exit_constant() -> None:
    """The wait directive constant is the documented value."""
    assert WAIT_STORAGE_EXIT == "wait_storage"
