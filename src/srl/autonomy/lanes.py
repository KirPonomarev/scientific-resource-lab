"""Machine-enforced active-lane ledger with leases and path ownership.

This module is the governance enforcement layer for parallel autonomous
work. Under ``AutonomyPolicy/v2`` the repository may run up to
``max_parallel_implementation_lanes`` implementation lanes concurrently
(see ``automation/policy.json``). Concurrency without coordination would
let two lanes clobber the same file, so every lane must claim its work via
this ledger before it mutates anything.

The ledger is the single source of truth for *which lanes are active, what
each one owns, and whether its lease is live*. Three invariants are enforced
at acquire time:

1. **Lane count is bounded by the policy.** The cap is read from the policy
   via :func:`srl.autonomy.policy.load_policy`; this module never hardcodes
   the number. A gate (``scripts/checks/gov-lanes-gate.py``) proves the cap
   the gate enforces is the policy's cap, so a policy change is the only way
   the bound moves.

2. **Owned paths are disjoint.** A new lane's owned paths must not equal,
   nest under, or enclose any active lane's owned paths. A collision raises
   :class:`PathOwnershipError` with fail reason ``CONTRACT_INVALID`` naming
   the conflicting lane, so the offending lane never starts.

3. **Worktrees are distinct.** The worktree fingerprint (SHA-256 of the
   absolute worktree path) must be unique among active lanes. The raw
   absolute path is never persisted (privacy: the public boundary holds).

Each lane carries a lease: an acquired-at timestamp, a heartbeat timestamp,
and a TTL (default 900s). A lane that stops heartbeating past its TTL is
stopped by :func:`expire_leases` with fail reason ``ORPHAN_PROCESS_DETECTED``
documented in ``automation/fail-reasons.json``.

Persistence is atomic (tmp + ``fsync`` + ``os.replace`` + dir ``fsync``),
matching the CAS engine discipline, and the canonical form is sorted-key,
compact-separator, ASCII JSON with a trailing newline. Two writers over the
same ledger produce byte-identical files.

Like the rest of :mod:`srl.autonomy`, this module is pure standard library
so it runs in any CI environment without coupling to the scientific stack.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final

from srl.autonomy.policy import PolicyError, load_policy

# ---------------------------------------------------------------------------
# Schema identity. Bumping this is a governance change (see GOVERNANCE.md).
# ---------------------------------------------------------------------------

LEDGER_SCHEMA_VERSION: Final[str] = "ActiveLaneLedger/v1"

# The policy key that is the single source of the lane cap. Kept as a symbol
# so the gate and the docs reference the same name.
LANE_CAP_POLICY_KEY: Final[str] = "max_parallel_implementation_lanes"

# Default lease TTL in seconds (15 minutes). A lane that does not heartbeat
# within this window is treated as orphaned and stopped.
DEFAULT_LEASE_TTL_SECONDS: Final[int] = 900

# Typed fail reasons. Mirrors entries in automation/fail-reasons.json. Kept as
# constants so the strings live in one place and tests assert against symbols.
CONTRACT_INVALID_FAIL_REASON: Final[str] = "CONTRACT_INVALID"
ORPHAN_PROCESS_FAIL_REASON: Final[str] = "ORPHAN_PROCESS_DETECTED"

# Canonical JSON encoding for the ledger file. ASCII-only (the public
# boundary holds; no non-ASCII leaks into a persisted governance artifact),
# sorted keys, compact separators, no NaN/Infinity, single trailing newline.
# Mirrors the autonomy-package convention (srl.canonical) rather than the
# UTF-8 contracts-layer convention, since this is a Phase-A autonomy artifact.
_SEP: Final[tuple[str, str]] = (",", ":")
_NEWLINE: Final[str] = "\n"
_ENCODING: Final[str] = "utf-8"


class Executor(StrEnum):
    """The executor entitled to run a lane.

    ``StrEnum`` keeps the serialized form a plain JSON string while giving us
    enum membership tests. Membership is closed: an unknown executor string
    is rejected at acquire time.
    """

    GLM_52 = "glm-5.2"
    KIMI_FOR_CODING = "kimi-for-coding"
    ORCHESTRATOR = "orchestrator"


class LaneStatus(StrEnum):
    """The lifecycle status of a lane entry.

    Only ``active`` lanes count against the cap and are checked for path
    ownership. ``parked`` and ``completed`` release their ownership claims
    but remain in the ledger as a record. ``stopped`` marks an expired or
    force-stopped lane.
    """

    ACTIVE = "active"
    PARKED = "parked"
    COMPLETED = "completed"
    STOPPED = "stopped"


# Statuses that hold an ownership claim and count against the cap.
# Tuple (not set) for stable membership diagnostics; converted where needed.
_ACTIVE_STATUSES: Final[frozenset[LaneStatus]] = frozenset({LaneStatus.ACTIVE})

# Statuses a caller may explicitly release a lane into. ``active`` is not
# admissible for release (use heartbeat to keep a lane active).
_RELEASE_STATUSES: Final[frozenset[LaneStatus]] = frozenset(
    {LaneStatus.PARKED, LaneStatus.COMPLETED}
)


class LaneError(ValueError):
    """Base for lane-ledger contract failures.

    Subclasses :class:`ValueError` (not :class:`Exception`) so a caller
    handling malformed input via ``except ValueError`` still catches the
    lane family, mirroring :mod:`srl.autonomy.policy` and
    :mod:`srl.autonomy.scopes`.
    """

    def __init__(self, message: str, *, fail_reason: str = CONTRACT_INVALID_FAIL_REASON) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


class PathOwnershipError(LaneError):
    """Raised when a new lane's owned paths collide with an active lane.

    Carries the ``conflicting_lane_id`` so the caller can report exactly
    which lane holds the contested path. The fail reason is always
    ``CONTRACT_INVALID``: an ownership collision is a structural contract
    violation, not a transient conflict.
    """

    def __init__(
        self,
        message: str,
        *,
        conflicting_lane_id: str,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.conflicting_lane_id: str = conflicting_lane_id


# ---------------------------------------------------------------------------
# Data model.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lease:
    """The lease attached to a lane entry.

    Attributes
    ----------
    acquired_utc:
        ISO-8601 ``Z`` timestamp when the lane was acquired.
    heartbeat_utc:
        ISO-8601 ``Z`` timestamp of the most recent heartbeat. Refreshed by
        :func:`heartbeat`; compared against ``ttl_seconds`` by
        :func:`expire_leases`.
    ttl_seconds:
        How long the lane may go without a heartbeat before it is expired.
        Defaults to :data:`DEFAULT_LEASE_TTL_SECONDS`.
    """

    acquired_utc: str
    heartbeat_utc: str
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS


@dataclass(frozen=True)
class LaneEntry:
    """A single lane record in the active-lane ledger.

    Attributes
    ----------
    lane_id:
        Stable identifier for the lane (e.g. ``gov-lane-ledger``).
    wp_id:
        The work-package identifier the lane is implementing.
    executor:
        The :class:`Executor` entitled to run the lane.
    worktree_fingerprint:
        SHA-256 hex of the absolute worktree path. The raw path is never
        persisted (privacy: the public boundary holds).
    branch:
        The git branch the lane is working on.
    base_sha:
        The commit SHA the lane branched from.
    owned_paths:
        Repo-relative paths the lane is authorized to mutate. Disjointness
        against other active lanes is enforced at acquire time.
    lease:
        The :class:`Lease` for the lane.
    status:
        The :class:`LaneStatus` of the lane.
    """

    lane_id: str
    wp_id: str
    executor: Executor
    worktree_fingerprint: str
    branch: str
    base_sha: str
    owned_paths: tuple[str, ...]
    lease: Lease
    status: LaneStatus = LaneStatus.ACTIVE


@dataclass
class LaneLedger:
    """The active-lane ledger.

    Attributes
    ----------
    schema_version:
        Always :data:`LEDGER_SCHEMA_VERSION`.
    lanes:
        Ordered list of :class:`LaneEntry`. Order is insertion order; the
        canonical serialization sorts by ``lane_id`` so two writers produce
        byte-identical files.
    """

    schema_version: str = LEDGER_SCHEMA_VERSION
    lanes: list[LaneEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical serialization.
# ---------------------------------------------------------------------------


def _lane_to_dict(entry: LaneEntry) -> dict[str, Any]:
    """Render a :class:`LaneEntry` as a canonical-JSON-friendly dict."""
    return {
        "lane_id": entry.lane_id,
        "wp_id": entry.wp_id,
        "executor": entry.executor.value,
        "worktree_fingerprint": entry.worktree_fingerprint,
        "branch": entry.branch,
        "base_sha": entry.base_sha,
        "owned_paths": list(entry.owned_paths),
        "lease": asdict(entry.lease),
        "status": entry.status.value,
    }


def _lane_from_dict(data: Mapping[str, Any]) -> LaneEntry:
    """Reconstruct a :class:`LaneEntry` from its canonical dict form.

    Validates enum membership so a corrupted ledger fails loudly rather than
    silently accepting an unknown executor/status.
    """
    try:
        executor = Executor(data["executor"])
    except ValueError as exc:
        msg = f"lane {data.get('lane_id', '?')!r} has unknown executor {data['executor']!r}"
        raise LaneError(msg) from exc
    try:
        status = LaneStatus(data["status"])
    except ValueError as exc:
        msg = f"lane {data.get('lane_id', '?')!r} has unknown status {data['status']!r}"
        raise LaneError(msg) from exc
    lease_data = data["lease"]
    lease = Lease(
        acquired_utc=lease_data["acquired_utc"],
        heartbeat_utc=lease_data["heartbeat_utc"],
        ttl_seconds=int(lease_data.get("ttl_seconds", DEFAULT_LEASE_TTL_SECONDS)),
    )
    return LaneEntry(
        lane_id=data["lane_id"],
        wp_id=data["wp_id"],
        executor=executor,
        worktree_fingerprint=data["worktree_fingerprint"],
        branch=data["branch"],
        base_sha=data["base_sha"],
        owned_paths=tuple(data["owned_paths"]),
        lease=lease,
        status=status,
    )


def _canonical_bytes(ledger: LaneLedger) -> bytes:
    """Encode a ledger as canonical JSON bytes with a trailing newline.

    Lanes are sorted by ``lane_id`` so two writers over the same set produce
    byte-identical files (the determinism contract).
    """
    payload: dict[str, Any] = {
        "schema_version": ledger.schema_version,
        "lanes": [_lane_to_dict(e) for e in sorted(ledger.lanes, key=lambda x: x.lane_id)],
    }
    text = json.dumps(payload, sort_keys=True, separators=_SEP, ensure_ascii=True)
    return (text + _NEWLINE).encode(_ENCODING)


# ---------------------------------------------------------------------------
# Atomic persistence (mirrors srl.cas.engine._atomic_write_bytes discipline).
# ---------------------------------------------------------------------------


def _fsync_dir(path: Path) -> None:
    """``fsync`` the directory at ``path`` (durability of directory entries).

    Best-effort: on a filesystem that refuses directory fsync we already got
    the atomic rename; we do not fail the write over it. Mirrors the CAS
    engine's durability contract.
    """
    if not path.is_dir():
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via same-dir tmp + fsync + replace.

    The temp is created in the same directory so the rename is atomic on the
    same filesystem. The file is fsynced before the rename, and the
    containing directory is fsynced after. On any failure the temp is removed
    and the original file is left intact (old-or-new, never partial).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".atomic-", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def save_ledger(ledger: LaneLedger, path: str | Path) -> None:
    """Persist ``ledger`` to ``path`` as canonical JSON, atomically.

    The write is atomic (tmp + ``fsync`` + ``os.replace`` + dir ``fsync``):
    a crash mid-write leaves the previously-persisted ledger intact. The
    canonical form is byte-stable for equal content, so two saves of the
    same ledger produce identical files.
    """
    _atomic_write_bytes(Path(path), _canonical_bytes(ledger))


def load_ledger(path: str | Path) -> LaneLedger:
    """Load and validate the lane ledger at ``path``.

    Parameters
    ----------
    path:
        Filesystem path to a canonical ``ActiveLaneLedger/v1`` JSON document.

    Returns
    -------
    LaneLedger
        The parsed and validated ledger.

    Raises
    ------
    LaneError
        If the file is missing, is not valid JSON, is not an object, has the
        wrong schema version, or contains a lane with an unknown
        executor/status.
    """
    p = Path(path)
    if not p.is_file():
        msg = f"lane ledger file not found: {p}"
        raise LaneError(msg)
    try:
        raw = p.read_text(encoding=_ENCODING)
    except OSError as exc:
        msg = f"could not read lane ledger {p}: {exc}"
        raise LaneError(msg) from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"lane ledger {p} is not valid JSON: {exc}"
        raise LaneError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"lane ledger {p} must be a JSON object, got {type(parsed).__name__}"
        raise LaneError(msg)
    if parsed.get("schema_version") != LEDGER_SCHEMA_VERSION:
        msg = (
            f"lane ledger has schema_version {parsed.get('schema_version')!r}, "
            f"expected {LEDGER_SCHEMA_VERSION!r}"
        )
        raise LaneError(msg)
    raw_lanes = parsed.get("lanes", [])
    if not isinstance(raw_lanes, list):
        msg = "lane ledger 'lanes' must be an array"
        raise LaneError(msg)
    lanes = [_lane_from_dict(item) for item in raw_lanes]
    return LaneLedger(schema_version=LEDGER_SCHEMA_VERSION, lanes=lanes)


# ---------------------------------------------------------------------------
# Policy cap.
# ---------------------------------------------------------------------------


def policy_lane_cap(policy: Mapping[str, Any]) -> int:
    """Return the lane cap declared by ``policy``.

    The policy (loaded via :func:`srl.autonomy.policy.load_policy`) is the
    single source of the cap. This helper exists so the gate and the
    :func:`acquire_lane` enforcement read the cap through one symbol, making
    it impossible for the gate to hardcode a different number.

    Returns
    -------
    int
        The value of ``policy[LANE_CAP_POLICY_KEY]``.

    Raises
    ------
    LaneError
        If the key is missing or not a positive int (the loader validates
        the enum membership ``4|5|6``; this is a belt-and-braces type check).
    """
    if LANE_CAP_POLICY_KEY not in policy:
        msg = f"policy missing lane-cap key {LANE_CAP_POLICY_KEY!r}"
        raise LaneError(msg)
    value = policy[LANE_CAP_POLICY_KEY]
    # bool is a subclass of int; exclude it explicitly.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        msg = f"policy lane cap must be a positive int, got {value!r}"
        raise LaneError(msg)
    return int(value)


# ---------------------------------------------------------------------------
# Worktree fingerprinting.
# ---------------------------------------------------------------------------


def worktree_fingerprint(worktree_path: str | Path) -> str:
    """Return the SHA-256 hex of the absolute worktree path.

    The raw absolute path is never persisted (privacy: the public boundary
    holds). The fingerprint is the stable, privacy-preserving identifier for
    a worktree. Two lanes over the same worktree collide, which is enforced
    as a uniqueness invariant at acquire time.
    """
    absolute = str(Path(worktree_path).resolve())
    return hashlib.sha256(absolute.encode(_ENCODING)).hexdigest()


# ---------------------------------------------------------------------------
# Path-ownership disjointness.
# ---------------------------------------------------------------------------


def _normalize_owned(path: str) -> PurePosixPath:
    """Normalize an owned path to a POSIX relative form for disjointness.

    Mirrors the discipline in :func:`srl.autonomy.scopes._normalize`: no
    absolute paths, no ``..`` segments, POSIX separators only. An invalid
    owned path is a contract bug and raises :class:`LaneError`.
    """
    if not isinstance(path, str) or path == "":
        msg = "owned path must be a non-empty string"
        raise LaneError(msg)
    if "\\" in path:
        msg = f"owned path contains a backslash (non-portable): {path!r}"
        raise LaneError(msg)
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        msg = f"owned path is absolute (must be repo-relative): {path!r}"
        raise LaneError(msg)
    if ".." in candidate.parts:
        msg = f"owned path contains '..' (traversal forbidden): {path!r}"
        raise LaneError(msg)
    return PurePosixPath(*[p for p in candidate.parts if p != "."])


def _paths_overlap(a: PurePosixPath, b: PurePosixPath) -> bool:
    """Return True iff ``a`` equals, is a prefix of, or is prefixed by ``b``.

    This is the ownership-collision predicate: two owned paths collide if one
    contains the other (directory containment) or they are the same path.
    Sibling paths do not collide.
    """
    if a == b:
        return True
    a_parts = a.parts
    b_parts = b.parts
    # a is a prefix of b: b nests under a.
    if len(a_parts) < len(b_parts) and b_parts[: len(a_parts)] == a_parts:
        return True
    # a is prefixed by b: a nests under b.
    if len(b_parts) < len(a_parts) and a_parts[: len(b_parts)] == b_parts:
        return True
    return False


def _find_ownership_collision(
    candidate: PurePosixPath, active: Iterable[LaneEntry]
) -> PathOwnershipError | None:
    """Return a collision error if ``candidate`` overlaps any active lane path."""
    for entry in active:
        for owned in entry.owned_paths:
            if _paths_overlap(candidate, _normalize_owned(owned)):
                msg = (
                    f"owned path {str(candidate)!r} collides with lane "
                    f"{entry.lane_id!r} (owned {owned!r})"
                )
                return PathOwnershipError(msg, conflicting_lane_id=entry.lane_id)
    return None


# ---------------------------------------------------------------------------
# Lane lifecycle: acquire, heartbeat, expire, release.
# ---------------------------------------------------------------------------


def _active(lanes: Iterable[LaneEntry]) -> list[LaneEntry]:
    """Return only the lanes whose status counts against the cap/ownership."""
    return [e for e in lanes if e.status in _ACTIVE_STATUSES]


def _check_disjointness(
    owned_paths: Iterable[str], active: Iterable[LaneEntry]
) -> tuple[PurePosixPath, PathOwnershipError] | None:
    """Return the first collision among ``owned_paths`` against ``active`` lanes."""
    for raw in owned_paths:
        normalized = _normalize_owned(raw)
        collision = _find_ownership_collision(normalized, active)
        if collision is not None:
            return normalized, collision
    return None


def acquire_lane(  # noqa: PLR0913 (the kw-only set IS the lane's identity fields)
    ledger: LaneLedger,
    *,
    wp_id: str,
    executor: Executor | str,
    worktree_path: str | Path,
    branch: str,
    base_sha: str,
    owned_paths: Iterable[str],
    lane_id: str,
    now: str,
    policy: Mapping[str, Any] | str | Path,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> LaneEntry:
    """Acquire a new lane in ``ledger`` and return the new entry.

    Enforces, in order:

    1. **Cap.** The number of currently-active lanes must be below the policy
       cap. The cap is read from ``policy`` via :func:`policy_lane_cap`, so
       the policy file is the single source of the bound. ``policy`` may be a
       loaded policy dict, or a path loaded on the fly.
    2. **Disjointness.** Every owned path must be disjoint from every active
       lane's owned paths (no equal, prefix-of, or prefixed-by). A collision
       raises :class:`PathOwnershipError` naming the conflicting lane.
    3. **Worktree uniqueness.** The worktree fingerprint must not match an
       active lane's fingerprint (one worktree, one lane).
    4. **Lane-id uniqueness.** No active lane may already carry ``lane_id``.

    On success the new entry (status ``active``) is appended to
    ``ledger.lanes`` and returned. The ledger is mutated in place; persist it
    with :func:`save_ledger`.

    Parameters
    ----------
    ledger:
        The ledger to acquire into.
    wp_id:
        Work-package identifier for the lane.
    executor:
        The :class:`Executor` (or its string value) entitled to run the lane.
    worktree_path:
        Absolute path to the lane's git worktree. Fingerprinted; never
        persisted raw.
    branch, base_sha:
        Git identity of the lane.
    owned_paths:
        Repo-relative paths the lane is authorized to mutate.
    lane_id:
        Stable identifier for the lane.
    now:
        ISO-8601 ``Z`` timestamp used for both acquire and the first
        heartbeat.
    policy:
        Either a loaded policy dict, or a path to ``policy.json`` (loaded via
        :func:`srl.autonomy.policy.load_policy`).
    ttl_seconds:
        Lease TTL. Defaults to :data:`DEFAULT_LEASE_TTL_SECONDS`.
    """
    # Resolve the cap from the policy, the single source of the bound.
    if isinstance(policy, Mapping):
        cap = policy_lane_cap(policy)
    else:
        try:
            loaded = load_policy(policy)
        except PolicyError as exc:
            msg = f"could not load policy for lane cap: {exc}"
            raise LaneError(msg) from exc
        cap = policy_lane_cap(loaded)

    executor_enum = Executor(executor) if not isinstance(executor, Executor) else executor
    owned_tuple = tuple(owned_paths)

    active = _active(ledger.lanes)

    # (1) Cap.
    if len(active) >= cap:
        msg = (
            f"lane cap reached: {len(active)} active lanes, cap is {cap} "
            f"(policy key {LANE_CAP_POLICY_KEY!r})"
        )
        raise LaneError(msg)

    # (2) Disjoint ownership.
    collision = _check_disjointness(owned_tuple, active)
    if collision is not None:
        _, err = collision
        raise err

    # (3) Worktree fingerprint uniqueness.
    fp = worktree_fingerprint(worktree_path)
    for entry in active:
        if entry.worktree_fingerprint == fp:
            msg = (
                f"worktree fingerprint already in use by active lane {entry.lane_id!r} "
                "(one worktree, one lane)"
            )
            raise LaneError(msg)

    # (4) Lane-id uniqueness among active lanes.
    for entry in active:
        if entry.lane_id == lane_id:
            msg = f"active lane with id {lane_id!r} already exists"
            raise LaneError(msg)

    entry = LaneEntry(
        lane_id=lane_id,
        wp_id=wp_id,
        executor=executor_enum,
        worktree_fingerprint=fp,
        branch=branch,
        base_sha=base_sha,
        owned_paths=owned_tuple,
        lease=Lease(acquired_utc=now, heartbeat_utc=now, ttl_seconds=ttl_seconds),
        status=LaneStatus.ACTIVE,
    )
    ledger.lanes.append(entry)
    return entry


def heartbeat(ledger: LaneLedger, lane_id: str, now: str) -> LaneEntry:
    """Refresh the heartbeat timestamp for ``lane_id``.

    Replaces the matched entry in place with an updated heartbeat. The lane
    must be active; a heartbeat on a non-active lane is a no-op contract
    violation (the lane has already been released or stopped).

    Raises
    ------
    LaneError
        If no active lane with ``lane_id`` exists.
    """
    for i, entry in enumerate(ledger.lanes):
        if entry.lane_id == lane_id and entry.status == LaneStatus.ACTIVE:
            updated = LaneEntry(
                lane_id=entry.lane_id,
                wp_id=entry.wp_id,
                executor=entry.executor,
                worktree_fingerprint=entry.worktree_fingerprint,
                branch=entry.branch,
                base_sha=entry.base_sha,
                owned_paths=entry.owned_paths,
                lease=Lease(
                    acquired_utc=entry.lease.acquired_utc,
                    heartbeat_utc=now,
                    ttl_seconds=entry.lease.ttl_seconds,
                ),
                status=entry.status,
            )
            ledger.lanes[i] = updated
            return updated
    msg = f"no active lane with id {lane_id!r} to heartbeat"
    raise LaneError(msg)


def release_lane(ledger: LaneLedger, lane_id: str, status: LaneStatus) -> LaneEntry:
    """Release ``lane_id`` into ``status`` (``parked`` or ``completed``).

    Idempotent: releasing an already-released lane with the same status is a
    no-op (returns the existing entry). Releasing into a different status
    than the current one updates the entry. ``status`` must be a release
    status (``parked`` or ``completed``); ``active`` is not admissible here
    (use :func:`heartbeat` to keep a lane active).

    Raises
    ------
    LaneError
        If ``status`` is not a release status, or the lane is not found.
    """
    if status not in _RELEASE_STATUSES:
        admissible = sorted(s.value for s in _RELEASE_STATUSES)
        msg = f"release status must be one of {admissible}, got {status!r}"
        raise LaneError(msg)
    for i, entry in enumerate(ledger.lanes):
        if entry.lane_id == lane_id:
            if entry.status == status:
                # Idempotent release: already in the target status.
                return entry
            updated = LaneEntry(
                lane_id=entry.lane_id,
                wp_id=entry.wp_id,
                executor=entry.executor,
                worktree_fingerprint=entry.worktree_fingerprint,
                branch=entry.branch,
                base_sha=entry.base_sha,
                owned_paths=entry.owned_paths,
                lease=entry.lease,
                status=status,
            )
            ledger.lanes[i] = updated
            return updated
    msg = f"no lane with id {lane_id!r} to release"
    raise LaneError(msg)


def expire_leases(
    ledger: LaneLedger, now: str, *, _fail_reason: str = ORPHAN_PROCESS_FAIL_REASON
) -> list[LaneEntry]:
    """Stop active lanes whose heartbeat is older than their TTL.

    Each active lane whose ``heartbeat_utc + ttl_seconds`` is in the past
    relative to ``now`` is transitioned to status ``stopped``. The
    ``_fail_reason`` (default ``ORPHAN_PROCESS_DETECTED``, documented in
    ``automation/fail-reasons.json``) records *why* the lane was stopped: a
    lane that stops heartbeating is treated as an orphaned process.

    Returns the list of lanes that were expired (empty if none). The ledger
    is mutated in place; persist it with :func:`save_ledger`.

    Notes
    -----
    Timestamp comparison is lexical over the ISO-8601 ``Z`` form, which is
    monotonic for the same format. ``now`` must be in the same format.
    """
    expired: list[LaneEntry] = []
    for i, entry in enumerate(ledger.lanes):
        if entry.status != LaneStatus.ACTIVE:
            continue
        ttl = entry.lease.ttl_seconds
        # Compute the deadline and compare to now. We add the TTL in seconds
        # to the heartbeat via datetime to stay robust to the lexical form.
        deadline = _add_seconds(entry.lease.heartbeat_utc, ttl)
        if _parse_utc(now) >= deadline:
            updated = LaneEntry(
                lane_id=entry.lane_id,
                wp_id=entry.wp_id,
                executor=entry.executor,
                worktree_fingerprint=entry.worktree_fingerprint,
                branch=entry.branch,
                base_sha=entry.base_sha,
                owned_paths=entry.owned_paths,
                lease=entry.lease,
                status=LaneStatus.STOPPED,
            )
            ledger.lanes[i] = updated
            expired.append(updated)
    return expired


# ---------------------------------------------------------------------------
# Timestamp helpers (kept local to avoid an intra-package dependency).
# ---------------------------------------------------------------------------


def _parse_utc(ts: str) -> _dt.datetime:
    """Parse an ISO-8601 ``Z`` timestamp to an aware datetime."""
    # Accept the trailing Z; fromisoformat handles +00:00 in 3.11+.
    cleaned = ts.rstrip("Z")
    try:
        dt = _dt.datetime.fromisoformat(cleaned)
    except ValueError as exc:
        msg = f"timestamp {ts!r} is not a valid ISO-8601 datetime: {exc}"
        raise LaneError(msg) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    return dt


def _add_seconds(ts: str, seconds: int) -> _dt.datetime:
    """Return ``ts`` advanced by ``seconds`` as an aware datetime."""
    return _parse_utc(ts) + _dt.timedelta(seconds=seconds)


__all__ = [
    "CONTRACT_INVALID_FAIL_REASON",
    "DEFAULT_LEASE_TTL_SECONDS",
    "LANE_CAP_POLICY_KEY",
    "LEDGER_SCHEMA_VERSION",
    "ORPHAN_PROCESS_FAIL_REASON",
    "Executor",
    "LaneEntry",
    "LaneError",
    "LaneLedger",
    "LaneStatus",
    "Lease",
    "PathOwnershipError",
    "acquire_lane",
    "expire_leases",
    "heartbeat",
    "load_ledger",
    "policy_lane_cap",
    "release_lane",
    "save_ledger",
    "worktree_fingerprint",
]
