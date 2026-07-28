"""Unit tests for the SRL CLI dispatcher.

The CLI is JSON-first: every path emits canonical JSON on stdout with a
deterministic exit code. These tests pin that contract without invoking a
subprocess, by calling :func:`srl.cli.main` directly against a captured stdout.
"""

from __future__ import annotations

import json
import sys

import pytest

from srl import __version__
from srl.cli import EXIT_OK, EXIT_USAGE, main

# Canonical exit codes reused across cases.
_DOCTOR_REQUIRED_KEYS = {"schema_version", "srl_version", "python", "platform", "status"}


@pytest.fixture()
def captured_stdout(capsys: pytest.CaptureFixture[str]) -> object:
    """Provide the pytest capsys fixture under a descriptive local name.

    This is a thin alias so test bodies read as "capture stdout" rather than
    "the capsys contract". It returns the fixture unchanged.
    """

    return capsys


def _parse_stdout(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    """Parse the single canonical JSON line written to stdout into a dict."""
    captured = capsys.readouterr()
    # Exactly one line, terminated by a newline.
    lines = captured.out.splitlines()
    assert len(lines) == 1, f"expected one JSON line, got {lines!r}"
    return json.loads(lines[0])


def test_doctor_emits_valid_json_status_ok(
    captured_stdout: pytest.CaptureFixture[str],
) -> None:
    """``doctor`` emits one canonical JSON line with all required keys and ok status."""
    capsys = captured_stdout
    code = main(["doctor"])

    assert code == EXIT_OK
    report = _parse_stdout(capsys)

    assert isinstance(report, dict)
    assert set(report) >= _DOCTOR_REQUIRED_KEYS
    assert report["schema_version"] == "DoctorReport/v1"
    assert report["status"] == "ok"
    assert report["srl_version"] == __version__
    # python field must match the running interpreter (deterministic for the env).
    assert report["python"] == sys.version.split()[0]
    # platform is a non-empty string.
    assert isinstance(report["platform"], str) and report["platform"]


def test_version_exits_zero(captured_stdout: pytest.CaptureFixture[str]) -> None:
    """``version`` exits 0 and reports the package version."""
    capsys = captured_stdout
    code = main(["version"])

    assert code == EXIT_OK
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "VersionReport/v1"
    assert report["srl_version"] == __version__


def test_unknown_command_exits_two_with_json_error(
    captured_stdout: pytest.CaptureFixture[str],
) -> None:
    """An unknown command exits 2 and emits an ``ErrorReport/v1`` JSON object."""
    capsys = captured_stdout
    code = main(["nope"])

    assert code == EXIT_USAGE
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["error"] == "unknown command"
    assert report["command"] == "nope"


def test_missing_command_exits_two_with_json_error(
    captured_stdout: pytest.CaptureFixture[str],
) -> None:
    """No command at all exits 2 with a ``missing command`` error."""
    capsys = captured_stdout
    code = main([])

    assert code == EXIT_USAGE
    report = _parse_stdout(capsys)
    assert report["schema_version"] == "ErrorReport/v1"
    assert report["error"] == "missing command"
    assert report["command"] == ""


def test_doctor_output_is_canonical(captured_stdout: pytest.CaptureFixture[str]) -> None:
    """``doctor`` output is canonical: sorted keys, compact separators, one line.

    This guards the byte-stable contract: two independent runs must produce
    identical bytes for equal data.
    """
    capsys = captured_stdout
    _ = main(["doctor"])
    raw = capsys.readouterr().out

    # Canonical: compact (no spaces after ',' or ':'), single trailing newline.
    assert raw.endswith("\n")
    body = raw[:-1]
    assert ", " not in body
    assert ": " not in body

    # Re-serializing the parsed object must reproduce the same bytes (canonical
    # round-trip).
    parsed = json.loads(body)
    assert body == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
