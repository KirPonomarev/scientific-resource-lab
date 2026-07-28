"""Pytest configuration for the knowledge retriever test package."""

from __future__ import annotations

import sys
from pathlib import Path

# The conformance fake-transport module lives under fixtures/conformance/knowledge,
# which is not a Python package. Make it importable for the hermetic tests.
_FX_KNOWLEDGE = Path(__file__).resolve().parents[2] / "fixtures" / "conformance" / "knowledge"
if str(_FX_KNOWLEDGE) not in sys.path:
    sys.path.insert(0, str(_FX_KNOWLEDGE))
