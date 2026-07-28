"""Hermetic tests for the read-only P0 method implementations (WP-F51)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# The conftest makes the fake-transport module importable.
from fake_transport import FakeTransport, canned_payload  # type: ignore[import-not-found]

from srl.contracts.ids import object_id
from srl.mcp import methods as m
from srl.mcp.methods import (
    CONTRACT_INVALID,
    WAIT_CAPABILITY_FAIL_REASON,
    WAIT_ENVIRONMENT_FAIL_REASON,
    McpMethodError,
    MethodContext,
)
from srl.planning.request import build_request

# ---------------------------------------------------------------------------
# Claim / request builders.
# ---------------------------------------------------------------------------


def _minimal_claim() -> dict[str, Any]:
    """Return a valid ScientificClaim/v1 skeleton."""
    return {
        "schema_version": "ScientificClaim/v1",
        "statement": {"subject": "mass", "predicate": "equals", "object": "energy"},
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }


def _valid_claim() -> dict[str, Any]:
    """Return a valid claim with a computed claim_id."""
    claim = _minimal_claim()
    claim["claim_id"] = object_id(claim)
    return claim


def _valid_request(claim_id_value: str) -> dict[str, Any]:
    """Return a valid request engaging an applicable profile."""
    return build_request(
        claim_id=claim_id_value,
        requested_profiles=["algebra_exact"],
        created_utc="2026-07-28T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Safety consts are echoed on every result.
# ---------------------------------------------------------------------------


class TestSafetyConsts:
    """Every result echoes canonical_writes=0 and grants_authority=False."""

    def test_list_capabilities_echoes_safety_consts(self) -> None:
        out = m.m_list_capabilities(MethodContext(), {})
        assert out["canonical_writes"] == 0
        assert out["grants_authority"] is False


# ---------------------------------------------------------------------------
# list_capabilities / inspect_capability.
# ---------------------------------------------------------------------------


class TestListCapabilities:
    """``list_capabilities`` returns the shipped catalog read-only."""

    def test_returns_sorted_entries_with_digest(self) -> None:
        out = m.m_list_capabilities(MethodContext(), {})
        assert out["status"] == "SUCCESS"
        result = out["result"]
        assert result["catalog_digest"].startswith("sha256:")
        profiles = [e["profile"] for e in result["entries"]]
        assert profiles == sorted(profiles)
        assert "algebra_exact" in profiles


class TestInspectCapability:
    """``inspect_capability`` reads one catalog entry by profile."""

    def test_known_profile(self) -> None:
        out = m.m_inspect_capability(MethodContext(), {"profile": "algebra_exact"})
        assert out["status"] == "SUCCESS"
        entry = out["result"]["entry"]
        assert entry["profile"] == "algebra_exact"
        assert entry["availability"] in {"available", "future", "remote_required"}

    def test_unknown_profile_is_contract_invalid(self) -> None:
        with pytest.raises(McpMethodError) as exc_info:
            m.m_inspect_capability(MethodContext(), {"profile": "nope"})
        assert exc_info.value.fail_reason == CONTRACT_INVALID

    def test_missing_profile_is_contract_invalid(self) -> None:
        with pytest.raises(McpMethodError) as exc_info:
            m.m_inspect_capability(MethodContext(), {})
        assert exc_info.value.fail_reason == CONTRACT_INVALID


# ---------------------------------------------------------------------------
# validate_claim.
# ---------------------------------------------------------------------------


class TestValidateClaim:
    """``validate_claim`` validates the claim schema and invariants."""

    def test_valid_claim_returns_success(self) -> None:
        out = m.m_validate_claim(MethodContext(), {"claim": _valid_claim()})
        assert out["status"] == "SUCCESS"
        result = out["result"]
        assert result["valid"] is True
        assert result["claim_id"].startswith("sha256:")

    def test_invariant_violation_is_typed_invalid(self) -> None:
        # An established_law_reference asserted from an operator source (not
        # literature) violates the epistemic invariant. The schema and the
        # Python invariants both enforce this (defense in depth); either layer
        # may fire first, so the result carries a typed CONTRACT_INVALID with a
        # diagnostic pointer (an invariant name or a json_path).
        bad = _minimal_claim()
        bad["claim_class"] = "established_law_reference"
        bad["claim_id"] = object_id(bad)
        out = m.m_validate_claim(MethodContext(), {"claim": bad})
        assert out["status"] == "INVALID"
        assert out["fail_reason"] == CONTRACT_INVALID
        extra = out["extra"]
        assert extra is not None
        assert "invariant" in extra or "json_path" in extra

    def test_non_object_claim_raises(self) -> None:
        with pytest.raises(McpMethodError):
            m.m_validate_claim(MethodContext(), {"claim": "not-a-dict"})


# ---------------------------------------------------------------------------
# build_plan.
# ---------------------------------------------------------------------------


class TestBuildPlan:
    """``build_plan`` builds a plan with honest WAIT_CAPABILITY steps."""

    def test_valid_request_and_claim_builds_plan(self) -> None:
        claim = _valid_claim()
        request = _valid_request(claim["claim_id"])
        out = m.m_build_plan(MethodContext(), {"request": request, "claim": claim})
        assert out["status"] == "SUCCESS"
        plan = out["result"]["plan"]
        assert plan["schema_version"] == "ScienceLabPlan/v1"
        # The shipped catalog has no available adapter, so the requested profile
        # routes WAIT_CAPABILITY honestly.
        selections = {s["selection"] for s in plan["steps"]}
        assert "WAIT_CAPABILITY" in selections

    def test_missing_request_raises(self) -> None:
        with pytest.raises(McpMethodError):
            m.m_build_plan(MethodContext(), {"claim": _valid_claim()})


# ---------------------------------------------------------------------------
# inspect_run.
# ---------------------------------------------------------------------------


class TestInspectRun:
    """``inspect_run`` inspects a receipt without executing."""

    def test_valid_receipt_with_existing_output(self, tmp_path: Path) -> None:
        output = tmp_path / "out.json"
        output.write_text("{}", encoding="utf-8")
        receipt = {
            "schema_version": "RunReceipt/v1",
            "adapter_id": "echo.v1",
            "status": "completed",
            "usage": {"wall_seconds": 0.1, "rss_bytes": 0, "output_bytes": 2},
            "output_path": str(output),
        }
        out = m.m_inspect_run(MethodContext(), {"receipt": receipt})
        assert out["status"] == "SUCCESS"
        result = out["result"]
        assert result["output_exists"] is True
        assert result["valid"] is True

    def test_wrong_schema_version_raises(self) -> None:
        with pytest.raises(McpMethodError):
            m.m_inspect_run(MethodContext(), {"receipt": {"schema_version": "Other/v1"}})

    def test_receipt_path_loads_file(self, tmp_path: Path) -> None:
        receipt_path = tmp_path / "receipt.json"
        receipt_path.write_text(
            json.dumps(
                {"schema_version": "RunReceipt/v1", "status": "completed", "adapter_id": "x"}
            ),
            encoding="utf-8",
        )
        out = m.m_inspect_run(MethodContext(), {"receipt_path": str(receipt_path)})
        assert out["status"] == "SUCCESS"

    def test_bad_receipt_path_raises(self) -> None:
        with pytest.raises(McpMethodError):
            m.m_inspect_run(MethodContext(), {"receipt_path": "/no/such/file.json"})


# ---------------------------------------------------------------------------
# search_knowledge.
# ---------------------------------------------------------------------------


class TestSearchKnowledge:
    """``search_knowledge`` is offline by default and works with a fake transport."""

    def test_offline_default_is_wait_environment(self) -> None:
        out = m.m_search_knowledge(MethodContext(), {"endpoint_id": "openalex", "path": "/works"})
        assert out["status"] == "WAIT_ENVIRONMENT"
        assert out["fail_reason"] == WAIT_ENVIRONMENT_FAIL_REASON

    def test_fake_transport_returns_receipt(self, tmp_path: Path) -> None:
        transport = FakeTransport(
            canned_payload("openalex_works.json"), final_host="api.openalex.org"
        )
        ctx = MethodContext(transport=transport, cache_dir=str(tmp_path))
        out = m.m_search_knowledge(
            ctx,
            {"endpoint_id": "openalex", "path": "/works", "params": {}},
        )
        assert out["status"] == "SUCCESS"
        receipt = out["result"]["receipt"]
        assert receipt["schema_version"] == "QueryReceipt/v1"
        assert receipt["endpoint_id"] == "openalex"

    def test_unknown_endpoint_is_network_policy(self, tmp_path: Path) -> None:
        transport = FakeTransport(
            canned_payload("openalex_works.json"), final_host="api.openalex.org"
        )
        ctx = MethodContext(transport=transport, cache_dir=str(tmp_path))
        out = m.m_search_knowledge(ctx, {"endpoint_id": "unknown", "path": "/x"})
        assert out["status"] == "NETWORK_POLICY_VIOLATION"

    def test_missing_endpoint_id_raises(self) -> None:
        with pytest.raises(McpMethodError):
            m.m_search_knowledge(MethodContext(), {"path": "/works"})


# ---------------------------------------------------------------------------
# build_export_packet (honestly stubbed).
# ---------------------------------------------------------------------------


class TestBuildExportPacket:
    """``build_export_packet`` returns an honest WAIT_CAPABILITY, never faked."""

    def test_returns_wait_capability(self) -> None:
        out = m.m_build_export_packet(MethodContext(), {"plan_id": "sha256:abc"})
        assert out["status"] == "WAIT_CAPABILITY"
        assert out["fail_reason"] == WAIT_CAPABILITY_FAIL_REASON
        assert out["extra"]["dependents_on"] == "WP-I80"

    def test_non_object_args_raises(self) -> None:
        with pytest.raises(McpMethodError):
            m.m_build_export_packet(MethodContext(), "not-a-dict")  # type: ignore[arg-type]
