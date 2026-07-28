"""T7 mount-state probe.

Before the store writes to the T7 volume it must answer two questions:

1. **Is a volume mounted at the expected mount point?** (mounted vs absent)
2. **Is it *the* expected volume?** (expected vs foreign)

:func:`probe_mount` answers both in one call, returning a :class:`MountState`
that the store maps to an action:

- :attr:`MountState.MOUNTED_EXPECTED` — proceed; identity verified.
- :attr:`MountState.MOUNTED_FOREIGN` — fail closed (:class:`WrongVolumeError`,
  ``WRONG_T7_VOLUME``). Never fall back to another volume.
- :attr:`MountState.ABSENT` — the store waits (``WAIT_STORAGE`` /
  :class:`T7UnavailableError`); the volume may appear later. The store never
  falls back to a local volume for T7-bound content.
- :attr:`MountState.AMBIGUOUS` — the probe could not decide (provider returned a
  malformed result); the store waits (``WAIT_STORAGE``) rather than guessing.

The probe is hermetic by construction: the volume-identity provider is
injectable, so tests pass a fake and never touch a real disk.
"""

from __future__ import annotations

import enum
from typing import Final

from srl.cas.t7_identity import (
    MountInfoProvider,
    T7UnavailableError,
    WrongVolumeError,
    verify_t7_identity,
)


class MountState(enum.Enum):
    """The state of the T7 mount as observed by :func:`probe_mount`.

    The four members partition all observable outcomes so the store has exactly
    one action per state (proceed / fail-closed / wait / wait).
    """

    # The expected volume is mounted at the expected point; identity verified.
    MOUNTED_EXPECTED = "mounted_expected"
    # A volume is mounted but it is NOT the expected one; fail closed.
    MOUNTED_FOREIGN = "mounted_foreign"
    # No volume is mounted at the expected point; wait for it to appear.
    ABSENT = "absent"
    # The probe could not decide (provider returned a malformed result); wait.
    AMBIGUOUS = "ambiguous"


# The exit signal for "the store must wait for the T7 volume". Returned alongside
# the ABSENT and AMBIGUOUS states so the caller (the store) can raise the typed
# WAIT_STORAGE without re-deriving the policy.
WAIT_STORAGE_EXIT: Final[str] = "wait_storage"


def probe_mount(
    *,
    expected_uuid: str,
    mount_point: str,
    provider: MountInfoProvider,
) -> tuple[MountState, str]:
    """Probe the T7 mount state at ``mount_point`` against ``expected_uuid``.

    Parameters
    ----------
    expected_uuid:
        The expected Volume UUID (canonical lowercase-hex form).
    mount_point:
        The absolute path the T7 volume is expected at.
    provider:
        Injectable callable returning a :class:`~srl.cas.t7_identity.MountInfo`.

    Returns
    -------
    tuple[MountState, str]
        The observed mount state and an exit directive. The directive is
        ``"proceed"`` for MOUNTED_EXPECTED, ``"fail_closed"`` for
        MOUNTED_FOREIGN, and ``"wait_storage"`` for ABSENT and AMBIGUOUS. The
        store maps the directive to its action without re-deriving the policy.

    Notes
    -----
    This function catches :class:`WrongVolumeError` and
    :class:`T7UnavailableError` from the identity verifier and translates them
    into mount states rather than propagating them, so a caller asking "what is
    the mount state?" gets an answer, not an exception. The store still consults
    :func:`~srl.cas.t7_identity.verify_t7_identity` directly on a proceed to
    obtain the typed :class:`~srl.cas.t7_identity.IdentityReceipt`-shaped dict.
    """
    try:
        # Reuse the identity verifier's full validation (key set, UUID shape,
        # UUID match) so the probe and the verifier agree on what "expected"
        # means. probe_mount only translates the outcome to a state.
        verify_t7_identity(
            expected_uuid=expected_uuid,
            mount_point=mount_point,
            provider=provider,
        )
    except WrongVolumeError:
        # A different volume is mounted at the point: fail closed.
        return MountState.MOUNTED_FOREIGN, "fail_closed"
    except T7UnavailableError as exc:
        # The provider failed. If the reason indicates the volume is simply not
        # there (diskutil nonzero exit / missing tool) the state is ABSENT;
        # ambiguous provider output is AMBIGUOUS. Both map to wait_storage.
        if exc.reason in {"diskutil_nonzero_exit", "diskutil_missing", "provider_raised"}:
            return MountState.ABSENT, WAIT_STORAGE_EXIT
        return MountState.AMBIGUOUS, WAIT_STORAGE_EXIT
    return MountState.MOUNTED_EXPECTED, "proceed"


__all__ = ["WAIT_STORAGE_EXIT", "MountState", "probe_mount"]
