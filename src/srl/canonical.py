"""Canonical JSON helpers for SRL.

SRL reports are JSON-first. A canonical encoding makes two independent agents
produce byte-identical output for equal data, which is a prerequisite for
content-addressed receipts and reproducible comparison.

The canonical form is intentionally restrictive:

- sorted object keys (deterministic ordering),
- compact separators (no insignificant whitespace),
- ASCII-only output via ``ensure_ascii=True`` (stable across locales),
- a single trailing newline (the SRL line contract).

This module is pure standard library and performs no I/O of its own.
"""

from __future__ import annotations

import json
from typing import Any, Final

# Separators that produce compact canonical JSON without insignificant whitespace.
# Note: the space after the comma default would be removed; both are tightened.
_CANONICAL_SEPARATORS: Final[tuple[str, str]] = (",", ":")
_CANONICAL_ENSURE_ASCII: Final[bool] = True
_CANONICAL_SORT_KEYS: Final[bool] = True
_TRAILING_NEWLINE: Final[str] = "\n"


class CanonicalJSONError(ValueError):
    """Raised when a value cannot be encoded as canonical JSON.

    Canonical JSON only supports JSON-native structures produced by
    :func:`json.dumps`. Subclasses of :class:`ValueError` keep the failure in
    the expected family for callers that already handle malformed input.
    """


def canonical_json(value: Any) -> str:
    """Encode ``value`` as canonical JSON without a trailing newline.

    Parameters
    ----------
    value:
        Any :mod:`json`-serializable value (dict, list, str, int, float, bool,
        ``None``, and nested combinations).

    Returns
    -------
    str
        Canonical JSON: sorted keys, compact separators, ASCII-only, no trailing
        newline.

    Raises
    ------
    CanonicalJSONError
        If ``value`` cannot be serialized as JSON.

    Notes
    -----
    The canonical form deliberately excludes whitespace. Callers that need the
    SRL line contract (one record per line) should use :func:`canonical_json_line`.
    """
    try:
        return json.dumps(
            value,
            sort_keys=_CANONICAL_SORT_KEYS,
            separators=_CANONICAL_SEPARATORS,
            ensure_ascii=_CANONICAL_ENSURE_ASCII,
        )
    except (TypeError, ValueError) as exc:
        msg = "value is not canonical-JSON serializable"
        raise CanonicalJSONError(msg) from exc


def canonical_json_line(value: Any) -> str:
    """Encode ``value`` as canonical JSON with a single trailing newline.

    This is the SRL line contract: one canonical record terminated by ``\\n``.
    """
    return canonical_json(value) + _TRAILING_NEWLINE
