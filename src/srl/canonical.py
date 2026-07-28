"""Canonical JSON helpers for SRL (Phase A compatibility shim).

Historical note
---------------
This module was the Phase-A canonical JSON helper: an ASCII-only, ``str``
return encoding used by the autonomy receipts emitted in WP-A01..WP-A03. It
remains the wire format for those receipts and for the CLI dispatcher.

The scientific contracts layer (WP-B10) introduced a stricter canonical form
in :mod:`srl.contracts.canonical`: UTF-8 bytes, ``allow_nan=False``, and a
decimal-string policy. That module is the canonical form for new scientific
artifacts and new receipts.

This file is now a thin re-export so existing imports
(``from srl.canonical import canonical_json``) and the WP-A03 tests keep
working unchanged. The two public names ``canonical_json`` and
``canonical_json_line`` retain their original semantics exactly: sorted keys,
compact separators, ASCII-only, ``str`` return, and (for the line form) a
single trailing newline. They do **not** enforce ``allow_nan=False`` — that
refusal is the contracts-layer policy; the legacy helper must stay
behavior-identical so Phase-A receipts encode the same way they always did.
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

    Note: this is the legacy ``ValueError``-based error, distinct from
    :class:`srl.contracts.canonical.CanonicalJSONError` (a
    :class:`srl.contracts.errors.ContractError`). Both subclass
    :class:`ValueError`, so ``except ValueError`` catches either.
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


__all__ = ["CanonicalJSONError", "canonical_json", "canonical_json_line"]
