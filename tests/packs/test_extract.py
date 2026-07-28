"""Tests for :mod:`srl.packs.extract`.

Tests use the runtime-generated malicious archives and assert that each unsafe
content pattern is rejected with ``PACK_INTEGRITY_FAILURE``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest

from srl.packs import (
    PACK_INTEGRITY_FAILURE_REASON,
    ExtractionReport,
    PackIntegrityError,
    extract_pack,
)


def test_extract_valid_tar(make_fixtures: Any, tmp_path: Path) -> None:
    """A benign archive extracts all expected files and directories."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    dest = tmp_path / "dest"
    entrypoints = {"run.py", "compute.py"}
    report = extract_pack(fixtures.valid_tar, dest, entrypoints=entrypoints)
    assert isinstance(report, ExtractionReport)
    assert report.dest == dest
    assert "run.py" in report.extracted_files
    assert "compute.py" in report.extracted_files
    assert "data/parameters.json" in report.extracted_files
    assert (dest / "data").is_dir()
    # Entrypoints get executable bits.
    assert (dest / "run.py").stat().st_mode & 0o111
    # Non-entrypoints do not.
    assert not ((dest / "data" / "parameters.json").stat().st_mode & 0o111)


@pytest.mark.parametrize(
    "archive_attr",
    [
        "traversal_tar",
        "symlink_tar",
        "hardlink_tar",
        "device_tar",
        "setuid_tar",
    ],
)
def test_malicious_archives_rejected(
    archive_attr: str,
    make_fixtures: Any,
    tmp_path: Path,
) -> None:
    """Traversal, symlink, hardlink, device, and setuid archives are rejected."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    archive = getattr(fixtures, archive_attr)
    dest = tmp_path / "dest"
    with pytest.raises(PackIntegrityError) as exc_info:
        extract_pack(archive, dest)
    assert exc_info.value.fail_reason == PACK_INTEGRITY_FAILURE_REASON


def test_stray_executable_rejected(make_fixtures: Any, tmp_path: Path) -> None:
    """A non-entrypoint file with executable bits is rejected."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    dest = tmp_path / "dest"
    with pytest.raises(PackIntegrityError) as exc_info:
        extract_pack(fixtures.stray_exec_tar, dest)
    assert exc_info.value.fail_reason == PACK_INTEGRITY_FAILURE_REASON


def test_declared_entrypoint_executable_allowed(make_fixtures: Any, tmp_path: Path) -> None:
    """A declared entrypoint with executable bits is accepted and normalized."""
    fixtures = make_fixtures.make_all_fixtures(tmp_path / "fixtures")
    dest = tmp_path / "dest"
    report = extract_pack(fixtures.stray_exec_tar, dest, entrypoints={"not_an_entrypoint.sh"})
    assert "not_an_entrypoint.sh" in report.extracted_files


def test_extract_zip_archive(tmp_path: Path) -> None:
    """A zip archive is also handled by the safe extractor."""
    archive = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("hello.txt", b"world")
    dest = tmp_path / "dest"
    report = extract_pack(archive, dest)
    assert "hello.txt" in report.extracted_files
    assert (dest / "hello.txt").read_bytes() == b"world"
