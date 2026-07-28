"""Path redaction for the content-addressed store.

A content-addressed store may be rooted at a host-local directory (a T7 mount
point, an operator home directory). Receipts and logs that name the store root
would leak the operator's machine layout (``/Volumes/...``, ``/Users/...``),
which is a :class:`~srl.autonomy.leakguard.LeakViolation`-class leak. This module
reduces any store path to a **digest-prefix form** so a receipt carries enough
to identify the store (a short, stable token) without carrying the raw path.

Redaction form
--------------
The redacted form is the first 16 hex characters of the SHA-256 of the path's
absolute string form, prefixed with ``redacted:``:

    redacted:<16 lowercase hex>

The prefix makes the token self-describing in receipts (a reader knows it is a
redacted path, not a real one). The 16-hex width is long enough to distinguish
stores in a single mission's receipt set while being far too short to recover
the original path (SHA-256 is a one-way function).

This module is the only place a raw store path should be observed *unredacted*
in the CAS package. Every public function in :mod:`srl.cas` that returns a path
or a receipt string must route through :func:`redact_store_path`; the gate
script (``scripts/checks/wp20-gate.py``) asserts no public API ever emits a
string beginning with ``/Volumes/`` or ``/Users/``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from srl.contracts.errors import ContractError

# The prefix that marks a redacted path token in receipts and logs. A reader
# seeing ``redacted:...`` knows the value is a digest-prefix form, not a path.
_REDACTED_PREFIX: Final[str] = "redacted:"

# Number of hex characters kept from the SHA-256 digest. 16 hex = 64 bits of
# distinguishing entropy, enough to separate stores in a mission while being
# cryptographically unrecoverable to the original path.
_REDACTED_HEX_WIDTH: Final[int] = 16


class PrivacyError(ContractError):
    """Raised when a store path cannot be redacted.

    The only failure mode is a path whose ``absolute()`` form cannot be encoded
    as UTF-8 (extremely rare on POSIX, where paths are bytes). Kept as a typed
    error in the contract family so a caller routing through the fail-reason
    machinery sees ``CONTRACT_INVALID``.
    """


def redact_store_path(path: str | Path) -> str:
    """Reduce ``path`` to a digest-prefix redacted form.

    The path is resolved to its absolute form first (so a relative and an
    absolute reference to the same store redact identically), then SHA-256
    hashed, and the first 16 hex characters of the digest are returned under the
    ``redacted:`` prefix. The original path never appears in the output.

    Parameters
    ----------
    path:
        A store root path, absolute or relative. Relative paths are resolved
        against the current working directory (the same resolution Python's
        :class:`~pathlib.Path` applies), so two callers in the same directory
        with the same relative path produce the same redaction.

    Returns
    -------
    str
        ``redacted:<16 lowercase hex>`` — a stable, non-reversible token for the
        store root.

    Raises
    ------
    PrivacyError
        If the absolute path cannot be encoded as UTF-8 (propagated from
        :func:`pathlib.Path.absolute`'s string form).

    Notes
    -----
    This function performs no I/O and writes nothing. :func:`pathlib.Path.absolute`
    is a pure string operation on POSIX; it does not touch the filesystem.
    """
    abs_path = Path(path).absolute()
    try:
        raw = str(abs_path).encode("utf-8")
    except UnicodeEncodeError as exc:
        msg = f"store path cannot be encoded as UTF-8 for redaction: {abs_path!s}"
        raise PrivacyError(msg) from exc
    digest = hashlib.sha256(raw).hexdigest()
    return f"{_REDACTED_PREFIX}{digest[:_REDACTED_HEX_WIDTH]}"


__all__ = ["PrivacyError", "redact_store_path"]
