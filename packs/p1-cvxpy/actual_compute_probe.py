#!/usr/bin/env python3
"""Actual-compute probe for the p1-cvxpy pack.

Runs a tiny bounded ridge regression and prints a canonical JSON line with the
SolveResult.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.packs.adapters.cvxpy_adapter import solve  # noqa: E402


def main() -> int:
    """Run a bounded ridge solve and print a canonical result line."""
    spec = {
        "problem_type": "ridge",
        "A": [
            [1, 1],
            [1, 2],
            [1, 3],
        ],
        "b": [1, 2, 3],
        "lambda": 0.1,
    }
    result = solve(spec)
    sys.stdout.buffer.write(dumps(result.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
