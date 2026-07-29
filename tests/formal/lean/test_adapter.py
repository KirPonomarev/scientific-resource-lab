from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from srl.packs.formal.lean import (
    LeanAdmissionStatus,
    LeanProofStatus,
    build_lean_admission_bundle,
    check_lean_source,
    default_lean_pins,
    discover_lean_environment,
)


def test_default_pins_bind_stable_lean_and_mathlib() -> None:
    pins = default_lean_pins()

    assert pins.toolchain == "leanprover/lean4:v4.32.2"
    assert pins.lean_version == "4.32.2"
    assert pins.mathlib_tag == "v4.32.2"
    assert pins.mathlib_revision == "905b95818eb32af7874a58b427f50c1711a5e96c"


def test_missing_toolchain_waits_without_authority() -> None:
    env = discover_lean_environment(lean_executable="/definitely/missing/lean")

    assert env.status is LeanAdmissionStatus.WAIT_TOOLCHAIN
    assert env.to_dict()["canonical_writes"] == 0
    assert env.to_dict()["grants_authority"] is False


def test_version_skew_waits(tmp_path: Path) -> None:
    lean = _write_tool(tmp_path / "lean", "Lean (version 4.31.0, commit bad)")
    lake = _write_tool(tmp_path / "lake", "Lake version 5.0.0-src+bad")

    env = discover_lean_environment(lean_executable=str(lean), lake_executable=str(lake))

    assert env.status is LeanAdmissionStatus.WAIT_TOOLCHAIN
    assert env.reason == "lean_version_mismatch"


def test_checked_proof_receipt_is_authority_negative(tmp_path: Path) -> None:
    lean = _write_fake_lean(tmp_path / "lean")
    lake = _write_tool(tmp_path / "lake", "Lake version 5.0.0-src+f3b06c7 (Lean version 4.32.2)")

    receipt = check_lean_source(
        "theorem ok : True := by trivial\n",
        theorem_name="ok",
        lean_executable=str(lean),
        lake_executable=str(lake),
    )

    assert receipt["status"] == LeanProofStatus.CHECKED.value
    assert receipt["formal_check"] == "checked"
    assert receipt["formal_certificate_ref"] is None
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_rejected_proof_does_not_become_checked(tmp_path: Path) -> None:
    lean = _write_fake_lean(tmp_path / "lean")
    lake = _write_tool(tmp_path / "lake", "Lake version 5.0.0-src+f3b06c7 (Lean version 4.32.2)")

    receipt = check_lean_source(
        "theorem bad : False := by trivial\n",
        theorem_name="bad",
        lean_executable=str(lean),
        lake_executable=str(lake),
    )

    assert receipt["status"] == LeanProofStatus.REJECTED.value
    assert receipt["formal_check"] == "unchecked"
    assert "unsolved goals" in cast(str, receipt["stderr_preview"])


def test_admission_bundle_requires_mathlib_smoke() -> None:
    pins = default_lean_pins()
    env = discover_lean_environment(
        lean_executable=None,
        lake_executable=None,
        pins=pins,
    )
    bundle = build_lean_admission_bundle(pins=pins, environment=env)

    assert bundle["status"] == LeanAdmissionStatus.WAIT_TOOLCHAIN.value
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


def test_admission_bundle_active_with_checked_smoke(tmp_path: Path) -> None:
    lean = _write_fake_lean(tmp_path / "lean")
    lake = _write_tool(tmp_path / "lake", "Lake version 5.0.0-src+f3b06c7 (Lean version 4.32.2)")
    env = discover_lean_environment(lean_executable=str(lean), lake_executable=str(lake))
    smoke = check_lean_source(
        "theorem ok : True := by trivial\n",
        theorem_name="ok",
        lean_executable=str(lean),
        lake_executable=str(lake),
    )

    bundle = build_lean_admission_bundle(environment=env, mathlib_smoke_receipt=smoke)

    assert bundle["status"] == LeanAdmissionStatus.ACTIVE.value
    assert bundle["reason"] == "lean_kernel_and_pinned_mathlib_smoke_checked"
    assert bundle["mathlib_smoke_receipt_id"] == smoke["receipt_id"]


def _write_tool(path: Path, output: str) -> Path:
    path.write_text(
        f"#!/usr/bin/env python3\nimport sys\nprint({output!r})\nsys.exit(0)\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return path


def _write_fake_lean(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        "    print('Lean (version 4.32.2, arm64-apple-darwin, commit "
        "f3b06c705e6c85f5314019d5d3baab0fec5b580c, Release)')\n"
        "    sys.exit(0)\n"
        "text = Path(sys.argv[-1]).read_text(encoding='utf-8')\n"
        "if 'False' in text:\n"
        "    print('error: unsolved goals', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return path
