#!/usr/bin/env python3
"""WP-C22 acceptance gate for pack manifest and safe materialization.

Runs the six WP-C22 checks, prints a single canonical ``GateReceipt/v1`` JSON
line to stdout, and exits 0 only if every check PASSes. The gate exercises the
pack manifest validator, safe archive extraction, platform matching, and the
materialization bridge on a set of runtime-generated fixtures.

Checks
------
C22-01 traversal/symlink/hardlink/device/setuid rejected
    Each malicious archive raises ``PackIntegrityError`` with fail reason
    ``PACK_INTEGRITY_FAILURE`` before any unsafe content is materialized.

C22-02 unexpected executable rejected
    A non-entrypoint file with executable bits is rejected during extraction.

C22-03 wrong ABI/platform rejected
    A manifest whose platform list does not include the current platform raises
    ``PlatformError`` with fail reason ``PLATFORM_UNSUPPORTED``.

C22-04 GPL/unknown license rejected
    A GPL-licensed manifest raises ``LicenseError`` with
    ``LICENSE_INCOMPATIBLE``; an unrecognized license raises ``LicenseError``
    with ``LICENSE_UNKNOWN``.

C22-05 tree hash mismatch after copy rejected
    Materializing a pack whose post-copy tree hash differs from the manifest
    (e.g., a pack containing a symlink that the pre-copy hash ignores but the
    copy materializes) raises ``MaterializationError`` with
    ``PACK_INTEGRITY_FAILURE``.

C22-06 immutable-store execution refused
    Materializing from a pack root that is marked immutable by a
    ``.srl_immutable`` flag file raises ``MaterializationError`` with
    ``PACK_INTEGRITY_FAILURE`` and the note "mutable T7 execution forbidden".
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# Make the in-repo srl package and the fixture generator importable when run as a
# bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp22-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_FIXTURES_DIR = _REPO_ROOT / "fixtures" / "conformance" / "packs"
if str(_FIXTURES_DIR) not in sys.path:
    sys.path.insert(0, str(_FIXTURES_DIR))

import make_fixtures  # noqa: E402

from srl.contracts import dumps  # noqa: E402
from srl.packs import (  # noqa: E402
    LICENSE_INCOMPATIBLE_REASON,
    LICENSE_UNKNOWN_REASON,
    PLATFORM_UNSUPPORTED_REASON,
    LicenseError,
    MaterializationError,
    PackIntegrityError,
    PlatformError,
    build_manifest,
    check_manifest_platform,
    compute_tree_sha256,
    current_platform,
    extract_pack,
    materialize,
)
from srl.packs.manifest import PACK_INTEGRITY_FAILURE_REASON  # noqa: E402

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-C22"


# Short aliases for the fail reasons used in assertions below.
LICENSE_INCOMPATIBLE: Final[str] = LICENSE_INCOMPATIBLE_REASON
LICENSE_UNKNOWN: Final[str] = LICENSE_UNKNOWN_REASON
PACK_INTEGRITY_FAILURE: Final[str] = PACK_INTEGRITY_FAILURE_REASON
PLATFORM_UNSUPPORTED: Final[str] = PLATFORM_UNSUPPORTED_REASON


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_manifest(path: Path) -> dict[str, Any]:
    """Load a JSON manifest dict from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# C22-01: traversal/symlink/hardlink/device/setuid rejected.
# ---------------------------------------------------------------------------


def _check_c22_01(fixtures: Any, tmp: Path) -> dict[str, Any]:
    """C22-01: each malicious archive raises PACK_INTEGRITY_FAILURE."""
    cases: list[dict[str, Any]] = []
    malicious_archives = [
        ("traversal", fixtures.traversal_tar),
        ("symlink", fixtures.symlink_tar),
        ("hardlink", fixtures.hardlink_tar),
        ("device", fixtures.device_tar),
        ("setuid", fixtures.setuid_tar),
    ]
    for name, archive in malicious_archives:
        dest = tmp / f"c22_01_{name}"
        try:
            extract_pack(archive, dest)
            cases.append({"case": name, "pass": False, "reason": "no exception raised"})
        except PackIntegrityError as exc:
            cases.append({"case": name, "pass": exc.fail_reason == PACK_INTEGRITY_FAILURE})
        except Exception as exc:
            reason = f"unexpected {type(exc).__name__}: {exc}"
            cases.append({"case": name, "pass": False, "reason": reason})

    failures = [c["case"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"malicious archive checks failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "traversal, symlink, hardlink, device, and setuid archives all raised "
            "PACK_INTEGRITY_FAILURE"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C22-02: unexpected executable bit rejected.
# ---------------------------------------------------------------------------


def _check_c22_02(fixtures: Any, tmp: Path) -> dict[str, Any]:
    """C22-02: a non-entrypoint file with executable bits is rejected."""
    dest = tmp / "c22_02"
    try:
        extract_pack(fixtures.stray_exec_tar, dest)
        return {"status": "FAIL", "detail": "stray executable archive was accepted"}
    except PackIntegrityError as exc:
        if exc.fail_reason == PACK_INTEGRITY_FAILURE:
            return {
                "status": "PASS",
                "detail": "non-entrypoint executable bit rejected with PACK_INTEGRITY_FAILURE",
            }
        return {
            "status": "FAIL",
            "detail": f"stray executable rejected with wrong fail_reason: {exc.fail_reason!r}",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# C22-03: wrong ABI/platform rejected.
# ---------------------------------------------------------------------------


def _check_c22_03(fixtures: Any) -> dict[str, Any]:
    """C22-03: a manifest with no matching platform raises PLATFORM_UNSUPPORTED."""
    manifest = _load_manifest(fixtures.manifest_wrong_platform)
    current = current_platform()
    try:
        check_manifest_platform(manifest, current)
        return {"status": "FAIL", "detail": "wrong-platform manifest was accepted"}
    except PlatformError as exc:
        if exc.fail_reason == PLATFORM_UNSUPPORTED:
            return {
                "status": "PASS",
                "detail": (
                    f"wrong-platform manifest rejected for {current!r} with PLATFORM_UNSUPPORTED"
                ),
            }
        return {
            "status": "FAIL",
            "detail": (
                f"wrong-platform manifest rejected with wrong fail_reason: {exc.fail_reason!r}"
            ),
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# C22-04: GPL license -> LICENSE_INCOMPATIBLE, unknown -> LICENSE_UNKNOWN.
# ---------------------------------------------------------------------------


def _check_c22_04(fixtures: Any) -> dict[str, Any]:
    """C22-04: license policy enforcement for GPL and unknown licenses."""
    cases: list[dict[str, Any]] = []
    for name, expected_reason in (
        ("gpl", LICENSE_INCOMPATIBLE),
        ("unknown", LICENSE_UNKNOWN),
    ):
        manifest = _load_manifest(getattr(fixtures, f"manifest_{name}"))
        try:
            build_manifest(manifest)
            cases.append({"case": name, "pass": False, "reason": "no exception raised"})
        except LicenseError as exc:
            cases.append({"case": name, "pass": exc.fail_reason == expected_reason})
        except Exception as exc:
            cases.append(
                {
                    "case": name,
                    "pass": False,
                    "reason": f"unexpected {type(exc).__name__}: {exc}",
                }
            )

    failures = [c["case"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"license policy checks failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": "GPL license rejected as LICENSE_INCOMPATIBLE, unknown as LICENSE_UNKNOWN",
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# C22-05: tree hash mismatch after copy rejected.
# ---------------------------------------------------------------------------


def _build_sneaky_symlink_pack(tmp: Path, fixtures: Any) -> tuple[Path, dict[str, Any]]:
    """Build a pack whose pre-copy hash ignores a symlink but copy materializes it.

    ``compute_tree_sha256`` skips symlinks (only regular files are hashed), but
    ``materialize`` copies symlinks as regular files. The manifest tree hash is
    correct for the pre-copy state, so the pre-copy check passes and the post-copy
    check fails.
    """
    pack_dir = tmp / "sneaky_pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "real.txt").write_text("hello", encoding="utf-8")
    (pack_dir / "link.txt").symlink_to(pack_dir / "real.txt")
    tree = compute_tree_sha256(pack_dir)
    manifest = _load_manifest(fixtures.manifest_valid)
    manifest["tree_sha256"] = tree
    return pack_dir, manifest


def _check_c22_05(tmp: Path, fixtures: Any) -> dict[str, Any]:
    """C22-05: a post-copy tree hash mismatch raises PACK_INTEGRITY_FAILURE."""
    pack_dir, manifest = _build_sneaky_symlink_pack(tmp, fixtures)
    staging = tmp / "sneaky_staging"
    try:
        materialize(manifest, pack_dir, staging)
        return {"status": "FAIL", "detail": "sneaky symlink pack materialized without error"}
    except MaterializationError as exc:
        if exc.fail_reason == PACK_INTEGRITY_FAILURE:
            return {
                "status": "PASS",
                "detail": "post-copy tree hash mismatch rejected with PACK_INTEGRITY_FAILURE",
            }
        return {
            "status": "FAIL",
            "detail": f"mismatch rejected with wrong fail_reason: {exc.fail_reason!r}",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# C22-06: immutable-store execution refused.
# ---------------------------------------------------------------------------


def _check_c22_06(fixtures: Any, tmp: Path) -> dict[str, Any]:
    """C22-06: materializing from an immutable store root is refused."""
    immutable_root = tmp / "immutable_store"
    immutable_root.mkdir(parents=True, exist_ok=True)
    pack_dir = immutable_root / "packs" / "test_pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "run.py").write_text("# runtime", encoding="utf-8")
    (immutable_root / ".srl_immutable").write_text("", encoding="utf-8")

    manifest = _load_manifest(fixtures.manifest_valid)
    manifest["tree_sha256"] = compute_tree_sha256(pack_dir)
    staging = tmp / "c22_06_staging"

    try:
        materialize(manifest, pack_dir, staging)
        return {"status": "FAIL", "detail": "immutable store pack materialized without error"}
    except MaterializationError as exc:
        forbidden = "mutable T7 execution forbidden" in str(exc)
        if exc.fail_reason == PACK_INTEGRITY_FAILURE and forbidden:
            return {
                "status": "PASS",
                "detail": "immutable store execution refused with PACK_INTEGRITY_FAILURE",
            }
        return {
            "status": "FAIL",
            "detail": f"immutable store refusal raised wrong error: {exc!r}",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "detail": f"unexpected exception: {type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Generate fixtures, run all six checks, and assemble the receipt."""
    with tempfile.TemporaryDirectory(prefix="wp22_gate_") as tmpdir:
        tmp = Path(tmpdir)
        fixtures = make_fixtures.make_all_fixtures(tmp / "fixtures")
        checks = {
            "C22-01": _check_c22_01(fixtures, tmp),
            "C22-02": _check_c22_02(fixtures, tmp),
            "C22-03": _check_c22_03(fixtures),
            "C22-04": _check_c22_04(fixtures),
            "C22-05": _check_c22_05(tmp, fixtures),
            "C22-06": _check_c22_06(fixtures, tmp),
        }

    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            "current_platform": current_platform(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    if args and args[0] == "--check":
        # Single-check mode is not implemented for C22 because the gate
        # generates fixtures as a whole; re-run the whole receipt for now.
        receipt = _build_receipt()
        _emit(receipt)
        return 0 if receipt["overall"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
