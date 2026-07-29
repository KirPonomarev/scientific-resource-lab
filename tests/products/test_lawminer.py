from __future__ import annotations

from typing import cast

import pytest

from srl.products import (
    DiscoveryPackStatus,
    LawMinerError,
    build_lawminer_admission_bundle,
    default_discovery_pack_cards,
    fit_linear_dynamics,
    fit_linear_law,
)


def test_discovery_pack_cards_record_wait_capabilities() -> None:
    cards = default_discovery_pack_cards()
    by_id = {card.pack_id: card for card in cards}

    assert by_id["lawminer.linear_baseline"].status is DiscoveryPackStatus.ACTIVE
    assert by_id["pysr"].status is DiscoveryPackStatus.WAIT_CAPABILITY
    assert by_id["pysindy"].status is DiscoveryPackStatus.WAIT_CAPABILITY
    assert by_id["pydmd"].status is DiscoveryPackStatus.WAIT_CAPABILITY


def test_admission_bundle_waits_when_optional_engines_are_not_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("srl.products.lawminer.importlib.util.find_spec", lambda _name: None)

    bundle = build_lawminer_admission_bundle()

    assert bundle["active_pack_ids"] == ["lawminer.linear_baseline"]
    assert "pysr" in cast(list[str], bundle["wait_pack_ids"])
    assert bundle["promotion_policy"] == "candidate_only_no_automatic_law_promotion"
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


def test_admission_bundle_remains_authority_negative_with_importable_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("srl.products.lawminer.importlib.util.find_spec", lambda _name: object())

    bundle = build_lawminer_admission_bundle()

    assert {"pysr", "pysindy", "pydmd"}.issubset(cast(list[str], bundle["active_pack_ids"]))
    assert bundle["promotion_policy"] == "candidate_only_no_automatic_law_promotion"
    assert bundle["canonical_writes"] == 0
    assert bundle["grants_authority"] is False


def test_linear_law_recovers_synthetic_fixture_without_promotion() -> None:
    x_values = tuple(float(i) for i in range(10))
    y_values = tuple(2.0 * x + 1.0 for x in x_values)

    receipt = fit_linear_law(
        x_values,
        y_values,
        train_indices=(0, 1, 2, 3, 4, 5),
        validation_indices=(6, 7, 8, 9),
        null_seed=17,
    )

    candidate = receipt["candidate"]
    assert isinstance(candidate, dict)
    assert candidate["slope"] == pytest.approx(2.0)
    assert candidate["intercept"] == pytest.approx(1.0)
    assert receipt["observed_above_null"] is True
    assert receipt["promotion_allowed"] is False
    assert receipt["prospective_holdout_materialization_allowed"] is False
    assert receipt["canonical_writes"] == 0
    assert receipt["grants_authority"] is False


def test_split_overlap_is_rejected_as_leakage() -> None:
    with pytest.raises(LawMinerError, match="must not overlap"):
        fit_linear_law(
            (0.0, 1.0, 2.0),
            (1.0, 3.0, 5.0),
            train_indices=(0, 1),
            validation_indices=(1, 2),
            null_seed=1,
        )


def test_linear_dynamics_fixture_is_candidate_only() -> None:
    series = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)

    receipt = fit_linear_dynamics(
        series,
        train_indices=(0, 1, 2),
        validation_indices=(3, 4),
        null_seed=3,
    )

    candidate = receipt["candidate"]
    assert isinstance(candidate, dict)
    assert candidate["form"] == "x_next = multiplier*x + intercept"
    assert candidate["slope"] == pytest.approx(2.0)
    assert receipt["promotion_allowed"] is False


def test_constant_x_is_rejected() -> None:
    with pytest.raises(LawMinerError, match="non-constant"):
        fit_linear_law(
            (1.0, 1.0, 1.0),
            (2.0, 2.0, 2.0),
            train_indices=(0, 1),
            validation_indices=(2,),
            null_seed=1,
        )
