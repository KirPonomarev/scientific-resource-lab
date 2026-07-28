"""``LabExportPacket/v1`` exporter (WP-I80).

This module is the Python counterpart of the
``src/srl/contracts/schemas/v1/lab-export-packet.json`` JSON Schema 2020-12
document. It is the single producer of public export packets.

The two load-bearing properties are:

1. **Sanitized disclosure** (refuse-not-strip): every object summary is run
   through :func:`srl.bridge.sanitizer.normalize_summary`, which refuses (not
   strips) any summary containing a local path, credential, private key marker,
   or other forbidden class. A refused object never becomes a packet.
2. **Digest replacement for private identities**: under the
   ``digest_replaced`` disclosure policy, each raw private object digest is
   replaced with a packet-local digest derived from a packet-scoped seed and
   the private digest, deterministically derivable but uncorrelated with the
   raw digest. The raw private digest never appears in the packet.

Both are enforced at BOTH the schema layer (consts, patterns, maxLength) and
here in Python (defense in depth), matching the repo convention.

Digest-replacement design
-------------------------
The packet-local replacement digest is
``sha256(packet_seed_hex + private_digest_hex)``. The ``packet_seed`` is the
content-addressed id of a STABLE representation built from each object's public
content (``object_type`` + normalized ``sanitized_summary``) plus the disclosure
policy — computed BEFORE any digest replacement is applied, so it is free of
self-reference and free of any raw private digest. Two packets with identical
public content yield an identical seed; a different private digest yields a
different replacement; the same private digest in two packets with different
public content yields different replacements (the seed differs). The raw
private digest is never recoverable from the replacement.

Honesty
-------
A packet is a disclosure of summary evidence. ``review_only=true``,
``canonical_effect='none'``, ``grants_authority=false``, and
``canonical_writes=0`` are pinned consts. Exportable is not admitted (mirrors
the evidence-model orthogonality in :mod:`srl.semantic.evidence`): a packet
discloses that summaries exist; it does not admit a scientific claim or
authorize an integration.

Size cap
--------
The canonical ENCODED packet (UTF-8, sorted keys, compact separators, one
trailing newline) MUST be at most ``PACKET_MAX_BYTES`` (1 MiB). An oversize
packet is a typed ``BRIDGE_CONTRACT_MISMATCH`` refusal — the exporter performs
NO truncation, because truncating would silently corrupt the content-addressed
identity and the disclosure.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final

from srl.bridge import (
    BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
    LAB_EXPORT_PACKET_SCHEMA_VERSION,
    PACKET_MAX_BYTES,
)
from srl.bridge.sanitizer import (
    SanitizerRefusalError,
    normalize_summary,
    scan_payload,
)
from srl.contracts import object_id, validate_object_id
from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.contracts.schema import validate as schema_validate
from srl.contracts.timestamps import normalize as normalize_timestamp

# ---------------------------------------------------------------------------
# Disclosure policy + object input.
# ---------------------------------------------------------------------------

# The two permitted private-identities policies.
_PRIVATE_IDENTITIES_DIGEST_REPLACED: Final[str] = "digest_replaced"
_PRIVATE_IDENTITIES_OMITTED: Final[str] = "omitted"
_PRIVATE_IDENTITIES_ALLOWED: Final[frozenset[str]] = frozenset(
    {_PRIVATE_IDENTITIES_DIGEST_REPLACED, _PRIVATE_IDENTITIES_OMITTED}
)

# The schema's hard per-summary char ceiling; the policy's summary_max_bytes is
# the operative byte cap and may be stricter.
_SUMMARY_MAX_CHARS: Final[int] = 2000
# The default byte budget when a policy does not specify one. Kept well under
# the schema char ceiling so a default-budgeted summary has headroom.
_SUMMARY_MAX_BYTES_DEFAULT: Final[int] = 1024

# The coarse object-type vocabulary a packet may carry. Mirrors the schema
# enum exactly; kept here as a frozenset for membership validation.
_EXPORT_OBJECT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "claim",
        "math_ir",
        "symbol_table",
        "condition_set",
        "constant_ref",
        "model_interface",
        "adapter_profile",
        "transformation_receipt",
        "evidence_assessment",
        "engine_receipt",
        "validation_receipt",
        "run_receipt",
        "plan",
        "request",
        "pilot_spec",
    }
)

# The default created_utc for a packet. Matches the repo-wide canonical epoch.
_DEFAULT_CREATED_UTC: Final[str] = "2026-07-28T00:00:00Z"


@dataclass(frozen=True)
class DisclosurePolicy:
    """The disclosure policy applied when building a packet.

    Attributes
    ----------
    private_identities:
        ``'digest_replaced'`` — substitute a packet-local digest for each raw
        private digest; the raw private digest never appears in the packet.
        ``'omitted'`` — the object is summarized but its provenance_refs list is
        emptied (no provenance crosses the boundary).
    summary_max_bytes:
        The byte budget enforced on each sanitized summary (1..2000). Defaults
        to 1024.
    """

    private_identities: str
    summary_max_bytes: int = _SUMMARY_MAX_BYTES_DEFAULT

    def __post_init__(self) -> None:
        """Validate the policy fields at construction."""
        if self.private_identities not in _PRIVATE_IDENTITIES_ALLOWED:
            msg = (
                f"disclosure_policy.private_identities {self.private_identities!r} "
                f"must be one of {sorted(_PRIVATE_IDENTITIES_ALLOWED)}"
            )
            raise ContractError(msg)
        if (
            not isinstance(self.summary_max_bytes, int)
            or isinstance(self.summary_max_bytes, bool)
            or self.summary_max_bytes < 1
            or self.summary_max_bytes > _SUMMARY_MAX_CHARS
        ):
            msg = (
                f"disclosure_policy.summary_max_bytes must be an integer in "
                f"1..{_SUMMARY_MAX_CHARS}, got {self.summary_max_bytes!r}"
            )
            raise ContractError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Return the wire-form dict for the packet's disclosure_policy field."""
        return {
            "private_identities": self.private_identities,
            "summary_max_bytes": self.summary_max_bytes,
        }


@dataclass(frozen=True)
class ExportObject:
    """A single internal object to be exported.

    Attributes
    ----------
    object_digest:
        The object's RAW private content-addressed digest (``sha256:<64 hex>``).
        Under the ``digest_replaced`` policy this is NEVER emitted; a
        packet-local replacement is substituted. Under ``omitted`` the object is
        still summarized and assigned a packet-local digest, but its
        provenance_refs list is emptied.
    object_type:
        A coarse, disclosure-safe object type label from the export vocabulary.
    sanitized_summary:
        The raw candidate summary text. Normalized and forbidden-class-checked
        by the sanitizer at build time; a forbidden summary refuses the whole
        packet.
    provenance_refs:
        The raw private provenance digests this summary derives from. Under
        ``digest_replaced`` each is replaced with a packet-local digest; under
        ``omitted`` the list is dropped (empty in the packet).
    """

    object_digest: str
    object_type: str
    sanitized_summary: str
    provenance_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the object's fields at construction."""
        _require_digest(self.object_digest, field="object_digest")
        if self.object_type not in _EXPORT_OBJECT_TYPES:
            msg = f"object_type {self.object_type!r} must be one of {sorted(_EXPORT_OBJECT_TYPES)}"
            raise ContractError(msg)
        # sanitized_summary type is enforced by the dataclass annotation; the
        # content (empty, oversize, forbidden) is validated by normalize_summary
        # at build time, which is the single refuse-not-strip gate.
        refs: list[str] = []
        for ref in self.provenance_refs:
            _require_digest(ref, field="provenance_refs entry")
            refs.append(ref)
        if len(set(refs)) != len(refs):
            msg = "provenance_refs must be unique"
            raise ContractError(msg)
        object.__setattr__(self, "provenance_refs", tuple(refs))


# ---------------------------------------------------------------------------
# Typed errors.
# ---------------------------------------------------------------------------


class ExporterError(ContractError):
    """Raised when a packet cannot be built.

    The base for exporter failures. Subclasses pin their own fail reason:
    :class:`SanitizerRefusalError` and :class:`OversizePacketError` use
    ``BRIDGE_CONTRACT_MISMATCH`` (a deterministic boundary violation); field
    and shape failures use ``CONTRACT_INVALID``.
    """


class OversizePacketError(ExporterError):
    """Raised when the canonical encoded packet exceeds the 1 MiB cap.

    The exporter refuses (typed ``BRIDGE_CONTRACT_MISMATCH``); it performs NO
    truncation, because truncating would corrupt the content-addressed identity
    and the disclosure. The caller must reduce the object set or shorten
    summaries and rebuild.

    Attributes
    ----------
    encoded_bytes:
        The measured canonical byte length that exceeded the cap.
    """

    def __init__(
        self,
        message: str,
        *,
        encoded_bytes: int = 0,
        fail_reason: str = BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.encoded_bytes: int = encoded_bytes


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _require_digest(value: Any, *, field: str) -> str:
    """Raise ContractError if ``value`` is not a sha256 digest string."""
    try:
        return validate_object_id(value)
    except ContractError as exc:
        msg = f"{field} must be a 'sha256:<64 hex>' digest: {exc}"
        raise ContractError(msg) from exc


def _seed_objects(objects: list[ExportObject], policy: DisclosurePolicy) -> list[dict[str, Any]]:
    """Return the stable, public-content representation used for the packet seed.

    Only ``object_type`` + ``sanitized_summary`` (normalized) per object, plus
    the disclosure policy. No raw private digest is included, so the seed is
    free of self-reference and free of private data. Two packets with identical
    public content yield an identical seed.
    """
    out: list[dict[str, Any]] = []
    for obj in objects:
        summary = normalize_summary(obj.sanitized_summary, max_bytes=policy.summary_max_bytes)
        out.append({"object_type": obj.object_type, "sanitized_summary": summary})
    return out


def packet_seed(
    objects: list[ExportObject],
    policy: DisclosurePolicy,
) -> str:
    """Compute the packet-scoped seed used for digest replacement.

    Public and stable: the seed is the content-addressed id of the objects'
    public content (``object_type`` + normalized ``sanitized_summary``) plus the
    disclosure policy. It does NOT depend on any raw private digest, so it is
    reproducible from a packet's public content alone and is free of
    self-reference. Returns a ``sha256:<64 hex>`` id.
    """
    seed_objs = _seed_objects(objects, policy)
    return object_id({"objects": seed_objs, "policy": policy.to_dict()})


def replacement_digest(seed: str, private_digest: str) -> str:
    """Return the packet-local replacement digest for a private digest.

    The replacement is ``sha256(seed_hex + private_digest_hex)`` prefixed
    ``sha256:`` — a deterministic function of the (packet-seed, private-digest)
    pair. It is uncorrelated with the raw private digest (the raw digest does
    not appear in the hash input as a standalone identity; it is mixed with the
    packet-local seed). Two different private digests yield two different
    replacements; the same private digest in two different packets yields two
    different replacements (the seed differs).

    The raw private digest NEVER appears in the returned value.
    """
    seed_hex = seed.removeprefix("sha256:")
    private_hex = private_digest.removeprefix("sha256:")
    mixed = (seed_hex + private_hex).encode("utf-8")
    return "sha256:" + hashlib.sha256(mixed).hexdigest()


def replacement_digest_for(
    packet: dict[str, Any],
    objects: list[ExportObject],
    policy: DisclosurePolicy,
    private_digest: str,
) -> str:
    """Recompute the expected replacement digest for a raw private digest.

    For verification (gates, tests): given a packet built from ``objects``
    under ``policy``, return the replacement digest that the raw
    ``private_digest`` SHOULD map to. A caller compares this to the
    ``object_digest`` (or a ``provenance_refs`` entry) present in the packet to
    assert the replacement is deterministic and the raw digest is absent.

    The recompute is independent of any stored raw digest: it rebuilds the seed
    from the objects' public content and applies :func:`replacement_digest`.
    """
    seed = packet_seed(objects, policy)
    return replacement_digest(seed, private_digest)


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def build_packet(
    objects: list[ExportObject],
    policy: DisclosurePolicy,
    *,
    created_utc: str = _DEFAULT_CREATED_UTC,
    source_snapshot_digest: str | None = None,
) -> dict[str, Any]:
    """Build a sanitized, validated ``LabExportPacket/v1``.

    Applies the disclosure policy to each object: normalizes and forbidden-class
    -checks every summary (refuse-not-strip), and substitutes a packet-local
    digest for each private identity when ``policy.private_identities`` is
    ``'digest_replaced'``. Then recursively scans EVERY string field of the
    assembled packet (defense in depth, so a forbidden value cannot hide in any
    field other than ``sanitized_summary``), validates the packet against the
    schema (defense in depth), and enforces the 1 MiB canonical-encoded cap.

    Parameters
    ----------
    objects:
        The internal objects to export. May be empty (an empty export is a valid
        disclosure).
    policy:
        The :class:`DisclosurePolicy` to apply.
    created_utc:
        RFC 3339 UTC timestamp. Normalized to canonical form.
    source_snapshot_digest:
        Optional internal source-snapshot digest for traceability, or ``None``.

    Returns
    -------
    dict[str, Any]
        A validated ``LabExportPacket/v1`` dict with a computed ``packet_id``.

    Raises
    ------
    SanitizerRefusalError
        If any object's summary contains a forbidden class (refuse-not-strip).
    OversizePacketError
        If the canonical encoded packet exceeds ``PACKET_MAX_BYTES``.
    ContractError
        If any field is malformed, the snapshot digest is invalid, the
        timestamp is invalid, or the built packet fails schema validation.
    """
    normalized_utc = normalize_timestamp(created_utc)
    if source_snapshot_digest is not None:
        _require_digest(source_snapshot_digest, field="source_snapshot_digest")

    # Compute the packet-scoped seed from the objects' PUBLIC content only.
    seed = packet_seed(objects, policy) if objects else "sha256:" + ("0" * 64)
    replace = policy.private_identities == _PRIVATE_IDENTITIES_DIGEST_REPLACED

    # Build the wire-form objects, applying the policy.
    objects_wire: list[dict[str, Any]] = []
    for obj in objects:
        # Normalize + forbidden-class check (refuse-not-strip).
        summary = normalize_summary(obj.sanitized_summary, max_bytes=policy.summary_max_bytes)
        # The object always gets a packet-local digest (its identity WITHIN the
        # packet). The raw private digest is never emitted.
        obj_digest = replacement_digest(seed, obj.object_digest)
        if replace:
            prov_refs = [replacement_digest(seed, ref) for ref in obj.provenance_refs]
        else:
            # 'omitted': no provenance crosses the boundary.
            prov_refs = []
        # Defense in depth: replacements must be unique within the object.
        if len(set(prov_refs)) != len(prov_refs):
            msg = "provenance_refs must be unique after digest replacement"
            raise ContractError(msg)
        objects_wire.append(
            {
                "object_digest": obj_digest,
                "object_type": obj.object_type,
                "sanitized_summary": summary,
                "provenance_refs": prov_refs,
            }
        )

    # Assemble the packet WITHOUT packet_id (content-addressed), then compute.
    packet: dict[str, Any] = {
        "schema_version": LAB_EXPORT_PACKET_SCHEMA_VERSION,
        "created_utc": normalized_utc,
        "source_snapshot_digest": source_snapshot_digest,
        "objects": objects_wire,
        "disclosure_policy": policy.to_dict(),
        "review_only": True,
        "canonical_effect": "none",
        "grants_authority": False,
        "canonical_writes": 0,
    }
    packet["packet_id"] = object_id(packet)

    # Defense in depth: recursively scan EVERY string field of the assembled
    # packet (not just sanitized_summary) for forbidden classes. Each summary was
    # already checked by normalize_summary above; this closes a smuggling vector
    # where a forbidden value hidden in any other (current or future) string
    # field would reach a built packet. Refuse-not-strip: a hit raises here.
    scan_payload(packet)

    # Defense in depth: schema-validate the final packet.
    schema_validate(packet, "LabExportPacket")

    # Enforce the 1 MiB canonical-encoded cap. NO truncation.
    encoded = dumps(packet)
    if len(encoded) > PACKET_MAX_BYTES:
        msg = (
            f"canonical encoded packet is {len(encoded)} bytes, exceeds the "
            f"{PACKET_MAX_BYTES} byte (1 MiB) cap; the exporter refuses and "
            "performs no truncation — reduce the object set or shorten summaries"
        )
        raise OversizePacketError(msg, encoded_bytes=len(encoded))

    return packet


__all__ = [
    "DisclosurePolicy",
    "ExportObject",
    "ExporterError",
    "OversizePacketError",
    "SanitizerRefusalError",
    "build_packet",
    "packet_seed",
    "replacement_digest",
    "replacement_digest_for",
]
