"""Tests for the S03 SRF federation/access/transport schema family."""

from __future__ import annotations

import pytest

from srl.contracts.schema import ContractValidationError, list_schemas, validate
from srl.labctl import lab_access_receipt

_DIGEST = "sha256:" + "a" * 64
_FINGERPRINT = "d56e03d0d5e1a9bb9c33a008ab9895102d8e41e8bfd001dfbfc8e1c80b9df0b3"
_UTC = "2026-07-29T00:00:00Z"
_HEAD = "947cbb4515307b54fe3eb9b6366cdb392361c867"


def _base_docs() -> dict[str, dict[str, object]]:
    return {
        "LabCellManifest": {
            "schema_version": "LabCellManifest/v1",
            "cell_id": "standalone",
            "project_fingerprint": _FINGERPRINT,
            "native_bootstrap": "srlab doctor",
            "proposal_only": False,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "LabFederationManifest": {
            "schema_version": "LabFederationManifest/v1",
            "manifest_id": _DIGEST,
            "project_fingerprint": _FINGERPRINT,
            "cells": ["standalone"],
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "LabSessionEnvelope": {
            "schema_version": "LabSessionEnvelope/v1",
            "session_id": _DIGEST,
            "cell_id": "standalone",
            "project_fingerprint": _FINGERPRINT,
            "created_utc": _UTC,
            "classification": "D0",
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "CapabilityManifest": {
            "schema_version": "CapabilityManifest/v1",
            "manifest_id": _DIGEST,
            "capabilities": ["catalog.inspect"],
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "SciencePackManifestV2": {
            "schema_version": "SciencePackManifest/v2",
            "pack_id": "core-units",
            "version": "1.0.0",
            "licenses": ["Apache-2.0"],
            "sources": [_DIGEST],
            "resource_envelope": {"wall_seconds": 5},
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "ScientificRequestEnvelope": {
            "schema_version": "ScientificRequestEnvelope/v1",
            "request_id": _DIGEST,
            "trace_id": _DIGEST,
            "payload": {},
            "created_utc": _UTC,
            "classification": "D0",
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "ScientificResultEnvelope": {
            "schema_version": "ScientificResultEnvelope/v1",
            "result_id": _DIGEST,
            "request_id": _DIGEST,
            "status": "COMPLETED",
            "payload": {},
            "created_utc": _UTC,
            "classification": "D0",
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "ScientificRunReceipt": {
            "schema_version": "ScientificRunReceipt/v1",
            "receipt_id": _DIGEST,
            "request_id": _DIGEST,
            "terminal_status": "COMPLETED",
            "created_utc": _UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "ScientificImportReceipt": {
            "schema_version": "ScientificImportReceipt/v1",
            "receipt_id": _DIGEST,
            "source_packet_id": _DIGEST,
            "import_status": "IMPORTED_AS_C3",
            "created_utc": _UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "SRFPulse": {
            "schema_version": "SRFPulse/v1",
            "pulse_id": _DIGEST,
            "status": "GREEN",
            "observed_utc": _UTC,
            "head_sha": _HEAD,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "FederationStatus": {
            "schema_version": "FederationStatus/v1",
            "status_id": _DIGEST,
            "observed_utc": _UTC,
            "cells": [{"cell_id": "standalone", "status": "GREEN"}],
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "SpoolMessage": {
            "schema_version": "SpoolMessage/v1",
            "message_id": _DIGEST,
            "idempotency_key": _DIGEST,
            "source_cell": "srf",
            "target_cell": "market",
            "payload_ref": _DIGEST,
            "classification": "D0",
            "created_utc": _UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "SpoolAck": {
            "schema_version": "SpoolAck/v1",
            "ack_id": _DIGEST,
            "message_id": _DIGEST,
            "ack_status": "ACKNOWLEDGED",
            "created_utc": _UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "DeadLetterRecord": {
            "schema_version": "DeadLetterRecord/v1",
            "record_id": _DIGEST,
            "message_id": _DIGEST,
            "reason": "schema validation failed",
            "created_utc": _UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "CheckpointManifest": {
            "schema_version": "CheckpointManifest/v1",
            "checkpoint_id": _DIGEST,
            "run_id": _DIGEST,
            "artifact_refs": [_DIGEST],
            "created_utc": _UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
        "RestoreDrillReceipt": {
            "schema_version": "RestoreDrillReceipt/v1",
            "receipt_id": _DIGEST,
            "result": "PASS",
            "restored_artifacts": [_DIGEST],
            "created_utc": _UTC,
            "canonical_writes": 0,
            "grants_authority": False,
        },
    }


def test_s03_schema_names_registered() -> None:
    """All S03 schema names are explicit registry entries."""
    names = set(list_schemas())
    for name in _base_docs():
        assert name in names
    assert "LabAccessReceipt" in names


@pytest.mark.parametrize("schema_name", sorted(_base_docs()))
def test_s03_positive_documents_validate(schema_name: str) -> None:
    """Every new S03 schema accepts its minimal positive fixture."""
    validate(_base_docs()[schema_name], schema_name)


def test_labctl_receipt_validates_against_schema() -> None:
    """The S02 labctl receipt conforms to the S03 LabAccessReceipt schema."""
    validate(lab_access_receipt(), "LabAccessReceipt")


@pytest.mark.parametrize("schema_name", sorted(_base_docs()))
def test_s03_grants_authority_true_rejected(schema_name: str) -> None:
    """Authority-grant attempts fail closed across all new S03 schemas."""
    doc = _base_docs()[schema_name]
    doc["grants_authority"] = True
    with pytest.raises(ContractValidationError):
        validate(doc, schema_name)


@pytest.mark.parametrize("schema_name", sorted(_base_docs()))
def test_s03_additional_properties_rejected(schema_name: str) -> None:
    """Unknown fields are rejected so security-sensitive additions cannot pass silently."""
    doc = _base_docs()[schema_name]
    doc["orders_allowed"] = True
    with pytest.raises(ContractValidationError):
        validate(doc, schema_name)
