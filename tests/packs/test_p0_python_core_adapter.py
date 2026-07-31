from __future__ import annotations

import ast
from pathlib import Path

from srl.packs.adapters.p0_python_core import FLINT_WAIT_REASON, run_p0_python_core_smoke

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "srl"
_ADAPTER_MODULE = _SRC_ROOT / "packs" / "adapters" / "p0_python_core.py"


def test_p0_python_core_runs_real_smoke_and_crosschecks() -> None:
    smoke = run_p0_python_core_smoke()
    data = smoke.to_dict()

    assert data["schema_version"] == "P0PythonCoreSmoke/v1"
    assert data["sympy_version"]
    assert data["mpmath_version"]
    assert data["flint_version"] == "0.9.0"
    assert data["exact_factorization"] == "(x - 1)*(x + 1)*(x**2 + 1)"
    assert data["high_precision_value"].startswith("1.414213562373095048801688724209698")
    interval = data["interval_enclosure"]
    assert isinstance(interval, dict)
    assert interval["lower"] <= data["high_precision_value"] <= interval["upper"]
    assert data["dimensional_consistency"] == "parse_unit('kg*m/s^2') == parse_unit('N')"
    assert data["flint_status"] == "ACTIVE"
    assert data["flint_integer_partition"] == "627"
    assert data["flint_rational_identity"] == "1/2"
    assert data["flint_matrix_entry"] == "89"
    assert data["flint_license_closure"] == FLINT_WAIT_REASON
    assert data["canonical_writes"] == 0
    assert data["grants_authority"] is False


def test_p0_python_core_adapter_is_only_sympy_mpmath_import_site() -> None:
    offenders: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        if path == _ADAPTER_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".", 1)[0] for alias in node.names}
                if names & {"sympy", "mpmath", "flint"}:
                    offenders.append(str(path.relative_to(_REPO_ROOT)))
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in {"sympy", "mpmath", "flint"}:
                    offenders.append(str(path.relative_to(_REPO_ROOT)))

    assert offenders == []
