"""Unit tests for deterministic resume reconciliation (``srl.autonomy.resume``).

The reconciler must answer "what next?" deterministically for a given observed
state. These tests pin:

1. Every row of the resume table selects the documented :class:`Decision`.
2. Only ``RECONCILE_MERGED`` permits merge; every other decision forbids it,
   and a failing check can never reach a merge-permitting decision.
3. The idempotency key is a stable 64-hex SHA-256 and changes when any of the
   five identity fields change.
4. Two reconciles over the same serialized state produce byte-identical JSON.
5. Type errors in the observed state raise loudly.
"""

from __future__ import annotations

import json

import pytest

from srl.autonomy.resume import (
    Decision,
    IdempotencyInputs,
    decision_to_json,
    idempotency_key,
    reconcile,
)

# Fixed identity inputs shared across table tests so the idempotency key is
# stable and the assertions focus on the decision.
_INPUTS = IdempotencyInputs(
    repository_id="KirPonomarev/scientific-resource-lab",
    mission_digest="0" * 64,
    wp_id="WP-A03",
    base_sha="1" * 40,
    policy_sha="2" * 64,
)


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        # Row: external commit -> terminal stop.
        ({"external_commit": True}, Decision.STOP_EXTERNAL),
        # Row: unknown dirty state -> terminal stop.
        ({"dirty": True}, Decision.STOP_DRIFT),
        # Row: inputs changed -> rerun.
        ({"inputs_changed": True}, Decision.RERUN),
        # Row: outputs verified -> noop.
        (
            {"output_hash": "h", "computed_output_hash": "h"},
            Decision.NOOP_VERIFIED,
        ),
        # Row: PR merged, checks failing -> stop (not merge).
        ({"pr_state": "merged", "checks_passed": False}, Decision.STOP_DRIFT),
        # Row: PR merged, checks passing -> the only merge-permitting decision.
        ({"pr_state": "merged", "checks_passed": True}, Decision.RECONCILE_MERGED),
        # Row: commit exists, checks failing -> update PR (not reuse, not merge).
        ({"commit_sha": "c" * 40, "checks_passed": False}, Decision.UPDATE_PR),
        # Row: commit exists, checks passing -> reuse.
        ({"commit_sha": "c" * 40, "checks_passed": True}, Decision.REUSE_COMMIT),
        # Row: open PR -> update it.
        ({"pr_state": "open"}, Decision.UPDATE_PR),
        # Default: no recognized prior state -> rerun.
        ({}, Decision.RERUN),
    ],
)
def test_resume_table_rows(observed: dict[str, object], expected: Decision) -> None:
    """Each resume-table row selects the documented decision."""
    decision = reconcile(_INPUTS, observed)
    assert decision.decision is expected


def test_only_reconcile_merged_permits_merge() -> None:
    """Only RECONCILE_MERGED has permits_merge == True."""
    rows = [
        {"external_commit": True},
        {"dirty": True},
        {"inputs_changed": True},
        {"output_hash": "h", "computed_output_hash": "h"},
        {"pr_state": "merged", "checks_passed": False},
        {"pr_state": "merged", "checks_passed": True},
        {"commit_sha": "c" * 40, "checks_passed": False},
        {"commit_sha": "c" * 40, "checks_passed": True},
        {"pr_state": "open"},
        {},
    ]
    merge_counts = sum(1 for obs in rows if reconcile(_INPUTS, obs).permits_merge)
    assert merge_counts == 1, "exactly one row should permit merge"


def test_failing_check_never_permits_merge() -> None:
    """A failing check cannot reach a merge-permitting decision.

    The merged-but-failing row downgrades to STOP_DRIFT, and the
    commit-but-failing row downgrades to UPDATE_PR; neither permits merge.
    """
    failing_states = [
        {"pr_state": "merged", "checks_passed": False},
        {"commit_sha": "c" * 40, "checks_passed": False},
        {"checks_passed": False},
    ]
    for obs in failing_states:
        decision = reconcile(_INPUTS, obs)
        assert not decision.permits_merge, f"failing-check state {obs} permitted merge"


def test_external_commit_takes_precedence() -> None:
    """An external commit is honored before any other row (terminal stop)."""
    # Even with a merged PR and passing checks, external_commit wins.
    decision = reconcile(
        _INPUTS,
        {"external_commit": True, "pr_state": "merged", "checks_passed": True},
    )
    assert decision.decision is Decision.STOP_EXTERNAL


def test_dirty_takes_precedence_over_inputs_changed() -> None:
    """Unknown dirty state beats inputs_changed."""
    decision = reconcile(_INPUTS, {"dirty": True, "inputs_changed": True})
    assert decision.decision is Decision.STOP_DRIFT


def test_outputs_verified_beats_merged_when_both_set() -> None:
    """Verified outputs are honored before the merged row.

    Verified outputs mean the work is done and verified; the merged/PR state
    is irrelevant in that case.
    """
    decision = reconcile(
        _INPUTS,
        {
            "output_hash": "h",
            "computed_output_hash": "h",
            "pr_state": "merged",
            "checks_passed": True,
        },
    )
    assert decision.decision is Decision.NOOP_VERIFIED


def test_idempotency_key_is_stable_64_hex() -> None:
    """The idempotency key is a stable 64-char hex SHA-256."""
    k1 = idempotency_key(_INPUTS)
    k2 = idempotency_key(_INPUTS)
    assert k1 == k2
    assert len(k1) == 64
    int(k1, 16)  # raises if not hex


def test_idempotency_key_changes_with_each_field() -> None:
    """Changing any of the five identity fields changes the key."""
    base = idempotency_key(_INPUTS)
    variants = [
        IdempotencyInputs(
            "other/repo",
            _INPUTS.mission_digest,
            _INPUTS.wp_id,
            _INPUTS.base_sha,
            _INPUTS.policy_sha,
        ),
        IdempotencyInputs(
            _INPUTS.repository_id, "f" * 64, _INPUTS.wp_id, _INPUTS.base_sha, _INPUTS.policy_sha
        ),
        IdempotencyInputs(
            _INPUTS.repository_id,
            _INPUTS.mission_digest,
            "WP-A04",
            _INPUTS.base_sha,
            _INPUTS.policy_sha,
        ),
        IdempotencyInputs(
            _INPUTS.repository_id,
            _INPUTS.mission_digest,
            _INPUTS.wp_id,
            "2" * 40,
            _INPUTS.policy_sha,
        ),
        IdempotencyInputs(
            _INPUTS.repository_id, _INPUTS.mission_digest, _INPUTS.wp_id, _INPUTS.base_sha, "3" * 64
        ),
    ]
    for v in variants:
        assert idempotency_key(v) != base


def test_two_reconciles_over_same_state_produce_identical_json() -> None:
    """Deterministic resume: same serialized state -> byte-identical JSON."""
    observed = {"pr_state": "open", "commit_sha": "c" * 40, "checks_passed": True}
    serialized = json.dumps(observed, sort_keys=True, separators=(",", ":"))
    run1 = decision_to_json(reconcile(_INPUTS, json.loads(serialized)))
    run2 = decision_to_json(reconcile(_INPUTS, json.loads(serialized)))
    assert run1 == run2


def test_decision_json_is_canonical() -> None:
    """The decision JSON is canonical (sorted keys, compact, one newline)."""
    decision = reconcile(_INPUTS, {"pr_state": "open"})
    raw = decision_to_json(decision)
    assert raw.endswith("\n")
    body = raw[:-1]
    assert ", " not in body
    assert ": " not in body
    parsed = json.loads(body)
    assert body == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def test_decision_json_includes_required_fields() -> None:
    """The serialized decision carries decision, key, rationale, permits_merge."""
    decision = reconcile(_INPUTS, {"commit_sha": "c" * 40, "checks_passed": True})
    parsed = json.loads(decision_to_json(decision))
    assert set(parsed) == {"decision", "idempotency_key", "permits_merge", "rationale"}
    assert parsed["decision"] == "REUSE_COMMIT"
    assert parsed["permits_merge"] is False


def test_bad_observed_field_type_raises() -> None:
    """A string|None observed field with the wrong type raises TypeError."""
    with pytest.raises(TypeError):
        reconcile(_INPUTS, {"commit_sha": 123})
    with pytest.raises(TypeError):
        reconcile(_INPUTS, {"pr_state": 5})


def test_output_hash_mismatch_is_not_verified() -> None:
    """A mismatch between expected and computed output hashes is not a noop."""
    decision = reconcile(_INPUTS, {"output_hash": "h1", "computed_output_hash": "h2"})
    # Mismatched hashes fall through to the default rerun.
    assert decision.decision is Decision.RERUN
