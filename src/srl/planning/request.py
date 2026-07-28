"""ScienceLabRunRequest/v1 builder (the router/planner input).

This module is the Python counterpart of the ``ScienceLabRunRequest/v1`` JSON
Schema (``src/srl/contracts/schemas/v1/science-lab-run-request.json``). It
builds a typed, validated request with a content-addressed ``request_id`` and
the two safety consts pinned (``canonical_writes=0``, ``grants_authority=
false``, plus the two request-specific safety consts
``prospective_holdout_materialization_allowed=false`` and
``status_promotion_allowed=false``).

A request is an INTENT, not an authority: it carries no evidence and no plan.
The router produces a :class:`~srl.planning.router.RoutingDecision` from it;
the planner produces a ``ScienceLabPlan/v1`` from the decision. Neither the
request nor the plan grants authority.
"""

from __future__ import annotations

from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id, validate_object_id
from srl.contracts.timestamps import normalize as normalize_timestamp
from srl.planning.profiles import PROFILE_NAMES

# Schema-version anchor.
_RUN_REQUEST_V1: Final[str] = "ScienceLabRunRequest/v1"

# The typed fail reason for a request-structural violation.
REQUEST_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON


def _validate_profiles(profiles: Any) -> list[str]:
    """Validate the requested_profiles list: each a known profile, unique."""
    if not isinstance(profiles, list):
        msg = "requested_profiles must be an array"
        raise ContractError(msg)
    out: list[str] = []
    for p in profiles:
        if not isinstance(p, str) or p not in PROFILE_NAMES:
            msg = f"requested_profiles entry {p!r} is not a known profile"
            raise ContractError(msg)
        out.append(p)
    if len(set(out)) != len(out):
        msg = "requested_profiles must be unique"
        raise ContractError(msg)
    return out


def _validate_seed_policy(seed_policy: Any) -> dict[str, int]:
    """Validate the seed_policy: {seed: int>=0, threads: int>=1}."""
    if not isinstance(seed_policy, dict):
        msg = "seed_policy must be an object"
        raise ContractError(msg)
    for key in ("seed", "threads"):
        if key not in seed_policy:
            msg = f"seed_policy missing key {key!r}"
            raise ContractError(msg)
    seed = seed_policy["seed"]
    threads = seed_policy["threads"]
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        msg = f"seed_policy.seed must be a non-negative integer, got {seed!r}"
        raise ContractError(msg)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        msg = f"seed_policy.threads must be a positive integer, got {threads!r}"
        raise ContractError(msg)
    return {"seed": seed, "threads": threads}


def build_request(  # noqa: PLR0913 (kw-only set IS the request's field set)
    *,
    claim_id: str,
    requested_profiles: list[str] | None = None,
    resource_class: str = "default",
    seed: int = 0,
    threads: int = 1,
    output_schemas: list[str] | None = None,
    created_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a typed, validated ScienceLabRunRequest/v1.

    Parameters
    ----------
    claim_id:
        The claim_id of the ScientificClaim/v1 this request targets.
    requested_profiles:
        The profiles to engage (may be empty = auto-classify). Each must be a
        known profile; duplicates are rejected.
    resource_class:
        ``default`` or ``exception``.
    seed:
        Non-negative PRNG seed.
    threads:
        Positive thread budget (>=1).
    output_schemas:
        The schema names the run should emit (may be empty).
    created_utc:
        RFC 3339 UTC timestamp.

    Returns
    -------
    dict[str, Any]
        A validated ``ScienceLabRunRequest/v1`` dict with a computed
        ``request_id``.

    Raises
    ------
    ContractError
        If any field is malformed.
    """
    validate_object_id(claim_id)
    if resource_class not in {"default", "exception"}:
        msg = f"resource_class {resource_class!r} must be 'default' or 'exception'"
        raise ContractError(msg)
    profiles = _validate_profiles(requested_profiles or [])
    sp = _validate_seed_policy({"seed": seed, "threads": threads})
    # output_schemas is typed list[str] | None; coerce defensively in case a
    # caller passes a non-list (defense in depth on the wire boundary).
    raw_schemas: Any = output_schemas if output_schemas is not None else []
    if not isinstance(raw_schemas, list):
        msg = "output_schemas must be an array"
        raise ContractError(msg)
    schemas: list[str] = []
    for s in raw_schemas:
        if not isinstance(s, str) or not s:
            msg = f"output_schemas entry {s!r} must be a non-empty string"
            raise ContractError(msg)
        schemas.append(s)
    if len(set(schemas)) != len(schemas):
        msg = "output_schemas must be unique"
        raise ContractError(msg)
    normalized_utc = normalize_timestamp(created_utc)

    request: dict[str, Any] = {
        "schema_version": _RUN_REQUEST_V1,
        "claim_id": claim_id,
        "requested_profiles": profiles,
        "resource_class": resource_class,
        "seed_policy": sp,
        "output_schemas": schemas,
        "prospective_holdout_materialization_allowed": False,
        "status_promotion_allowed": False,
        "created_utc": normalized_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }
    request["request_id"] = object_id(request)
    return request


def request_id(request: dict[str, Any]) -> str:
    """Recompute the ``request_id`` (sha256 over canonical bytes, no request_id)."""
    body = {k: v for k, v in request.items() if k != "request_id"}
    return object_id(body)


__all__ = [
    "REQUEST_FAIL_REASON",
    "build_request",
    "request_id",
]
