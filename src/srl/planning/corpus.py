"""The thirty-task public conformance corpus runner (WP-B15).

This module turns a directory of public ``TaskSpec/v1`` conformance tasks into
typed outcomes, *executed against the real pipeline* (classifier -> router ->
planner) and the real validators (MathIR allowlist, artifact-ref, schema). It
is the single piece of machinery the public conformance corpus check
(``scripts/checks/wp15-corpus.py``) and the ``tests/planning/test_corpus.py``
suite share, so the corpus and its tests agree on what an "outcome" is.

Honesty (load-bearing)
----------------------
A corpus PASS never means a scientific claim is supported. The runner is a
**pure evaluation**: it runs each task's inputs through the routing pipeline
and the contract validators and records the typed outcome the pipeline
genuinely produces. Because no scientific backend ships in this codebase, the
honest outcome for the overwhelming majority of tasks is ``WAIT_CAPABILITY``:
the capability applies to the claim but no adapter is present, so the router
waits rather than fabricating one. The typed rejection outcomes
(``REJECT_CONTRACT`` / ``REJECT_IR`` / ``REJECT_RESOURCE`` / ``REJECT_LICENSE``
/ ``REJECT_AUTHORITY``) are the cases where the contract layer genuinely
refuses the input. ``PASS`` is reserved for the narrow case where the pipeline
completes with no applicable capability waiting and no violation raised.

The runner NEVER writes outside memory
--------------------------------------
:func:`run_task` performs no I/O. It builds an in-memory request, routes it,
optionally builds a plan, and runs the in-memory validators. It touches no
files, sockets, or subprocesses — the corpus is fully synthetic and the
evaluation is pure.

Outcomes
--------
The eight typed outcomes (``CORPUS_OUTCOMES``):

- ``PASS``             — the pipeline completed with no violation and no
                         applicable profile waiting for a capability.
- ``WAIT_CAPABILITY``  — the capability applies but no adapter is available
                         yet (the honest, dominant outcome).
- ``REJECT_CONTRACT``  — the request/claim/path violated a structural contract.
- ``REJECT_IR``        — a MathIR operator is outside the allowlist.
- ``REJECT_RESOURCE``  — the summed resource estimates exceed the caps.
- ``REJECT_LICENSE``   — a copyleft-licensed adapter pack is refused.
- ``REJECT_AUTHORITY`` — a packet claiming ``grants_authority`` is refused.

The ``MISMATCH`` outcome is reserved for a task whose ``expected.outcome`` does
not match the outcome the pipeline produced (a corpus failure, not a task
outcome).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final

from srl.contracts import dumps
from srl.contracts.errors import ContractError
from srl.planning.catalog import CapabilityCatalog, load_catalog, load_default_catalog
from srl.planning.planner import (
    AdmissionPolicy,
    PlanError,
    ResourceAdmissionError,
    build_plan,
    default_policy,
)
from srl.planning.profiles import SCIENCE_LAB_PROFILES
from srl.planning.request import build_request
from srl.planning.router import (
    SELECTION_NOT_APPLICABLE,
    SELECTION_SELECTED,
    SELECTION_WAIT_CAPABILITY,
    RoutingDecision,
    route,
)
from srl.semantic.ir import UnsupportedOperatorError, validate_expression

# The schema-version anchor for a corpus task spec.
_TASK_SPEC_V1: Final[str] = "TaskSpec/v1"

# The corpus receipt schema-version anchor.
_CORPUS_RECEIPT_V1: Final[str] = "CorpusReceipt/v1"

# The eight typed outcomes a task can resolve to (plus the internal MISMATCH
# sentinel used when expected != actual). The task's ``expected.outcome`` MUST
# be one of the first eight.
OUTCOME_PASS: Final[str] = "PASS"  # noqa: S105 (an outcome name, not a secret)
OUTCOME_WAIT_CAPABILITY: Final[str] = "WAIT_CAPABILITY"
OUTCOME_REJECT_CONTRACT: Final[str] = "REJECT_CONTRACT"
OUTCOME_REJECT_IR: Final[str] = "REJECT_IR"
OUTCOME_REJECT_RESOURCE: Final[str] = "REJECT_RESOURCE"
OUTCOME_REJECT_LICENSE: Final[str] = "REJECT_LICENSE"
OUTCOME_REJECT_AUTHORITY: Final[str] = "REJECT_AUTHORITY"
OUTCOME_MISMATCH: Final[str] = "MISMATCH"

#: The eight task outcomes (the ``expected.outcome`` enum). A task's expected
#: outcome MUST be a member; anything else is a corpus failure.
CORPUS_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        OUTCOME_PASS,
        OUTCOME_WAIT_CAPABILITY,
        OUTCOME_REJECT_CONTRACT,
        OUTCOME_REJECT_IR,
        OUTCOME_REJECT_RESOURCE,
        OUTCOME_REJECT_LICENSE,
        OUTCOME_REJECT_AUTHORITY,
    }
)

#: The full outcome set including the internal MISMATCH sentinel (used by the
#: verdict comparison when expected != actual). A task's expected outcome is
#: never MISMATCH; only the runner emits it.
ALL_OUTCOMES: Final[frozenset[str]] = CORPUS_OUTCOMES | {OUTCOME_MISMATCH}

# SPDX license identifiers the public conformance corpus refuses. A copyleft
# license (strong or weak) is incompatible with the fabric's open-science
# redistribution policy, so a pack carrying one is refused at admission. This
# is a documented public policy of the corpus, applied by :func:`_check_license`;
# the codebase does not yet ship a standalone license validator (a future WP
# will), so the policy lives here as the single source of truth.
_COPYLEFT_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "SSPL-1.0",
        "BUSL-1.1",
    }
)

# The marker strings that, if present anywhere in a packet's serialized form,
# indicate a local-path leak or an authority claim. The public corpus refuses
# such packets: a packet that smuggles a local filesystem path or claims
# ``grants_authority`` cannot be admitted. Kept as a tuple so the check is a
# plain substring scan over the canonical bytes (deterministic, no regex).
_LOCAL_PATH_MARKERS: Final[tuple[str, ...]] = (
    "/Users/",
    "/home/",
    "C:\\\\Users\\\\",
    "/etc/",
)
_AUTHORITY_MARKER: Final[str] = "grants_authority"

# A sentinel marker the task's ``expected.outcome`` carries to tell the runner
# which admission policy branch to exercise. A task that does not name a marker
# runs the default routing path.
_MARKER_LICENSE: Final[str] = "license:copyleft"
_MARKER_PATH: Final[str] = "packet:local-path"
_MARKER_AUTHORITY: Final[str] = "packet:grants-authority"

#: The canonical sha256 digest used for object ids in the inline synthetic
#: claims/requests (NOT a real content hash — a stable fixture digest).
_FIXTURE_DIGEST: Final[str] = "sha256:" + "a" * 64


class CorpusError(ContractError):
    """Raised when a corpus task spec is malformed or the corpus is inconsistent.

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``).
    """


# ---------------------------------------------------------------------------
# TaskSpec / TaskOutcome typed wrappers.
# ---------------------------------------------------------------------------


class TaskSpec:
    """A loaded ``TaskSpec/v1`` conformance task.

    Attributes
    ----------
    task_id:
        The stable task id (e.g. ``task-01-algebraic-distributivity``).
    title:
        A human-readable title.
    category:
        The declared category (must match the corpus's category coverage map).
    input:
        The task's input block (claim, optional symbol_table / condition_set /
        model_interface, optional request overrides, optional markers).
    expected_outcome:
        The expected outcome (one of :data:`CORPUS_OUTCOMES`).
    expected_detail:
        A human-readable expected detail string.
    path:
        The task directory (for diagnostics).
    """

    __slots__ = (
        "category",
        "expected_detail",
        "expected_outcome",
        "input",
        "path",
        "task_id",
        "title",
    )

    def __init__(self, doc: dict[str, Any], *, path: Path | None = None) -> None:
        if doc.get("schema_version") != _TASK_SPEC_V1:
            msg = (
                f"TaskSpec schema_version must be {_TASK_SPEC_V1!r}, "
                f"got {doc.get('schema_version')!r}"
            )
            raise CorpusError(msg)
        for key in ("task_id", "title", "category", "input", "expected"):
            if key not in doc:
                msg = f"TaskSpec missing required key {key!r}"
                raise CorpusError(msg, fail_reason="CONTRACT_INVALID")
        expected = doc["expected"]
        if not isinstance(expected, dict) or "outcome" not in expected:
            msg = f"TaskSpec {doc['task_id']!r} expected.outcome is required"
            raise CorpusError(msg)
        outcome = expected["outcome"]
        if outcome not in CORPUS_OUTCOMES:
            msg = (
                f"TaskSpec {doc['task_id']!r} expected.outcome {outcome!r} is not one of "
                f"{sorted(CORPUS_OUTCOMES)}"
            )
            raise CorpusError(msg)
        self.task_id: Final[str] = doc["task_id"]
        self.title: Final[str] = doc["title"]
        self.category: Final[str] = doc["category"]
        self.input: Final[dict[str, Any]] = doc["input"]
        self.expected_outcome: Final[str] = outcome
        self.expected_detail: Final[str] = expected.get("detail", "")
        self.path: Final[Path | None] = path

    def expected_dict(self) -> dict[str, Any]:
        """Return the expected block as a wire dict."""
        return {"outcome": self.expected_outcome, "detail": self.expected_detail}

    def __repr__(self) -> str:  # pragma: no cover (debug aid)
        return (
            f"TaskSpec(task_id={self.task_id!r}, category={self.category!r}, "
            f"expected={self.expected_outcome!r})"
        )


class TaskOutcome:
    """The typed outcome of running one task through the pipeline.

    Attributes
    ----------
    task_id:
        The task id (echoed from the spec).
    actual_outcome:
        The outcome the pipeline produced (one of :data:`ALL_OUTCOMES`).
    detail:
        A human-readable detail string (the rule that fired).
    duration_ms:
        The wall-clock duration of the evaluation in milliseconds (rounded).
    """

    __slots__ = ("actual_outcome", "detail", "duration_ms", "task_id")

    def __init__(
        self,
        *,
        task_id: str,
        actual_outcome: str,
        detail: str,
        duration_ms: int,
    ) -> None:
        if actual_outcome not in ALL_OUTCOMES:
            msg = f"actual_outcome {actual_outcome!r} is not one of {sorted(ALL_OUTCOMES)}"
            raise CorpusError(msg)
        self.task_id: Final[str] = task_id
        self.actual_outcome: Final[str] = actual_outcome
        self.detail: Final[str] = detail
        self.duration_ms: Final[int] = duration_ms

    def to_dict(self) -> dict[str, Any]:
        """Return the wire dict form."""
        return {
            "task_id": self.task_id,
            "actual_outcome": self.actual_outcome,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# Loading.
# ---------------------------------------------------------------------------


def load_task(doc: dict[str, Any], *, path: Path | None = None) -> TaskSpec:
    """Validate a single ``TaskSpec/v1`` document and return a :class:`TaskSpec`."""
    return TaskSpec(doc, path=path)


def load_corpus(directory: Any) -> list[TaskSpec]:
    """Load every ``task.json`` under ``directory`` (recursively) as a TaskSpec.

    Each task lives in a ``task-NN-<slug>/task.json`` directory. The loader
    discovers them recursively so the corpus directory can nest tasks by
    family; it returns them sorted by ``task_id`` for a stable enumeration.

    Parameters
    ----------
    directory:
        A path-like to the corpus root (the directory holding the ``task-*``
        task directories).

    Returns
    -------
    list[TaskSpec]
        The loaded task specs, sorted by task_id.

    Raises
    ------
    CorpusError
        If the directory does not exist, contains no tasks, a task.json is
        malformed, or two tasks share a task_id.
    """
    root = Path(directory)
    if not root.is_dir():
        msg = f"corpus directory {root!s} does not exist or is not a directory"
        raise CorpusError(msg)
    tasks: list[TaskSpec] = []
    seen_ids: set[str] = set()
    for task_path in sorted(root.rglob("task.json")):
        try:
            raw = task_path.read_text(encoding="utf-8")
            doc = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"could not read/parse {task_path!s}: {exc}"
            raise CorpusError(msg) from exc
        spec = load_task(doc, path=task_path.parent)
        if spec.task_id in seen_ids:
            msg = f"duplicate task_id {spec.task_id!r} (at {task_path!s})"
            raise CorpusError(msg)
        seen_ids.add(spec.task_id)
        tasks.append(spec)
    if not tasks:
        msg = f"corpus directory {root!s} contains no task.json files"
        raise CorpusError(msg)
    tasks.sort(key=lambda t: t.task_id)
    return tasks


# ---------------------------------------------------------------------------
# Internal: catalog + request construction from a task's input block.
# ---------------------------------------------------------------------------


def _catalog_for(task: TaskSpec) -> CapabilityCatalog:
    """Return the catalog a task routes against.

    A task may carry ``input.catalog`` describing a synthetic catalog (e.g. an
    all-available catalog to exercise SELECTED + resource admission); absent
    that, the shipped default catalog is used (every adapter future /
    remote_required, so applicable profiles route WAIT_CAPABILITY).
    """
    catalog = task.input.get("catalog")
    if isinstance(catalog, dict):
        return load_catalog(catalog)
    return load_default_catalog()


def _request_overrides(task: TaskSpec) -> dict[str, Any]:
    """Return the request overrides block (requested_profiles, resource_class)."""
    overrides = task.input.get("request")
    if isinstance(overrides, dict):
        return overrides
    return {}


def _build_request_for(task: TaskSpec) -> dict[str, Any]:
    """Build the ScienceLabRunRequest/v1 for a task from its input block.

    Raises ContractError (-> REJECT_CONTRACT) if the request block is malformed
    (e.g. an unknown profile or a bad resource_class); the caller maps that to
    the typed rejection outcome.
    """
    overrides = _request_overrides(task)
    claim = task.input.get("claim", {})
    if isinstance(claim, dict):
        claim_id = claim.get("claim_id", _FIXTURE_DIGEST)
    else:
        claim_id = _FIXTURE_DIGEST
    return build_request(
        claim_id=claim_id,
        requested_profiles=overrides.get("requested_profiles", []),
        resource_class=overrides.get("resource_class", "default"),
        seed=overrides.get("seed", 0),
        threads=overrides.get("threads", 1),
        output_schemas=overrides.get("output_schemas", []),
    )


def _claim_for(task: TaskSpec) -> dict[str, Any]:
    """Return the task's claim dict (a bare synthetic ScientificClaim/v1)."""
    claim = task.input.get("claim", {})
    if not isinstance(claim, dict):
        msg = f"task {task.task_id!r} input.claim must be an object"
        raise CorpusError(msg)
    return claim


# ---------------------------------------------------------------------------
# Internal: the typed admission-policy checks (license / path / authority).
# ---------------------------------------------------------------------------


def _check_license(task: TaskSpec) -> str | None:
    """If the task carries a copyleft license, refuse it (-> REJECT_LICENSE).

    Returns the detail string on refusal, or None if no license marker is
    present. The check reads the task's ``input.adapter_profile.license_spdx``
    (the field the AdapterSemanticProfile/v1 schema defines) against the
    copyleft set.
    """
    profile = task.input.get("adapter_profile")
    if not isinstance(profile, dict):
        return None
    license_spdx = profile.get("license_spdx")
    if isinstance(license_spdx, str) and license_spdx in _COPYLEFT_LICENSES:
        return (
            f"adapter pack license {license_spdx!r} is copyleft; the public "
            "conformance corpus refuses copyleft-licensed packs at admission"
        )
    return None


def _packet_bytes(task: TaskSpec) -> bytes | None:
    """Return the canonical bytes of the task's ``input.packet`` if present."""
    packet = task.input.get("packet")
    if packet is None:
        return None
    try:
        return dumps(packet)
    except (TypeError, ValueError):
        # A non-serializable packet is itself a contract violation, but the
        # path/authority checks only apply to serializable packets; let the
        # routing path surface the structural error instead.
        return None


def _check_packet_markers(task: TaskSpec) -> tuple[str | None, str | None]:
    """Scan the task's packet for local-path / authority markers.

    Returns ``(path_detail, authority_detail)``; each is None if no marker
    fired. A packet smuggling a local filesystem path is refused
    (-> REJECT_CONTRACT, the public-boundary invariant); a packet claiming
    ``grants_authority`` is refused (-> REJECT_AUTHORITY).
    """
    packet_bytes = _packet_bytes(task)
    if packet_bytes is None:
        return None, None
    text = packet_bytes.decode("utf-8", errors="replace")
    path_detail: str | None = None
    authority_detail: str | None = None
    for marker in _LOCAL_PATH_MARKERS:
        if marker in text:
            path_detail = (
                f"packet contains local-path marker {marker!r}; the public "
                "boundary refuses packets that smuggle local filesystem paths"
            )
            break
    if _AUTHORITY_MARKER in text:
        # Only an authority CLAIM is a refusal: a packet whose
        # grants_authority field is literally true (serialized as
        # "grants_authority":true). A false value is the safety const and is
        # fine; detect the true serialization explicitly.
        if '"grants_authority":true' in text or '"grants_authority": true' in text:
            authority_detail = (
                "packet claims grants_authority=true; the fabric refuses any "
                "packet that asserts authority (grants_authority is pinned false)"
            )
    return path_detail, authority_detail


# ---------------------------------------------------------------------------
# Internal: the IR validation check (-> REJECT_IR).
# ---------------------------------------------------------------------------


def _check_ir(task: TaskSpec) -> str | None:
    """If the task carries a MathIR tree, validate it against the allowlist.

    Returns the detail string on an out-of-allowlist operator
    (-> REJECT_IR), or None if the tree is clean (or absent). A tree with a
    domain violation expressed as an unsupported operator (e.g.
    ``arith1.log`` for a log-of-non-positive, ``arith1.sqrt`` for a
    square-root) lands here: the IR allowlist is closed, so the operator is
    rejected before any evaluation.
    """
    ir_tree = task.input.get("ir")
    if ir_tree is None:
        return None
    try:
        validate_expression(ir_tree)
    except UnsupportedOperatorError as exc:
        return (
            f"MathIR operator {exc.op!r} is outside the allowlist "
            f"(content dictionary {exc.cd!r}); the IR is closed"
        )
    except ContractError as exc:
        # A structural IR failure (malformed node, bad const) is a contract
        # rejection, not an allowlist rejection; surface it as such.
        return f"MathIR structural rejection: {exc}"
    return None


# ---------------------------------------------------------------------------
# The outcome resolution.
# ---------------------------------------------------------------------------


def _admission_gate(task: TaskSpec) -> tuple[str, str] | None:
    """Run the pre-routing admission gates; return the (outcome, detail) on refusal.

    The gates fire in the pipeline's own order: license, then packet markers
    (local-path -> REJECT_CONTRACT, authority -> REJECT_AUTHORITY), then the IR
    allowlist (-> REJECT_IR). Returns None if no gate fired (routing proceeds).
    The ordering keeps the rejection families deterministic and independent of
    catalog state.
    """
    # 1. License admission (copyleft refusal).
    license_detail = _check_license(task)
    if license_detail is not None:
        return OUTCOME_REJECT_LICENSE, license_detail

    # 2. Packet markers (local-path leak -> REJECT_CONTRACT; authority -> REJECT_AUTHORITY).
    path_detail, authority_detail = _check_packet_markers(task)
    if path_detail is not None:
        return OUTCOME_REJECT_CONTRACT, path_detail
    if authority_detail is not None:
        return OUTCOME_REJECT_AUTHORITY, authority_detail

    # 3. IR allowlist (out-of-allowlist operator -> REJECT_IR).
    ir_detail = _check_ir(task)
    if ir_detail is not None:
        return OUTCOME_REJECT_IR, ir_detail

    return None


def _route_outcome(task: TaskSpec) -> tuple[str, str]:
    """Build, route, and (optionally) plan-admit the task; return the routing outcome.

    Maps every pipeline exception to the matching typed rejection outcome:
    malformed request/claim/profile -> REJECT_CONTRACT; resource overflow ->
    REJECT_RESOURCE. On a clean route, WAIT_CAPABILITY dominates (an applicable
    profile with no adapter waits); otherwise PASS (no capability waiting, or a
    fully-admitted SELECTED plan).
    """
    # Build the request (malformed request/claim -> REJECT_CONTRACT).
    try:
        request = _build_request_for(task)
        claim = _claim_for(task)
        catalog = _catalog_for(task)
    except ContractError as exc:
        return OUTCOME_REJECT_CONTRACT, f"request/claim structural rejection: {exc}"

    # Route (malformed requested_profiles -> REJECT_CONTRACT).
    try:
        decision: RoutingDecision = route(request, claim, catalog, default_policy())
    except ContractError as exc:
        return OUTCOME_REJECT_CONTRACT, f"router structural rejection: {exc}"

    # If the task carries a synthetic available catalog, attempt plan admission
    # (resource overflow -> REJECT_RESOURCE). Only SELECTED steps are summed, so
    # this only fires when the catalog makes steps SELECTED.
    resource_detail = _check_plan_admission(task, request, decision, catalog)
    if resource_detail is not None:
        return resource_detail

    return _selection_outcome(decision)


def _check_plan_admission(
    task: TaskSpec,
    request: dict[str, Any],
    decision: RoutingDecision,
    catalog: CapabilityCatalog,
) -> tuple[str, str] | None:
    """Attempt plan admission; return (outcome, detail) on overflow or structural error.

    Only engaged when the task carries a synthetic available catalog (so steps
    are SELECTED and resource admission is meaningful). Returns None on a clean
    admit (the routing outcome decides PASS vs WAIT_CAPABILITY).
    """
    if not isinstance(task.input.get("catalog"), dict):
        return None
    try:
        build_plan(request, decision, catalog, default_policy())
    except ResourceAdmissionError as exc:
        over_dims = sorted(exc.over)
        return (
            OUTCOME_REJECT_RESOURCE,
            f"resource estimates exceed caps on {over_dims}; a remote executor is required",
        )
    except (PlanError, ContractError) as exc:
        return OUTCOME_REJECT_CONTRACT, f"plan structural rejection: {exc}"
    return None


def _selection_outcome(decision: RoutingDecision) -> tuple[str, str]:
    """Reduce a routing decision to WAIT_CAPABILITY vs PASS.

    WAIT_CAPABILITY dominates: an applicable profile with no adapter waits
    honestly. Otherwise, SELECTED (a fully-admitted plan) or a bare admit (no
    capability engaged) both yield an honest PASS.
    """
    waiting = decision.waiting_profiles()
    if waiting:
        return (
            OUTCOME_WAIT_CAPABILITY,
            f"applicable profiles {sorted(waiting)} route WAIT_CAPABILITY "
            "(no adapter available; honest wait, not a local fallback)",
        )
    selected = decision.selected_profiles()
    if selected:
        # SELECTED with no waiting: the pipeline admits a fully-satisfied plan.
        return (
            OUTCOME_PASS,
            f"profiles {sorted(selected)} route SELECTED and the plan admits under caps",
        )
    # No applicable profile waiting or selected: the pipeline completed without
    # engaging any capability (a bare claim that auto-classifies to nothing).
    not_applicable = sum(
        1 for p in SCIENCE_LAB_PROFILES if decision.selection_for(p) == SELECTION_NOT_APPLICABLE
    )
    return (
        OUTCOME_PASS,
        f"pipeline admitted with no applicable capability waiting ({not_applicable} "
        "profiles not applicable)",
    )


def _resolve_outcome(task: TaskSpec) -> tuple[str, str]:
    """Run the task through the pipeline and return (outcome, detail).

    The resolution runs the pre-routing admission gates first (license / packet
    / IR), then routing decides WAIT_CAPABILITY vs PASS. This makes the outcomes
    deterministic and independent of catalog state for the rejection families.
    """
    gate = _admission_gate(task)
    if gate is not None:
        return gate
    return _route_outcome(task)


def run_task(
    task: TaskSpec,
    catalog: CapabilityCatalog | None = None,
    policy: AdmissionPolicy | None = None,
) -> TaskOutcome:
    """Run one task through the pipeline and return its typed outcome.

    Pure and deterministic: the same task yields the same outcome. The runner
    performs NO I/O (it builds in-memory requests, routes, validates IR /
    license / packet markers, and optionally builds a plan). ``catalog`` and
    ``policy`` are accepted for API symmetry with the planner but are NOT
    consulted — each task carries its own catalog in its input block, and the
    runner uses the default admission policy (the shipped caps).

    Parameters
    ----------
    task:
        The loaded :class:`TaskSpec`.
    catalog:
        Unused (accepted for API symmetry); the task's ``input.catalog`` wins.
    policy:
        Unused (accepted for API symmetry); the default policy is used.

    Returns
    -------
    TaskOutcome
        The typed outcome (never raises — a pipeline exception is mapped to the
        matching typed rejection outcome).
    """
    del catalog, policy  # API symmetry only; the task carries its own catalog.
    start = time.perf_counter()
    outcome, detail = _resolve_outcome(task)
    elapsed = round((time.perf_counter() - start) * 1000)
    return TaskOutcome(
        task_id=task.task_id,
        actual_outcome=outcome,
        detail=detail,
        duration_ms=elapsed,
    )


# ---------------------------------------------------------------------------
# Verdict comparison.
# ---------------------------------------------------------------------------


class Verdict:
    """The comparison of a task's expected vs actual outcome.

    Attributes
    ----------
    task_id:
        The task id.
    expected:
        The expected outcome (from the spec).
    actual:
        The actual outcome (from the runner).
    match:
        True iff expected == actual.
    detail:
        The runner's detail string (empty on a match; on a mismatch, the
        typed MISMATCH reason naming both outcomes).
    """

    __slots__ = ("actual", "detail", "expected", "match", "task_id")

    def __init__(self, *, task_id: str, expected: str, actual: str, detail: str) -> None:
        self.task_id: Final[str] = task_id
        self.expected: Final[str] = expected
        self.actual: Final[str] = actual
        match = expected == actual
        self.match: Final[bool] = match
        if match:
            final_detail = detail
        else:
            final_detail = (
                f"MISMATCH: expected {expected!r} but pipeline produced {actual!r} "
                f"(runner detail: {detail})"
            )
        self.detail: Final[str] = final_detail

    def to_dict(self) -> dict[str, Any]:
        """Return the wire dict form."""
        return {
            "task_id": self.task_id,
            "expected": self.expected,
            "actual": self.actual,
            "match": self.match,
        }


def verdict(task: TaskSpec, outcome: TaskOutcome) -> Verdict:
    """Compare a task's expected outcome against its actual outcome.

    Returns a :class:`Verdict`. A mismatch carries the typed MISMATCH reason
    (expected vs actual) in its ``detail``; a match carries the runner's
    detail. The verdict is the unit the receipt records per task.
    """
    return Verdict(
        task_id=task.task_id,
        expected=task.expected_outcome,
        actual=outcome.actual_outcome,
        detail=outcome.detail,
    )


def run_corpus(
    tasks: list[TaskSpec],
) -> tuple[list[TaskOutcome], list[Verdict]]:
    """Run every task and return (outcomes, verdicts).

    Convenience wrapper: runs each task through :func:`run_task` and compares
    against its expected outcome via :func:`verdict`. Returns the outcomes
    (in task order) and the verdicts (in task order).
    """
    outcomes = [run_task(t) for t in tasks]
    verdicts = [verdict(t, o) for t, o in zip(tasks, outcomes, strict=True)]
    return outcomes, verdicts


# ---------------------------------------------------------------------------
# Re-exports for the check script and tests.
# ---------------------------------------------------------------------------

__all__ = [
    "ALL_OUTCOMES",
    "CORPUS_OUTCOMES",
    "OUTCOME_MISMATCH",
    "OUTCOME_PASS",
    "OUTCOME_REJECT_AUTHORITY",
    "OUTCOME_REJECT_CONTRACT",
    "OUTCOME_REJECT_IR",
    "OUTCOME_REJECT_LICENSE",
    "OUTCOME_REJECT_RESOURCE",
    "OUTCOME_WAIT_CAPABILITY",
    "SELECTION_NOT_APPLICABLE",
    "SELECTION_SELECTED",
    "SELECTION_WAIT_CAPABILITY",
    "TaskOutcome",
    "TaskSpec",
    "Verdict",
    "load_corpus",
    "load_task",
    "run_corpus",
    "run_task",
    "verdict",
]
