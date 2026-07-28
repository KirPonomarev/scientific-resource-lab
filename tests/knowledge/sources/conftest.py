"""Pytest configuration for the WP-E44 source adapter test package."""

from __future__ import annotations

import sys
from pathlib import Path

# The WP-E44 canned payload loader lives under fixtures/conformance/knowledge/sources,
# which is not covered by the parent knowledge conftest path. Add it here so the
# hermetic source tests can import canned_payloads.
_FX_E44 = Path(__file__).resolve().parents[3] / "fixtures" / "conformance" / "knowledge" / "sources"
if str(_FX_E44) not in sys.path:
    sys.path.insert(0, str(_FX_E44))
