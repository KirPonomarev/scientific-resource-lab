"""Pytest configuration for the read-only MCP server test package (WP-F51).

Makes the hermetic knowledge fake-transport importable (it lives outside the
Python package tree under ``fixtures/conformance/knowledge``) so the
``search_knowledge`` tests can drive a real receipt path without any network.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FX_KNOWLEDGE = Path(__file__).resolve().parents[2] / "fixtures" / "conformance" / "knowledge"
if str(_FX_KNOWLEDGE) not in sys.path:
    sys.path.insert(0, str(_FX_KNOWLEDGE))
