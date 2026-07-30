#!/usr/bin/env python3
"""V3.7 A22 final acceptance and v2.0.0 false-closure gate."""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.health.final_acceptance import (  # noqa: E402
    A22_TERMINAL_STATE,
    build_a22_final_acceptance_receipt,
    build_a22_operator_action,
)


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="optional path for the generated A22 receipt")
    parser.add_argument(
        "--operator-action-out",
        type=Path,
        help="optional path for the generated A22 operator action",
    )
    parser.add_argument(
        "--mission-closeout-out",
        type=Path,
        help="optional path for the generated blocked mission closeout receipt",
    )
    args = parser.parse_args()
    receipt = build_a22_final_acceptance_receipt(repo_root=REPO_ROOT)
    rendered = dumps(receipt)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(rendered)
    if args.operator_action_out is not None:
        args.operator_action_out.parent.mkdir(parents=True, exist_ok=True)
        args.operator_action_out.write_bytes(dumps(build_a22_operator_action()))
    if args.mission_closeout_out is not None:
        args.mission_closeout_out.parent.mkdir(parents=True, exist_ok=True)
        args.mission_closeout_out.write_bytes(dumps(receipt["mission_closeout_receipt"]))
    sys.stdout.buffer.write(rendered)
    sys.stdout.buffer.flush()
    return (
        0 if receipt["result"] == "PASS" and receipt["terminal_state"] == A22_TERMINAL_STATE else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
