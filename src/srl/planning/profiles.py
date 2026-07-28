"""The 15 capability profiles the science-lab router/planner routes over.

A *capability profile* is a named class of scientific capability the science
lab can engage for a claim (e.g. ``geometry_tda`` = topological data
analysis, ``executable_ode_dae_sde_model`` = a runnable ODE/DAE/SDE model).
The router decides, for each profile, one of four typed selection states:

- ``SELECTED`` — the profile applies to the claim AND an adapter is available;
- ``EXCLUDED_TYPED`` — the request or classifier explicitly excluded it (reason);
- ``NOT_APPLICABLE`` — the profile does not apply to this claim;
- ``WAIT_CAPABILITY`` — the profile applies but no adapter is available yet
  (the capability is unknown / future / remote_required). This is an HONEST
  wait, never a silent fallback to a local substitute.

This module is the single source of truth for the 15 profile names and their
typed metadata:

- ``required_inputs`` — which MathIR content-dictionaries (cds) / object types
  the profile consumes (e.g. ``geometry_tda`` consumes point-cloud objects and
  ``relation1`` / ``set1`` cds);
- ``produced_evidence_axes`` — which :mod:`srl.semantic.evidence` axes a run of
  the profile can move (the planner does not assert these; it records them so a
  consumer knows what evidence a SELECTED step could contribute);
- ``default_resource_class`` — the resource class the profile prefers
  (``default`` or ``exception``); the request's class overrides this.

The 15 names mirror the ``requested_profiles`` enum in
``science-lab-run-request.json`` / ``science-lab-plan.json`` exactly. They are
kept here as a frozenset + tuple so the router and classifier can introspect
them in canonical order.

Profile grouping
----------------
The profiles fall into families that the classifier keys off:

- **symbolic** — ``algebra_exact``, ``symbolic_law``, ``theorem_or_proof_obligation``,
  ``formal_protocol``;
- **dynamical** — ``dynamics``, ``executable_ode_dae_sde_model``,
  ``pde_variational_model``, ``nonlinear_continuous_or_hybrid_constraint``;
- **geometric** — ``geometry_tda``;
- **statistical** — ``causal_time_series``, ``uncertainty``, ``optimization``;
- **compositional** — ``model_composition``;
- **literature** — ``literature``, ``literature_extraction``.

The families are documented here for the classifier's rule table; the router
treats each profile independently.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# The 15 capability profile names (canonical order — matches the schema enum).
# ---------------------------------------------------------------------------

#: The 15 profile names in canonical order. This tuple IS the schema enum order;
#: the JSON Schemas list the same names verbatim.
SCIENCE_LAB_PROFILES: Final[tuple[str, ...]] = (
    "algebra_exact",
    "symbolic_law",
    "dynamics",
    "geometry_tda",
    "causal_time_series",
    "uncertainty",
    "optimization",
    "formal_protocol",
    "literature",
    "theorem_or_proof_obligation",
    "nonlinear_continuous_or_hybrid_constraint",
    "executable_ode_dae_sde_model",
    "pde_variational_model",
    "model_composition",
    "literature_extraction",
)

#: O(1) membership test for the 15 profile names.
PROFILE_NAMES: Final[frozenset[str]] = frozenset(SCIENCE_LAB_PROFILES)


# ---------------------------------------------------------------------------
# Typed profile metadata.
# ---------------------------------------------------------------------------


class CapabilityProfile:
    """A typed capability profile with its required inputs and evidence axes.

    Attributes
    ----------
    name:
        The profile name (one of :data:`SCIENCE_LAB_PROFILES`).
    family:
        The profile family (symbolic / dynamical / geometric / statistical /
        composition / literature). Informational; the router treats each
        profile independently.
    required_inputs:
        The MathIR content-dictionaries / object types a run of the profile
        consumes. Used by the classifier to decide applicability. Each entry is
        either a MathIR cd prefix (e.g. ``"calculus1"``) or an object-type name
        the fabric produces (e.g. ``"model_interface"``).
    produced_evidence_axes:
        The :mod:`srl.semantic.evidence` axis names a SELECTED run of the
        profile could move. The planner records these on a step so a consumer
        knows what evidence a step could contribute; the planner NEVER asserts
        a movement (a SELECTED step is "will run", not "ran").
    default_resource_class:
        The resource class the profile prefers. The request's resource_class
        overrides this for admission; the default is informational.
    """

    __slots__ = (
        "default_resource_class",
        "family",
        "name",
        "produced_evidence_axes",
        "required_inputs",
    )

    def __init__(
        self,
        *,
        name: str,
        family: str,
        required_inputs: tuple[str, ...],
        produced_evidence_axes: tuple[str, ...],
        default_resource_class: str = "default",
    ) -> None:
        if name not in PROFILE_NAMES:
            msg = f"unknown profile name {name!r}; must be one of {sorted(PROFILE_NAMES)}"
            raise ValueError(msg)
        if default_resource_class not in {"default", "exception"}:
            msg = (
                f"default_resource_class {default_resource_class!r} must be "
                "'default' or 'exception'"
            )
            raise ValueError(msg)
        self.name: Final[str] = name
        self.family: Final[str] = family
        self.required_inputs: Final[tuple[str, ...]] = required_inputs
        self.produced_evidence_axes: Final[tuple[str, ...]] = produced_evidence_axes
        self.default_resource_class: Final[str] = default_resource_class

    def __repr__(self) -> str:  # pragma: no cover (debug aid)
        return f"CapabilityProfile(name={self.name!r}, family={self.family!r})"


# The 15 typed profile specs: (name, family, required_inputs, produced_axes, default_class).
# required_inputs lists the MathIR cds / object types the profile consumes;
# produced_evidence_axes lists the evidence axes a SELECTED run could move
# (informational — the planner never asserts a movement).
_PROFILE_SPECS: Final[tuple[tuple[str, str, tuple[str, ...], tuple[str, ...], str], ...]] = (
    # --- symbolic family ---
    (
        "algebra_exact",
        "symbolic",
        ("arith1", "relation1", "linalg1"),
        ("formal_check", "formal_scope"),
        "default",
    ),
    (
        "symbolic_law",
        "symbolic",
        ("relation1", "logic1", "nums1"),
        ("formal_check", "formal_scope"),
        "default",
    ),
    # --- dynamical family ---
    (
        "dynamics",
        "dynamical",
        ("calculus1", "arith1", "relation1"),
        ("scientific_check", "statistical_support"),
        "default",
    ),
    # --- geometric family ---
    (
        "geometry_tda",
        "geometric",
        ("set1", "relation1", "model_interface"),
        ("scientific_check", "statistical_support"),
        "exception",
    ),
    # --- statistical family ---
    (
        "causal_time_series",
        "statistical",
        ("calculus1", "relation1", "model_interface"),
        ("statistical_support", "causal_identification"),
        "default",
    ),
    (
        "uncertainty",
        "statistical",
        ("arith1", "relation1", "linalg1"),
        ("statistical_support",),
        "default",
    ),
    (
        "optimization",
        "statistical",
        ("calculus1", "arith1", "relation1"),
        ("statistical_support",),
        "default",
    ),
    # --- symbolic family (cont.) ---
    (
        "formal_protocol",
        "symbolic",
        ("logic1", "relation1", "fns1"),
        ("formal_check", "formal_scope"),
        "default",
    ),
    # --- literature family ---
    (
        "literature",
        "literature",
        ("claim",),
        ("scientific_check", "independent_empirical_replication"),
        "default",
    ),
    # --- symbolic family (cont.) ---
    (
        "theorem_or_proof_obligation",
        "symbolic",
        ("logic1", "relation1", "fns1"),
        ("formal_check", "formal_scope"),
        "default",
    ),
    # --- dynamical family (cont.) ---
    (
        "nonlinear_continuous_or_hybrid_constraint",
        "dynamical",
        ("calculus1", "logic1", "relation1", "linalg1"),
        ("formal_check", "formal_scope"),
        "exception",
    ),
    (
        "executable_ode_dae_sde_model",
        "dynamical",
        ("calculus1", "arith1", "model_interface"),
        ("scientific_check", "statistical_support"),
        "exception",
    ),
    (
        "pde_variational_model",
        "dynamical",
        ("calculus1", "linalg1", "model_interface"),
        ("scientific_check", "statistical_support"),
        "exception",
    ),
    # --- composition family ---
    (
        "model_composition",
        "composition",
        ("fns1", "arith1", "model_interface"),
        ("scientific_check", "statistical_support"),
        "exception",
    ),
    # --- literature family (cont.) ---
    ("literature_extraction", "literature", ("claim",), ("scientific_check",), "default"),
)

# Profile families (used by the classifier's rule table documentation). A
# profile belongs to exactly one family; the router treats each profile
# independently so the family is informational, not load-bearing for routing.
SYMBOLIC_PROFILES: Final[frozenset[str]] = frozenset(
    {
        "algebra_exact",
        "symbolic_law",
        "theorem_or_proof_obligation",
        "formal_protocol",
    }
)
DYNAMICAL_PROFILES: Final[frozenset[str]] = frozenset(
    {
        "dynamics",
        "executable_ode_dae_sde_model",
        "pde_variational_model",
        "nonlinear_continuous_or_hybrid_constraint",
    }
)
GEOMETRIC_PROFILES: Final[frozenset[str]] = frozenset({"geometry_tda"})
STATISTICAL_PROFILES: Final[frozenset[str]] = frozenset(
    {"causal_time_series", "uncertainty", "optimization"}
)
COMPOSITION_PROFILES: Final[frozenset[str]] = frozenset({"model_composition"})
LITERATURE_PROFILES: Final[frozenset[str]] = frozenset({"literature", "literature_extraction"})


def _build_profile_table() -> dict[str, CapabilityProfile]:
    """Build the 15-entry profile table keyed by profile name.

    Asserts each spec is a known profile name, there are no duplicates, and the
    table is complete (every profile name has an entry, no extras).
    """
    table: dict[str, CapabilityProfile] = {}
    for name, family, inputs, axes, rclass in _PROFILE_SPECS:
        if name in table:
            msg = f"duplicate profile {name!r} in spec table"
            raise ValueError(msg)
        table[name] = CapabilityProfile(
            name=name,
            family=family,
            required_inputs=inputs,
            produced_evidence_axes=axes,
            default_resource_class=rclass,
        )
    missing = sorted(set(SCIENCE_LAB_PROFILES) - set(table))
    if missing:
        msg = f"profile table missing entries for: {missing}"
        raise ValueError(msg)
    extra = sorted(set(table) - set(SCIENCE_LAB_PROFILES))
    if extra:
        msg = f"profile table has unexpected entries: {extra}"
        raise ValueError(msg)
    return table


#: The 15 typed profile definitions, keyed by profile name.
PROFILES: Final[dict[str, CapabilityProfile]] = _build_profile_table()


def profile(name: str) -> CapabilityProfile:
    """Return the typed :class:`CapabilityProfile` for ``name``.

    Raises
    ------
    ValueError
        If ``name`` is not one of the 15 profile names.
    """
    p = PROFILES.get(name)
    if p is None:
        msg = f"unknown profile name {name!r}; must be one of {sorted(PROFILE_NAMES)}"
        raise ValueError(msg)
    return p


def required_inputs(name: str) -> tuple[str, ...]:
    """Return the required-inputs tuple for profile ``name`` (MathIR cds / object types)."""
    return profile(name).required_inputs


def produced_evidence_axes(name: str) -> tuple[str, ...]:
    """Return the produced-evidence-axes tuple for profile ``name``."""
    return profile(name).produced_evidence_axes


def default_resource_class(name: str) -> str:
    """Return the default resource class for profile ``name`` ('default' or 'exception')."""
    return profile(name).default_resource_class


# ---------------------------------------------------------------------------
# Inter-profile dependencies (the DAG edges the planner threads).
# ---------------------------------------------------------------------------

#: Static inter-profile dependency edges. A profile listed as a key depends on
#: the profiles in its value tuple (its outputs feed the dependent's inputs).
#: The planner also adds a validation step depending on each engine step at run
#: time; here we encode only the profile-level composition edges. The canonical
#: case: ``model_composition`` depends on at least one component profile; the
#: specific components are claim-dependent (the classifier selects them), so the
#: planner adds those edges dynamically. This static entry is informational.
PROFILE_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    "model_composition": (),
}


__all__ = [
    "COMPOSITION_PROFILES",
    "DYNAMICAL_PROFILES",
    "GEOMETRIC_PROFILES",
    "LITERATURE_PROFILES",
    "PROFILES",
    "PROFILE_DEPENDENCIES",
    "PROFILE_NAMES",
    "SCIENCE_LAB_PROFILES",
    "STATISTICAL_PROFILES",
    "SYMBOLIC_PROFILES",
    "CapabilityProfile",
    "default_resource_class",
    "produced_evidence_axes",
    "profile",
    "required_inputs",
]
