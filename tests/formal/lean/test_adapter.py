from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import cast

from srl.packs.formal.lean import (
    LeanAdmissionStatus,
    LeanCorpusStatement,
    LeanCorpusStatus,
    LeanProofStatus,
    a09_mathlib_cache_key,
    build_lean_admission_bundle,
    check_lean_source,
    default_corpus_pins,
    default_corpus_statements,
    default_lean_pins,
    discover_lean_environment,
    mathlib_lakefile_text,
    traverse_pinned_corpus_statements,
    validate_mathlib_project,
)

PREPARE_A09_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "ci" / "prepare_a09_mathlib.py"
)


def _load_prepare_a09_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_a09_mathlib", PREPARE_A09_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(ModuleType, module)


prepare_a09 = _load_prepare_a09_module()


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
        expect_axioms=True,
    )

    assert receipt["status"] == LeanProofStatus.CHECKED.value
    assert receipt["formal_check"] == "checked"
    assert receipt["formal_certificate_ref"] is None
    assert receipt["axioms"] == []
    assert receipt["revision_bindings"]["lean_commit"] == (
        "f3b06c705e6c85f5314019d5d3baab0fec5b580c"
    )
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
        lean_executable="/definitely/missing/lean",
        lake_executable="/definitely/missing/lake",
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


def test_default_corpus_pins_bind_a09_sources() -> None:
    pins = {pin.corpus_id: pin for pin in default_corpus_pins()}
    statements = default_corpus_statements()

    assert pins["cslib-index"].repository_revision == ("93aa05752a62ad3498e734d5b75fcbff965891ce")
    assert pins["formal-conjectures"].tag == "v4.32.0"
    assert statements[0].source_path == "FormalConjectures/ErdosProblems/12.lean"
    assert statements[0].source_sha256 == (
        "7b999f416f15608a603cdc35c906ec3a860161dd2f0615490e2f898786558fd4"
    )


def test_pinned_corpus_statement_traverses_without_authority() -> None:
    receipt = traverse_pinned_corpus_statements()

    assert receipt["status"] == LeanCorpusStatus.TRAVERSED.value
    assert receipt["statement_count"] == 1
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_corpus_traversal_rejects_unbound_marker() -> None:
    statement = default_corpus_statements()[0]
    bad = LeanCorpusStatement(
        statement_id=statement.statement_id,
        corpus_id=statement.corpus_id,
        source_path=statement.source_path,
        source_blob_sha1=statement.source_blob_sha1,
        source_sha256=statement.source_sha256,
        theorem_label=statement.theorem_label,
        statement_kind=statement.statement_kind,
        parser_markers=("not present in pinned source",),
    )

    receipt = traverse_pinned_corpus_statements(statements=(bad,))

    assert receipt["status"] == LeanCorpusStatus.REJECTED.value


def test_mathlib_project_validation_rejects_corrupt_or_mismatched_cache(tmp_path: Path) -> None:
    valid_root = _write_valid_mathlib_project(tmp_path / "valid")
    assert validate_mathlib_project(valid_root)["status"] == "PASS"

    corrupt_root = _write_valid_mathlib_project(tmp_path / "corrupt")
    (corrupt_root / "lake-manifest.json").write_text("{", encoding="utf-8")
    corrupt = validate_mathlib_project(corrupt_root)
    assert corrupt["status"] == "FAIL"
    assert "lake-manifest_invalid_json" in corrupt["failures"]

    mismatch_root = _write_valid_mathlib_project(tmp_path / "mismatch", revision="bad")
    mismatch = validate_mathlib_project(mismatch_root)
    assert mismatch["status"] == "FAIL"
    assert "lake-manifest_mathlib_pin_mismatch" in mismatch["failures"]


def test_a09_cache_key_binds_platform_pins_manifest_and_installer() -> None:
    pins = default_lean_pins()
    one = a09_mathlib_cache_key(
        pins=pins,
        installer_hash="a" * 64,
        os_name="darwin",
        arch="arm64",
    )
    two = a09_mathlib_cache_key(
        pins=pins,
        installer_hash="b" * 64,
        os_name="darwin",
        arch="arm64",
    )

    assert one != two
    assert pins.lean_version in one
    assert pins.mathlib_revision[:12] in one


def test_prepare_session_project_cold_once_warm_zero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_prepare(project_dir: str | Path, **_kwargs: object) -> dict[str, object]:
        _write_valid_mathlib_project(Path(project_dir))
        return {
            "schema_version": "PinnedMathlibProjectReceipt/v1",
            "status": "PASS",
            "commands": [{"command": ["lake", "update", "mathlib"], "status": "PASS"}],
        }

    monkeypatch.setattr(prepare_a09, "prepare_mathlib_project", fake_prepare)

    cold = prepare_a09.prepare_session_project(cache_root=tmp_path / "cache", timeout_seconds=1.0)
    warm = prepare_a09.prepare_session_project(cache_root=tmp_path / "cache", timeout_seconds=1.0)

    assert cold["status"] == "PASS"
    assert cold["cache_status"] == "prepared"
    assert cold["prepare_count"] == 1
    assert cold["fetch_count"] == 1
    assert warm["status"] == "PASS"
    assert warm["cache_status"] == "reused"
    assert warm["prepare_count"] == 0
    assert warm["fetch_count"] == 0


def _write_tool(path: Path, output: str) -> Path:
    path.write_text(
        f"#!/usr/bin/env python3\nimport sys\nprint({output!r})\nsys.exit(0)\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return path


def _write_valid_mathlib_project(
    root: Path,
    *,
    revision: str | None = None,
) -> Path:
    pins = default_lean_pins()
    root.mkdir(parents=True, exist_ok=True)
    (root / "lean-toolchain").write_text(pins.toolchain + "\n", encoding="utf-8")
    (root / "lakefile.lean").write_text(mathlib_lakefile_text(pins=pins), encoding="utf-8")
    (root / ".lake" / "packages" / "mathlib").mkdir(parents=True)
    (root / "lake-manifest.json").write_text(
        (
            '{"packages":[{"name":"mathlib","url":"'
            + pins.mathlib_url
            + '","rev":"'
            + (revision or pins.mathlib_revision)
            + '","inputRev":"'
            + pins.mathlib_tag
            + '"}]}'
        ),
        encoding="utf-8",
    )
    return root


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
        "if '#print axioms' in text:\n"
        "    print('ok does not depend on any axioms')\n"
        "if 'False' in text:\n"
        "    print('error: unsolved goals', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o700)
    return path
