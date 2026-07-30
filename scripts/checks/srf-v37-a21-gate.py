#!/usr/bin/env python3
"""V3.7 A21 disaster-recovery and chaos gate."""

from __future__ import annotations

import sys
import tempfile
from argparse import ArgumentParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.health.disaster_recovery import run_a21_disaster_recovery_drill  # noqa: E402


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="optional path for the generated A21 receipt")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="srl-a21-dr-chaos-") as tmp:
        receipt = run_a21_disaster_recovery_drill(
            repo_root=REPO_ROOT,
            drill_root=Path(tmp),
        )
    rendered = dumps(receipt)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(rendered)
    sys.stdout.buffer.write(rendered)
    sys.stdout.buffer.flush()
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
