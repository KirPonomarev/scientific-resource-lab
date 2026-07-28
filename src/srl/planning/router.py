"""The deterministic claim router: request + claim + catalog -> RoutingDecision.

The router decides, for EACH of the 15 capability profiles, one of four typed
selection states:

- ``SELECTED``        — the profile applies to the claim AND a local adapter is
                        available (catalog availability=available);
- ``EXCLUDED_TYPED``  — the request or classifier explicitly excluded the
                        profile, with a typed reason;
- ``NOT_APPLICABLE``  — the profile does not apply to the claim;
- ``WAIT_CAPABILITY`` — the profile applies but no adapter is available yet
                        (availability future / remote_required, OR the profile
                        is unknown to the catalog). This is an HONEST wait,
                        NEVER a silent fallback to a local substitute.

No silent fallback (load-bearing)
---------------------------------
A ``remote_required`` profile NEVER falls back to a local adapter, even if a
local adapter id were named in the catalog. Absence of an ``available``
adapter yields ``WAIT_CAPABILITY`` — the router refuses to fabricate a local
substitute for a capability that is not present. This is the honesty property
that keeps a plan from claiming it can run something it cannot.

The router is a pure function
-----------------------------
The router is deterministic: ``route(request, claim, catalog, policy)`` yields
the same :class:`RoutingDecision` for the same inputs. The decision covers ALL
15 profiles (a gate asserts this: no profile is silently dropped). The
classifier is consulted only when the request's ``requested_profiles`` is
empty (auto-classify); otherwise the request's explicit list is honored.
"""

from __future__ import annotations

from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.planning.catalog import CapabilityCatalog
from srl.planning.classifier import classify
from srl.planning.future_profiles import FUTURE_PROFILE_IDS
from srl.planning.profiles import SCIENCE_LAB_PROFILES

# The four typed selection states a profile can be routed to.
SELECTION_SELECTED: Final[str] = "SELECTED"
SELECTION_EXCLUDED_TYPED: Final[str] = "EXCLUDED_TYPED"
SELECTION_NOT_APPLICABLE: Final[str] = "NOT_APPLICABLE"
SELECTION_WAIT_CAPABILITY: Final[str] = "WAIT_CAPABILITY"
SELECTION_STATES: Final[frozenset[str]] = frozenset(
    {
        SELECTION_SELECTED,
        SELECTION_EXCLUDED_TYPED,
        SELECTION_NOT_APPLICABLE,
        SELECTION_WAIT_CAPABILITY,
    }
)

# Profiles the router can legally emit a decision for: the 15 shipped profiles
# plus the semantic future profiles registered in srl.planning.future_profiles.
_KNOWN_PROFILES: Final[frozenset[str]] = frozenset(SCIENCE_LAB_PROFILES) | FUTURE_PROFILE_IDS

# The typed fail reason for a router-structural violation.
ROUTER_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Typed exclusion reasons (carried when selection=EXCLUDED_TYPED).
EXCLUSION_NOT_REQUESTED: Final[str] = "not_requested"
EXCLUSION_CLASSIFIER_EXCLUDED: Final[str] = "classifier_excluded"


class ProfileRouting:
    """The routing decision for ONE profile.

    Attributes
    ----------
    profile:
        The profile name.
    selection:
        One of :data:`SELECTION_STATES`.
    capability_id:
        The catalog capability id (``cap.<profile>`` if unknown to catalog).
    adapter_id:
        The adapter id when SELECTED, else ``None``.
    availability:
        The catalog availability for the profile (``unknown`` if not in catalog).
    exclusion_reason:
        A typed reason when ``EXCLUDED_TYPED``, else ``None``.
    """

    __slots__ = (
        "adapter_id",
        "availability",
        "capability_id",
        "exclusion_reason",
        "profile",
        "selection",
    )

    def __init__(  # noqa: PLR0913 (kw-only set IS the routing's field set)
        self,
        *,
        profile: str,
        selection: str,
        capability_id: str,
        adapter_id: str | None,
        availability: str,
        exclusion_reason: str | None,
    ) -> None:
        if profile not in _KNOWN_PROFILES:
            msg = f"unknown profile {profile!r}"
            raise ContractError(msg)
        if selection not in SELECTION_STATES:
            msg = f"selection {selection!r} must be one of {sorted(SELECTION_STATES)}"
            raise ContractError(msg)
        # exclusion_reason is REQUIRED non-null iff EXCLUDED_TYPED; null otherwise.
        if selection == SELECTION_EXCLUDED_TYPED:
            if not isinstance(exclusion_reason, str) or not exclusion_reason:
                msg = "exclusion_reason required (non-empty) when selection=EXCLUDED_TYPED"
                raise ContractError(msg)
        elif exclusion_reason is not None:
            msg = f"exclusion_reason must be null when selection={selection!r}"
            raise ContractError(msg)
        # SELECTED requires a non-null adapter_id.
        if selection == SELECTION_SELECTED and not (isinstance(adapter_id, str) and adapter_id):
            msg = "adapter_id required (non-empty) when selection=SELECTED"
            raise ContractError(msg)
        if selection != SELECTION_SELECTED and adapter_id is not None:
            msg = f"adapter_id must be null when selection={selection!r}"
            raise ContractError(msg)
        self.profile: Final[str] = profile
        self.selection: Final[str] = selection
        self.capability_id: Final[str] = capability_id
        self.adapter_id: Final[str | None] = adapter_id
        self.availability: Final[str] = availability
        self.exclusion_reason: Final[str | None] = exclusion_reason

    def to_dict(self) -> dict[str, Any]:
        """Return the wire dict form of this routing decision."""
        return {
            "profile": self.profile,
            "selection": self.selection,
            "capability_id": self.capability_id,
            "adapter_id": self.adapter_id,
            "availability": self.availability,
            "exclusion_reason": self.exclusion_reason,
        }


class RoutingDecision:
    """The routing decision for ALL 15 profiles, plus the classifier trace.

    Attributes
    ----------
    profiles:
        A dict of profile name -> :class:`ProfileRouting`. Covers all 15.
    classifier_trace:
        The rule trace from the classifier (empty if the request named profiles
        explicitly and the classifier was not consulted for selection — though
        it is always run for the trace record).
    """

    __slots__ = ("classifier_trace", "profiles")

    def __init__(
        self,
        profiles: dict[str, ProfileRouting],
        classifier_trace: list[str],
    ) -> None:
        # Completeness: every profile must have a decision (no silent drops).
        missing = sorted(set(SCIENCE_LAB_PROFILES) - set(profiles))
        if missing:
            msg = f"RoutingDecision missing profiles: {missing}"
            raise ContractError(msg)
        extra = sorted(set(profiles) - set(SCIENCE_LAB_PROFILES) - FUTURE_PROFILE_IDS)
        if extra:
            msg = f"RoutingDecision has unexpected profiles: {extra}"
            raise ContractError(msg)
        self.profiles: Final[dict[str, ProfileRouting]] = dict(profiles)
        self.classifier_trace: Final[list[str]] = list(classifier_trace)

    def selection_for(self, profile: str) -> str:
        """Return the selection state for ``profile``."""
        pr = self.profiles.get(profile)
        if pr is None:
            msg = f"unknown profile {profile!r}"
            raise ContractError(msg)
        return pr.selection

    def applicable_profiles(self) -> frozenset[str]:
        """Return the profiles that APPLY to the claim (SELECTED or WAIT_CAPABILITY).

        These are the profiles the claim needs (the classifier selected them or
        the request named them); SELECTED means an adapter is available,
        WAIT_CAPABILITY means one is not.
        """
        return frozenset(
            p
            for p, pr in self.profiles.items()
            if pr.selection in {SELECTION_SELECTED, SELECTION_WAIT_CAPABILITY}
        )

    def selected_profiles(self) -> frozenset[str]:
        """Return the profiles routed SELECTED (adapter available)."""
        return frozenset(p for p, pr in self.profiles.items() if pr.selection == SELECTION_SELECTED)

    def waiting_profiles(self) -> frozenset[str]:
        """Return the profiles routed WAIT_CAPABILITY (adapterless / unknown / remote)."""
        return frozenset(
            p for p, pr in self.profiles.items() if pr.selection == SELECTION_WAIT_CAPABILITY
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the wire dict form of the full decision."""
        return {
            "profiles": {p: pr.to_dict() for p, pr in sorted(self.profiles.items())},
            "classifier_trace": list(self.classifier_trace),
        }


def _route_one(
    profile: str,
    *,
    applicable: bool,
    catalog: CapabilityCatalog,
) -> ProfileRouting:
    """Route a single profile given whether it applies and the catalog.

    Honesty rule: a profile routes SELECTED ONLY if it applies AND the catalog
    marks it ``available``. ``remote_required`` and ``future`` both yield
    WAIT_CAPABILITY when applicable; a non-applicable profile yields
    NOT_APPLICABLE. An unknown profile (not in catalog) that applies yields
    WAIT_CAPABILITY (the router never fabricates an adapter).
    """
    capability_id = catalog.capability_id_for(profile)
    entry = catalog.entry_for(profile)
    availability = entry.availability if entry is not None else "unknown"
    if not applicable:
        return ProfileRouting(
            profile=profile,
            selection=SELECTION_NOT_APPLICABLE,
            capability_id=capability_id,
            adapter_id=None,
            availability=availability,
            exclusion_reason=None,
        )
    # Applicable: SELECTED only if a local adapter is available. is_available
    # returns True only for an entry whose availability == 'available', so entry
    # is guaranteed non-None here; guard defensively (no fabricated adapter).
    if catalog.is_available(profile) and entry is not None:
        return ProfileRouting(
            profile=profile,
            selection=SELECTION_SELECTED,
            capability_id=capability_id,
            adapter_id=entry.adapter_id,
            availability=availability,
            exclusion_reason=None,
        )
    # Applicable but adapterless / remote_required / future / unknown -> WAIT.
    # REMOTE_REQUIRED never falls back to local: even if an adapter_id is named
    # in the catalog for a remote_required entry, we do NOT engage it locally.
    return ProfileRouting(
        profile=profile,
        selection=SELECTION_WAIT_CAPABILITY,
        capability_id=capability_id,
        adapter_id=None,
        availability=availability,
        exclusion_reason=None,
    )


def _route_future_profiles(
    applicable_set: set[str],
    catalog: CapabilityCatalog,
) -> dict[str, ProfileRouting]:
    """Route any explicitly-requested semantic future profiles.

    Future profiles are not part of the 15 shipped capability profiles, so the
    catalog has no entry for them. They are covered by the router's existing
    unknown/future capability path and always produce WAIT_CAPABILITY with no
    adapter.
    """
    decisions: dict[str, ProfileRouting] = {}
    for profile in sorted(applicable_set & FUTURE_PROFILE_IDS):
        decisions[profile] = _route_one(profile, applicable=True, catalog=catalog)
    return decisions


def route(
    request: Any,
    claim: Any,
    catalog: CapabilityCatalog,
    policy: Any,
) -> RoutingDecision:
    """Route a request against a claim, producing a decision for all 15 profiles.

    Pure and deterministic: the same ``(request, claim, catalog, policy)``
    yields the same :class:`RoutingDecision`. The decision covers ALL 15
    profiles (no silent drops).

    Parameters
    ----------
    request:
        A ScienceLabRunRequest/v1 wire dict (reads ``requested_profiles``).
    claim:
        A ScientificClaim/v1 wire dict.
    catalog:
        A loaded :class:`CapabilityCatalog`.
    policy:
        The admission policy (unused for routing, but threaded for API
        symmetry with the planner; the router does not consult caps).

    Returns
    -------
    RoutingDecision
        A decision covering all 15 profiles.

    Raises
    ------
    ContractError
        If ``request`` or ``claim`` is not an object, or ``requested_profiles``
        names an unknown profile.
    """
    del policy  # router does not consult caps; threaded for API symmetry
    if not isinstance(request, dict):
        msg = f"request must be an object, got {type(request).__name__}"
        raise ContractError(msg)
    if not isinstance(claim, dict):
        msg = f"claim must be an object, got {type(claim).__name__}"
        raise ContractError(msg)

    requested = request.get("requested_profiles", [])
    if not isinstance(requested, list):
        msg = "request 'requested_profiles' must be an array"
        raise ContractError(msg)
    for p in requested:
        if not isinstance(p, str) or p not in _KNOWN_PROFILES:
            msg = f"requested_profiles entry {p!r} is not a known profile"
            raise ContractError(msg)

    # The symbol_table / condition_set may be absent (a bare claim); the
    # classifier tolerates empty dicts. They are read from the request if
    # carried there (a request may bundle its inputs); else empty.
    symbol_table = (
        request.get("symbol_table", {}) if isinstance(request.get("symbol_table"), dict) else {}
    )
    condition_set = (
        request.get("condition_set", {}) if isinstance(request.get("condition_set"), dict) else {}
    )

    # Always run the classifier (for the trace); it selects the applicable set.
    classified, trace = classify(claim, symbol_table, condition_set)
    classified_set = set(classified)

    # Determine the "applicable" set:
    #  - if requested_profiles is non-empty, the applicable set is the
    #    requested profiles (the request explicitly names them); classifier
    #    output is still recorded in the trace but does not expand the set.
    #  - if requested_profiles is empty (auto-classify), the applicable set is
    #    the classifier's selection.
    if requested:
        applicable_set = set(requested)
    else:
        applicable_set = classified_set

    decisions: dict[str, ProfileRouting] = {}
    for profile in SCIENCE_LAB_PROFILES:
        if profile in applicable_set:
            decisions[profile] = _route_one(profile, applicable=True, catalog=catalog)
        else:
            # Not applicable -> either EXCLUDED_TYPED (request named others) or
            # NOT_APPLICABLE (auto-classify and classifier didn't select).
            capability_id = catalog.capability_id_for(profile)
            entry = catalog.entry_for(profile)
            availability = entry.availability if entry is not None else "unknown"
            if requested:
                # The request named a non-empty set; profiles outside it are
                # EXCLUDED_TYPED with reason 'not_requested'.
                decisions[profile] = ProfileRouting(
                    profile=profile,
                    selection=SELECTION_EXCLUDED_TYPED,
                    capability_id=capability_id,
                    adapter_id=None,
                    availability=availability,
                    exclusion_reason=EXCLUSION_NOT_REQUESTED,
                )
            else:
                # Auto-classify: a profile the classifier didn't select is
                # NOT_APPLICABLE. (If the classifier explicitly excluded it via
                # a future negative rule, that would be classifier_excluded;
                # today the classifier only adds, so this is NOT_APPLICABLE.)
                decisions[profile] = ProfileRouting(
                    profile=profile,
                    selection=SELECTION_NOT_APPLICABLE,
                    capability_id=capability_id,
                    adapter_id=None,
                    availability=availability,
                    exclusion_reason=None,
                )

    # Cover any explicitly-requested semantic future profiles through the
    # unknown/future capability path (no local adapter, no silent fallback).
    decisions.update(_route_future_profiles(applicable_set, catalog))

    return RoutingDecision(profiles=decisions, classifier_trace=trace)


__all__ = [
    "EXCLUSION_CLASSIFIER_EXCLUDED",
    "EXCLUSION_NOT_REQUESTED",
    "ROUTER_FAIL_REASON",
    "SELECTION_EXCLUDED_TYPED",
    "SELECTION_NOT_APPLICABLE",
    "SELECTION_SELECTED",
    "SELECTION_STATES",
    "SELECTION_WAIT_CAPABILITY",
    "ProfileRouting",
    "RoutingDecision",
    "route",
]
