from __future__ import annotations

from typing import cast

import pytest

from srl.integrations import (
    MarketBridgeError,
    MarketBridgeStatus,
    build_market_bridge_health_projection,
    build_market_science_request,
    import_market_observation_packet,
)

_MARKET_HEAD = "59ce6ff4c8b514c93d8d4b26d648ba6e7dd7b764"


def _request() -> dict[str, object]:
    return build_market_science_request(
        objective="evaluate public synthetic volatility feature stability",
        market_head=_MARKET_HEAD,
        evidence_refs=("sha256:" + "1" * 64,),
    )


def _packet(request_id: str | None = None, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": "MarketScienceObservationPacket/v1",
        "observation_id": "sha256:" + "2" * 64,
        "request_id": request_id or cast(str, _request()["request_id"]),
        "market_head": _MARKET_HEAD,
        "payload": {"finding": "synthetic C3 proposal only"},
        "classification": "D0",
        "semantic_class": "C3_PROPOSAL",
        "authority_claimed": False,
        "trading_action": None,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    data.update(overrides)
    return data


def test_market_request_is_inactive_c3_and_schema_valid() -> None:
    request = _request()
    payload = cast(dict[str, object], request["payload"])

    assert request["schema_version"] == "ScientificRequestEnvelope/v1"
    assert payload["semantic_class"] == "C3_PROPOSAL"
    assert payload["activation_state"] == "INACTIVE"
    assert payload["central_projector_required"] is True
    assert payload["native_admission_required"] is True
    assert payload["trading_allowed"] is False
    assert request["canonical_writes"] == 0
    assert request["grants_authority"] is False


def test_market_request_rejects_live_trading_language() -> None:
    with pytest.raises(MarketBridgeError, match="forbidden"):
        build_market_science_request(
            objective="place order to buy BTC",
            market_head=_MARKET_HEAD,
        )


def test_market_request_rejects_private_path_material() -> None:
    with pytest.raises(MarketBridgeError, match="forbidden"):
        build_market_science_request(
            objective="inspect /Users/example/private.csv",
            market_head=_MARKET_HEAD,
        )


def test_market_observation_import_maps_to_c3_result() -> None:
    result = import_market_observation_packet(
        _packet(),
        expected_market_head=_MARKET_HEAD,
    )
    payload = cast(dict[str, object], result["payload"])

    assert result["schema_version"] == "ScientificResultEnvelope/v1"
    assert result["status"] == "COMPLETED"
    assert payload["semantic_class"] == "C3_PROPOSAL"
    assert payload["activation_state"] == "INACTIVE"
    assert payload["central_projector_required"] is True
    assert result["canonical_writes"] == 0
    assert result["grants_authority"] is False


def test_market_observation_rejects_authority_claim() -> None:
    with pytest.raises(MarketBridgeError, match="authority"):
        import_market_observation_packet(
            _packet(authority_claimed=True),
            expected_market_head=_MARKET_HEAD,
        )


def test_market_observation_rejects_trading_action() -> None:
    with pytest.raises(MarketBridgeError, match="trading action"):
        import_market_observation_packet(
            _packet(trading_action="buy"),
            expected_market_head=_MARKET_HEAD,
        )


def test_market_observation_rejects_duplicate_import() -> None:
    packet = _packet()
    with pytest.raises(MarketBridgeError, match="duplicate"):
        import_market_observation_packet(
            packet,
            expected_market_head=_MARKET_HEAD,
            seen_observation_ids=frozenset({cast(str, packet["observation_id"])}),
        )


def test_market_observation_rejects_stale_head() -> None:
    with pytest.raises(MarketBridgeError, match="stale"):
        import_market_observation_packet(
            _packet(market_head="0" * 40),
            expected_market_head=_MARKET_HEAD,
        )


def test_market_bridge_health_projection_is_inactive_wait_on_red() -> None:
    projection = build_market_bridge_health_projection(
        market_gate="RED_F8",
        market_head=_MARKET_HEAD,
    )

    assert projection["status"] == MarketBridgeStatus.WAIT_RUNTIME_HEALTH.value
    assert projection["activation_state"] == "INACTIVE"
    assert projection["market_writes"] == 0
    assert projection["live_actions"] == 0
    assert projection["trading_allowed"] is False
    assert projection["grants_authority"] is False
