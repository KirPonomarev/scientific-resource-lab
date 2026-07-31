#!/usr/bin/env python3
"""Bind/probe the V3.7 A04 production Ed25519 keyring.

This script may create a private Ed25519 key outside the repository only when
``--create-missing`` is passed. It never accepts private key bytes in argv/env
and writes only a public, secret-free receipt to stdout or ``--out``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srl.contracts import dumps  # noqa: E402
from srl.transport.native_keyring import (  # noqa: E402
    build_production_key_binding_receipt,
    default_native_key_dir,
    probe_private_file_keyring,
)

DEFAULT_RECEIPT_PATH = (
    REPO_ROOT / "docs" / "verification" / "srf-v3-7-a04-production-key-binding-receipt.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="create the private production key if absent",
    )
    parser.add_argument(
        "--key-dir",
        type=Path,
        default=default_native_key_dir(),
        help="out-of-repository native private key directory",
    )
    parser.add_argument(
        "--authority-directive-id",
        default="SRF_PHYSICAL_ACTIVATION_V2_OWNER_DIRECTIVE_2026_07_30",
        help="public directive id; never a secret",
    )
    parser.add_argument("--out", type=Path, help="write receipt JSON to this path")
    args = parser.parse_args()

    probe = probe_private_file_keyring(
        key_dir=args.key_dir,
        create_missing=args.create_missing,
        authority_directive_present=True,
    )
    receipt = build_production_key_binding_receipt(
        probe=probe,
        authority_directive_id=args.authority_directive_id,
    )
    payload = dumps(receipt)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(payload)
    else:
        sys.stdout.buffer.write(payload)
    return 0 if receipt["status"] == "ACTIVE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
