"""SRL public bridge: the export boundary to the public repository.

This package owns the **export** direction of the public boundary: turning a
set of internal scientific objects into a sanitized, disclosure-safe
``LabExportPacket/v1`` that may be released across the public boundary.

The load-bearing property of this package is the **refuse-not-strip** sanitizer
(see :mod:`srl.bridge.sanitizer`): a summary that contains a local path, a
credential, a private key marker, or any other forbidden class is REFUSED at
build time with a typed ``BRIDGE_CONTRACT_MISMATCH`` error. The exporter never
silently strips or rewrites a forbidden substring, because a quiet rewrite
would let a private value leak through in a subtly-different form. A refused
object must be honestly re-summarized before it can be exported.

The second load-bearing property is **digest replacement** (see
:mod:`srl.bridge.exporter`): a private object's identity digest is not
automatically publishable. Under the ``digest_replaced`` disclosure policy the
exporter substitutes a packet-local digest
``sha256(packet_seed + private_digest)`` for the raw private digest. The
replacement is deterministic (the same packet_seed + private digest always
yields the same replacement) but uncorrelated with the raw digest, so the raw
private identity never crosses the boundary.

Honesty
-------
A packet is a disclosure of summary evidence. It is NOT an admission of
scientific truth and NOT an authorization to integrate. The four safety consts
are pinned: ``review_only=true``, ``canonical_effect='none'``,
``grants_authority=false``, ``canonical_writes=0``. "Exportable is not admitted"
mirrors the evidence-model orthogonality rule in
:mod:`srl.semantic.evidence`.
"""

from __future__ import annotations

from typing import Final

# The typed fail reason for a bridge-contract mismatch. Mirrors the
# ``BRIDGE_CONTRACT_MISMATCH`` entry in ``automation/fail-reasons.json`` (class
# ``bridge``, ``hard_stop=true``, ``retriable=false``). A refused summary or an
# oversize packet is a deterministic, terminal bridge failure: the input must be
# fixed, not retried. Kept as a constant so the string lives in one place.
BRIDGE_CONTRACT_MISMATCH_FAIL_REASON: Final[str] = "BRIDGE_CONTRACT_MISMATCH"

# The identity anchor for the export packet schema.
LAB_EXPORT_PACKET_SCHEMA_VERSION: Final[str] = "LabExportPacket/v1"

# The hard byte ceiling on the canonical ENCODED packet. A packet whose
# canonical bytes exceed this is refused (typed BRIDGE_CONTRACT_MISMATCH); the
# exporter performs no truncation, because truncating would silently corrupt
# the content-addressed identity and the disclosure.
PACKET_MAX_BYTES: Final[int] = 1024 * 1024  # 1 MiB

__all__ = [
    "BRIDGE_CONTRACT_MISMATCH_FAIL_REASON",
    "LAB_EXPORT_PACKET_SCHEMA_VERSION",
    "PACKET_MAX_BYTES",
]
