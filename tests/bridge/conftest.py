"""Pytest configuration for the bridge test package (WP-I80).

Adds the repository root to ``sys.path`` so the in-repo ``srl`` package is
importable, and exposes shared synthetic digests used across the hermetic
bridge tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
