"""P1 pack-admission framework: typed candidate verdicts (WP-H70).

The P0 admission machine (:mod:`srl.packs.admission`) moves a single *already
built* pack through nine stages from ``DISCOVERED`` to
``EXPERIMENTAL_ACCEPTED``. P1 sits one layer above it: the decision to invest
in building an actual-compute adapter for a candidate external capability at
all.

A P1 candidate is an *external scientific capability* (an upstream library or
tool) that the SRL fabric could wrap with an actual-compute adapter. Before any
pack is built, eight machine-checkable requirements must each carry honest
evidence. :func:`evaluate_p1_candidate` reads a candidate card against a
:class:`P1AdmissionPolicy` and returns a :class:`P1Verdict` with a typed
outcome and the explicit list of missing requirement ids. Evidence is never
inferred: a requirement with no evidence is reported as missing.

Typed outcomes
--------------
A candidate is *admitted to the pipeline* only when every required requirement
carries evidence. Otherwise the verdict is typed by the most severe gap, in
this order of severity:

- ``REJECT_CONTRACT`` -- the candidate has no documented removal/rollback path.
  A capability we cannot cleanly remove must never enter the fabric, so this is
  the most severe gap and outranks every other missing requirement.
- ``WAIT_LICENSE`` -- the candidate has no license-closure receipt (the upstream
  SPDX has not been identified and cleared against the SRL pack policy).
- ``WAIT_CAPABILITY`` -- a capability-scoped requirement is missing: the
  capability is not unique, the hypothesis is not concrete, the platform build
  test is missing, the actual-compute adapter is absent, or the capability has
  no independent scientific role.
- ``WAIT_RESOURCE`` -- only ``resource_measurement`` is missing.
- ``ADMIT_TO_PIPELINE`` -- all eight requirements carry evidence.

Honest WAIT semantics
---------------------
The four first-wave P1 candidate cards (see :data:`FIRST_WAVE_CANDIDATES`) are
filled to their honest current state: most evidence is absent, so their
verdicts are ``WAIT_*``. That is correct and intentional: the P1 framework and
its machine-checkable gate exist *before* any of the first-wave packs are
built. An admission decision is never faked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Schema identity for the canonical policy document. Bumped only on a contract
# change to the policy shape.
P1_POLICY_SCHEMA_VERSION: Final[str] = "P1AdmissionPolicy/v1"

# The eight P1 admission requirements, in canonical (severity-rank) order. The
# order is the single source of truth for requirement identity and for the
# ``missing`` list ordering in a verdict.
P1_REQUIREMENTS: Final[tuple[str, ...]] = (
    "unique_capability",
    "concrete_hypothesis",
    "license_closure",
    "platform_build",
    "resource_measurement",
    "actual_compute_adapter",
    "independent_scientific_role",
    "removal_rollback_path",
)

# Allowed evidence kinds. Each requirement pins its kind in the policy document;
# this frozenset is the schema-level allowlist.
P1_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset({"receipt", "document", "test", "measurement"})

# The typed verdict outcomes, ordered from least to most severe so the verdict
# resolver picks the most severe applicable outcome.
VERDICT_ADMIT_TO_PIPELINE: Final[str] = "ADMIT_TO_PIPELINE"
VERDICT_WAIT_RESOURCE: Final[str] = "WAIT_RESOURCE"
VERDICT_WAIT_CAPABILITY: Final[str] = "WAIT_CAPABILITY"
VERDICT_WAIT_LICENSE: Final[str] = "WAIT_LICENSE"
VERDICT_REJECT_CONTRACT: Final[str] = "REJECT_CONTRACT"

VERDICTS: Final[tuple[str, ...]] = (
    VERDICT_ADMIT_TO_PIPELINE,
    VERDICT_WAIT_RESOURCE,
    VERDICT_WAIT_CAPABILITY,
    VERDICT_WAIT_LICENSE,
    VERDICT_REJECT_CONTRACT,
)

# Maps a missing requirement id to the verdict it forces. Requirements not in
# this map force the default ``WAIT_CAPABILITY`` outcome (the capability-class
# gap). ``removal_rollback_path`` is the contract gap and ``license_closure`` is
# the license gap; both override the default.
_REQUIREMENT_VERDICT: Final[dict[str, str]] = {
    "license_closure": VERDICT_WAIT_LICENSE,
    "resource_measurement": VERDICT_WAIT_RESOURCE,
    "removal_rollback_path": VERDICT_REJECT_CONTRACT,
}

# Severity rank of each verdict (higher = more severe). Used to resolve the
# single most severe gap when several requirements are missing. Mirrors the
# order in :data:`VERDICTS`.
_VERDICT_RANK: Final[dict[str, int]] = {verdict: i for i, verdict in enumerate(VERDICTS)}


class P1AdmissionError(ContractError):
    """Raised when a P1 policy document or candidate card violates its contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default.
    """

    def __init__(
        self,
        message: str,
        *,
        fail_reason: str = CONTRACT_INVALID_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


@dataclass(frozen=True, slots=True)
class P1RequirementSpec:
    """One machine-checkable admission requirement as declared by the policy.

    Attributes
    ----------
    requirement_id:
        One of :data:`P1_REQUIREMENTS`.
    required:
        Whether the requirement is mandatory. (The canonical policy marks all
        eight as required; the flag is kept so future relaxations are cheap.)
    evidence_kind:
        The expected evidence kind for this requirement, one of
        :data:`P1_EVIDENCE_KINDS`.
    """

    requirement_id: str
    required: bool
    evidence_kind: str


@dataclass(frozen=True, slots=True)
class P1AdmissionPolicy:
    """P1AdmissionPolicy/v1: the eight P1 admission requirements as a contract.

    Attributes
    ----------
    schema_version:
        Always ``P1AdmissionPolicy/v1``.
    policy_id:
        Stable policy identifier (e.g. ``p1-admission-default``).
    requirements:
        Mapping of requirement id to :class:`P1RequirementSpec`.
    canonical_writes:
        Always ``0`` (a policy is a read-only contract document).
    grants_authority:
        Always ``False`` (a policy declaration grants no scientific authority).
    """

    schema_version: str
    policy_id: str
    requirements: dict[str, P1RequirementSpec]
    canonical_writes: int
    grants_authority: bool

    def requirement_ids(self) -> tuple[str, ...]:
        """Return the required requirement ids in canonical order."""
        return tuple(rid for rid in P1_REQUIREMENTS if self.requirements[rid].required)


@dataclass(frozen=True, slots=True)
class P1Verdict:
    """A typed P1 admission verdict for one candidate.

    Attributes
    ----------
    candidate_id:
        The candidate identifier from the card.
    verdict:
        One of :data:`VERDICTS`.
    missing:
        Tuple of requirement ids whose evidence is absent, in canonical order.
        Empty iff ``verdict`` is ``ADMIT_TO_PIPELINE``.
    detail:
        Human-readable summary of the decision and the missing requirements.
    """

    candidate_id: str
    verdict: str
    missing: tuple[str, ...]
    detail: str


# ---------------------------------------------------------------------------
# Policy loading and validation.
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, field: str) -> str:
    """Return ``value`` if it is a non-empty string, else raise P1AdmissionError."""
    if not isinstance(value, str) or value == "":
        msg = f"{field} must be a non-empty string, got {value!r}"
        raise P1AdmissionError(msg)
    return value


def _build_requirement(requirement_id: str, raw: Any) -> P1RequirementSpec:
    """Build a :class:`P1RequirementSpec` from a raw dict and validate it."""
    if not isinstance(raw, dict):
        msg = f"requirement {requirement_id!r} must be an object, got {type(raw).__name__}"
        raise P1AdmissionError(msg)
    required_keys = {"required", "evidence_kind"}
    actual = set(raw.keys())
    missing = required_keys - actual
    if missing:
        msg = f"requirement {requirement_id!r} missing key(s): {sorted(missing)}"
        raise P1AdmissionError(msg)
    extra = actual - required_keys
    if extra:
        msg = f"requirement {requirement_id!r} has unexpected key(s): {sorted(extra)}"
        raise P1AdmissionError(msg)

    required = raw["required"]
    if not isinstance(required, bool):
        msg = (
            f"requirement {requirement_id!r}.required must be a bool, got {type(required).__name__}"
        )
        raise P1AdmissionError(msg)

    evidence_kind = raw["evidence_kind"]
    if not isinstance(evidence_kind, str):
        msg = (
            f"requirement {requirement_id!r}.evidence_kind must be a string, "
            f"got {type(evidence_kind).__name__}"
        )
        raise P1AdmissionError(msg)
    if evidence_kind not in P1_EVIDENCE_KINDS:
        msg = (
            f"requirement {requirement_id!r}.evidence_kind {evidence_kind!r} must be one of "
            f"{sorted(P1_EVIDENCE_KINDS)}"
        )
        raise P1AdmissionError(msg)
    return P1RequirementSpec(
        requirement_id=requirement_id, required=required, evidence_kind=evidence_kind
    )


def _check_keys(actual: set[str], expected: frozenset[str], what: str) -> None:
    """Raise P1AdmissionError if ``actual`` is missing or has extra keys."""
    missing = expected - actual
    if missing:
        msg = f"{what} missing required key(s): {sorted(missing)}"
        raise P1AdmissionError(msg)
    extra = actual - expected
    if extra:
        msg = f"{what} has unexpected key(s): {sorted(extra)}"
        raise P1AdmissionError(msg)


_POLICY_TOP_KEYS: Final[frozenset[str]] = frozenset(
    {"schema_version", "policy_id", "requirements", "canonical_writes", "grants_authority"}
)

# The set form of the eight requirement ids, for key-set validation.
_REQUIREMENT_IDS: Final[frozenset[str]] = frozenset(P1_REQUIREMENTS)


def _validate_policy_top(raw: Any) -> dict[str, Any]:
    """Validate the top-level dict shape and schema version; return the dict."""
    if not isinstance(raw, dict):
        msg = f"P1 policy must be an object, got {type(raw).__name__}"
        raise P1AdmissionError(msg)
    _check_keys(set(raw.keys()), _POLICY_TOP_KEYS, "P1 policy")
    schema_version = _require_non_empty_str(raw["schema_version"], "schema_version")
    if schema_version != P1_POLICY_SCHEMA_VERSION:
        msg = f"schema_version is {schema_version!r}, expected {P1_POLICY_SCHEMA_VERSION!r}"
        raise P1AdmissionError(msg)
    return raw


def _validate_requirements(raw: Any) -> dict[str, P1RequirementSpec]:
    """Validate the requirements block and return the built requirement specs."""
    if not isinstance(raw, dict):
        msg = f"requirements must be an object, got {type(raw).__name__}"
        raise P1AdmissionError(msg)
    _check_keys(set(raw.keys()), _REQUIREMENT_IDS, "requirements")
    return {rid: _build_requirement(rid, raw[rid]) for rid in P1_REQUIREMENTS}


def _validate_policy_tail(raw: dict[str, Any]) -> tuple[int, bool]:
    """Validate canonical_writes and grants_authority; return (writes, authority)."""
    canonical_writes = raw["canonical_writes"]
    if not isinstance(canonical_writes, int) or isinstance(canonical_writes, bool):
        msg = f"canonical_writes must be an integer, got {type(canonical_writes).__name__}"
        raise P1AdmissionError(msg)
    if canonical_writes != 0:
        msg = f"canonical_writes must be 0, got {canonical_writes!r}"
        raise P1AdmissionError(msg)

    grants_authority = raw["grants_authority"]
    if not isinstance(grants_authority, bool):
        msg = f"grants_authority must be a bool, got {type(grants_authority).__name__}"
        raise P1AdmissionError(msg)
    if grants_authority is not False:
        msg = f"grants_authority must be false, got {grants_authority!r}"
        raise P1AdmissionError(msg)
    return canonical_writes, grants_authority


def build_p1_policy(raw: Any) -> P1AdmissionPolicy:
    """Build and validate a :class:`P1AdmissionPolicy` from a raw dict.

    Parameters
    ----------
    raw:
        Raw JSON-decoded dict claiming to be a ``P1AdmissionPolicy/v1``.

    Returns
    -------
    P1AdmissionPolicy
        A validated, immutable policy.

    Raises
    ------
    P1AdmissionError
        With ``CONTRACT_INVALID`` if the structure, schema version, or any
        requirement is malformed.
    """
    value = _validate_policy_top(raw)
    policy_id = _require_non_empty_str(value["policy_id"], "policy_id")
    requirements = _validate_requirements(value["requirements"])
    canonical_writes, grants_authority = _validate_policy_tail(value)
    return P1AdmissionPolicy(
        schema_version=P1_POLICY_SCHEMA_VERSION,
        policy_id=policy_id,
        requirements=requirements,
        canonical_writes=canonical_writes,
        grants_authority=grants_authority,
    )


def load_p1_policy(path: str | Path) -> P1AdmissionPolicy:
    """Load a :class:`P1AdmissionPolicy` from a canonical JSON file.

    Parameters
    ----------
    path:
        Path to a ``P1AdmissionPolicy/v1`` JSON document.

    Returns
    -------
    P1AdmissionPolicy
        A validated, immutable policy.

    Raises
    ------
    P1AdmissionError
        If the file is missing, not valid JSON, or fails validation.
    """
    policy_path = Path(path)
    try:
        raw_text = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"could not read P1 policy {policy_path!s}: {exc}"
        raise P1AdmissionError(msg) from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        msg = f"P1 policy {policy_path!s} is not valid JSON: {exc}"
        raise P1AdmissionError(msg) from exc
    return build_p1_policy(raw)


def default_p1_policy_path() -> Path:
    """Return the repo-relative path to the canonical P1 policy document."""
    # src/srl/packs/p1.py -> repo root / policies / p1-admission.json
    return Path(__file__).resolve().parents[3] / "policies" / "p1-admission.json"


def load_default_p1_policy() -> P1AdmissionPolicy:
    """Load the canonical packaged P1 policy (``policies/p1-admission.json``)."""
    return load_p1_policy(default_p1_policy_path())


# ---------------------------------------------------------------------------
# Candidate evaluation.
# ---------------------------------------------------------------------------


def _validate_candidate_card(candidate: Any) -> dict[str, Any]:
    """Validate the structural shape of a candidate card and return it.

    A card is a dict with a non-empty ``candidate_id`` and an ``evidence`` block
    keyed by requirement id. The presence/absence of each requirement id is the
    only evidence signal P1 reads; richer evidence shapes belong to later
    work-packages.
    """
    if not isinstance(candidate, dict):
        msg = f"candidate must be an object, got {type(candidate).__name__}"
        raise P1AdmissionError(msg)
    candidate_id = _require_non_empty_str(candidate.get("candidate_id"), "candidate_id")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, dict):
        msg = (
            f"candidate {candidate_id!r} evidence must be an object, got {type(evidence).__name__}"
        )
        raise P1AdmissionError(msg)
    allowed = set(P1_REQUIREMENTS)
    extra = set(evidence.keys()) - allowed
    if extra:
        msg = (
            f"candidate {candidate_id!r} evidence has unexpected requirement id(s): {sorted(extra)}"
        )
        raise P1AdmissionError(msg)
    return candidate


def evaluate_p1_candidate(candidate: dict[str, Any], policy: dict[str, Any]) -> P1Verdict:
    """Evaluate a P1 candidate card against a policy document.

    Parameters
    ----------
    candidate:
        A candidate card dict with a non-empty ``candidate_id`` and an
        ``evidence`` block. A requirement id present in ``evidence`` means that
        requirement carries honest evidence; a requirement id absent means the
        evidence is missing.
    policy:
        A ``P1AdmissionPolicy/v1`` dict (or any dict accepted by
        :func:`build_p1_policy`). Required requirements drive the verdict.

    Returns
    -------
    P1Verdict
        The typed verdict with the explicit list of missing requirement ids.

    Raises
    ------
    P1AdmissionError
        With ``CONTRACT_INVALID`` if the policy or candidate card is malformed.

    Notes
    -----
    Evidence is never inferred. A requirement is satisfied only when its id is
    present in the candidate's ``evidence`` block. When requirements are missing
    the verdict is typed by the most severe gap: ``REJECT_CONTRACT`` (no removal
    path) outranks ``WAIT_LICENSE`` (no license closure) outranks
    ``WAIT_CAPABILITY`` (a capability-class gap) outranks ``WAIT_RESOURCE`` (no
    resource measurement).
    """
    validated_policy = build_p1_policy(policy)
    card = _validate_candidate_card(candidate)

    candidate_id: str = card["candidate_id"]
    evidence: dict[str, Any] = card["evidence"]

    missing: list[str] = [
        rid
        for rid in P1_REQUIREMENTS
        if validated_policy.requirements[rid].required and rid not in evidence
    ]

    if not missing:
        return P1Verdict(
            candidate_id=candidate_id,
            verdict=VERDICT_ADMIT_TO_PIPELINE,
            missing=(),
            detail=(
                f"candidate {candidate_id!r} admitted to the P1 pipeline: "
                "all eight requirements carry evidence"
            ),
        )

    # Resolve the single most severe verdict from the missing requirements.
    forced = sorted(
        (_REQUIREMENT_VERDICT.get(rid, VERDICT_WAIT_CAPABILITY) for rid in missing),
        key=lambda v: _VERDICT_RANK[v],
        reverse=True,
    )
    verdict = forced[0]
    return P1Verdict(
        candidate_id=candidate_id,
        verdict=verdict,
        missing=tuple(missing),
        detail=(
            f"candidate {candidate_id!r} held at {verdict}: missing evidence for {list(missing)}"
        ),
    )


# ---------------------------------------------------------------------------
# First-wave candidate cards (honest current state: most evidence absent).
# ---------------------------------------------------------------------------

#: Authoritative upstream SPDX identifiers for the first-wave candidates, from
#: PyPI metadata. These are *declarations of upstream intent*, not P1 license
#: receipts: a license_closure receipt is issued only after the SPDX is checked
#: against the SRL pack policy by the P0 admission machine.
_UPSTREAM_LICENSES: Final[dict[str, str]] = {
    "pymc_arviz": "Apache-2.0",
    "cvxpy": "Apache-2.0",
    "tigramite_dowhy": "Apache-2.0 AND MIT",
    "pyoperon": "MIT",
}

#: The four first-wave P1 candidate cards, filled to their honest current
#: state. None of them have a built actual-compute adapter, a measured resource
#: footprint, a platform build test, or a registered unique capability yet, so
#: most requirements carry no evidence. The cards exist so the P1 gate can
#: prove that the framework produces typed WAIT verdicts before any pack is
#: built. No card is faked into ADMIT.
FIRST_WAVE_CANDIDATES: Final[tuple[dict[str, Any], ...]] = (
    {
        "candidate_id": "pymc_arviz",
        "description": (
            "PyMC probabilistic-programming capability surfaced through ArviZ "
            "exploratory analysis and diagnostics"
        ),
        "upstream": {
            "pymc": {"pypi": "pymc", "license_spdx": "Apache-2.0"},
            "arviz": {"pypi": "arviz", "license_spdx": "Apache-2.0"},
        },
        "evidence": {
            # Upstream SPDX declared (Apache-2.0 for both); a license_closure
            # receipt is NOT yet recorded because no P0 pack has cleared the
            # SRL license policy for this candidate. Honest: WAIT_LICENSE-class.
            "license_closure": {
                "upstream_spdx": "Apache-2.0",
                "cleared_against_policy": False,
            },
            # A pip-uninstall + adapter-removal rollback path is documented.
            "removal_rollback_path": {
                "mechanism": "pip-uninstall adapter; drop capability from registry",
            },
        },
    },
    {
        "candidate_id": "cvxpy",
        "description": "CVXPY disciplined convex optimization capability",
        "upstream": {
            "cvxpy": {"pypi": "cvxpy", "license_spdx": "Apache-2.0"},
        },
        "evidence": {
            "license_closure": {
                "upstream_spdx": "Apache-2.0",
                "cleared_against_policy": False,
            },
            "removal_rollback_path": {
                "mechanism": "pip-uninstall adapter; drop capability from registry",
            },
        },
    },
    {
        "candidate_id": "tigramite_dowhy",
        "description": (
            "Tigramite time-series causal-graph estimation capability composed "
            "with the DoWhy causal-reasoning interface"
        ),
        "upstream": {
            "tigramite": {"pypi": "tigramite", "license_spdx": "GPL-3.0-or-later"},
            "dowhy": {"pypi": "dowhy", "license_spdx": "MIT"},
        },
        "evidence": {
            # Upstream SPDX declared (GPL-3.0-or-later for tigramite; the GPL
            # family is barred by the SRL pack policy). No license_closure
            # receipt: the composite closure has not been resolved. Honest:
            # WAIT_LICENSE-class (and, were it resolved, REJECT on GPL).
            "license_closure": {
                "upstream_spdx": "GPL-3.0-or-later AND MIT",
                "cleared_against_policy": False,
            },
            "removal_rollback_path": {
                "mechanism": "pip-uninstall adapter; drop capability from registry",
            },
        },
    },
    {
        "candidate_id": "pyoperon",
        "description": "PyOperon symbolic-regression capability",
        "upstream": {
            "pyoperon": {"pypi": "pyoperon", "license_spdx": "MIT"},
        },
        "evidence": {
            # Upstream SPDX declared via classifier only (MIT); PyPI metadata
            # carries no license_expression. No license_closure receipt until
            # the SPDX is confirmed against the LICENSE text. Honest:
            # WAIT_LICENSE-class.
            "license_closure": {
                "upstream_spdx": "MIT",
                "cleared_against_policy": False,
            },
            "removal_rollback_path": {
                "mechanism": "pip-uninstall adapter; drop capability from registry",
            },
        },
    },
)


__all__ = [
    "FIRST_WAVE_CANDIDATES",
    "P1_EVIDENCE_KINDS",
    "P1_POLICY_SCHEMA_VERSION",
    "P1_REQUIREMENTS",
    "VERDICTS",
    "VERDICT_ADMIT_TO_PIPELINE",
    "VERDICT_REJECT_CONTRACT",
    "VERDICT_WAIT_CAPABILITY",
    "VERDICT_WAIT_LICENSE",
    "VERDICT_WAIT_RESOURCE",
    "P1AdmissionError",
    "P1AdmissionPolicy",
    "P1RequirementSpec",
    "P1Verdict",
    "build_p1_policy",
    "default_p1_policy_path",
    "evaluate_p1_candidate",
    "load_default_p1_policy",
    "load_p1_policy",
]
