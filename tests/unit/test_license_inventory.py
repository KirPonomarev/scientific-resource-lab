from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _license_inventory_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "checks" / "license_inventory.py"
    spec = importlib.util.spec_from_file_location("license_inventory_under_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load license_inventory.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_license_inventory_allows_llvmlite_spdx_exception_expression() -> None:
    module = _license_inventory_module()

    normalized = module._normalize_license("BSD-2-Clause AND Apache-2.0 WITH LLVM-exception")

    assert normalized == "BSD-2-CLAUSE AND APACHE-2.0 WITH LLVM-EXCEPTION"
    assert module._evaluate_license(normalized) == "allowed"


def test_license_inventory_denies_gpl_family_even_with_exception() -> None:
    module = _license_inventory_module()

    assert module._evaluate_license("GPL-2.0 WITH LLVM-EXCEPTION") == "denied"
    assert module._evaluate_license("LGPL-3.0-OR-LATER WITH LLVM-EXCEPTION") == "denied"


def test_license_inventory_allows_only_exact_python_flint_exception() -> None:
    module = _license_inventory_module()

    assert (
        module._policy_exception_for_package(
            name="python-flint",
            version="0.9.0",
            normalized_license="MIT AND LGPL-3.0-OR-LATER",
        )
        == "A07_PYTHON_FLINT_LGPL_CLOSURE_ADR_0010"
    )
    assert (
        module._policy_exception_for_package(
            name="cons",
            version="0.4.7",
            normalized_license="LGPL-3.0-ONLY",
        )
        is None
    )


def test_license_inventory_rejects_unknown_spdx_exception() -> None:
    module = _license_inventory_module()

    assert module._evaluate_license("APACHE-2.0 WITH UNKNOWN-EXCEPTION") == "unknown"


def test_license_inventory_does_not_treat_license_body_prefix_as_spdx() -> None:
    module = _license_inventory_module()

    license_body = (
        "License agreement for matplotlib versions 1.3.0 and later\n"
        "This binary distribution can also bundle font license texts."
    )

    assert module._is_spdx_expression(license_body) is False
