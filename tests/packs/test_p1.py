"""Tests for :mod:`srl.packs.p1` (P1 admission framework, WP-H70).

All tests are hermetic: they build a canonical policy dict in-process, exercise
the evaluator with synthetic candidate cards, and never touch the network or
the real pack store. The canonical packaged policy is also asserted to round
trip through :func:`build_p1_policy` so the on-disk document stays valid.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.packs.p1 import (
    FIRST_WAVE_CANDIDATES,
    P1_EVIDENCE_KINDS,
    P1_POLICY_SCHEMA_VERSION,
    P1_REQUIREMENTS,
    VERDICT_ADMIT_TO_PIPELINE,
    VERDICT_REJECT_CONTRACT,
    VERDICT_WAIT_CAPABILITY,
    VERDICT_WAIT_LICENSE,
    VERDICT_WAIT_RESOURCE,
    P1AdmissionError,
    build_p1_policy,
    default_p1_policy_path,
    evaluate_p1_candidate,
    load_default_p1_policy,
    load_p1_policy,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _canonical_policy() -> dict[str, Any]:
    """Return the canonical P1 policy dict as loaded from the on-disk document."""
    return json.loads((_REPO_ROOT / "policies" / "p1-admission.json").read_text(encoding="utf-8"))


def _full_card(candidate_id: str = "c.full") -> dict[str, Any]:
    """Return a candidate card carrying evidence for all eight requirements."""
    return {
        "candidate_id": candidate_id,
        "evidence": {rid: {"satisfied": True} for rid in P1_REQUIREMENTS},
    }


# ---------------------------------------------------------------------------
# Policy shape.
# ---------------------------------------------------------------------------


def test_canonical_policy_loads_and_round_trips() -> None:
    """The on-disk canonical policy is a valid P1AdmissionPolicy/v1 document."""
    policy = load_default_p1_policy()
    assert policy.schema_version == P1_POLICY_SCHEMA_VERSION
    assert policy.policy_id == "p1-admission-default"
    assert policy.canonical_writes == 0
    assert policy.grants_authority is False
    assert set(policy.requirements) == set(P1_REQUIREMENTS)
    assert policy.requirement_ids() == tuple(P1_REQUIREMENTS)
    for rid in P1_REQUIREMENTS:
        assert policy.requirements[rid].required is True
        assert policy.requirements[rid].evidence_kind in P1_EVIDENCE_KINDS


def test_default_policy_path_points_at_canonical_document() -> None:
    """default_p1_policy_path() resolves to policies/p1-admission.json."""
    assert default_p1_policy_path() == _REPO_ROOT / "policies" / "p1-admission.json"


def test_requirements_and_evidence_kinds_match_design() -> None:
    """The eight requirement ids and four evidence kinds are exactly as designed."""
    assert P1_REQUIREMENTS == (
        "unique_capability",
        "concrete_hypothesis",
        "license_closure",
        "platform_build",
        "resource_measurement",
        "actual_compute_adapter",
        "independent_scientific_role",
        "removal_rollback_path",
    )
    assert P1_EVIDENCE_KINDS == frozenset({"receipt", "document", "test", "measurement"})


# ---------------------------------------------------------------------------
# Evaluation: ADMIT and the four typed WAIT/REJECT verdicts.
# ---------------------------------------------------------------------------


def test_full_evidence_candidate_is_admitted() -> None:
    """A candidate carrying all eight requirements is ADMIT_TO_PIPELINE."""
    verdict = evaluate_p1_candidate(_full_card(), _canonical_policy())
    assert verdict.verdict == VERDICT_ADMIT_TO_PIPELINE
    assert verdict.missing == ()
    assert verdict.candidate_id == "c.full"


@pytest.mark.parametrize("rid", list(P1_REQUIREMENTS))
def test_each_missing_requirement_yields_typed_verdict(rid: str) -> None:
    """Removing exactly one requirement yields the expected typed verdict."""
    card = _full_card(candidate_id="c.solo")
    del card["evidence"][rid]
    verdict = evaluate_p1_candidate(card, _canonical_policy())

    expected: dict[str, str] = {
        "license_closure": VERDICT_WAIT_LICENSE,
        "resource_measurement": VERDICT_WAIT_RESOURCE,
        "removal_rollback_path": VERDICT_REJECT_CONTRACT,
    }
    assert verdict.verdict == expected.get(rid, VERDICT_WAIT_CAPABILITY)
    assert list(verdict.missing) == [rid]


def test_removal_path_gap_dominates_license_gap() -> None:
    """REJECT_CONTRACT outranks WAIT_LICENSE when both requirements are missing."""
    card = _full_card(candidate_id="c.dominates")
    del card["evidence"]["license_closure"]
    del card["evidence"]["removal_rollback_path"]
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert verdict.verdict == VERDICT_REJECT_CONTRACT
    assert list(verdict.missing) == ["license_closure", "removal_rollback_path"]


def test_license_gap_dominates_capability_gap() -> None:
    """WAIT_LICENSE outranks WAIT_CAPABILITY when both are missing."""
    card = _full_card(candidate_id="c.lic-over-cap")
    del card["evidence"]["license_closure"]
    del card["evidence"]["unique_capability"]
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert verdict.verdict == VERDICT_WAIT_LICENSE
    # missing is always emitted in canonical requirement order.
    assert list(verdict.missing) == ["unique_capability", "license_closure"]


def test_capability_gap_dominates_resource_gap() -> None:
    """WAIT_CAPABILITY outranks WAIT_RESOURCE when both are missing."""
    card = _full_card(candidate_id="c.cap-over-res")
    del card["evidence"]["unique_capability"]
    del card["evidence"]["resource_measurement"]
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert verdict.verdict == VERDICT_WAIT_CAPABILITY
    assert list(verdict.missing) == ["unique_capability", "resource_measurement"]


def test_resource_only_gap_yields_wait_resource() -> None:
    """Only resource_measurement missing yields WAIT_RESOURCE."""
    card = _full_card(candidate_id="c.res-only")
    del card["evidence"]["resource_measurement"]
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert verdict.verdict == VERDICT_WAIT_RESOURCE
    assert list(verdict.missing) == ["resource_measurement"]


def test_license_unknown_only_gap_yields_wait_license() -> None:
    """All requirements satisfied except license_closure yields WAIT_LICENSE."""
    card = {"candidate_id": "c.lic-unknown", "evidence": {}}
    for rid in P1_REQUIREMENTS:
        if rid != "license_closure":
            card["evidence"][rid] = {"satisfied": True}
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert verdict.verdict == VERDICT_WAIT_LICENSE
    assert list(verdict.missing) == ["license_closure"]


def test_empty_evidence_yields_reject_contract() -> None:
    """A card with no evidence: rollback gap dominates -> REJECT_CONTRACT."""
    card = {"candidate_id": "c.empty", "evidence": {}}
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert verdict.verdict == VERDICT_REJECT_CONTRACT
    assert list(verdict.missing) == list(P1_REQUIREMENTS)


def test_missing_list_in_canonical_order() -> None:
    """The missing list is always emitted in canonical requirement order."""
    card = _full_card(candidate_id="c.order")
    # Remove in reverse order; the missing list must still be canonical order.
    for rid in reversed(P1_REQUIREMENTS):
        del card["evidence"][rid]
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert list(verdict.missing) == list(P1_REQUIREMENTS)


# ---------------------------------------------------------------------------
# First-wave candidate cards (honest current state).
# ---------------------------------------------------------------------------


def test_first_wave_has_exactly_four_candidates() -> None:
    """The first wave comprises exactly the four named candidates."""
    ids = {c["candidate_id"] for c in FIRST_WAVE_CANDIDATES}
    assert ids == {"pymc_arviz", "cvxpy", "tigramite_dowhy", "pyoperon"}


@pytest.mark.parametrize(
    "card", FIRST_WAVE_CANDIDATES, ids=[c["candidate_id"] for c in FIRST_WAVE_CANDIDATES]
)
def test_first_wave_candidates_wait_with_explicit_missing(card: dict[str, Any]) -> None:
    """Each first-wave candidate is a typed WAIT with explicit missing evidence."""
    verdict = evaluate_p1_candidate(card, _canonical_policy())
    assert verdict.verdict.startswith("WAIT_")
    assert verdict.candidate_id == card["candidate_id"]
    assert len(verdict.missing) > 0
    for rid in verdict.missing:
        assert rid in P1_REQUIREMENTS


def test_first_wave_cards_carry_license_and_rollback_evidence() -> None:
    """Each first-wave card honestly declares upstream SPDX and a rollback path."""
    for card in FIRST_WAVE_CANDIDATES:
        # license_closure and removal_rollback_path are present as evidence so
        # the honest verdict is WAIT_CAPABILITY (the capability build is the
        # actual blocker), not WAIT_LICENSE/REJECT_CONTRACT.
        assert "license_closure" in card["evidence"]
        assert "removal_rollback_path" in card["evidence"]
        assert card["evidence"]["license_closure"]["cleared_against_policy"] is False


def test_first_wave_tigramite_declares_gpl_upstream() -> None:
    """The tigramite_dowhy card honestly records the GPL-3.0 upstream SPDX."""
    card = next(c for c in FIRST_WAVE_CANDIDATES if c["candidate_id"] == "tigramite_dowhy")
    spdx = card["evidence"]["license_closure"]["upstream_spdx"]
    assert "GPL-3.0" in spdx


# ---------------------------------------------------------------------------
# Contract errors (policy and candidate validation).
# ---------------------------------------------------------------------------


def test_policy_wrong_schema_version_rejected() -> None:
    """A policy with the wrong schema_version is CONTRACT_INVALID."""
    bad = _canonical_policy()
    bad["schema_version"] = "P1AdmissionPolicy/v0"
    with pytest.raises(P1AdmissionError) as exc_info:
        build_p1_policy(bad)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_policy_missing_requirement_rejected() -> None:
    """A policy missing one of the eight requirements is CONTRACT_INVALID."""
    bad = copy.deepcopy(_canonical_policy())
    del bad["requirements"]["license_closure"]
    with pytest.raises(P1AdmissionError) as exc_info:
        build_p1_policy(bad)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_policy_extra_requirement_rejected() -> None:
    """A policy with an unexpected requirement id is CONTRACT_INVALID."""
    bad = copy.deepcopy(_canonical_policy())
    bad["requirements"]["ninth_requirement"] = {"required": True, "evidence_kind": "document"}
    with pytest.raises(P1AdmissionError) as exc_info:
        build_p1_policy(bad)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_policy_bad_evidence_kind_rejected() -> None:
    """An evidence_kind outside the allowlist is CONTRACT_INVALID."""
    bad = copy.deepcopy(_canonical_policy())
    bad["requirements"]["unique_capability"]["evidence_kind"] = "vibe"
    with pytest.raises(P1AdmissionError) as exc_info:
        build_p1_policy(bad)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_policy_grants_authority_must_be_false() -> None:
    """grants_authority must be false for a P1 policy document."""
    bad = copy.deepcopy(_canonical_policy())
    bad["grants_authority"] = True
    with pytest.raises(P1AdmissionError) as exc_info:
        build_p1_policy(bad)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_policy_canonical_writes_must_be_zero() -> None:
    """canonical_writes must be 0 for a P1 policy document."""
    bad = copy.deepcopy(_canonical_policy())
    bad["canonical_writes"] = 1
    with pytest.raises(P1AdmissionError) as exc_info:
        build_p1_policy(bad)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_candidate_not_dict_rejected() -> None:
    """A candidate that is not a dict is CONTRACT_INVALID."""
    with pytest.raises(P1AdmissionError) as exc_info:
        evaluate_p1_candidate("not-a-card", _canonical_policy())  # type: ignore[arg-type]
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_candidate_missing_candidate_id_rejected() -> None:
    """A candidate card without candidate_id is CONTRACT_INVALID."""
    with pytest.raises(P1AdmissionError) as exc_info:
        evaluate_p1_candidate({"evidence": {}}, _canonical_policy())
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_candidate_missing_evidence_block_rejected() -> None:
    """A candidate card without an evidence block is CONTRACT_INVALID."""
    with pytest.raises(P1AdmissionError) as exc_info:
        evaluate_p1_candidate({"candidate_id": "c"}, _canonical_policy())
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_candidate_evidence_extra_requirement_rejected() -> None:
    """A candidate card with an unknown evidence key is CONTRACT_INVALID."""
    card = _full_card()
    card["evidence"]["unknown_requirement"] = {"x": 1}
    with pytest.raises(P1AdmissionError) as exc_info:
        evaluate_p1_candidate(card, _canonical_policy())
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_load_p1_policy_missing_file_rejected(tmp_path: Path) -> None:
    """Loading a nonexistent policy file raises P1AdmissionError."""
    with pytest.raises(P1AdmissionError) as exc_info:
        load_p1_policy(tmp_path / "does-not-exist.json")
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


def test_load_p1_policy_bad_json_rejected(tmp_path: Path) -> None:
    """Loading a malformed JSON policy raises P1AdmissionError."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(P1AdmissionError) as exc_info:
        load_p1_policy(bad)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON
