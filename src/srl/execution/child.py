"""Fixed-module child entrypoint for the bounded runner (WP-D31).

The runner never shells out to an arbitrary path. It spawns a single, fixed
module — this one — via ``python -m srl.execution.child <adapter_id>
<input_file> <output_file>``. The child:

1. loads the adapter from the **static registry** in
   :mod:`srl.execution.entrypoints` by id (an unknown id exits with code 2,
   never reaching a handler);
2. reads the canonical-JSON input file the runner materialised in scratch;
3. validates the payload against the adapter's input schema;
4. runs the pure handler in-process (no network, no extra I/O);
5. validates the handler output against the adapter's output schema;
6. writes the result as canonical JSON to ``output_file``; and
7. exits ``0`` on success or ``2`` on any contract/handler failure.

Exit codes are the contract between child and runner:

- ``0`` — success, a canonical output file was written;
- ``2`` — a contract or handler failure (unknown adapter, schema mismatch,
  handler exception); no output file is trusted by the runner.

The child is standard library only and imports nothing from the scientific
contracts layer, so it runs in the minimal sandbox environment without
``jsonschema``. Canonical JSON is encoded with the same compact form used across
:mod:`srl.execution` (sorted keys, ``ensure_ascii=False``, ``allow_nan=False``,
one trailing newline).
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Final

from srl.execution.entrypoints import UnknownAdapterError, run_handler

# Canonical JSON separators and newline contract, mirroring the rest of the
# execution package so the child's output bytes match the runner's expectation.
_SEP: Final[tuple[str, str]] = (",", ":")
_NEWLINE: Final[str] = "\n"
_ENCODING: Final[str] = "utf-8"

# Exit codes (see module docstring).
_EXIT_OK: Final[int] = 0
_EXIT_CONTRACT: Final[int] = 2

# The exact positional argument count the child expects: adapter id, input
# file, output file. A wrong count is a contract failure (exit 2).
_EXPECTED_ARGC: Final[int] = 3


def _canonical_dump(obj: Any) -> bytes:
    """Return ``obj`` encoded as canonical JSON bytes with a trailing newline.

    Sorted keys, compact separators, UTF-8 passthrough, no ``NaN``/``Infinity``,
    one trailing newline — the SRL canonical line form used by the runner and
    the child so both sides agree on the output bytes.
    """
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=_SEP,
        ensure_ascii=False,
        allow_nan=False,
    )
    return (text + _NEWLINE).encode(_ENCODING)


def _read_input(path: Path) -> Any:
    """Read and decode the canonical-JSON input file at ``path``.

    ``parse_constant`` rejects ``NaN``/``Infinity`` at decode time so a
    non-finite value can never reach the handler. A read or parse failure is a
    contract failure (exit 2), surfaced to the runner as no-trusted-output.
    """
    raw = path.read_bytes()
    return json.loads(raw, parse_constant=_reject_constant)


def _reject_constant(name: str) -> Any:
    """``json.loads`` hook: reject ``NaN``/``Infinity`` constants."""
    msg = f"canonical JSON must not contain the constant {name!r}"
    raise ValueError(msg)


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as canonical JSON to ``path`` (truncating first)."""
    path.write_bytes(_canonical_dump(payload))


def run(adapter_id: str, input_file: str, output_file: str) -> int:
    """Run one adapter: read input, validate, run handler, write output.

    Returns the exit code (``0`` on success, ``2`` on any failure). All
    exceptions are caught and reported on stderr with a traceback, then mapped
    to exit code 2; the child never propagates an unhandled exception (the
    runner reads the exit code and stderr to classify the outcome).
    """
    try:
        payload = _read_input(Path(input_file))
        result = run_handler(adapter_id, payload)
        _write_output(Path(output_file), result)
    except UnknownAdapterError as exc:
        sys.stderr.write(f"child: contract failure: {exc}\n")
        return _EXIT_CONTRACT
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return _EXIT_CONTRACT
    return _EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """``python -m srl.execution.child`` entrypoint.

    Usage: ``python -m srl.execution.child <adapter_id> <input_file>
    <output_file>``. Validates the argument count, then delegates to
    :func:`run`. A bad invocation exits 2 (a contract failure), never 0.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != _EXPECTED_ARGC:
        sys.stderr.write(
            "usage: python -m srl.execution.child <adapter_id> <input_file> <output_file>\n"
        )
        return _EXIT_CONTRACT
    adapter_id, input_file, output_file = args
    return run(adapter_id, input_file, output_file)


if __name__ == "__main__":  # pragma: no cover  (exercised via subprocess)
    raise SystemExit(main())
