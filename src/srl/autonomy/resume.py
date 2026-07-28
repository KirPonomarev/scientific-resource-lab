"""Deterministic resume reconciliation for autonomous work.

When an autonomous run is interrupted and resumed, the reconciler must answer
one question deterministically: given what was *observed* on disk and on the
remote, what is the single correct next action? The answer must be the same
for the same inputs, on any machine, at any time, so that two resumes over
identical state produce byte-identical decisions.

This module implements the resume table from the implementation plan:

    output hash matches  -> NOOP_VERIFIED   (nothing to do; outputs verified)
    commit exists        -> REUSE_COMMIT    (skip recomputing/recommitting)
    PR exists            -> UPDATE_PR       (push new state to the open PR)
    PR merged            -> RECONCILE_MERGED(fetch main, reconcile, move on)
    inputs changed       -> RERUN           (recompute from the new inputs)
    unknown dirty state  -> STOP_DRIFT      (cannot reconcile safely; stop)
    external commit      -> STOP_EXTERNAL   (a non-mission commit landed; stop)

The table is encoded as an ordered list of rules (see :data:`_RULES`) and
evaluated in a fixed precedence order by :func:`reconcile`. The decision is
emitted as a plain :class:`ResumeDecision` dataclass that serializes to
canonical JSON via :func:`decision_to_json`. That serialized form is the
contract: two ``reconcile`` calls over the same observed state must yield
identical JSON bytes.

Idempotency key
---------------
The idempotency key is the SHA-256 of the canonical encoding of the ordered
tuple ``(repository_id, mission_digest, wp_id, base_sha, policy_sha)``. It
anchors resume: the same key means "the same work, against the same base,
under the same policy". A change to any field invalidates prior artifacts
bound to the old key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

# Canonical separators and newline contract, mirroring srl.canonical. Kept
# local so this module has no intra-package dependency and can be vendored.
_SEP: Final[tuple[str, str]] = (",", ":")
_NEWLINE: Final[str] = "\n"


class Decision(StrEnum):
    """The set of resume decisions.

    ``StrEnum`` keeps the serialized form a plain JSON string
    (``"NOOP_VERIFIED"``) while giving us enum membership tests. The order of
    members mirrors the precedence order of the resume table.
    """

    NOOP_VERIFIED = "NOOP_VERIFIED"
    REUSE_COMMIT = "REUSE_COMMIT"
    UPDATE_PR = "UPDATE_PR"
    RECONCILE_MERGED = "RECONCILE_MERGED"
    RERUN = "RERUN"
    STOP_DRIFT = "STOP_DRIFT"
    STOP_EXTERNAL = "STOP_EXTERNAL"

    @property
    def permits_merge(self) -> bool:
        """True iff this decision represents an already-merged state.

        Only :pyattr:`RECONCILE_MERGED` permits merge: it describes a PR that
        is already merged. Every other decision describes work that is not
        yet merged, or a stop that forbids merge. A failing check must map to
        a decision where ``permits_merge`` is ``False``.
        """
        return self is Decision.RECONCILE_MERGED


@dataclass(frozen=True)
class IdempotencyInputs:
    """The five inputs to the idempotency key.

    Attributes
    ----------
    repository_id:
        Stable identifier for the repository (e.g. ``owner/repo``).
    mission_digest:
        SHA-256 hex of the mission manifest.
    wp_id:
        Work-package identifier (e.g. ``WP-A03``).
    base_sha:
        The git commit sha the WP branched from.
    policy_sha:
        SHA-256 hex of the canonical policy document in force.
    """

    repository_id: str
    mission_digest: str
    wp_id: str
    base_sha: str
    policy_sha: str


@dataclass(frozen=True)
class ResumeDecision:
    """A reconcile result.

    Attributes
    ----------
    decision:
        The :class:`Decision` selected by the resume table.
    idempotency_key:
        SHA-256 hex of the canonical (repository_id, mission_digest, wp_id,
        base_sha, policy_sha) tuple.
    rationale:
        Short human-readable string naming the table row that fired.
    permits_merge:
        Convenience mirror of :pyattr:`Decision.permits_merge` so a serialized
        decision states its merge posture explicitly.
    """

    decision: Decision
    idempotency_key: str
    rationale: str
    permits_merge: bool


@dataclass(frozen=True)
class _Observed:
    """Normalized view of the observed runtime state.

    All fields are optional in the raw ``observed`` dict; here they are
    materialized with defaults so the rule predicates read as plain booleans
    and strings. ``None`` for the hash/sha/state fields means "unknown".
    """

    output_hash: str | None
    computed_output_hash: str | None
    commit_sha: str | None
    pr_state: str | None
    inputs_changed: bool
    external_commit: bool
    checks_passed: bool
    dirty: bool


@dataclass(frozen=True)
class _Rule:
    """A resume-table row: a predicate and the decision it yields.

    The first row whose predicate matches the normalized observed state wins.
    Encoding the table as data keeps :func:`reconcile` linear and its
    precedence order auditable in one place.
    """

    name: str
    predicate: Callable[[_Observed], bool]
    decision: Decision
    rationale: str


def _parse_observed(observed: dict[str, Any]) -> _Observed:
    """Coerce a raw observed dict into the normalized :class:`_Observed`.

    Type-checks the string|None fields so the table logic is clean and a
    malformed observed state fails loudly rather than silently mis-routing.
    """
    for fname in ("output_hash", "computed_output_hash", "commit_sha", "pr_state"):
        fval = observed.get(fname)
        if fval is not None and not isinstance(fval, str):
            msg = f"observed state field {fname!r} must be a string or None"
            raise TypeError(msg)
    return _Observed(
        output_hash=observed.get("output_hash"),
        computed_output_hash=observed.get("computed_output_hash"),
        commit_sha=observed.get("commit_sha"),
        pr_state=observed.get("pr_state"),
        inputs_changed=bool(observed.get("inputs_changed", False)),
        external_commit=bool(observed.get("external_commit", False)),
        checks_passed=bool(observed.get("checks_passed", True)),
        dirty=bool(observed.get("dirty", False)),
    )


# --- Predicates. One per table concern, kept as named functions so the rule ---
# --- table reads as data and each predicate is independently checkable. ------


def _is_external(obs: _Observed) -> bool:
    """External (non-mission) commit on the target branch."""
    return obs.external_commit


def _is_dirty(obs: _Observed) -> bool:
    """Working tree in an unknown dirty state."""
    return obs.dirty


def _inputs_changed(obs: _Observed) -> bool:
    """WP inputs changed since the last recorded run."""
    return obs.inputs_changed


def _outputs_verified(obs: _Observed) -> bool:
    """Expected and computed output hashes are both present and equal."""
    return (
        obs.output_hash is not None
        and obs.computed_output_hash is not None
        and obs.output_hash == obs.computed_output_hash
    )


def _merged_checks_failing(obs: _Observed) -> bool:
    """PR merged but the gate checks are failing (untrustworthy merge)."""
    return obs.pr_state == "merged" and not obs.checks_passed


def _merged_checks_passing(obs: _Observed) -> bool:
    """PR merged and the gate checks are passing (admissible merge)."""
    return obs.pr_state == "merged" and obs.checks_passed


def _commit_checks_failing(obs: _Observed) -> bool:
    """Mission commit exists but checks are failing (push, do not reuse)."""
    return obs.commit_sha is not None and not obs.checks_passed


def _commit_checks_passing(obs: _Observed) -> bool:
    """Mission commit exists and checks pass (reuse, do not recompute)."""
    return obs.commit_sha is not None and obs.checks_passed


def _pr_open(obs: _Observed) -> bool:
    """An open (not merged) PR exists."""
    return obs.pr_state == "open"


# The resume table, in precedence order. The first matching row wins. The two
# check-sensitive rows (merged, commit) are split into a passing-check and a
# failing-check variant so a failing check can never permit a merge and the
# downgrade is visible in the table itself.
_RULES: Final[tuple[_Rule, ...]] = (
    _Rule(
        "external_commit",
        _is_external,
        Decision.STOP_EXTERNAL,
        "external commit detected on target branch",
    ),
    _Rule("dirty", _is_dirty, Decision.STOP_DRIFT, "working tree in unknown dirty state"),
    _Rule(
        "inputs_changed",
        _inputs_changed,
        Decision.RERUN,
        "WP inputs changed since last recorded run",
    ),
    _Rule(
        "outputs_verified",
        _outputs_verified,
        Decision.NOOP_VERIFIED,
        "output hash matches; outputs verified",
    ),
    _Rule(
        "merged_checks_failing",
        _merged_checks_failing,
        Decision.STOP_DRIFT,
        "PR merged but checks failing; reconcile manually",
    ),
    _Rule(
        "merged_checks_passing",
        _merged_checks_passing,
        Decision.RECONCILE_MERGED,
        "PR already merged; reconcile against main",
    ),
    _Rule(
        "commit_checks_failing",
        _commit_checks_failing,
        Decision.UPDATE_PR,
        "commit exists but checks failing; update the PR",
    ),
    _Rule(
        "commit_checks_passing",
        _commit_checks_passing,
        Decision.REUSE_COMMIT,
        "mission commit exists for this WP",
    ),
    _Rule("pr_open", _pr_open, Decision.UPDATE_PR, "open PR exists; push new state to it"),
)


def _canonical_json(value: Any) -> str:
    """Encode ``value`` as canonical JSON (sorted keys, compact, ASCII)."""
    return json.dumps(value, sort_keys=True, separators=_SEP, ensure_ascii=True)


def idempotency_key(inputs: IdempotencyInputs) -> str:
    """Compute the SHA-256 idempotency key for ``inputs``.

    The key is the SHA-256 hex of the canonical JSON encoding of the ordered
    tuple ``[repository_id, mission_digest, wp_id, base_sha, policy_sha]``.
    A list (not a dict) fixes the field order, so the key is independent of
    dict insertion order and stable across implementations.
    """
    payload = [
        inputs.repository_id,
        inputs.mission_digest,
        inputs.wp_id,
        inputs.base_sha,
        inputs.policy_sha,
    ]
    blob = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def reconcile(inputs: IdempotencyInputs, observed: dict[str, Any]) -> ResumeDecision:
    """Reconcile observed state against the resume table and decide.

    Parameters
    ----------
    inputs:
        The identity fields (:class:`IdempotencyInputs`) that anchor the
        idempotency key: repository, mission, WP, base, policy. Together they
        identify "the same work, same base, same policy".
    observed:
        The observed runtime state. Recognized keys (all optional; their
        presence drives the table):

        - ``output_hash`` (str|None): hash of the WP's expected outputs.
        - ``computed_output_hash`` (str|None): hash of outputs on disk.
        - ``commit_sha`` (str|None): a mission commit for this WP, if any.
        - ``pr_state`` (str|None): one of ``"open"``, ``"merged"``, ``None``.
        - ``inputs_changed`` (bool): whether WP inputs changed since last run.
        - ``external_commit`` (bool): a non-mission commit is on the target.
        - ``checks_passed`` (bool): whether gate checks currently pass.
        - ``dirty`` (bool): whether the tree is in an unknown dirty state.

    Returns
    -------
    ResumeDecision
        The selected decision, the idempotency key, a rationale naming the
        table row, and the merge posture.

    Raises
    ------
    TypeError
        If a recognized observed field has the wrong type.

    Notes
    -----
    The table is evaluated in a fixed precedence order (see :data:`_RULES`)
    so the decision is deterministic. A failing check forbids any
    merge-permitting decision: the merged/commit rows split into a
    passing-check and failing-check variant, and the failing variants never
    permit merge.
    """
    key = idempotency_key(inputs)
    obs = _parse_observed(observed)
    for rule in _RULES:
        if rule.predicate(obs):
            return ResumeDecision(
                decision=rule.decision,
                idempotency_key=key,
                rationale=rule.rationale,
                permits_merge=rule.decision.permits_merge,
            )
    # Default: no recognized prior state -> recompute from scratch.
    return ResumeDecision(
        decision=Decision.RERUN,
        idempotency_key=key,
        rationale="no recognized prior state; run the WP",
        permits_merge=Decision.RERUN.permits_merge,
    )


def decision_to_json(decision: ResumeDecision) -> str:
    """Serialize a :class:`ResumeDecision` to canonical JSON + trailing newline.

    The serialized form is the contract for deterministic resume: two
    decisions over the same state must produce byte-identical output here.
    Fields are emitted in sorted key order with compact separators.
    """
    payload: dict[str, Any] = {
        "decision": decision.decision.value,
        "idempotency_key": decision.idempotency_key,
        "permits_merge": decision.permits_merge,
        "rationale": decision.rationale,
    }
    return _canonical_json(payload) + _NEWLINE
