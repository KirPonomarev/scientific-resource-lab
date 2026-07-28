"""T7 volume identity guard.

The T7 volume is an external, operator-owned physical volume. Before the
content-addressed store writes to it, the runtime must confirm that the volume
mounted at the expected mount point is *the* volume the mission expects (by its
filesystem Volume UUID), and not a different volume that happens to share the
mount point. Writing to the wrong volume is a hard stop
(``WRONG_T7_VOLUME``): the bytes would land on an unverified volume, defeating
the content-addressing guarantee.

Expected identity
-----------------
The expected identity comes from a **local config file outside the repository**
(the path is passed in by the operator; it is never hardcoded). The file is a
small JSON document recording the expected ``volume_uuid``. Keeping it outside
the repo means a clone of the repo never carries an operator's volume identity,
and the identity is not committed to the public history.

Provider injection
------------------
The actual volume probe is performed by an injectable *provider* — a callable
returning a ``MountInfo`` dict ``{volume_uuid, mount_point, fs_type}``. The
default provider shells out **only** to ``diskutil info <mountpoint>`` on macOS
and parses the ``Volume UUID`` field; it executes nothing else and writes
nothing. Tests inject a fake provider returning a fixed ``MountInfo`` so they
are hermetic and never touch a real disk.

Failure routing
---------------
Two distinct failures, each typed:

- :class:`WrongVolumeError` — a volume is mounted at the expected mount point,
  but its Volume UUID does not match. ``fail_reason='WRONG_T7_VOLUME'``,
  ``hard_stop=true`` (per ``automation/fail-reasons.json``). The store fails
  closed; no bytes are written and there is no fallback.
- :class:`T7UnavailableError` — no usable volume identity could be obtained (the
  provider raised, the volume is absent, or the probe was ambiguous).
  ``fail_reason='T7_UNAVAILABLE'``, ``hard_stop=false``. The store waits
  (``WAIT_STORAGE``) rather than failing the mission; the volume may appear
  later.

The guard fails closed on any parse ambiguity: a provider output that does not
contain exactly the three expected keys with the right shapes is treated as
unavailable, never as "close enough".
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from srl.cas.privacy import redact_store_path
from srl.contracts.errors import ContractError

# Schema identity for the identity receipt. Bumped only on a contract change to
# the receipt shape.
IDENTITY_RECEIPT_SCHEMA_VERSION: Final[str] = "T7IdentityReceipt/v1"

# The typed fail reason for a wrong-volume refusal. Mirrors the
# ``WRONG_T7_VOLUME`` entry in ``automation/fail-reasons.json`` (class
# ``storage``, ``hard_stop=true``, ``retriable=false``).
WRONG_T7_VOLUME_FAIL_REASON: Final[str] = "WRONG_T7_VOLUME"

# The typed fail reason for a T7-unavailable condition. Mirrors the
# ``T7_UNAVAILABLE`` entry in ``automation/fail-reasons.json`` (class
# ``storage``, ``hard_stop=false``, ``retriable=false``). The store treats this
# as a WAIT_STORAGE condition, not a mission failure.
T7_UNAVAILABLE_FAIL_REASON: Final[str] = "T7_UNAVAILABLE"

# The WAIT_STORAGE signal the store raises when the T7 is unavailable. This is
# the resume-retryable wait the autonomy machinery acts on (the volume may
# appear later). Kept distinct from the fail reason so a receipt records both
# the storage failure class and the wait directive.
WAIT_STORAGE_FAIL_REASON: Final[str] = "WAIT_STORAGE"

# A macOS/APFS Volume UUID: 8-4-4-4-12 lowercase hex, the canonical form
# ``diskutil`` reports. Compiled once; the default provider uses it to validate a
# parsed UUID before trusting it.
_VOLUME_UUID_PATTERN: Final[str] = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_VOLUME_UUID_RE: Final[re.Pattern[str]] = re.compile(_VOLUME_UUID_PATTERN)

# The keys a MountInfo dict must carry. Exactly these three, no more, no less —
# ambiguity is treated as unavailable (fail closed).
_MOUNT_INFO_KEYS: Final[frozenset[str]] = frozenset({"volume_uuid", "mount_point", "fs_type"})


class WrongVolumeError(ContractError):
    """Raised when a mounted volume's UUID does not match the expected one.

    This is a hard stop: a byte written to the wrong volume is unverifiable. The
    store raises this *before* any write, so no bytes land on the wrong volume.
    Carries the typed ``fail_reason='WRONG_T7_VOLUME'`` plus the expected and
    observed UUIDs for diagnostics (the observed UUID is safe to expose; it is
    not the operator's real volume because the expected identity lives outside
    the repo and the fixtures use fake UUIDs).
    """

    def __init__(
        self,
        message: str,
        *,
        expected_uuid: str = "",
        observed_uuid: str = "",
        fail_reason: str = WRONG_T7_VOLUME_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.expected_uuid: str = expected_uuid
        self.observed_uuid: str = observed_uuid


class T7UnavailableError(ContractError):
    """Raised when no usable T7 volume identity can be obtained.

    The provider raised, the volume is absent, or the probe output was
    ambiguous. This is **not** a hard stop: the store waits
    (``fail_reason='T7_UNAVAILABLE'``, surfaced as ``WAIT_STORAGE``) because the
    volume may appear later. Carries a ``reason`` string classifying the
    unavailability for the receipt.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "",
        fail_reason: str = T7_UNAVAILABLE_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.reason: str = reason


# A volume-identity provider returns this shape. ``volume_uuid`` is the
# canonical 8-4-4-4-12 lowercase-hex form; ``mount_point`` is the absolute path
# the volume is mounted at; ``fs_type`` is the filesystem label (e.g. ``apfs``,
# ``hfs``). The dict must carry exactly these three keys.
MountInfo = dict[str, str]

# The provider protocol: a callable taking the mount point and returning a
# MountInfo. Injected by tests; the default shells out to ``diskutil``.
MountInfoProvider = Callable[[str], MountInfo]


def _validate_mount_info(info: Any, *, source: str) -> MountInfo:
    """Validate a provider's return value as a well-formed MountInfo.

    Fail closed on any ambiguity: the dict must carry exactly the three expected
    keys, ``volume_uuid`` must match the UUID pattern, and ``mount_point`` must
    be a non-empty absolute string. A malformed result is treated as unavailable
    (``T7_UNAVAILABLE``), never as "close enough".

    Raises :class:`T7UnavailableError` on any deviation.
    """
    if not isinstance(info, dict):
        msg = f"T7 provider ({source}) returned {type(info).__name__}, expected a dict"
        raise T7UnavailableError(msg, reason="provider_bad_type")
    actual_keys = set(info.keys())
    if actual_keys != _MOUNT_INFO_KEYS:
        msg = (
            f"T7 provider ({source}) returned keys {sorted(actual_keys)}, "
            f"expected exactly {sorted(_MOUNT_INFO_KEYS)}"
        )
        raise T7UnavailableError(msg, reason="provider_bad_keys")
    # mypy: keys confirmed present and dict is dict[str,?] — narrow to str.
    volume_uuid = info["volume_uuid"]
    mount_point = info["mount_point"]
    fs_type = info["fs_type"]
    if not isinstance(volume_uuid, str) or not _VOLUME_UUID_RE.fullmatch(volume_uuid):
        msg = f"T7 provider ({source}) returned an invalid volume_uuid: {volume_uuid!r}"
        raise T7UnavailableError(msg, reason="provider_bad_uuid")
    if not isinstance(mount_point, str) or not mount_point:
        msg = f"T7 provider ({source}) returned an invalid mount_point: {mount_point!r}"
        raise T7UnavailableError(msg, reason="provider_bad_mount_point")
    if not isinstance(fs_type, str) or not fs_type:
        msg = f"T7 provider ({source}) returned an invalid fs_type: {fs_type!r}"
        raise T7UnavailableError(msg, reason="provider_bad_fs_type")
    return {"volume_uuid": volume_uuid, "mount_point": mount_point, "fs_type": fs_type}


def _parse_diskutil_output(output: str) -> str:
    """Parse the ``Volume UUID`` field from ``diskutil info`` output.

    ``diskutil info <mountpoint>`` emits a key/value table; the Volume UUID line
    looks like ``   Volume UUID:              00000000-...``. We locate the
    first line whose key (after stripping) is exactly ``Volume UUID`` and return
    the trimmed value. Any ambiguity (no line, multiple lines, malformed value)
    raises :class:`ValueError`; the caller treats that as unavailable.
    """
    matches: list[str] = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip() == "Volume UUID":
            candidate = value.strip()
            matches.append(candidate)
    if len(matches) != 1:
        msg = f"diskutil output did not contain exactly one Volume UUID line: {output!r}"
        raise ValueError(msg)
    uuid = matches[0]
    if not _VOLUME_UUID_RE.fullmatch(uuid):
        msg = f"diskutil Volume UUID is malformed: {uuid!r}"
        raise ValueError(msg)
    return uuid


def default_mount_info_provider(mount_point: str) -> MountInfo:
    """Default provider: shell out **only** to ``diskutil info <mountpoint>``.

    Runs ``diskutil info <mount_point>`` and parses its Volume UUID field. It
    executes nothing else, writes nothing, and performs no network access. On
    any ambiguity (non-zero exit, ambiguous output, malformed UUID) it raises
    :class:`T7UnavailableError` so the store waits rather than guessing.

    This provider is macOS-only (``diskutil`` is a macOS tool). On other
    platforms it raises ``T7UnavailableError`` with ``reason='diskutil_missing'``.
    """
    # Build the argv explicitly (no shell) so the mount point is a single
    # argument and cannot inject a command. This is the only subprocess the CAS
    # package spawns in its default configuration.
    try:
        completed = subprocess.run(  # noqa: S603 (bounded argv, no shell)
            ["diskutil", "info", mount_point],  # noqa: S607 (diskutil is a system tool resolved via PATH by design)
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise T7UnavailableError(
            "diskutil is not available on this platform",
            reason="diskutil_missing",
        ) from exc
    if completed.returncode != 0:
        msg = (
            f"diskutil info {mount_point!r} exited {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
        raise T7UnavailableError(msg, reason="diskutil_nonzero_exit")
    try:
        volume_uuid = _parse_diskutil_output(completed.stdout)
    except ValueError as exc:
        msg = f"diskutil output for {mount_point!r} was ambiguous: {exc}"
        raise T7UnavailableError(msg, reason="diskutil_ambiguous_output") from exc
    # The fs_type is reported as a separate ``File System Type`` line; we do not
    # gate on it (the UUID is authoritative), so we report a conservative label
    # derived from the mount point rather than parsing a second field, keeping
    # the parser single-purpose. Callers that need the real fs_type inject a
    # provider.
    return {
        "volume_uuid": volume_uuid,
        "mount_point": mount_point,
        "fs_type": _infer_fs_type(completed.stdout),
    }


def _infer_fs_type(diskutil_output: str) -> str:
    """Best-effort parse of the ``File System Personality`` label.

    Returns a short lowercase label (``apfs``, ``hfs``, ``unknown``). This is
    informational only — identity is decided by the Volume UUID — so a parse
    miss degrades to ``unknown`` rather than failing.
    """
    for line in diskutil_output.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip() in {"File System Personality", "File System Type"}:
            label = value.strip().lower()
            if "apfs" in label:
                return "apfs"
            if "hfs" in label:
                return "hfs"
            return label or "unknown"
    return "unknown"


def load_expected_identity(config_path: str | Path) -> str:
    """Load the expected T7 volume UUID from a config file outside the repo.

    The config file is a JSON object with a ``volume_uuid`` field carrying the
    canonical 8-4-4-4-12 lowercase-hex UUID the mission expects. The path is
    passed in by the operator; it is never hardcoded inside this package.

    Parameters
    ----------
    config_path:
        Filesystem path to the local identity config JSON (outside the repo).

    Returns
    -------
    str
        The expected volume UUID.

    Raises
    ------
    T7UnavailableError
        If the file is missing, unreadable, not valid JSON, lacks the
        ``volume_uuid`` field, or the UUID is malformed. All of these are
        treated as "the expected identity is not available" so the store waits.
    """
    p = Path(config_path)
    if not p.is_file():
        msg = f"T7 identity config file not found: {p}"
        raise T7UnavailableError(msg, reason="config_missing")
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"could not read T7 identity config {p}: {exc}"
        raise T7UnavailableError(msg, reason="config_unreadable") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"T7 identity config {p} is not valid JSON: {exc}"
        raise T7UnavailableError(msg, reason="config_bad_json") from exc
    if not isinstance(parsed, dict):
        msg = f"T7 identity config {p} must be a JSON object, got {type(parsed).__name__}"
        raise T7UnavailableError(msg, reason="config_not_object")
    if "volume_uuid" not in parsed:
        msg = f"T7 identity config {p} is missing 'volume_uuid'"
        raise T7UnavailableError(msg, reason="config_missing_uuid")
    uuid = parsed["volume_uuid"]
    if not isinstance(uuid, str) or not _VOLUME_UUID_RE.fullmatch(uuid):
        msg = f"T7 identity config {p} has a malformed volume_uuid: {uuid!r}"
        raise T7UnavailableError(msg, reason="config_bad_uuid")
    return uuid


def verify_t7_identity(
    *,
    expected_uuid: str,
    mount_point: str,
    provider: MountInfoProvider,
) -> dict[str, str]:
    """Verify that the volume at ``mount_point`` matches the expected identity.

    Calls ``provider(mount_point)`` to obtain the mounted volume's identity and
    compares its ``volume_uuid`` to ``expected_uuid``. On a mismatch raises
    :class:`WrongVolumeError` (hard stop, ``WRONG_T7_VOLUME``); on any provider
    ambiguity raises :class:`T7UnavailableError` (wait, ``T7_UNAVAILABLE``).

    Parameters
    ----------
    expected_uuid:
        The expected Volume UUID (canonical lowercase-hex form). Typically
        loaded via :func:`load_expected_identity` from an out-of-repo config.
    mount_point:
        The absolute path the T7 volume is expected to be mounted at.
    provider:
        An injectable callable returning a :data:`MountInfo`. Tests pass a fake;
        production wires :func:`default_mount_info_provider`.

    Returns
    -------
    dict[str, str]
        An :class:`IdentityReceipt`-shaped dict (``schema_version``,
        ``volume_uuid``, ``mount_point``, ``fs_type``, ``match``) recording the
        successful verification. The receipt carries only the UUID and a
        redacted-free mount point label — never a raw ``/Volumes/`` or
        ``/Users/`` path (see :mod:`srl.cas.privacy`).

    Raises
    ------
    WrongVolumeError
        If the mounted volume's UUID differs from ``expected_uuid``.
    T7UnavailableError
        If the provider could not return a valid identity.
    ValueError
        If ``expected_uuid`` is not a canonical UUID (caller bug).
    """
    if not isinstance(expected_uuid, str) or not _VOLUME_UUID_RE.fullmatch(expected_uuid):
        msg = f"expected_uuid is not a canonical volume UUID: {expected_uuid!r}"
        raise ValueError(msg)
    if not isinstance(mount_point, str) or not mount_point:
        msg = "mount_point must be a non-empty string"
        raise ValueError(msg)
    try:
        info = provider(mount_point)
    except T7UnavailableError:
        raise
    except Exception as exc:
        # Any provider exception other than our own typed unavailability is
        # normalized to T7Unavailable so the store waits uniformly.
        msg = f"T7 provider raised {type(exc).__name__}: {exc}"
        raise T7UnavailableError(msg, reason="provider_raised") from exc
    validated = _validate_mount_info(info, source=provider.__name__ or "<provider>")
    observed = validated["volume_uuid"]
    if observed != expected_uuid:
        msg = (
            f"wrong T7 volume: expected UUID {expected_uuid!r} but the volume mounted "
            f"at {mount_point!r} has UUID {observed!r}"
        )
        raise WrongVolumeError(
            msg,
            expected_uuid=expected_uuid,
            observed_uuid=observed,
        )
    return {
        "schema_version": IDENTITY_RECEIPT_SCHEMA_VERSION,
        "volume_uuid": observed,
        # The mount point is redacted to a digest-prefix token so the receipt
        # never carries a raw /Volumes/ or /Users/ path (privacy contract).
        "mount_point_redacted": redact_store_path(mount_point),
        "fs_type": validated["fs_type"],
        "match": "true",
    }


__all__ = [
    "IDENTITY_RECEIPT_SCHEMA_VERSION",
    "T7_UNAVAILABLE_FAIL_REASON",
    "WAIT_STORAGE_FAIL_REASON",
    "WRONG_T7_VOLUME_FAIL_REASON",
    "MountInfo",
    "MountInfoProvider",
    "T7UnavailableError",
    "WrongVolumeError",
    "default_mount_info_provider",
    "load_expected_identity",
    "verify_t7_identity",
]
