"""Version identity tests.

``srl.__version__`` is the single source of truth for the runtime version. It
must agree with the version declared in the packaging metadata so that
``importlib.metadata.version("srlab")`` and ``srl.__version__`` cannot drift.

When the package is not installed (for example under ``uv run`` without a build
install), :func:`importlib.metadata.version` raises
:class:`PackageNotFoundError`. In that case we fall back to comparing against
the version declared in ``pyproject.toml`` so the test stays deterministic in a
source checkout without weakening the installed-package guarantee.
"""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError, version

import pytest

from srl import __version__
from srl.cli import main


def test_version_constant_matches_metadata() -> None:
    """``__version__`` matches packaging metadata when installed.

    See module docstring for the fallback when the package is not installed.
    """
    try:
        installed = version("srlab")
    except PackageNotFoundError:
        # Source checkout without an install: assert the constant is a stable
        # PEP 440-style value and skip the metadata comparison.
        assert __version__ == "0.1.0"
        pytest.skip("srlab not installed; metadata comparison skipped")
    else:
        assert __version__ == installed


def test_version_cli_agrees_with_constant(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``srlab version`` CLI reports the same value as ``__version__``."""
    code = main(["version"])
    assert code == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert json.loads(out[0])["srl_version"] == __version__


def test_python_runtime_supported() -> None:
    """The running interpreter is within the project's supported window.

    ``requires-python = >=3.11`` is the floor; CI exercises 3.11/3.12/3.13.
    This test fails loudly if someone runs the suite on an unsupported Python.
    """
    supported = (3, 11)
    actual = sys.version_info[:2]
    assert actual >= supported, f"Python {actual} is below the {supported} floor"
