"""The deterministic plan builder: request + routing + catalog + policy -> ScienceLabPlan.

The planner turns a :class:`~srl.planning.router.RoutingDecision` into a
``ScienceLabPlan/v1``: a DAG of steps in topological order, each with a typed
selection state, an adapter (or null), dependency edges, and a resource
estimate. The summed resource estimates of the SELECTED steps are admitted
against the request's resource_class caps; overflow raises
:class:`ResourceAdmissionError` carrying ``WAIT_REMOTE_EXECUTOR``.

Determinism (load-bearing)
---------------------------
The planner is a pure function: ``build_plan(request, routing, catalog, policy)``
yields byte-identical output for byte-identical inputs. This holds even when the
input key order is shuffled, because:

- the canonical JSON encoder sorts keys;
- the steps are emitted in a STABLE order (canonical profile order, then
  dependency-respecting topological order within that);
- the resource estimates are deterministic functions of the profile + class;
- the plan_digest and plan_id are computed over canonical bytes.

The WP-B14 determinism gate rebuilds the plan three times (including a
shuffled-input-key variant) and asserts byte-identical output.

DAG and cycles
--------------
Each applicable profile becomes a step. ``model_composition`` (when applicable)
depends on the OTHER applicable component profiles (its inputs come from their
outputs); a validation obligation depends on the engine step it validates. The
planner performs a topological sort and raises :class:`PlanError`
(``CONTRACT_INVALID``) on a cycle.

Admission, not authorization
----------------------------
A plan is NOT evidence: ``grants_authority`` is pinned to false, and a SELECTED
step means "will run", not "the claim is supported". Resource admission is a
bound, not an authorization to overflow: exceeding the caps raises
``WAIT_REMOTE_EXECUTOR`` (an honest wait for a remote executor) rather than
silently admitting an oversized local plan.
"""

from __future__ import annotations

from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id
from srl.contracts.timestamps import normalize as normalize_timestamp
from srl.planning.catalog import CapabilityCatalog
from srl.planning.profiles import SCIENCE_LAB_PROFILES
from srl.planning.router import (
    SELECTION_SELECTED,
    SELECTION_WAIT_CAPABILITY,
    RoutingDecision,
)

# Schema-version anchors.
_RUN_REQUEST_V1: Final[str] = "ScienceLabRunRequest/v1"
_PLAN_V1: Final[str] = "ScienceLabPlan/v1"

# The typed fail reasons. A plan structural failure (cycle, malformed inputs) is
# CONTRACT_INVALID; a resource overflow is WAIT_REMOTE_EXECUTOR (an honest wait
# for a remote executor, never a silent local overflow).
PLAN_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON
RESOURCE_ADMISSION_FAIL_REASON: Final[str] = "WAIT_REMOTE_EXECUTOR"

# ---------------------------------------------------------------------------
# Admission policy: per-class resource caps.
# ---------------------------------------------------------------------------

#: The default caps (resource_class='default'): wall 300s, rss 1.5 GiB,
#: scratch 4 GiB. 1.5 GiB = 1610612736 bytes; 4 GiB = 4294967296 bytes.
DEFAULT_CAPS: Final[dict[str, int]] = {
    "wall_seconds": 300,
    "rss_bytes": 1610612736,  # 1.5 * 2**30
    "scratch_bytes": 4294967296,  # 4 * 2**30
}

#: The exception caps (resource_class='exception'): wall 900s, rss 2 GiB.
#: scratch inherits the default cap (4 GiB).
EXCEPTION_CAPS: Final[dict[str, int]] = {
    "wall_seconds": 900,
    "rss_bytes": 2147483648,  # 2 * 2**30
    "scratch_bytes": 4294967296,  # 4 * 2**30
}

#: The canonical admission policy document (content-addressed via policy_hash).
#: A plan carries the policy_hash so a re-plan after a cap change is detectable.
DEFAULT_POLICY: Final[dict[str, Any]] = {
    "schema_version": "AdmissionPolicy/v1",
    "default_caps": dict(DEFAULT_CAPS),
    "exception_caps": dict(EXCEPTION_CAPS),
}


class AdmissionPolicy:
    """The resource admission policy: per-class resource caps.

    Attributes
    ----------
    default_caps, exception_caps:
        The cap dicts (each ``wall_seconds`` / ``rss_bytes`` / ``scratch_bytes``).
    digest:
        The ``policy_hash``: sha256 over the canonical bytes of the policy.
    """

    __slots__ = ("default_caps", "digest", "doc", "exception_caps")

    def __init__(self, doc: dict[str, Any] | None = None) -> None:
        # doc is typed dict | None; coerce defensively in case a caller passes
        # a non-dict (defense in depth on the wire boundary).
        source: Any = doc if doc is not None else DEFAULT_POLICY
        if not isinstance(source, dict):
            msg = "admission policy must be an object"
            raise ContractError(msg)
        default_caps = source.get("default_caps", DEFAULT_CAPS)
        exception_caps = source.get("exception_caps", EXCEPTION_CAPS)
        if not isinstance(default_caps, dict) or not isinstance(exception_caps, dict):
            msg = "admission policy caps must be objects"
            raise ContractError(msg)
        for caps in (default_caps, exception_caps):
            for key in ("wall_seconds", "rss_bytes", "scratch_bytes"):
                v = caps.get(key)
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    msg = f"policy cap {key!r} must be a non-negative integer, got {v!r}"
                    raise ContractError(msg)
        self.doc: Final[dict[str, Any]] = {
            "schema_version": source.get("schema_version", "AdmissionPolicy/v1"),
            "default_caps": dict(default_caps),
            "exception_caps": dict(exception_caps),
        }
        self.default_caps: Final[dict[str, int]] = dict(default_caps)
        self.exception_caps: Final[dict[str, int]] = dict(exception_caps)
        self.digest: Final[str] = object_id(self.doc)

    def caps_for(self, resource_class: str) -> dict[str, int]:
        """Return the caps dict for ``resource_class`` ('default' or 'exception')."""
        if resource_class == "exception":
            return dict(self.exception_caps)
        return dict(self.default_caps)


def default_policy() -> AdmissionPolicy:
    """Return the default :class:`AdmissionPolicy` (the shipped caps)."""
    return AdmissionPolicy(DEFAULT_POLICY)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class PlanError(ContractError):
    """Raised when a plan cannot be built (cycle, malformed inputs).

    Carries the typed ``fail_reason`` (``CONTRACT_INVALID``) and, for a cycle,
    the ``invariant`` name ``cycle_detected``.

    Attributes
    ----------
    invariant:
        The name of the violated plan invariant (e.g. ``cycle_detected``).
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: str = "",
        fail_reason: str = PLAN_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.invariant: str = invariant


class ResourceAdmissionError(ContractError):
    """Raised when a plan's summed estimates exceed the admission caps.

    Carries the typed ``fail_reason`` ``WAIT_REMOTE_EXECUTOR`` (an honest wait
    for a remote executor, never a silent local overflow) and the offending
    dimension(s) + the cap for diagnostics.

    Attributes
    ----------
    over:
        A dict of dimension -> {"requested": int, "cap": int} for each
        dimension that overflowed.
    """

    def __init__(
        self,
        message: str,
        *,
        over: dict[str, dict[str, int]] | None = None,
        fail_reason: str = RESOURCE_ADMISSION_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.over: Final[dict[str, dict[str, int]]] = over or {}


# ---------------------------------------------------------------------------
# Resource estimates (deterministic per profile + resource_class).
# ---------------------------------------------------------------------------

#: The base per-profile resource estimate (wall_seconds, rss_bytes,
#: scratch_bytes) for the DEFAULT resource class. These are deliberately modest
#: so a single profile admits under default caps, but several heavy profiles
#: together can overflow (exercising admission). The numbers are deterministic
#: functions of the profile name only (stable order via the profile's index in
#: SCIENCE_LAB_PROFILES), so the same inputs always yield the same estimates.
_BASE_ESTIMATES: Final[dict[str, dict[str, int]]] = {
    "algebra_exact": {"wall_seconds": 20, "rss_bytes": 268435456, "scratch_bytes": 104857600},
    "symbolic_law": {"wall_seconds": 30, "rss_bytes": 268435456, "scratch_bytes": 104857600},
    "dynamics": {"wall_seconds": 60, "rss_bytes": 536870912, "scratch_bytes": 524288000},
    "geometry_tda": {"wall_seconds": 120, "rss_bytes": 805306368, "scratch_bytes": 1073741824},
    "causal_time_series": {"wall_seconds": 45, "rss_bytes": 536870912, "scratch_bytes": 524288000},
    "uncertainty": {"wall_seconds": 40, "rss_bytes": 402653184, "scratch_bytes": 314572800},
    "optimization": {"wall_seconds": 90, "rss_bytes": 536870912, "scratch_bytes": 524288000},
    "formal_protocol": {"wall_seconds": 50, "rss_bytes": 402653184, "scratch_bytes": 209715200},
    "literature": {"wall_seconds": 10, "rss_bytes": 134217728, "scratch_bytes": 52428800},
    "theorem_or_proof_obligation": {
        "wall_seconds": 70,
        "rss_bytes": 536870912,
        "scratch_bytes": 314572800,
    },
    "nonlinear_continuous_or_hybrid_constraint": {
        "wall_seconds": 110,
        "rss_bytes": 805306368,
        "scratch_bytes": 536870912,
    },
    "executable_ode_dae_sde_model": {
        "wall_seconds": 100,
        "rss_bytes": 671088640,
        "scratch_bytes": 805306368,
    },
    "pde_variational_model": {
        "wall_seconds": 150,
        "rss_bytes": 939524096,
        "scratch_bytes": 1610612736,
    },
    "model_composition": {"wall_seconds": 80, "rss_bytes": 536870912, "scratch_bytes": 419430400},
    "literature_extraction": {
        "wall_seconds": 15,
        "rss_bytes": 201326592,
        "scratch_bytes": 104857600,
    },
}


def _estimate(profile: str, resource_class: str) -> dict[str, int]:
    """Return the deterministic resource estimate for ``profile`` + ``resource_class``.

    For ``exception``, wall_seconds is scaled 1.5x (rounded) and rss_bytes 1.25x
    (rounded) to reflect the larger budget; scratch is unchanged. The scaling is
    a pure function of the base estimate, so it is deterministic.
    """
    base = _BASE_ESTIMATES[profile]
    if resource_class == "exception":
        return {
            "wall_seconds": int(base["wall_seconds"] * 3 / 2),
            "rss_bytes": int(base["rss_bytes"] * 5 / 4),
            "scratch_bytes": base["scratch_bytes"],
        }
    return dict(base)


# ---------------------------------------------------------------------------
# Step + plan construction.
# ---------------------------------------------------------------------------


def _step_id(profile: str, index: int, multi: bool) -> str:
    """Return a stable step_id: '<profile>' or '<profile>:<index>'."""
    return f"{profile}:{index}" if multi else profile


def _build_dependency_graph(
    applicable: list[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build the step dependency graph for the applicable profiles.

    Returns ``(deps, dependents)`` where ``deps[step]`` is the set of steps
    ``step`` depends on, and ``dependents[step]`` is the reverse. Edges:

    - ``model_composition`` (if applicable) depends on every OTHER applicable
      profile (its inputs come from their outputs);
    - otherwise no inter-profile edges (each step is a root unless composed).

    Step ids equal profile names here (single-instance per profile).
    """
    deps: dict[str, set[str]] = {p: set() for p in applicable}
    dependents: dict[str, set[str]] = {p: set() for p in applicable}
    if "model_composition" in deps and len(applicable) > 1:
        for other in applicable:
            if other != "model_composition":
                deps["model_composition"].add(other)
                dependents[other].add("model_composition")
    return deps, dependents


def _topological_order(
    applicable: list[str],
    deps: dict[str, set[str]],
) -> list[str]:
    """Return the applicable profiles in topological order (stable on ties).

    Uses Kahn's algorithm with a canonical (sorted) tie-break so the order is
    deterministic. Raises :class:`PlanError` on a cycle.
    """
    # Work on a copy of in-degrees.
    indeg: dict[str, int] = {p: len(deps[p]) for p in applicable}
    # Ready set: profiles with no unmet dependencies, kept sorted for stability.
    ready: list[str] = sorted(p for p in applicable if indeg[p] == 0)
    order: list[str] = []
    dependents: dict[str, set[str]] = {p: set() for p in applicable}
    for p in applicable:
        for d in deps[p]:
            dependents[d].add(p)
    while ready:
        # Pop the canonical-smallest ready node for a stable order.
        ready.sort()
        node = ready.pop(0)
        order.append(node)
        for dep in sorted(dependents[node]):
            indeg[dep] -= 1
            if indeg[dep] == 0:
                ready.append(dep)
    if len(order) != len(applicable):
        cyclic = sorted(set(applicable) - set(order))
        msg = f"plan dependency cycle detected among profiles: {cyclic}"
        raise PlanError(msg, invariant="cycle_detected")
    return order


def topological_order(profiles: list[str], deps: dict[str, set[str]]) -> list[str]:
    """Public topological sort over ``profiles`` with the given dependency edges.

    A stable (canonical-smallest-tie-break) Kahn's algorithm. Raises
    :class:`PlanError` (``invariant=cycle_detected``) on a cycle. Exposed so a
    gate or test can exercise cycle detection directly without going through the
    full plan builder.

    Parameters
    ----------
    profiles:
        The profile names to order.
    deps:
        A dict of profile -> set of profiles it depends on.

    Returns
    -------
    list[str]
        The profiles in topological order (stable on ties).
    """
    return _topological_order(list(profiles), {k: set(v) for k, v in deps.items()})


def _build_steps(
    request: dict[str, Any],
    routing: RoutingDecision,
    catalog: CapabilityCatalog,
) -> list[dict[str, Any]]:
    """Build the ordered list of plan-step dicts from the routing decision.

    Emits a step for EVERY profile (all 15) so the plan's decision coverage is
    explicit: SELECTED / EXCLUDED_TYPED / NOT_APPLICABLE / WAIT_CAPABILITY.
    Steps are ordered topologically among the applicable set, with the
    non-applicable profiles appended in canonical order (they have no edges).
    """
    resource_class = request.get("resource_class", "default")
    if resource_class not in {"default", "exception"}:
        msg = f"request resource_class {resource_class!r} must be 'default' or 'exception'"
        raise ContractError(msg)

    applicable = [
        p
        for p in SCIENCE_LAB_PROFILES
        if routing.selection_for(p) in {SELECTION_SELECTED, SELECTION_WAIT_CAPABILITY}
    ]
    deps, _dependents = _build_dependency_graph(applicable)
    topo = _topological_order(applicable, deps)

    steps: list[dict[str, Any]] = []
    # First the applicable profiles in topological order.
    for profile in topo:
        pr = routing.profiles[profile]
        est = _estimate(profile, resource_class)
        steps.append(
            {
                "step_id": profile,
                "profile": profile,
                "capability_id": pr.capability_id,
                "adapter_id": pr.adapter_id,
                "depends_on": sorted(deps[profile]),
                "selection": pr.selection,
                "exclusion_reason": pr.exclusion_reason,
                "resource_estimate": est,
            }
        )
    # Then the non-applicable profiles in canonical order (no edges).
    for profile in SCIENCE_LAB_PROFILES:
        if profile in set(topo):
            continue
        pr = routing.profiles[profile]
        est = _estimate(profile, resource_class)
        steps.append(
            {
                "step_id": profile,
                "profile": profile,
                "capability_id": pr.capability_id,
                "adapter_id": pr.adapter_id,
                "depends_on": [],
                "selection": pr.selection,
                "exclusion_reason": pr.exclusion_reason,
                "resource_estimate": est,
            }
        )
    return steps


def _admit(steps: list[dict[str, Any]], policy: AdmissionPolicy, resource_class: str) -> None:
    """Admit the SELECTED steps' summed estimates against the class caps.

    Raises :class:`ResourceAdmissionError` (``WAIT_REMOTE_EXECUTOR``) if any
    dimension overflows. Only SELECTED steps are summed (a WAIT_CAPABILITY step
    is not admitted — it is not running locally).
    """
    caps = policy.caps_for(resource_class)
    totals = {"wall_seconds": 0, "rss_bytes": 0, "scratch_bytes": 0}
    for step in steps:
        if step["selection"] == SELECTION_SELECTED:
            est = step["resource_estimate"]
            for dim in totals:
                totals[dim] += est[dim]
    over: dict[str, dict[str, int]] = {}
    for dim, total in totals.items():
        cap = caps[dim]
        if total > cap:
            over[dim] = {"requested": total, "cap": cap}
    if over:
        msg = (
            f"plan resource estimates exceed {resource_class!r} caps: {over} "
            "(a remote executor is required; the planner waits rather than "
            "silently overflowing local)"
        )
        raise ResourceAdmissionError(msg, over=over)


def _require_request(request: Any) -> dict[str, Any]:
    """Validate the request is an object with the right schema_version + a request_id."""
    if not isinstance(request, dict):
        msg = f"request must be an object, got {type(request).__name__}"
        raise ContractError(msg)
    if request.get("schema_version") != _RUN_REQUEST_V1:
        msg = (
            "request schema_version must be "
            f"{_RUN_REQUEST_V1!r}, got {request.get('schema_version')!r}"
        )
        raise ContractError(msg)
    rid = request.get("request_id")
    if not isinstance(rid, str) or not rid.startswith("sha256:"):
        msg = "request must carry a sha256 request_id"
        raise ContractError(msg)
    return request


def build_plan(
    request: Any,
    routing: RoutingDecision,
    catalog: CapabilityCatalog,
    policy: AdmissionPolicy,
    *,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a deterministic ``ScienceLabPlan/v1`` from a routing decision.

    Parameters
    ----------
    request:
        A ScienceLabRunRequest/v1 wire dict (reads ``request_id``,
        ``resource_class``).
    routing:
        The :class:`~srl.planning.router.RoutingDecision` for the request.
    catalog:
        The loaded :class:`CapabilityCatalog` (its digest becomes catalog_hash).
    policy:
        The :class:`AdmissionPolicy` (its digest becomes policy_hash).
    created_utc:
        RFC 3339 UTC timestamp. Normalized to canonical form.

    Returns
    -------
    dict[str, Any]
        A validated ``ScienceLabPlan/v1`` dict with computed ``plan_digest``
        and ``plan_id``.

    Raises
    ------
    PlanError
        If the dependency graph has a cycle (CONTRACT_INVALID).
    ResourceAdmissionError
        If the SELECTED steps' summed estimates exceed the class caps
        (WAIT_REMOTE_EXECUTOR).
    ContractError
        If the request is malformed.
    """
    req = _require_request(request)
    normalized_utc = normalize_timestamp(created_utc)
    steps = _build_steps(req, routing, catalog)
    _admit(steps, policy, req.get("resource_class", "default"))

    plan_body: dict[str, Any] = {
        "schema_version": _PLAN_V1,
        "request_id": req["request_id"],
        "steps": steps,
        "policy_hash": policy.digest,
        "catalog_hash": catalog.digest,
        "created_utc": normalized_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    # plan_digest: sha256 over the canonical bytes of the body WITHOUT plan_id
    # and WITHOUT plan_digest (the content digest an executor can recompute).
    digest_body = {k: v for k, v in plan_body.items() if k not in {"plan_id", "plan_digest"}}
    plan_digest = object_id(digest_body)
    plan_body["plan_digest"] = plan_digest
    # plan_id: sha256 over the canonical bytes of the whole plan WITHOUT plan_id
    # (includes plan_digest).
    id_body = {k: v for k, v in plan_body.items() if k != "plan_id"}
    plan_body["plan_id"] = object_id(id_body)
    return plan_body


def plan_id(plan: dict[str, Any]) -> str:
    """Recompute the ``plan_id`` of a plan (sha256 over canonical bytes, no plan_id)."""
    body = {k: v for k, v in plan.items() if k != "plan_id"}
    return object_id(body)


def plan_digest(plan: dict[str, Any]) -> str:
    """Recompute the ``plan_digest`` (sha256 over canonical bytes, no plan_id/plan_digest)."""
    body = {k: v for k, v in plan.items() if k not in {"plan_id", "plan_digest"}}
    return object_id(body)


__all__ = [
    "DEFAULT_CAPS",
    "DEFAULT_POLICY",
    "EXCEPTION_CAPS",
    "PLAN_FAIL_REASON",
    "RESOURCE_ADMISSION_FAIL_REASON",
    "AdmissionPolicy",
    "PlanError",
    "ResourceAdmissionError",
    "build_plan",
    "default_policy",
    "plan_digest",
    "plan_id",
    "topological_order",
]
