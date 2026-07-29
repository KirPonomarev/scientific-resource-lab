"""Filesystem-neutral SRF storage layout and quota checks.

S04 defines the project-owned storage shape without touching a real T7 volume:
an immutable cold-CAS namespace, mutable rebuildable work namespaces, quarantine,
and bounded restore-test roots. The code operates on an explicitly supplied root
so tests can prove behavior on fixture directories.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from srl.cas.store import LocalArtifactStore, StoreError

BYTES_PER_GIB: Final[int] = 1024**3
DEFAULT_SRF_ALLOCATION_GIB: Final[int] = 400
DEFAULT_MIN_FREE_RESERVE_GIB: Final[int] = 100

COLD_CAS_DIR: Final[str] = "cold-cas"
QUARANTINE_DIR: Final[str] = "quarantine"
RESTORE_TESTS_DIR: Final[str] = "restore-tests"
WORK_DIR: Final[str] = "work"
WORK_NAMESPACES: Final[tuple[str, ...]] = ("envs", "caches", "scratch", "spool", "indexes")

_COLD_MUTABLE_SUFFIXES: Final[tuple[str, ...]] = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".sqlite-wal",
    ".wal",
)


class StorageQuotaStatus(Enum):
    """Admission result for SRF storage capacity checks."""

    OK = "OK"
    WAIT_T7_BINDING = "WAIT_T7_BINDING"
    T7_QUOTA_EXCEEDED = "T7_QUOTA_EXCEEDED"


@dataclass(frozen=True)
class StorageQuotaDecision:
    """A deterministic storage capacity decision."""

    status: StorageQuotaStatus
    allocation_bytes: int
    min_free_reserve_bytes: int
    observed_used_bytes: int
    observed_free_bytes: int
    reason: str


class StorageLayoutError(StoreError):
    """Raised when the SRF storage layout violates the S04 contract."""


@dataclass(frozen=True)
class SrfStorageLayout:
    """SRF storage namespace rooted at an explicit fixture or target directory."""

    root: Path

    @classmethod
    def at(cls, root: str | Path) -> SrfStorageLayout:
        """Build a layout from an explicit root path."""
        root_path = Path(root)
        if str(root_path) == "":
            msg = "SrfStorageLayout requires an explicit non-empty root"
            raise StorageLayoutError(msg)
        return cls(root=root_path)

    @property
    def cold_cas(self) -> Path:
        """Immutable content-addressed namespace."""
        return self.root / COLD_CAS_DIR

    @property
    def work(self) -> Path:
        """Mutable rebuildable work namespace."""
        return self.root / WORK_DIR

    @property
    def quarantine(self) -> Path:
        """Untrusted or invalid artifacts; no execution."""
        return self.root / QUARANTINE_DIR

    @property
    def restore_tests(self) -> Path:
        """Bounded restore-drill targets."""
        return self.root / RESTORE_TESTS_DIR

    def work_path(self, namespace: str) -> Path:
        """Return a mutable work namespace path, rejecting unknown names."""
        if namespace not in WORK_NAMESPACES:
            valid = ", ".join(WORK_NAMESPACES)
            msg = f"unknown work namespace {namespace!r}; expected one of: {valid}"
            raise StorageLayoutError(msg)
        return self.work / namespace

    def initialize(self) -> None:
        """Create the deterministic SRF storage directory tree."""
        self.cold_cas.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)
        self.restore_tests.mkdir(parents=True, exist_ok=True)
        for namespace in WORK_NAMESPACES:
            self.work_path(namespace).mkdir(parents=True, exist_ok=True)

    def cold_store(self) -> LocalArtifactStore:
        """Return a content-addressed store rooted at ``cold-cas``."""
        self.initialize()
        return LocalArtifactStore(self.cold_cas)

    def assert_cold_cas_immutable(self) -> None:
        """Reject active DB/WAL-style mutable files inside cold CAS."""
        if not self.cold_cas.exists():
            return
        for path in sorted(self.cold_cas.rglob("*")):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            if lowered.endswith(_COLD_MUTABLE_SUFFIXES):
                msg = f"cold-cas contains mutable database/WAL artifact {path.name!r}"
                raise StorageLayoutError(msg)


def check_srf_storage_quota(
    *,
    observed_used_bytes: int,
    observed_free_bytes: int,
    allocation_gib: int = DEFAULT_SRF_ALLOCATION_GIB,
    min_free_reserve_gib: int = DEFAULT_MIN_FREE_RESERVE_GIB,
) -> StorageQuotaDecision:
    """Classify SRF storage capacity against allocation and free-reserve caps."""
    if observed_used_bytes < 0 or observed_free_bytes < 0:
        msg = "observed storage byte counts must be non-negative"
        raise StorageLayoutError(msg)
    allocation_bytes = allocation_gib * BYTES_PER_GIB
    reserve_bytes = min_free_reserve_gib * BYTES_PER_GIB
    if observed_used_bytes > allocation_bytes:
        return StorageQuotaDecision(
            status=StorageQuotaStatus.T7_QUOTA_EXCEEDED,
            allocation_bytes=allocation_bytes,
            min_free_reserve_bytes=reserve_bytes,
            observed_used_bytes=observed_used_bytes,
            observed_free_bytes=observed_free_bytes,
            reason="allocation_exceeded",
        )
    if observed_free_bytes < reserve_bytes:
        return StorageQuotaDecision(
            status=StorageQuotaStatus.WAIT_T7_BINDING,
            allocation_bytes=allocation_bytes,
            min_free_reserve_bytes=reserve_bytes,
            observed_used_bytes=observed_used_bytes,
            observed_free_bytes=observed_free_bytes,
            reason="free_reserve_below_minimum",
        )
    return StorageQuotaDecision(
        status=StorageQuotaStatus.OK,
        allocation_bytes=allocation_bytes,
        min_free_reserve_bytes=reserve_bytes,
        observed_used_bytes=observed_used_bytes,
        observed_free_bytes=observed_free_bytes,
        reason="ok",
    )


__all__ = [
    "BYTES_PER_GIB",
    "COLD_CAS_DIR",
    "DEFAULT_MIN_FREE_RESERVE_GIB",
    "DEFAULT_SRF_ALLOCATION_GIB",
    "QUARANTINE_DIR",
    "RESTORE_TESTS_DIR",
    "WORK_DIR",
    "WORK_NAMESPACES",
    "SrfStorageLayout",
    "StorageLayoutError",
    "StorageQuotaDecision",
    "StorageQuotaStatus",
    "check_srf_storage_quota",
]
