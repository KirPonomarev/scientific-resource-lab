"""Safe archive extraction for SRL resource packs.

:func:`extract_pack` unpacks a tar or zip archive into a destination directory
while rejecting every path-escape and privilege-escalation trick that would
make the extracted tree unsafe to materialize:

- path traversal (``..``, absolute paths, or anything that resolves outside
  ``dest`` after extraction);
- symbolic links, hard links, and any special file type (FIFO, device, socket);
- setuid/setgid bits;
- executable bits on files that are not declared entrypoints.

Only regular files and directories are accepted. Permissions are normalized to
a deterministic, non-privileged mode: directories ``0o755``, regular files
``0o644``, and declared entrypoints ``0o755``.
"""

from __future__ import annotations

import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn

from srl.contracts.errors import ContractError
from srl.packs.manifest import PACK_INTEGRITY_FAILURE_REASON


class PackIntegrityError(ContractError):
    """Raised when an archive or extracted tree violates pack integrity rules.

    Carries the typed fail reason ``PACK_INTEGRITY_FAILURE``.
    """

    def __init__(self, message: str, *, fail_reason: str = PACK_INTEGRITY_FAILURE_REASON) -> None:
        super().__init__(message, fail_reason=fail_reason)


# Normalized permissions.
_DIR_MODE: Final[int] = 0o755
_FILE_MODE: Final[int] = 0o644
_ENTRYPOINT_MODE: Final[int] = 0o755

# Archive executable bits we care about (owner/group/other).
_EXEC_MASK: Final[int] = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
# Privilege-escalation bits.
_SUID_SGID_MASK: Final[int] = stat.S_ISUID | stat.S_ISGID

# Path constants.
_DRIVE_LETTER_LENGTH: Final[int] = 2

# Zip Unix file-type constants stored in the top 4 bits of the mode.
_ZIP_TYPE_SYMLINK: Final[int] = 0xA
_ZIP_TYPE_DIR: Final[int] = 0x4
_ZIP_TYPE_FILE: Final[int] = 0x8


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    """Result of a safe extraction."""

    dest: Path
    extracted_files: tuple[str, ...]
    extracted_dirs: tuple[str, ...]


def _reject(message: str) -> NoReturn:
    """Raise a typed integrity failure."""
    raise PackIntegrityError(message)


def _is_within_dest(member_path: Path, dest: Path) -> bool:
    """Return True iff ``member_path`` is inside ``dest`` after realpath resolution.

    Both paths are resolved to catch symlink-based escapes and ``..``
    normalization that may still land outside ``dest``.
    """
    try:
        resolved_member = member_path.resolve()
        resolved_dest = dest.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved_member == resolved_dest or resolved_dest in resolved_member.parents


def _relative_target(name: str, dest: Path) -> Path:
    """Return a safe destination path for archive member ``name``.

    Rejects absolute paths, ``..`` segments, and any name that escapes ``dest``
    via path-component tricks. The returned path is still under ``dest`` and
    has not yet been created on disk.
    """
    if name.startswith("/") or (name.startswith("\\") and len(name) > 1):
        _reject(f"archive contains absolute path: {name!r}")
    # Treat Windows drive letters as absolute (e.g. C:file).
    if len(name) >= _DRIVE_LETTER_LENGTH and name[1] == ":" and name[0].isalpha():
        _reject(f"archive contains absolute path with drive letter: {name!r}")
    # Split on both POSIX and Windows separators.
    parts = name.replace("\\", "/").split("/")
    # Filter out empty parts (leading/trailing slashes) and explicit current dir.
    clean = [p for p in parts if p not in {"", "."}]
    if any(p == ".." for p in clean):
        _reject(f"archive contains path traversal: {name!r}")
    if not clean:
        _reject(f"archive contains empty or all-dot path: {name!r}")
    return dest.joinpath(*clean)


def _check_archive_mode(
    raw_mode: int,
    rel_path: str,
    entrypoint_paths: frozenset[str],
) -> None:
    """Validate archive mode bits for a regular file or directory.

    Rejects setuid/setgid bits and executable bits on non-entrypoint files.
    """
    if raw_mode & _SUID_SGID_MASK:
        _reject(f"path {rel_path!r} has setuid/setgid bits ({oct(raw_mode & _SUID_SGID_MASK)})")
    if rel_path not in entrypoint_paths and (raw_mode & _EXEC_MASK):
        _reject(
            f"path {rel_path!r} has unexpected executable bits "
            f"({oct(raw_mode & _EXEC_MASK)}) and is not a declared entrypoint"
        )


def _normalize_file_mode(rel_path: str, entrypoint_paths: frozenset[str]) -> int:
    """Return the normalized on-disk mode for a regular file."""
    return _ENTRYPOINT_MODE if rel_path in entrypoint_paths else _FILE_MODE


def _extract_tar_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    dest: Path,
    entrypoint_paths: frozenset[str],
) -> str:
    """Extract one tar member safely and return its relative path.

    Raises :class:`PackIntegrityError` for any unsafe content.
    """
    rel_path = member.name.replace("\\", "/").lstrip("/")
    target = _relative_target(member.name, dest)

    if member.issym() or member.islnk():
        _reject(f"archive contains link at {rel_path!r}")
    if member.isfifo() or member.ischr() or member.isblk() or member.isdev():
        _reject(f"archive contains special device/fifo/socket at {rel_path!r}")
    if not (member.isreg() or member.isdir()):
        _reject(f"archive contains unsupported member type at {rel_path!r}")

    _check_archive_mode(member.mode, rel_path, entrypoint_paths)

    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        target.chmod(_DIR_MODE)
        return f"dir:{rel_path}"

    # Regular file.
    target.parent.mkdir(parents=True, exist_ok=True)
    source = tar.extractfile(member)
    if source is None:
        _reject(f"could not read regular file {rel_path!r} from archive")
    target.write_bytes(source.read())
    target.chmod(_normalize_file_mode(rel_path, entrypoint_paths))

    # Final escape check after the file exists on disk.
    if not _is_within_dest(target, dest):
        _reject(f"extracted path {rel_path!r} escaped destination after write")

    return f"file:{rel_path}"


def _extract_tar(
    archive_path: Path,
    dest: Path,
    entrypoint_paths: frozenset[str],
) -> ExtractionReport:
    """Safely extract a tar archive."""
    extracted_files: list[str] = []
    extracted_dirs: list[str] = []
    with tarfile.open(archive_path, "r:*") as tar:
        for member in tar.getmembers():
            result = _extract_tar_member(tar, member, dest, entrypoint_paths)
            if result.startswith("dir:"):
                extracted_dirs.append(result.removeprefix("dir:"))
            else:
                extracted_files.append(result.removeprefix("file:"))
    return ExtractionReport(
        dest=dest,
        extracted_files=tuple(sorted(extracted_files)),
        extracted_dirs=tuple(sorted(extracted_dirs)),
    )


def _zip_member_mode(info: zipfile.ZipInfo) -> int:
    """Return the Unix mode bits embedded in a ZipInfo, if present.

    The Unix mode lives in the high 16 bits of ``external_attr``.
    """
    return (info.external_attr >> 16) & 0xFFFF


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    """Return True if the zip entry is a symlink.

    The Unix file type is stored in the top 4 bits of the mode.
    """
    mode = _zip_member_mode(info)
    file_type = (mode >> 12) & 0xF
    return file_type == _ZIP_TYPE_SYMLINK


def _zip_member_is_special(info: zipfile.ZipInfo) -> bool:
    """Return True if the zip entry is anything other than a regular file or dir.

    A file type of 0 means no Unix mode was stored; we treat it as a regular
    file because most cross-platform zip files use that value.
    """
    mode = _zip_member_mode(info)
    file_type = (mode >> 12) & 0xF
    return file_type not in (0x0, _ZIP_TYPE_DIR, _ZIP_TYPE_FILE)


def _extract_zip(
    archive_path: Path,
    dest: Path,
    entrypoint_paths: frozenset[str],
) -> ExtractionReport:
    """Safely extract a zip archive."""
    extracted_files: list[str] = []
    extracted_dirs: list[str] = []
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            rel_path = info.filename.replace("\\", "/").rstrip("/")
            target = _relative_target(info.filename, dest)
            mode = _zip_member_mode(info)

            if _zip_member_is_symlink(info):
                _reject(f"archive contains symlink at {rel_path!r}")
            if _zip_member_is_special(info):
                _reject(f"archive contains special entry at {rel_path!r}")

            if info.is_dir() or info.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(_DIR_MODE)
                extracted_dirs.append(rel_path)
                continue

            _check_archive_mode(mode, rel_path, entrypoint_paths)

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info.filename))
            target.chmod(_normalize_file_mode(rel_path, entrypoint_paths))
            extracted_files.append(rel_path)

            if not _is_within_dest(target, dest):
                _reject(f"extracted path {rel_path!r} escaped destination after write")

    return ExtractionReport(
        dest=dest,
        extracted_files=tuple(sorted(extracted_files)),
        extracted_dirs=tuple(sorted(extracted_dirs)),
    )


def extract_pack(
    archive: str | Path,
    dest: str | Path,
    *,
    entrypoints: set[str] | frozenset[str] | None = None,
) -> ExtractionReport:
    """Extract ``archive`` into ``dest`` safely.

    Parameters
    ----------
    archive:
        Path to a tar, tar.gz, tar.bz2, tar.xz, or zip archive.
    dest:
        Destination directory. Created if it does not exist.
    entrypoints:
        Set of relative paths (POSIX-style) that are declared entrypoints and
        therefore permitted to carry executable bits. If ``None``, no file is
        allowed to have executable bits.

    Returns
    -------
    ExtractionReport
        Sorted lists of extracted files and directories.

    Raises
    ------
    PackIntegrityError
        With fail reason ``PACK_INTEGRITY_FAILURE`` on any unsafe archive
        content or post-write escape.
    """
    archive_path = Path(archive)
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    entrypoint_paths = frozenset(entrypoints) if entrypoints is not None else frozenset()

    if not archive_path.is_file():
        raise PackIntegrityError(f"archive not found: {archive_path}")

    if tarfile.is_tarfile(archive_path):
        return _extract_tar(archive_path, dest_path, entrypoint_paths)
    if zipfile.is_zipfile(archive_path):
        return _extract_zip(archive_path, dest_path, entrypoint_paths)

    raise PackIntegrityError(f"unsupported archive format for {archive_path}; expected tar or zip")


__all__ = [
    "PACK_INTEGRITY_FAILURE_REASON",
    "ExtractionReport",
    "PackIntegrityError",
    "extract_pack",
]
