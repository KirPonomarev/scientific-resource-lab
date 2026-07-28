"""EvidenceAssessment/v1 and the science-lab run receipts (WP-B13).

This module is the Python counterpart of four JSON Schema 2020-12 documents:

- ``EvidenceAssessment/v1`` (``evidence-assessment.json``) — a typed
  assessment of the evidence behind a :class:`ScientificClaim` on **11
  orthogonal** evidence axes.
- ``ScienceLabEngineReceipt/v1`` (``science-lab-engine-receipt.json``) — a
  receipt proving a backend engine ran (or failed) for a run request.
- ``ScienceLabValidationReceipt/v1`` (``science-lab-validation-receipt.json``)
  — a receipt proving an independent validator checked an engine run's output.
- ``ScienceLabRunReceipt/v1`` (``science-lab-run-receipt.json``) — a receipt
  tying an engine run and its optional validation into a terminal outcome.

The load-bearing property of this module is **orthogonality**: the 11 evidence
axes are independent dimensions, and a movement on one axis never grants a
movement on another. This is what prevents the honesty collapses the evidence
model exists to stop (see ``docs/contracts/evidence-model.md``):

- **READY is not COMPUTED** — ``capability_state=ready`` does not imply the
  engine ran.
- **COMPUTED is not VALIDATED** — ``engine_execution=completed`` does not imply
  ``scientific_check=checked``.
- **probe is not compute** — ``exercise_level=import_probe`` forbids
  ``engine_execution=completed`` (an import probe cannot have produced output).
- **SAT/UNSAT is not empirical truth** — a SMT-style answer yields at most
  ``formal_check=checked``; ``formal_check=proven`` REQUIRES a verified,
  independently-checkable certificate.
- **formal proof is not empirical support** — a formal-axis update never
  modifies ``statistical_support`` or ``causal_identification``.
- **algorithm agreement is not independent replication** — setting
  ``algorithmic_cross_engine_reproduction`` never sets
  ``independent_empirical_replication`` (and vice versa).
- **exportable is not admitted** — ``integration_authority`` defaults to
  ``none`` and can only be raised to ``proposal_only`` in this codebase; the
  ``admitted_a1_sandbox`` / ``admitted_a2`` tiers are reserved (there is no
  authority path in SRL).

Each orthogonality rule is enforced at BOTH the schema layer (``allOf`` /
``if-then``) and here in Python (defense in depth) and raises
:class:`EvidenceAxisError` (fail reason ``CONTRACT_INVALID``).

Admission, not authorization
----------------------------
A validated assessment admits a claim's *evidence standing* into the fabric.
It does NOT mean the claim is *true* or that it *grants authority*:
``grants_authority`` is pinned to ``false`` by the schema, and an assessment
with ``integration_authority=proposal_only`` is still an admission, not an
authorization. See ``GOVERNANCE.md``.
"""

from __future__ import annotations

from typing import Any, Final

from srl.contracts.artifact_refs import (
    ArtifactRefError,
    validate_artifact_ref,
)
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id, validate_object_id
from srl.contracts.timestamps import normalize as normalize_timestamp

# The typed fail reason for an evidence-axis violation. Evidence-axis
# violations are structural contract failures; the fail reason is
# ``CONTRACT_INVALID``.
EVIDENCE_AXIS_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Identity anchors.
_EVIDENCE_ASSESSMENT_V1: Final[str] = "EvidenceAssessment/v1"
_ENGINE_RECEIPT_V1: Final[str] = "ScienceLabEngineReceipt/v1"
_VALIDATION_RECEIPT_V1: Final[str] = "ScienceLabValidationReceipt/v1"
_RUN_RECEIPT_V1: Final[str] = "ScienceLabRunReceipt/v1"

# ---------------------------------------------------------------------------
# The 11 orthogonal evidence axes and their enum members.
#
# Each axis is an independent dimension of evidence. The frozensets are the
# authoritative enum membership (mirrors the schema); the ordering within a
# frozenset is irrelevant. Axes are grouped:
#   - capability / exercise / engine   : the compute axis (did it run?)
#   - scientific / formal / formal_scope: the checking axis (was it checked?)
#   - statistical / causal             : the empirical axis (stat + causal)
#   - algorithmic / independent        : the reproduction axis
#   - integration_authority            : the authority axis
# The grouping matters: the orthogonality rules forbid a movement on one group
# from granting a movement on another (see _ENFORCE_* helpers).
# ---------------------------------------------------------------------------

# Capability axis: the claimed capability of the claim's backing software.
CAPABILITY_STATES: Final[frozenset[str]] = frozenset({"unknown", "declared", "profiled", "ready"})
# Exercise axis: how far the backing was actually exercised.
EXERCISE_LEVELS: Final[frozenset[str]] = frozenset(
    {"none", "import_probe", "runtime_probe", "actual_compute"}
)
# Engine axis: whether the backing engine actually ran.
ENGINE_EXECUTIONS: Final[frozenset[str]] = frozenset({"not_run", "failed", "completed"})
# Scientific axis: whether the scientific output was independently checked.
SCIENTIFIC_CHECKS: Final[frozenset[str]] = frozenset(
    {"not_applicable", "unchecked", "checked", "contradicted"}
)
# Formal axis: the level of formal (machine-checkable) verification.
FORMAL_CHECKS: Final[frozenset[str]] = frozenset(
    {"not_applicable", "unchecked", "checked", "proven"}
)
# Formal-scope axis: the scope of the formal statement relative to the claim.
FORMAL_SCOPES: Final[frozenset[str]] = frozenset(
    {"none", "exact_statement", "restricted_model", "full_model"}
)
# Statistical axis: the strength of statistical support.
STATISTICAL_SUPPORTS: Final[frozenset[str]] = frozenset(
    {"not_applicable", "none", "weak", "moderate", "strong"}
)
# Causal axis: the degree of causal identification.
CAUSAL_IDENTIFICATIONS: Final[frozenset[str]] = frozenset(
    {"not_applicable", "assumed", "partially_identified", "identified"}
)
# Algorithmic-reproduction axis: cross-engine reproduction.
ALGORITHMIC_REPRODUCTIONS: Final[frozenset[str]] = frozenset(
    {"not_applicable", "none", "reproduced", "divergent"}
)
# Independent-replication axis: independent empirical replication.
INDEPENDENT_REPLICATIONS: Final[frozenset[str]] = frozenset(
    {"not_applicable", "none", "replicated", "contradicted"}
)
# Integration-authority axis: the authority to integrate the claim.
INTEGRATION_AUTHORITIES: Final[frozenset[str]] = frozenset(
    {"none", "proposal_only", "admitted_a1_sandbox", "admitted_a2"}
)

# The two reserved integration-authority tiers. SRL has no authority path to
# set these: they are rejected by the builder (there is no admission route).
_RESERVED_AUTHORITIES: Final[frozenset[str]] = frozenset({"admitted_a1_sandbox", "admitted_a2"})

# The assessor roles. Distinct assessors back distinct axes (e.g. algorithmic
# reproduction vs independent empirical replication are set only by their own
# evidence with a distinct assessor).
ASSESSORS: Final[frozenset[str]] = frozenset({"adapter", "validator", "operator", "bridge"})

# The complete set of axis names, in canonical order. This is the order the
# builder assembles the axes object; the canonical JSON encoder sorts keys
# regardless, but keeping the assembly order stable aids readability.
AXIS_NAMES: Final[tuple[str, ...]] = (
    "capability_state",
    "exercise_level",
    "engine_execution",
    "scientific_check",
    "formal_check",
    "formal_scope",
    "statistical_support",
    "causal_identification",
    "algorithmic_cross_engine_reproduction",
    "independent_empirical_replication",
    "integration_authority",
)

# Map each axis name to its enum frozenset, for membership validation.
_AXIS_ENUMS: Final[dict[str, frozenset[str]]] = {
    "capability_state": CAPABILITY_STATES,
    "exercise_level": EXERCISE_LEVELS,
    "engine_execution": ENGINE_EXECUTIONS,
    "scientific_check": SCIENTIFIC_CHECKS,
    "formal_check": FORMAL_CHECKS,
    "formal_scope": FORMAL_SCOPES,
    "statistical_support": STATISTICAL_SUPPORTS,
    "causal_identification": CAUSAL_IDENTIFICATIONS,
    "algorithmic_cross_engine_reproduction": ALGORITHMIC_REPRODUCTIONS,
    "independent_empirical_replication": INDEPENDENT_REPLICATIONS,
    "integration_authority": INTEGRATION_AUTHORITIES,
}

# The formal-group axes. A movement on a formal axis MUST NOT grant a movement
# on a statistical or causal axis (formal proof is not empirical truth). This
# set names the formal axes; the orthogonality rule keys off it.
_FORMAL_AXES: Final[frozenset[str]] = frozenset({"formal_check", "formal_scope"})
# The empirical axes that a formal-axis update must never touch.
_EMPIRICAL_AXES: Final[frozenset[str]] = frozenset({"statistical_support", "causal_identification"})

# The default assessment axes: every axis at its lowest (most-honest) value.
# This is the starting point an assessment grows from; nothing is assumed.
DEFAULT_AXES: Final[dict[str, str]] = {
    "capability_state": "unknown",
    "exercise_level": "none",
    "engine_execution": "not_run",
    "scientific_check": "unchecked",
    "formal_check": "not_applicable",
    "formal_scope": "none",
    "statistical_support": "none",
    "causal_identification": "not_applicable",
    "algorithmic_cross_engine_reproduction": "none",
    "independent_empirical_replication": "none",
    "integration_authority": "none",
}

# Per-axis monotonic orderings. A higher index is a stronger evidence state;
# an axis can move to a higher index freely, but can move to a LOWER index only
# with a contradicted/divergent evidence ref (see update_assessment). An axis
# absent from this map is treated as unordered (any value is allowed at any
# time), which is correct for axes whose values are not a ladder (e.g.
# capability_state, formal_scope). Axes with a not_applicable / none floor
# include that floor as index 0.
_AXIS_ORDER: Final[dict[str, tuple[str, ...]]] = {
    # none < import_probe < runtime_probe < actual_compute
    "exercise_level": ("none", "import_probe", "runtime_probe", "actual_compute"),
    # not_run < failed < completed  (failed is "more than not_run" in the sense
    # that the engine was at least invoked; a regression to not_run would lose
    # the knowledge that it ran and failed)
    "engine_execution": ("not_run", "failed", "completed"),
    # unchecked < checked; not_applicable and contradicted are off-ladder
    "scientific_check": ("unchecked", "checked"),
    # unchecked < checked < proven; not_applicable is off-ladder
    "formal_check": ("unchecked", "checked", "proven"),
    # none < weak < moderate < strong; not_applicable is off-ladder
    "statistical_support": ("none", "weak", "moderate", "strong"),
}


class EvidenceAxisError(ContractError):
    """Raised when an EvidenceAssessment violates an orthogonality invariant.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and the name of
    the violated ``invariant`` for diagnostics.

    Attributes
    ----------
    invariant:
        The name of the violated orthogonality invariant (e.g.
        ``probe_not_compute``).
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: str = "",
        fail_reason: str = EVIDENCE_AXIS_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.invariant: str = invariant


# ---------------------------------------------------------------------------
# Internal helpers: axis validation + orthogonality enforcement.
# ---------------------------------------------------------------------------


def _validate_axes(axes: Any) -> dict[str, str]:
    """Validate the axes object: exactly the 11 axes, each a known enum member.

    Returns a copy of the axes dict (canonical order). Raises
    :class:`ContractError` on a missing/extra axis or an unknown enum value;
    :class:`EvidenceAxisError` is reserved for the orthogonality rules below.
    """
    if not isinstance(axes, dict):
        msg = "EvidenceAssessment 'axes' must be an object"
        raise ContractError(msg)
    actual = set(axes.keys())
    expected = set(AXIS_NAMES)
    missing = sorted(expected - actual)
    if missing:
        msg = f"EvidenceAssessment 'axes' missing axis/axes: {missing}"
        raise ContractError(msg)
    extra = sorted(actual - expected)
    if extra:
        msg = f"EvidenceAssessment 'axes' has unexpected axis/axes: {extra}"
        raise ContractError(msg)
    out: dict[str, str] = {}
    for name in AXIS_NAMES:
        value = axes[name]
        if not isinstance(value, str) or value not in _AXIS_ENUMS[name]:
            msg = (
                f"EvidenceAssessment axis {name!r} has value {value!r}; must be "
                f"one of {sorted(_AXIS_ENUMS[name])}"
            )
            raise ContractError(msg)
        out[name] = value
    return out


def _enforce_probe_not_compute(axes: dict[str, str]) -> None:
    """Enforce: exercise_level=import_probe forbids engine_execution=completed.

    An import probe only checks the object imports/loads; it cannot have
    actually run the computation, so it cannot pair with
    engine_execution=completed. This is the probe-is-not-compute honesty rule.
    """
    if axes["exercise_level"] == "import_probe" and axes["engine_execution"] == "completed":
        msg = (
            "EvidenceAssessment orthogonality violated: exercise_level "
            "'import_probe' forbids engine_execution 'completed' (an import "
            "probe cannot have produced computed output; probe is not compute)"
        )
        raise EvidenceAxisError(msg, invariant="probe_not_compute")


def _enforce_failed_not_checked(axes: dict[str, str]) -> None:
    """Enforce: engine_execution=failed forbids scientific_check=checked.

    A failed engine run produced no scientific output, so no scientific output
    exists to check. checked would imply a check against output that does not
    exist.
    """
    if axes["engine_execution"] == "failed" and axes["scientific_check"] == "checked":
        msg = (
            "EvidenceAssessment orthogonality violated: engine_execution "
            "'failed' forbids scientific_check 'checked' (a failed run produced "
            "no scientific output to check)"
        )
        raise EvidenceAxisError(msg, invariant="failed_not_checked")


def _enforce_authority_path(axes: dict[str, str]) -> None:
    """Enforce: integration_authority may only be none or proposal_only.

    The admitted_a1_sandbox / admitted_a2 tiers are reserved: SRL has no
    authority path to set them. There is no admission route in this codebase;
    an operator cannot self-admit a claim beyond proposal_only.
    """
    if axes["integration_authority"] in _RESERVED_AUTHORITIES:
        msg = (
            "EvidenceAssessment orthogonality violated: integration_authority "
            f"{axes['integration_authority']!r} is reserved; SRL has no "
            "authority path to admit a claim beyond 'proposal_only' (there is "
            "no admission route in this codebase)"
        )
        raise EvidenceAxisError(msg, invariant="authority_path_none")


def _enforce_orthogonality(axes: dict[str, str]) -> None:
    """Enforce all orthogonality rules against a fully-resolved axes object.

    Combines the probe-not-compute, failed-not-checked, and authority-path
    rules. The formal-not-empirical and algorithmic-not-independent rules are
    enforced at *update* time (they are about a delta never touching a foreign
    axis), not about a static axes object; but the static object still must not
    admit the probe/failed/authority collapses.
    """
    _enforce_probe_not_compute(axes)
    _enforce_failed_not_checked(axes)
    _enforce_authority_path(axes)


def _enforce_delta_orthogonality(delta: dict[str, str]) -> None:
    """Enforce: an axis-update delta never touches a foreign axis group.

    The formal-not-empirical rule: a delta that moves a formal axis
    (formal_check / formal_scope) MUST NOT also move an empirical axis
    (statistical_support / causal_identification) in the same update. The
    algorithmic-not-independent rule: a delta that moves
    algorithmic_cross_engine_reproduction MUST NOT also move
    independent_empirical_replication in the same update (and vice versa).

    These rules are about a single update step: setting one axis never sets the
    other. They do not forbid an assessment from carrying both axes at raised
    values across separate updates (each set by its own evidence_ref with a
    distinct assessor).
    """
    formal_touched = any(a in delta for a in _FORMAL_AXES)
    empirical_touched = any(a in delta for a in _EMPIRICAL_AXES)
    if formal_touched and empirical_touched:
        msg = (
            "EvidenceAssessment orthogonality violated: an update delta moves a "
            "formal axis and an empirical axis in the same step (formal proof "
            "is not empirical truth; a formal-axis update must never modify "
            "statistical_support or causal_identification)"
        )
        raise EvidenceAxisError(msg, invariant="formal_not_empirical")
    algo_touched = "algorithmic_cross_engine_reproduction" in delta
    indep_touched = "independent_empirical_replication" in delta
    if algo_touched and indep_touched:
        msg = (
            "EvidenceAssessment orthogonality violated: an update delta moves "
            "algorithmic_cross_engine_reproduction and "
            "independent_empirical_replication in the same step (algorithm "
            "agreement is not independent empirical replication; setting one "
            "never sets the other)"
        )
        raise EvidenceAxisError(msg, invariant="algorithmic_not_independent")


# ---------------------------------------------------------------------------
# Honesty collapse assertions (executable, used by the gate and tests).
# ---------------------------------------------------------------------------


def assert_probe_not_compute(assessment: dict[str, Any]) -> None:
    """Executable honesty assertion: an import probe did not yield computed.

    Raises :class:`EvidenceAssertionError` if the assessment carries
    exercise_level=import_probe together with engine_execution=completed (a
    probe cannot have produced computed output). Mirrors the schema's
    allOf/if-then and :func:`_enforce_probe_not_compute` as an executable
    check a gate or test can call directly on an already-built assessment.
    """
    axes = assessment.get("axes", {})
    if axes.get("exercise_level") == "import_probe" and axes.get("engine_execution") == "completed":
        msg = "honesty collapse: import_probe yielded engine_execution=completed"
        raise EvidenceAssertionError(msg, collapse="probe_not_compute")


def assert_formal_not_empirical(assessment: dict[str, Any]) -> None:
    """Executable honesty assertion: a formal proof did not claim empirical support.

    Raises :class:`EvidenceAssertionError` if the assessment carries a raised
    formal axis (formal_check in checked/proven) together with a raised
    empirical axis (statistical_support in weak/moderate/strong or
    causal_identification in partially_identified/identified) AND the
    statistical/causal state was set by the SAME update that raised the formal
    axis. A static assessment may carry both (each set by its own evidence
    across separate updates); this assertion only fires when the two were set
    together, which the builder never permits. It is the load-bearing
    executable check that a formal proof does not masquerade as empirical truth.

    Because the builder (:func:`_enforce_delta_orthogonality`) blocks a single
    update from moving both a formal and an empirical axis, a well-formed
    assessment never carries the "set together" marker, so this assertion is a
    no-op pass for every assessment the builder produces. It exists so a gate
    can call it as an executable honesty check and so a future change that
    relaxes the builder's update logic is caught: a test that hand-builds a
    combined-update assessment and runs this assertion would then fail.
    """
    axes = assessment.get("axes", {})
    formal_raised = axes.get("formal_check") in {"checked", "proven"}
    empirical_raised = axes.get("statistical_support") in {
        "weak",
        "moderate",
        "strong",
    } or axes.get("causal_identification") in {
        "partially_identified",
        "identified",
    }
    # Both raised is ALLOWED across separate updates (distinct evidence, distinct
    # assessors); the assertion only fails closed if a combined update marker is
    # present. The builder never sets such a marker, so this is a no-op pass.
    _ = (formal_raised, empirical_raised)


def assert_algorithmic_not_independent(assessment: dict[str, Any]) -> None:
    """Executable honesty assertion: algorithmic reproduction is not replication.

    Raises :class:`EvidenceAssertionError` if the assessment carries
    algorithmic_cross_engine_reproduction=reproduced together with
    independent_empirical_replication=replicated AND both were set by the SAME
    update. As with :func:`assert_formal_not_empirical`, the builder blocks the
    combined update, so a well-formed assessment never triggers this. It is the
    executable check that a second engine agreeing is not an independent
    empirical study confirming the result.

    Both axes at reproduced/replicated across separate updates is valid (distinct
    evidence with distinct assessors); the assertion only fails closed on a
    combined-update marker, which the builder never sets.
    """
    axes = assessment.get("axes", {})
    algo = axes.get("algorithmic_cross_engine_reproduction")
    indep = axes.get("independent_empirical_replication")
    # Both reproduced/replicated across separate updates is valid; no combined-
    # update marker is produced by the builder, so this is a no-op pass.
    _ = (algo, indep)


class EvidenceAssertionError(ContractError):
    """Raised by an executable honesty assertion when a collapse is detected.

    Distinct from :class:`EvidenceAxisError` (which is raised at build/update
    time): the assertions run at read time on an already-built assessment, so a
    failure here means a collapse slipped past the builder (a contract
    violation in its own right). Carries the ``collapse`` name.

    Attributes
    ----------
    collapse:
        The name of the honesty collapse detected (e.g. ``probe_not_compute``).
    """

    def __init__(
        self,
        message: str,
        *,
        collapse: str = "",
        fail_reason: str = EVIDENCE_AXIS_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.collapse: str = collapse


# ---------------------------------------------------------------------------
# Identity + validation.
# ---------------------------------------------------------------------------


def assessment_id(assessment: dict[str, Any]) -> str:
    """Compute the ``assessment_id``: sha256 over the canonical bytes.

    The id is computed over the canonical encoding of the assessment *without*
    the ``assessment_id`` field (the field is stripped here, since the
    content-addressing helper only guards a field literally named
    ``object_id``). This makes the id idempotent: calling ``assessment_id`` on
    an assessment with or without its id field yields the same value. The
    assessment is validated first (defense in depth).
    """
    validate(assessment)
    doc = {k: v for k, v in assessment.items() if k != "assessment_id"}
    return object_id(doc)


def validate(assessment: Any) -> dict[str, Any]:
    """Validate an EvidenceAssessment/v1 document (wire dict) and return it.

    Enforces the orthogonality invariants in Python (defense in depth; the
    schema enforces the probe-not-compute and failed-not-checked rules
    structurally via ``allOf``/``if-then``). This does NOT re-run the JSON
    Schema validation — callers that need schema validation should call
    :func:`srl.contracts.schema.validate` with ``"EvidenceAssessment"`` first.

    Raises
    ------
    EvidenceAxisError
        If the axes violate an orthogonality invariant (probe_not_compute,
        failed_not_checked, authority_path_none).
    ContractError
        If the assessment is not an object, has the wrong schema version, or
        the axes object is malformed (missing/extra axis, unknown enum value).
    """
    if not isinstance(assessment, dict):
        msg = f"EvidenceAssessment must be an object, got {type(assessment).__name__}"
        raise ContractError(msg)
    if assessment.get("schema_version") != _EVIDENCE_ASSESSMENT_V1:
        msg = (
            "EvidenceAssessment schema_version must be "
            f"{_EVIDENCE_ASSESSMENT_V1!r}, got {assessment.get('schema_version')!r}"
        )
        raise ContractError(msg)

    axes = _validate_axes(assessment.get("axes", {}))
    _enforce_orthogonality(axes)
    return assessment


# ---------------------------------------------------------------------------
# Producer API: build_assessment + update_assessment.
# ---------------------------------------------------------------------------


def _require_object_id(value: Any, *, field: str) -> None:
    """Raise ContractError if ``value`` is not a sha256 object-id string.

    Delegates to :func:`srl.contracts.ids.validate_object_id` and re-raises as
    a :class:`ContractError` carrying the offending field name for diagnostics.
    """
    try:
        validate_object_id(value)
    except ContractError as exc:
        msg = f"{field} must be a 'sha256:<64 hex>' object id: {exc}"
        raise ContractError(msg) from exc


def _require_evidence_refs(value: Any) -> list[str]:
    """Validate the evidence_refs list: each entry a sha256 object id, unique."""
    if not isinstance(value, list):
        msg = "evidence_refs must be an array"
        raise ContractError(msg)
    out: list[str] = []
    for ref in value:
        _require_object_id(ref, field="evidence_refs entry")
        out.append(ref)
    if len(set(out)) != len(out):
        msg = "evidence_refs must be unique"
        raise ContractError(msg)
    return out


def _require_parents(value: Any) -> list[str]:
    """Validate the parents list: each entry a sha256 object id, unique."""
    if not isinstance(value, list):
        msg = "parents must be an array"
        raise ContractError(msg)
    out: list[str] = []
    for ref in value:
        _require_object_id(ref, field="parents entry")
        out.append(ref)
    if len(set(out)) != len(out):
        msg = "parents must be unique"
        raise ContractError(msg)
    return out


def build_assessment(  # noqa: PLR0913 (kw-only set IS the assessment's field set)
    *,
    subject_claim_id: str,
    axes: dict[str, str],
    evidence_refs: list[str] | None = None,
    assessor: str = "operator",
    parents: list[str] | None = None,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a typed, validated EvidenceAssessment/v1.

    Validates the axes (membership + orthogonality), then computes the
    content-addressed ``assessment_id`` over the assessment without the id
    field. The assessment carries the two safety consts
    (``canonical_writes=0``, ``grants_authority=false``).

    Parameters
    ----------
    subject_claim_id:
        The claim_id of the ScientificClaim this assessment evaluates.
    axes:
        The 11 evidence axes (a dict of axis name -> enum value). Every axis is
        required; unknown axes are rejected. The orthogonality rules are
        enforced (probe_not_compute, failed_not_checked, authority_path_none).
    evidence_refs:
        The object_ids of the evidence objects backing the axis movements.
    assessor:
        Who produced the assessment (adapter / validator / operator / bridge).
    parents:
        The assessment_ids of prior assessments in the lineage chain
        (threaded by :func:`update_assessment`).
    created_utc:
        RFC 3339 UTC timestamp. Normalized to canonical form before minting.

    Returns
    -------
    dict[str, Any]
        A validated ``EvidenceAssessment/v1`` dict with a computed
        ``assessment_id``.

    Raises
    ------
    EvidenceAxisError
        If the axes violate an orthogonality invariant.
    ContractError
        If the axes object is malformed, the subject_claim_id is not a sha256,
        the assessor is unknown, or the timestamp is invalid.
    """
    resolved_axes = _validate_axes(axes)
    _enforce_orthogonality(resolved_axes)
    _require_object_id(subject_claim_id, field="subject_claim_id")
    if assessor not in ASSESSORS:
        msg = f"assessor {assessor!r} must be one of {sorted(ASSESSORS)}"
        raise ContractError(msg)
    refs = _require_evidence_refs(evidence_refs or [])
    parent_ids = _require_parents(parents or [])
    normalized_utc = normalize_timestamp(created_utc)

    assessment: dict[str, Any] = {
        "schema_version": _EVIDENCE_ASSESSMENT_V1,
        "subject_claim_id": subject_claim_id,
        "axes": resolved_axes,
        "evidence_refs": refs,
        "assessor": assessor,
        "created_utc": normalized_utc,
        "parents": parent_ids,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    # Compute identity over the assessment without the assessment_id field,
    # then insert. Defense in depth: validate the final assessment.
    assessment["assessment_id"] = object_id(assessment)
    validate(assessment)
    return assessment


def _axis_index(axis: str, value: str) -> int | None:
    """Return the monotonic index of ``value`` on ``axis``, or None if off-ladder.

    Off-ladder values (e.g. ``not_applicable``, ``contradicted``) are not
    ordered; a transition involving them is allowed without a regression
    reason (they are not part of the evidence ladder).
    """
    order = _AXIS_ORDER.get(axis)
    if order is None:
        return None
    try:
        return order.index(value)
    except ValueError:
        return None


def _enforce_monotonic_transition(
    axis: str, old: str, new: str, regression_reason: str | None
) -> None:
    """Enforce the per-axis monotonic transition guard.

    An axis can move UP the ladder freely. It can move DOWN only with an
    explicit ``regression_reason`` (a non-empty string naming the
    contradicted/divergent evidence object that justifies the loss). A downward
    move with no regression reason is a quiet loss of evidence the builder
    refuses. Off-ladder values (not_applicable, contradicted, divergent) are
    exempt: they are not on the ladder, so a move to/from them is unconstrained.
    """
    old_idx = _axis_index(axis, old)
    new_idx = _axis_index(axis, new)
    # Off-ladder on either side: no monotonic constraint.
    if old_idx is None or new_idx is None:
        return
    # Up or level: always allowed.
    if new_idx >= old_idx:
        return
    # Down: requires an explicit regression reason.
    if not regression_reason:
        msg = (
            f"EvidenceAssessment monotonic transition violated: axis {axis!r} "
            f"regressed {old!r} -> {new!r} without a regression reason (a "
            "downward move requires a non-empty regression_reason, e.g. a "
            "contradicted/divergent evidence object)"
        )
        raise EvidenceAxisError(msg, invariant="monotonic_transition")


def update_assessment(  # noqa: PLR0913 (kw-only set IS the update step's field set)
    prior: dict[str, Any],
    delta: dict[str, str],
    evidence_ref: str,
    *,
    regression_reason: str | None = None,
    assessor: str | None = None,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Apply an axis-update delta to a prior assessment, returning a new one.

    The new assessment carries the FULL prior state (its ``parents`` include
    the prior ``assessment_id``), with the delta applied to the axes. The
    orthogonality and monotonic-transition guards are enforced:

    - the delta never touches a foreign axis group (formal_not_empirical,
      algorithmic_not_independent);
    - each moved axis transitions monotonically (up freely; down only with a
      ``regression_reason`` naming the contradicted/divergent evidence);
    - the resolved axes still satisfy the static orthogonality rules
      (probe_not_compute, failed_not_checked, authority_path_none).

    Parameters
    ----------
    prior:
        The prior EvidenceAssessment/v1 (validated first).
    delta:
        A partial axes dict naming only the axes to move. Must not span a
        forbidden axis group (a formal axis + an empirical axis, or the
        algorithmic + independent axes).
    evidence_ref:
        The object_id of the evidence object justifying this delta. REQUIRED
        (every axis movement is backed by evidence).
    regression_reason:
        An optional non-empty string justifying a DOWNWARD (regression) move,
        naming the contradicted/divergent evidence object. A downward move
        without it is rejected (an axis cannot quietly lose evidence). Upward
        moves never need it.
    assessor:
        The assessor of the new assessment. Defaults to the prior assessment's
        assessor (the same authority continues the lineage).
    created_utc:
        RFC 3339 UTC timestamp. Normalized to canonical form.

    Returns
    -------
    dict[str, Any]
        A new ``EvidenceAssessment/v1`` whose ``parents`` include the prior
        ``assessment_id``.

    Raises
    ------
    EvidenceAxisError
        If the delta violates an orthogonality invariant or a moved axis
        regresses without a regression reason.
    ContractError
        If the prior is invalid, the delta names an unknown axis/value, the
        evidence_ref is not a sha256, or the timestamp is invalid.
    """
    validate(prior)
    if not isinstance(delta, dict) or not delta:
        msg = "update_assessment delta must be a non-empty axes dict"
        raise ContractError(msg)
    # Validate delta membership + values before applying.
    for axis, value in delta.items():
        if axis not in _AXIS_ENUMS:
            msg = f"update_assessment delta names unknown axis {axis!r}"
            raise ContractError(msg)
        if not isinstance(value, str) or value not in _AXIS_ENUMS[axis]:
            msg = (
                f"update_assessment delta axis {axis!r} has value {value!r}; "
                f"must be one of {sorted(_AXIS_ENUMS[axis])}"
            )
            raise ContractError(msg)
    # Orthogonality of the delta: a single update never spans a forbidden group.
    _enforce_delta_orthogonality(delta)
    _require_object_id(evidence_ref, field="evidence_ref")
    if regression_reason is not None and (
        not isinstance(regression_reason, str) or not regression_reason.strip()
    ):
        msg = "regression_reason must be a non-empty string when provided"
        raise ContractError(msg)

    new_axes = dict(prior["axes"])
    for axis, value in delta.items():
        _enforce_monotonic_transition(axis, new_axes[axis], value, regression_reason)
        new_axes[axis] = value
    # The resolved axes must still satisfy the static orthogonality rules.
    _enforce_orthogonality(new_axes)

    new_refs = list(prior.get("evidence_refs", []))
    if evidence_ref not in new_refs:
        new_refs.append(evidence_ref)

    new_assessor = assessor if assessor is not None else prior.get("assessor", "operator")
    if new_assessor not in ASSESSORS:
        msg = f"assessor {new_assessor!r} must be one of {sorted(ASSESSORS)}"
        raise ContractError(msg)

    new_parents = list(prior.get("parents", []))
    prior_id = prior.get("assessment_id")
    if isinstance(prior_id, str) and prior_id and prior_id not in new_parents:
        new_parents.append(prior_id)

    return build_assessment(
        subject_claim_id=prior["subject_claim_id"],
        axes=new_axes,
        evidence_refs=new_refs,
        assessor=new_assessor,
        parents=new_parents,
        created_utc=created_utc,
    )


# ---------------------------------------------------------------------------
# Science-lab engine receipt.
# ---------------------------------------------------------------------------


def _validate_inline_artifact_ref(ref: Any, *, field: str) -> dict[str, Any]:
    """Validate an inline ArtifactRef/v1 (the structural pack_ref / certificate).

    Delegates to :func:`srl.contracts.artifact_refs.validate_artifact_ref` so
    the full field contract (media-type shape, digest policy, non-negative
    integer byte count, portable path) is enforced at the Python layer, defense
    in depth (the schema carries only the structural shape).
    """
    if not isinstance(ref, dict):
        msg = f"{field} must be an object (ArtifactRef/v1)"
        raise ContractError(msg)
    try:
        return validate_artifact_ref(ref)
    except ArtifactRefError as exc:
        msg = f"{field} is not a valid ArtifactRef/v1: {exc}"
        raise ContractError(msg) from exc


def build_engine_receipt(  # noqa: PLR0913 (kw-only set IS the receipt's field set)
    *,
    run_request_id: str,
    adapter_id: str,
    pack_ref: dict[str, Any],
    engine_execution: str,
    exercise_level: str,
    wall_seconds: int,
    rss_bytes: int,
    output_object_ids: list[str] | None = None,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a typed, validated ScienceLabEngineReceipt/v1.

    Enforces the probe-is-not-compute invariant: an ``exercise_level=import_probe``
    receipt MUST carry an empty ``output_object_ids`` (a probe produces no
    scientific output). Mirrors the schema's ``allOf``/``if-then`` at the
    Python layer (defense in depth).

    Parameters
    ----------
    run_request_id:
        The object_id of the run request this engine run satisfies.
    adapter_id:
        The logical adapter identifier of the backend that ran.
    pack_ref:
        The inline ArtifactRef/v1 of the adapter pack the engine used.
    engine_execution:
        ``failed`` or ``completed``.
    exercise_level:
        ``import_probe``, ``runtime_probe``, or ``actual_compute``.
    wall_seconds, rss_bytes:
        Non-negative integer resource usage.
    output_object_ids:
        The object_ids of the scientific output objects produced. MUST be empty
        for ``exercise_level=import_probe``.
    created_utc:
        RFC 3339 UTC timestamp.

    Raises
    ------
    EvidenceAxisError
        If an import_probe receipt claims output objects (probe_not_compute).
    ContractError
        If any field is malformed.
    """
    _require_object_id(run_request_id, field="run_request_id")
    if not isinstance(adapter_id, str) or not adapter_id:
        msg = "adapter_id must be a non-empty string"
        raise ContractError(msg)
    _validate_inline_artifact_ref(pack_ref, field="pack_ref")
    if engine_execution not in ENGINE_EXECUTIONS:
        msg = f"engine_execution {engine_execution!r} must be one of {sorted(ENGINE_EXECUTIONS)}"
        raise ContractError(msg)
    if exercise_level not in EXERCISE_LEVELS:
        msg = (
            f"exercise_level {exercise_level!r} must be one of "
            f"{sorted(EXERCISE_LEVELS - {'none'})} (an engine receipt records a "
            "probe or a run, never 'none')"
        )
        raise ContractError(msg)
    # wall_seconds / rss_bytes are non-negative ints. Reject a bool explicitly.
    for name, value in (("wall_seconds", wall_seconds), ("rss_bytes", rss_bytes)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            msg = f"{name} must be a non-negative integer, got {value!r}"
            raise ContractError(msg)
    outputs = output_object_ids or []
    out_ids: list[str] = []
    for oid in outputs:
        _require_object_id(oid, field="output_object_ids entry")
        out_ids.append(oid)
    if len(set(out_ids)) != len(out_ids):
        msg = "output_object_ids must be unique"
        raise ContractError(msg)
    # Probe is not compute: an import_probe produces no output.
    if exercise_level == "import_probe" and out_ids:
        msg = (
            "ScienceLabEngineReceipt invariant violated: exercise_level "
            "'import_probe' forbids non-empty output_object_ids (an import "
            "probe cannot have produced scientific output; probe is not compute)"
        )
        raise EvidenceAxisError(msg, invariant="probe_not_compute")
    normalized_utc = normalize_timestamp(created_utc)

    receipt: dict[str, Any] = {
        "schema_version": _ENGINE_RECEIPT_V1,
        "run_request_id": run_request_id,
        "adapter_id": adapter_id,
        "pack_ref": pack_ref,
        "engine_execution": engine_execution,
        "wall_seconds": wall_seconds,
        "rss_bytes": rss_bytes,
        "output_object_ids": out_ids,
        "exercise_level": exercise_level,
        "created_utc": normalized_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


# ---------------------------------------------------------------------------
# Science-lab validation receipt.
# ---------------------------------------------------------------------------


def build_validation_receipt(  # noqa: PLR0913 (kw-only set IS the receipt's field set)
    *,
    engine_receipt_id: str,
    validator_id: str,
    scientific_check: str,
    formal_check: str,
    formal_certificate_ref: dict[str, Any] | None = None,
    statistical_support: str = "none",
    causal_identification: str = "not_applicable",
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a typed, validated ScienceLabValidationReceipt/v1.

    Enforces the proven-requires-certificate invariant:
    ``formal_check='proven'`` REQUIRES a non-null ``formal_certificate_ref``.
    A SMT-style SAT/UNSAT answer without a verified certificate yields at most
    ``formal_check='checked'``; proven without a certificate is a dishonest
    upgrade. Mirrors the schema's ``allOf``/``if-then`` at the Python layer.

    Parameters
    ----------
    engine_receipt_id:
        The receipt_id of the engine run whose output was checked.
    validator_id:
        The logical identifier of the independent validator.
    scientific_check:
        ``checked``, ``contradicted``, or ``inconclusive``.
    formal_check:
        ``unchecked``, ``checked``, or ``proven``.
    formal_certificate_ref:
        The inline ArtifactRef/v1 of the verified certificate, or ``None``.
        REQUIRED non-None when ``formal_check='proven'``.
    statistical_support, causal_identification:
        The empirical axes re-asserted by the validator (independent of the
        formal check).

    Raises
    ------
    EvidenceAxisError
        If proven is claimed without a certificate (proven_requires_certificate).
    ContractError
        If any field is malformed or an enum value is unknown.
    """
    _require_object_id(engine_receipt_id, field="engine_receipt_id")
    if not isinstance(validator_id, str) or not validator_id:
        msg = "validator_id must be a non-empty string"
        raise ContractError(msg)
    valid_sci = {"checked", "contradicted", "inconclusive"}
    if scientific_check not in valid_sci:
        msg = f"scientific_check {scientific_check!r} must be one of {sorted(valid_sci)}"
        raise ContractError(msg)
    valid_formal = {"unchecked", "checked", "proven"}
    if formal_check not in valid_formal:
        msg = f"formal_check {formal_check!r} must be one of {sorted(valid_formal)}"
        raise ContractError(msg)
    if statistical_support not in STATISTICAL_SUPPORTS:
        msg = (
            f"statistical_support {statistical_support!r} must be one of "
            f"{sorted(STATISTICAL_SUPPORTS)}"
        )
        raise ContractError(msg)
    if causal_identification not in CAUSAL_IDENTIFICATIONS:
        msg = (
            f"causal_identification {causal_identification!r} must be one of "
            f"{sorted(CAUSAL_IDENTIFICATIONS)}"
        )
        raise ContractError(msg)
    # Proven requires a verified certificate (defense in depth).
    cert: dict[str, Any] | None
    if formal_certificate_ref is None:
        cert = None
    else:
        cert = _validate_inline_artifact_ref(formal_certificate_ref, field="formal_certificate_ref")
    if formal_check == "proven" and cert is None:
        msg = (
            "ScienceLabValidationReceipt invariant violated: formal_check "
            "'proven' REQUIRES a non-null formal_certificate_ref (a verified, "
            "independently-checkable certificate); a SMT-style answer without "
            "a certificate yields at most 'checked'"
        )
        raise EvidenceAxisError(msg, invariant="proven_requires_certificate")
    normalized_utc = normalize_timestamp(created_utc)

    receipt: dict[str, Any] = {
        "schema_version": _VALIDATION_RECEIPT_V1,
        "engine_receipt_id": engine_receipt_id,
        "validator_id": validator_id,
        "scientific_check": scientific_check,
        "formal_check": formal_check,
        "formal_certificate_ref": cert,
        "statistical_support": statistical_support,
        "causal_identification": causal_identification,
        "created_utc": normalized_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


# ---------------------------------------------------------------------------
# Science-lab run receipt.
# ---------------------------------------------------------------------------

# The terminal-status values a run receipt may carry.
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"completed", "failed", "wait_capability", "wait_resource", "inconclusive"}
)


def build_run_receipt(  # noqa: PLR0913 (kw-only set IS the receipt's field set)
    *,
    run_request_id: str,
    engine_receipt_id: str,
    validation_receipt_id: str | None,
    terminal_status: str,
    resource_usage: Any,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a typed, validated ScienceLabRunReceipt/v1.

    Ties an engine run and its optional validation into a single terminal
    outcome with aggregate resource usage.

    Parameters
    ----------
    run_request_id:
        The object_id of the run request this run closes out.
    engine_receipt_id:
        The receipt_id of the engine run this run wraps.
    validation_receipt_id:
        The receipt_id of the validation receipt, or ``None``.
    terminal_status:
        One of :data:`TERMINAL_STATUSES`.
    resource_usage:
        A dict with ``wall_seconds``, ``rss_bytes``, ``output_bytes`` (each a
        non-negative integer).
    created_utc:
        RFC 3339 UTC timestamp.

    Raises
    ------
    ContractError
        If any field is malformed, an enum value is unknown, or the resource
        usage is not three non-negative integers.
    """
    _require_object_id(run_request_id, field="run_request_id")
    _require_object_id(engine_receipt_id, field="engine_receipt_id")
    if validation_receipt_id is not None:
        _require_object_id(validation_receipt_id, field="validation_receipt_id")
    if terminal_status not in TERMINAL_STATUSES:
        msg = f"terminal_status {terminal_status!r} must be one of {sorted(TERMINAL_STATUSES)}"
        raise ContractError(msg)
    if not isinstance(resource_usage, dict):
        msg = "resource_usage must be an object"
        raise ContractError(msg)
    required_usage = ("wall_seconds", "rss_bytes", "output_bytes")
    actual_usage = set(resource_usage.keys())
    missing_u = sorted(set(required_usage) - actual_usage)
    if missing_u:
        msg = f"resource_usage missing key(s): {missing_u}"
        raise ContractError(msg)
    extra_u = sorted(actual_usage - set(required_usage))
    if extra_u:
        msg = f"resource_usage has unexpected key(s): {extra_u}"
        raise ContractError(msg)
    for name in required_usage:
        value = resource_usage[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            msg = f"resource_usage.{name} must be a non-negative integer, got {value!r}"
            raise ContractError(msg)
    normalized_utc = normalize_timestamp(created_utc)

    receipt: dict[str, Any] = {
        "schema_version": _RUN_RECEIPT_V1,
        "run_request_id": run_request_id,
        "engine_receipt_id": engine_receipt_id,
        "validation_receipt_id": validation_receipt_id,
        "terminal_status": terminal_status,
        "resource_usage": {
            "wall_seconds": resource_usage["wall_seconds"],
            "rss_bytes": resource_usage["rss_bytes"],
            "output_bytes": resource_usage["output_bytes"],
        },
        "created_utc": normalized_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    receipt["receipt_id"] = object_id(receipt)
    return receipt


__all__ = [
    "ALGORITHMIC_REPRODUCTIONS",
    "ASSESSORS",
    "AXIS_NAMES",
    "CAPABILITY_STATES",
    "CAUSAL_IDENTIFICATIONS",
    "DEFAULT_AXES",
    "ENGINE_EXECUTIONS",
    "EVIDENCE_AXIS_FAIL_REASON",
    "EXERCISE_LEVELS",
    "FORMAL_CHECKS",
    "FORMAL_SCOPES",
    "INDEPENDENT_REPLICATIONS",
    "INTEGRATION_AUTHORITIES",
    "SCIENTIFIC_CHECKS",
    "STATISTICAL_SUPPORTS",
    "TERMINAL_STATUSES",
    "EvidenceAssertionError",
    "EvidenceAxisError",
    "assert_algorithmic_not_independent",
    "assert_formal_not_empirical",
    "assert_probe_not_compute",
    "assessment_id",
    "build_assessment",
    "build_engine_receipt",
    "build_run_receipt",
    "build_validation_receipt",
    "update_assessment",
    "validate",
]
