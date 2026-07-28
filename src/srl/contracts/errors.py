"""Typed error base for SRL contract validation failures.

Every contract primitive in :mod:`srl.contracts` reports failure through a
typed exception that derives from :class:`ContractError`. Each instance carries
a ``fail_reason`` string drawn from the fail-reason registry
(``automation/fail-reasons.json``). The reason routes the failure through the
resume and retry machinery: contract failures are terminal
(``hard_stop=true``, ``retriable=false``) because a contract violation is
deterministic, not transient.

Design notes
------------
``ContractError`` subclasses :class:`ValueError` (not :class:`Exception`) so a
caller handling malformed input via ``except ValueError`` still catches the
contract family, mirroring the autonomy primitives in
:mod:`srl.autonomy.policy` and :mod:`srl.autonomy.scopes`.

The ``CONTRACT_INVALID`` fail reason is the canonical reason for a value that
does not satisfy the structural contract (encoding, identity, numeric,
timestamp, reference, or schema). Each typed subclass pins its reason at
construction so callers can assert against the symbol without re-deriving the
class hierarchy.
"""

from __future__ import annotations

from typing import Final

# The canonical fail reason for a contract-structural failure. Mirrors the
# ``CONTRACT_INVALID`` entry in ``automation/fail-reasons.json`` (class
# ``CONTRACT``, ``hard_stop=true``, ``retriable=false``). Kept as a constant so
# the string lives in one place and tests assert against the symbol.
CONTRACT_INVALID_FAIL_REASON: Final[str] = "CONTRACT_INVALID"


class ContractError(ValueError):
    """Base for all SRL contract validation failures.

    Attributes
    ----------
    fail_reason:
        Typed fail reason from the fail-reason registry. Defaults to
        ``CONTRACT_INVALID``; subclasses may narrow it.

    Notes
    -----
    Subclasses pass their own keyword (e.g. ``path`` for an artifact ref, the
    json pointer for a schema mismatch) up to ``super().__init__``. The base
    records only ``fail_reason``; subclasses own their richer attributes.
    """

    def __init__(self, message: str, *, fail_reason: str = CONTRACT_INVALID_FAIL_REASON) -> None:
        super().__init__(message)
        self.fail_reason: str = fail_reason


__all__ = ["CONTRACT_INVALID_FAIL_REASON", "ContractError"]
