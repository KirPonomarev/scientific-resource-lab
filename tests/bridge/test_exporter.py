"""Hermetic tests for the LabExportPacket/v1 exporter (:mod:`srl.bridge.exporter`).

Pins:

1. ``build_packet`` produces a schema-valid packet with a content-addressed
   ``packet_id`` and the four safety consts.
2. Digest replacement: under ``digest_replaced`` the raw private digest is
   ABSENT and the replacement is DETERMINISTIC; under ``omitted`` the
   provenance list is empty.
3. The 1 MiB canonical-encoded cap refuses an oversize packet with
   :class:`OversizePacketError` (no truncation).
4. ``DisclosurePolicy`` and ``ExportObject`` validate their fields at
   construction.
"""

from __future__ import annotations

import pytest

from srl.bridge import (
    BRIDGE_CONTRACT_MISMATCH_FAIL_REASON,
    LAB_EXPORT_PACKET_SCHEMA_VERSION,
    PACKET_MAX_BYTES,
)
from srl.bridge.exporter import (
    DisclosurePolicy,
    ExportObject,
    OversizePacketError,
    build_packet,
    packet_seed,
    replacement_digest,
    replacement_digest_for,
)
from srl.bridge.sanitizer import SanitizerRefusalError
from srl.contracts import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.schema import validate as schema_validate

# Synthetic sha256 digests (64 hex chars each).
_D_A = "sha256:" + "a" * 64
_D_B = "sha256:" + "b" * 64
_D_C = "sha256:" + "c" * 64
_D_1 = "sha256:" + "1" * 64


def _claim(digest: str, summary: str, refs: tuple[str, ...] = ()) -> ExportObject:
    """Build a claim-typed ExportObject."""
    return ExportObject(
        object_digest=digest,
        object_type="claim",
        sanitized_summary=summary,
        provenance_refs=refs,
    )


# ---------------------------------------------------------------------------
# build_packet: happy path + safety consts.
# ---------------------------------------------------------------------------


def test_build_packet_happy_path() -> None:
    """A single-object packet builds and validates."""
    objects = [_claim(_D_A, "A claim about convergence.")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy)
    assert packet["schema_version"] == LAB_EXPORT_PACKET_SCHEMA_VERSION
    assert packet["packet_id"].startswith("sha256:")
    # Schema validation (defense in depth) passes.
    schema_validate(packet, "LabExportPacket")
    # Safety consts.
    assert packet["review_only"] is True
    assert packet["canonical_effect"] == "none"
    assert packet["grants_authority"] is False
    assert packet["canonical_writes"] == 0


def test_build_packet_empty_objects_valid() -> None:
    """An empty object list is a valid (empty) disclosure."""
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet([], policy)
    assert packet["objects"] == []
    schema_validate(packet, "LabExportPacket")


def test_build_packet_packet_id_is_content_addressed() -> None:
    """The packet_id is deterministic for identical inputs."""
    objects = [_claim(_D_A, "Same summary.")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    p1 = build_packet(objects, policy)
    p2 = build_packet(objects, policy)
    assert p1["packet_id"] == p2["packet_id"]


def test_build_packet_normalizes_summary() -> None:
    """Summaries are whitespace-normalized in the packet."""
    objects = [_claim(_D_A, "  Weak   support.  ")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy)
    assert packet["objects"][0]["sanitized_summary"] == "Weak support."


def test_build_packet_refuses_forbidden_summary() -> None:
    """A forbidden summary refuses the whole packet (refuse-not-strip)."""
    # {S} -> slash ; reconstruct a local path at runtime from the placeholder.
    objects = [_claim(_D_A, "saw {S}Users{S}alice{S}secret".replace("{S}", "/"))]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    with pytest.raises(SanitizerRefusalError) as exc_info:
        build_packet(objects, policy)
    assert exc_info.value.fail_reason == BRIDGE_CONTRACT_MISMATCH_FAIL_REASON


def test_build_packet_source_snapshot_validated() -> None:
    """An invalid source_snapshot_digest is rejected."""
    objects = [_claim(_D_A, "A claim.")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    with pytest.raises(ContractError):
        build_packet(objects, policy, source_snapshot_digest="not-a-digest")


def test_build_packet_source_snapshot_null_allowed() -> None:
    """A null source_snapshot_digest is valid (loose-object export)."""
    objects = [_claim(_D_A, "A claim.")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy, source_snapshot_digest=None)
    assert packet["source_snapshot_digest"] is None


# ---------------------------------------------------------------------------
# Digest replacement (I80-03 contract).
# ---------------------------------------------------------------------------


def test_digest_replaced_raw_digest_absent() -> None:
    """Under digest_replaced the raw private digest never appears in the packet."""
    objects = [_claim(_D_A, "A claim.", refs=(_D_C, _D_1))]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy)
    blob = dumps(packet).decode("utf-8")
    assert _D_A not in blob
    assert _D_C not in blob
    assert _D_1 not in blob


def test_digest_replaced_replacement_deterministic() -> None:
    """The packet-local replacement is recomputable from public content + raw digest."""
    objects = [_claim(_D_A, "A claim.", refs=(_D_C,))]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy)
    expected_obj = replacement_digest_for(packet, objects, policy, _D_A)
    expected_prov = replacement_digest_for(packet, objects, policy, _D_C)
    assert packet["objects"][0]["object_digest"] == expected_obj
    assert expected_prov in packet["objects"][0]["provenance_refs"]


def test_digest_replaced_replacement_not_raw() -> None:
    """The replacement is never equal to the raw private digest (no fixed point)."""
    objects = [_claim(_D_A, "A claim.")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy)
    actual = packet["objects"][0]["object_digest"]
    assert actual != _D_A


def test_digest_replaced_distinct_privates_distinct_replacements() -> None:
    """Two different private digests yield two different replacements."""
    objects = [_claim(_D_A, "Claim A."), _claim(_D_B, "Claim B.")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy)
    digests = [o["object_digest"] for o in packet["objects"]]
    assert len(set(digests)) == len(digests)


def test_omitted_provenance_refs_empty() -> None:
    """Under omitted the provenance_refs list is empty."""
    objects = [_claim(_D_A, "A claim.", refs=(_D_C, _D_1))]
    policy = DisclosurePolicy(private_identities="omitted")
    packet = build_packet(objects, policy)
    assert packet["objects"][0]["provenance_refs"] == []
    # Raw digests still absent.
    blob = dumps(packet).decode("utf-8")
    assert _D_A not in blob
    assert _D_C not in blob


def test_packet_seed_is_public_content_only() -> None:
    """The packet seed does not depend on raw private digests."""
    objects_a = [_claim(_D_A, "Same summary.")]
    objects_b = [_claim(_D_B, "Same summary.")]  # different private digest
    policy = DisclosurePolicy(private_identities="digest_replaced")
    # Same public content (object_type + summary) -> same seed, even though the
    # private digests differ.
    assert packet_seed(objects_a, policy) == packet_seed(objects_b, policy)


def test_replacement_digest_two_packets_differ() -> None:
    """The same private digest in two different packets yields different replacements."""
    objects_a = [_claim(_D_A, "Summary A.")]
    objects_b = [_claim(_D_A, "Summary B.")]  # different public content -> different seed
    policy = DisclosurePolicy(private_identities="digest_replaced")
    seed_a = packet_seed(objects_a, policy)
    seed_b = packet_seed(objects_b, policy)
    assert seed_a != seed_b
    assert replacement_digest(seed_a, _D_A) != replacement_digest(seed_b, _D_A)


# ---------------------------------------------------------------------------
# Size cap (I80-04 contract).
# ---------------------------------------------------------------------------


def test_oversize_packet_refused_no_truncation() -> None:
    """A packet exceeding 1 MiB is refused with OversizePacketError."""
    summary = "convergence result " * 100  # ~1800 chars, all safe
    big = [_claim(_D_A, summary) for _ in range(700)]
    policy = DisclosurePolicy(private_identities="digest_replaced", summary_max_bytes=2000)
    with pytest.raises(OversizePacketError) as exc_info:
        build_packet(big, policy)
    assert exc_info.value.fail_reason == BRIDGE_CONTRACT_MISMATCH_FAIL_REASON
    assert exc_info.value.encoded_bytes > PACKET_MAX_BYTES


def test_under_cap_packet_passes() -> None:
    """A small packet well under 1 MiB builds fine."""
    objects = [_claim(_D_A, "Small summary.")]
    policy = DisclosurePolicy(private_identities="digest_replaced")
    packet = build_packet(objects, policy)
    assert len(dumps(packet)) <= PACKET_MAX_BYTES


# ---------------------------------------------------------------------------
# DisclosurePolicy + ExportObject construction validation.
# ---------------------------------------------------------------------------


def test_disclosure_policy_rejects_bad_private_identities() -> None:
    """An unknown private_identities value is rejected."""
    with pytest.raises(ContractError):
        DisclosurePolicy(private_identities="publish_raw")  # type: ignore[arg-type]


def test_disclosure_policy_rejects_bad_summary_max_bytes() -> None:
    """An out-of-range summary_max_bytes is rejected."""
    with pytest.raises(ContractError):
        DisclosurePolicy(private_identities="digest_replaced", summary_max_bytes=0)
    with pytest.raises(ContractError):
        DisclosurePolicy(private_identities="digest_replaced", summary_max_bytes=5000)


def test_export_object_rejects_bad_digest() -> None:
    """A non-sha256 object_digest is rejected."""
    with pytest.raises(ContractError):
        ExportObject(
            object_digest="not-a-digest",
            object_type="claim",
            sanitized_summary="A claim.",
        )


def test_export_object_rejects_bad_object_type() -> None:
    """An object_type outside the disclosure-safe enum is rejected."""
    with pytest.raises(ContractError) as exc_info:
        ExportObject(
            object_digest=_D_A,
            object_type="organism_pulse_payload",  # private, not in the vocabulary
            sanitized_summary="A claim.",
        )
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_export_object_rejects_duplicate_provenance() -> None:
    """Duplicate provenance_refs are rejected."""
    with pytest.raises(ContractError):
        ExportObject(
            object_digest=_D_A,
            object_type="claim",
            sanitized_summary="A claim.",
            provenance_refs=(_D_C, _D_C),
        )
