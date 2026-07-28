"""The science-lab router and planner (WP-B14).

This package turns a ``ScienceLabRunRequest/v1`` + a ``ScientificClaim/v1``
into a deterministic ``ScienceLabPlan/v1``: a DAG of capability-profile steps,
each in a typed selection state (SELECTED / EXCLUDED_TYPED / NOT_APPLICABLE /
WAIT_CAPABILITY), with resource estimates admitted against the request's class
caps.

Pipeline
--------
1. :mod:`srl.planning.classifier` — pure, deterministic claim classifier:
   ``classify(claim, symbol_table, condition_set) -> (frozenset, rule_trace)``.
2. :mod:`srl.planning.router` — :func:`srl.planning.router.route` produces a
   :class:`~srl.planning.router.RoutingDecision` over all 15 profiles.
3. :mod:`srl.planning.planner` — :func:`srl.planning.planner.build_plan` turns
   the decision into a topologically-ordered, resource-admitted plan.

Honesty (load-bearing)
----------------------
- **A plan is not evidence.** ``grants_authority`` is pinned to false; a
  SELECTED step means "will run", not "the claim is supported".
- **WAIT_CAPABILITY is honest absence.** A profile with no available adapter
  waits — the router NEVER fabricates a local substitute for a capability that
  is not present.
- **No silent fallback.** A ``remote_required`` profile never falls back to a
  local adapter; absence yields WAIT_CAPABILITY.
- **Admission, not authorization.** Exceeding the caps raises
  ``WAIT_REMOTE_EXECUTOR`` (an honest wait) rather than silently overflowing.
"""

from __future__ import annotations

from srl.planning.catalog import (
    AVAILABILITY_STATES,
    CapabilityCatalog,
    CapabilityEntry,
    CatalogError,
    load_catalog,
    load_default_catalog,
)
from srl.planning.classifier import classify
from srl.planning.planner import (
    DEFAULT_CAPS,
    DEFAULT_POLICY,
    EXCEPTION_CAPS,
    AdmissionPolicy,
    PlanError,
    ResourceAdmissionError,
    build_plan,
    default_policy,
    plan_digest,
    plan_id,
    topological_order,
)
from srl.planning.profiles import (
    PROFILE_NAMES,
    PROFILES,
    SCIENCE_LAB_PROFILES,
    CapabilityProfile,
)
from srl.planning.request import build_request, request_id
from srl.planning.router import (
    EXCLUSION_NOT_REQUESTED,
    SELECTION_STATES,
    SELECTION_WAIT_CAPABILITY,
    ProfileRouting,
    RoutingDecision,
    route,
)

__all__ = [
    "AVAILABILITY_STATES",
    "DEFAULT_CAPS",
    "DEFAULT_POLICY",
    "EXCEPTION_CAPS",
    "EXCLUSION_NOT_REQUESTED",
    "PROFILES",
    "PROFILE_NAMES",
    "SCIENCE_LAB_PROFILES",
    "SELECTION_STATES",
    "SELECTION_WAIT_CAPABILITY",
    "AdmissionPolicy",
    "CapabilityCatalog",
    "CapabilityEntry",
    "CapabilityProfile",
    "CatalogError",
    "PlanError",
    "ProfileRouting",
    "ResourceAdmissionError",
    "RoutingDecision",
    "build_plan",
    "build_request",
    "classify",
    "default_policy",
    "load_catalog",
    "load_default_catalog",
    "plan_digest",
    "plan_id",
    "request_id",
    "route",
    "topological_order",
]
