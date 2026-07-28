"""Declared write-scope enforcement for autonomous work.

A work package declares the set of paths it is authorized to mutate (its
*owned* set). Before any write, the automation must call :func:`check_write`
with the target path and the owned set. The check refuses the write if the
target falls outside the owned set, or if the path tries to escape the repo
root via ``..`` traversal or an absolute path.

The guard is deliberately conservative:

- Paths are normalized with :class:`pathlib.PurePosixPath` so behavior is
  identical on POSIX and Windows runners (no ``\\`` separators, no drive
  letters).
- An absolute path is rejected outright. Autonomous work writes inside the
  repository, never to absolute filesystem locations.
- A path containing ``..`` that resolves *outside* the owned set is rejected.
  A leading ``..`` is always rejected, even if a hypothetical owned ancestor
  would contain it, because the pattern is a strong signal of an escape
  attempt.
- The check is a pure function over path strings. It performs no I/O and
  creates no files. The caller is responsible for the actual write, and must
  perform the check *before* the write so a refusal is pre-write.

The exception, :class:`ScopeViolation`, carries the typed fail reason
``CONTRACT_INVALID`` so the failure routes correctly through the resume and
fail-reason machinery.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Final

# The typed fail reason emitted by scope violations. Kept as a constant so the
# string lives in one place and the tests can assert against the symbol.
SCOPE_VIOLATION_FAIL_REASON: Final[str] = "CONTRACT_INVALID"


class ScopeViolation(ValueError):
    """Raised when a write target falls outside the declared owned set.

    Carries the offending ``path``, the ``owned`` set it was checked against,
    and the typed ``fail_reason`` (always ``CONTRACT_INVALID`` for scope
    violations). The fail reason lets a caller route the failure through the
    resume/fail-reason registry without re-deriving the class.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str,
        owned: frozenset[str],
        fail_reason: str = SCOPE_VIOLATION_FAIL_REASON,
    ) -> None:
        super().__init__(message)
        self.path: str = path
        self.owned: frozenset[str] = owned
        self.fail_reason: str = fail_reason


def _normalize(path: str) -> PurePosixPath:
    """Normalize a candidate write path to a POSIX relative path.

    Rejects absolute paths and any ``..`` segment outright. Autonomous work is
    relative to the repo root; an absolute path or a parent-traversal segment
    is an escape attempt regardless of whether some owned ancestor would
    technically contain the resolved target.

    Raises :class:`ScopeViolation` on rejection. Returns the cleaned
    :class:`pathlib.PurePosixPath` (collapsed, with no leading ``./``).
    """
    if path is None or not isinstance(path, str) or path == "":
        msg = "write path must be a non-empty string"
        raise ScopeViolation(msg, path=str(path), owned=frozenset())
    # Reject backslashes explicitly: a POSIX-only model treats them as literal
    # characters, which would silently mask a Windows-style escape attempt.
    if "\\" in path:
        msg = f"write path contains a backslash (non-portable): {path!r}"
        raise ScopeViolation(msg, path=path, owned=frozenset())
    candidate = PurePosixPath(path)
    # Absolute path (leading '/' on POSIX) is always an escape.
    if candidate.is_absolute():
        msg = f"write path is absolute (must be repo-relative): {path!r}"
        raise ScopeViolation(msg, path=path, owned=frozenset())
    # Any '..' segment is rejected, even mid-path. This is stricter than
    # pure containment, but autonomous writes never need parent traversal.
    parts = candidate.parts
    if ".." in parts:
        msg = f"write path contains '..' (traversal forbidden): {path!r}"
        raise ScopeViolation(msg, path=path, owned=frozenset())
    # Collapse any '.' segments and strip a leading './' for stable comparison.
    normalized = PurePosixPath(*[p for p in parts if p != "."])
    return normalized


def _normalize_owned(owned_paths: frozenset[str]) -> frozenset[PurePosixPath]:
    """Normalize the owned set the same way candidate paths are normalized.

    Owned entries are trusted to be valid repo-relative directories/files, so
    a malformed owned entry is a contract bug and raises. We do not allow
    owned entries to contain '..' or be absolute either: the owned set is the
    authority, and an escaping owned entry would silently widen scope.
    """
    out: set[PurePosixPath] = set()
    for entry in owned_paths:
        # Reuse _normalize so owned and candidate paths share one rule set.
        # An invalid owned entry raises ScopeViolation with an empty owned set
        # (it is a programmer error, not a runtime refusal).
        out.add(_normalize(entry))
    return frozenset(out)


def _is_within(candidate: PurePosixPath, owned: frozenset[PurePosixPath]) -> bool:
    """Return True iff ``candidate`` is ``owned`` or nested under an owned dir.

    A candidate equals an owned entry exactly, or its parts begin with the
    owned entry's parts (directory containment). ``PurePosixPath`` comparison
    is structural, so this is insensitive to trailing slashes or ``./``.
    """
    for anchor in owned:
        if candidate == anchor:
            return True
        # Directory containment: candidate must be longer and start with anchor.
        anchor_parts = anchor.parts
        cand_parts = candidate.parts
        if len(cand_parts) > len(anchor_parts) and cand_parts[: len(anchor_parts)] == anchor_parts:
            return True
    return False


def check_write(path: str, owned_paths: frozenset[str]) -> None:
    """Assert that ``path`` is within ``owned_paths``; raise otherwise.

    Parameters
    ----------
    path:
        Candidate repo-relative write target. Must be a non-empty POSIX-style
        relative path. Absolute paths and any path containing ``..`` are
        rejected as escapes.
    owned_paths:
        The declared owned set for the current work package. Each entry is a
        repo-relative path or directory prefix; a write anywhere under an
        owned directory is permitted.

    Raises
    ------
    ScopeViolation
        If ``path`` is malformed, escapes the repo root, or falls outside the
        owned set. The violation carries ``fail_reason='CONTRACT_INVALID'``.

    Notes
    -----
    This function is a pure check. It performs no I/O and creates no files.
    The caller must invoke it *before* the write so a refusal is pre-write.
    """
    owned_normalized = _normalize_owned(frozenset(owned_paths))
    candidate = _normalize(path)
    owned_for_error = frozenset(owned_paths)
    if not _is_within(candidate, owned_normalized):
        msg = f"write target {path!r} is outside the owned set {sorted(owned_for_error)}"
        raise ScopeViolation(
            msg,
            path=path,
            owned=owned_for_error,
            fail_reason=SCOPE_VIOLATION_FAIL_REASON,
        )
