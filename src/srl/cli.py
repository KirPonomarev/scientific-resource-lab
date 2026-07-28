"""JSON-first command-line dispatcher for SRL.

This module is deliberately free of third-party dependencies and of
:mod:`argparse`. The dispatcher is a small, explicit table so that the CLI
contract is auditable: every command produces canonical JSON on stdout (see
:mod:`srl.canonical`) and a deterministic exit code.

Contracts
---------
- ``srlab doctor``
      Prints ``DoctorReport/v1`` and exits 0.
- ``srlab version``
      Prints ``VersionReport/v1`` and exits 0.
- any other (or missing) command
      Prints ``ErrorReport/v1`` on stdout and exits 2.

Exit code 0 means the operation completed and a receipt was emitted; it never
means a scientific claim is supported (see README.md).
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable
from typing import Any, Final

from srl import __version__
from srl.canonical import canonical_json_line

# Exit codes. Named to avoid magic-value lint and to document intent.
EXIT_OK: Final[int] = 0
EXIT_USAGE: Final[int] = 2

# Schema versions emitted by this dispatcher. Bumped only on a contract change.
DOCTOR_SCHEMA: Final[str] = "DoctorReport/v1"
VERSION_SCHEMA: Final[str] = "VersionReport/v1"
ERROR_SCHEMA: Final[str] = "ErrorReport/v1"


def _doctor_report() -> dict[str, Any]:
    """Build the ``DoctorReport/v1`` payload describing the runtime."""
    return {
        "schema_version": DOCTOR_SCHEMA,
        "srl_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "status": "ok",
    }


def _version_report() -> dict[str, Any]:
    """Build the ``VersionReport/v1`` payload."""
    return {
        "schema_version": VERSION_SCHEMA,
        "srl_version": __version__,
    }


def _error_report(command: str, message: str) -> dict[str, Any]:
    """Build the ``ErrorReport/v1`` payload for a failed dispatch."""
    return {
        "schema_version": ERROR_SCHEMA,
        "error": message,
        "command": command,
    }


def _emit(report: dict[str, Any]) -> None:
    """Write one canonical JSON record (with trailing newline) to stdout."""
    _ = sys.stdout.write(canonical_json_line(report))


# Dispatch table: command name -> (builder, exit code).
# ``Any`` builder return is the report dict; kept as Callable for clarity.
_DISPATCH: Final[dict[str, Callable[[], dict[str, Any]]]] = {
    "doctor": _doctor_report,
    "version": _version_report,
}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI dispatcher and return an exit code.

    Parameters
    ----------
    argv:
        Optional argument vector excluding the program name. When ``None`` the
        real :data:`sys.argv` is used (minus the program name). Extra arguments
        after a recognized command are ignored to keep the contract minimal.

    Returns
    -------
    int
        :data:`EXIT_OK` for a recognized command, :data:`EXIT_USAGE` for an
        unknown or missing command.
    """
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else ""

    builder = _DISPATCH.get(command)
    if builder is None:
        message = "missing command" if command == "" else "unknown command"
        _emit(_error_report(command, message))
        return EXIT_USAGE

    _emit(builder())
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
