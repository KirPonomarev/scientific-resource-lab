from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_prepare_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "ci" / "prepare_a10_hol4.py"
    spec = importlib.util.spec_from_file_location("prepare_a10_hol4_under_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare_a10_hol4 = _load_prepare_module()


def test_resolve_cache_root_returns_absolute_path(tmp_path: Path, monkeypatch) -> None:
    relative_root = Path("relative-a10-cache")

    monkeypatch.chdir(tmp_path)

    resolved = prepare_a10_hol4._resolve_cache_root(relative_root)

    assert resolved.is_absolute()
    assert resolved == (tmp_path / relative_root).resolve()


def test_polyml_includes_written_from_env_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lib_dir = tmp_path / "polyml-lib"
    lib_dir.mkdir()
    (lib_dir / "libpolymain.a").write_bytes(b"synthetic static library marker")
    hol4_home = tmp_path / "hol4"

    monkeypatch.setenv("SRL_A10_POLYML_LIB_DIR", str(lib_dir))

    discovered = prepare_a10_hol4._write_polyml_includes_if_found(hol4_home)

    assert discovered == str(lib_dir)
    assert (hol4_home / "tools-poly" / "poly-includes.ML").read_text(
        encoding="utf-8"
    ) == f'val polymllibdir = "{lib_dir}";\n'


def test_polyml_includes_not_written_without_library(
    tmp_path: Path,
    monkeypatch,
) -> None:
    empty_lib_dir = tmp_path / "empty-polyml-lib"
    empty_lib_dir.mkdir()
    hol4_home = tmp_path / "hol4"

    monkeypatch.setenv("SRL_A10_POLYML_LIB_DIR", str(empty_lib_dir))
    monkeypatch.setattr(prepare_a10_hol4, "_polyml_lib_dir_candidates", lambda: (empty_lib_dir,))
    monkeypatch.setattr(prepare_a10_hol4, "_polyml_search_roots", lambda: (tmp_path / "usr-lib",))

    discovered = prepare_a10_hol4._write_polyml_includes_if_found(hol4_home)

    assert discovered is None
    assert not (hol4_home / "tools-poly" / "poly-includes.ML").exists()
