"""Pytest configuration for tests/packs.

Makes the runtime fixture generator importable from ``fixtures/conformance/packs``
and exposes it as a pytest fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "conformance" / "packs"
if str(_FIXTURES_DIR) not in sys.path:
    sys.path.insert(0, str(_FIXTURES_DIR))

import make_fixtures as _make_fixtures  # noqa: E402


@pytest.fixture
def make_fixtures() -> Any:
    """Provide the WP-C22 runtime fixture generator module."""
    return _make_fixtures
