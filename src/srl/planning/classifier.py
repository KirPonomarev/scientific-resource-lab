"""Deterministic claim classifier: claim + inputs -> frozenset of profiles.

The classifier is a PURE, deterministic function: the same
``(claim, symbol_table, condition_set)`` always yields the same set of profiles
and the same ``rule_trace``. There is no randomness, no I/O, and no clock
dependence. This is the load-bearing property the router's determinism rests
on: the router is a pure function of (request, claim, catalog, policy) BECAUSE
the classifier is a pure function of its inputs.

Rule table
----------
The rule table is explicit in code (the ``_RULES`` list). Each rule has:

- ``id`` — a stable rule identifier (the trace records which rules fired);
- ``profiles`` — the profiles the rule selects when it fires;
- ``applies(claim, symbol_table, condition_set)`` — a predicate over the inputs.

Rules are evaluated in declaration order; a profile selected by any firing rule
is in the result. The trace is the list of rule ids that fired, in order. A
claim matching NO rule yields an empty frozenset (the router then routes every
profile NOT_APPLICABLE unless the request explicitly names it).

What the classifier keys off
----------------------------
The classifier reads only the claim's structural fields (``claim_class``,
``epistemic_source``, ``statement`` substrings) and the cds present in the
symbol_table / condition_set. It does NOT inspect evidence (a plan is not
evidence) and does NOT consult the catalog (catalog availability is the
router's concern, decided AFTER classification). This keeps classification
stable across catalog changes.
"""

from __future__ import annotations

from typing import Any, Final, Protocol

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.planning.profiles import PROFILE_NAMES, SCIENCE_LAB_PROFILES

# The typed fail reason for a classifier-structural violation (malformed inputs).
CLASSIFIER_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON


class _HasConditions(Protocol):
    """Structural protocol for a condition_set-like input (has 'conditions')."""

    conditions: Any


def _coerce_dict(value: Any, *, field: str) -> dict[str, Any]:
    """Return ``value`` if it is a dict; raise ContractError otherwise."""
    if not isinstance(value, dict):
        msg = f"classifier {field} must be an object, got {type(value).__name__}"
        raise ContractError(msg)
    return value


def _claim_statement(claim: dict[str, Any]) -> str:
    """Return the lowercased claim statement, or '' if absent/non-string."""
    statement = claim.get("statement", "")
    if not isinstance(statement, str):
        return ""
    return statement.lower()


def _claim_class(claim: dict[str, Any]) -> str:
    """Return the claim_class, or '' if absent/non-string."""
    cc = claim.get("claim_class", "")
    return cc if isinstance(cc, str) else ""


def _epistemic_source(claim: dict[str, Any]) -> str:
    """Return the epistemic_source, or '' if absent/non-string."""
    es = claim.get("epistemic_source", "")
    return es if isinstance(es, str) else ""


def _cds_present(symbol_table: dict[str, Any], condition_set: dict[str, Any]) -> frozenset[str]:
    """Return the set of MathIR cds present across the symbol_table + condition_set.

    A symbol_table entry's ``cd`` field names a content dictionary; a
    condition_set entry may carry an ``op`` (a ``<cd>.<name>`` string) whose
    ``<cd>`` prefix is extracted. The union is the cds the classifier can key
    applicability off.
    """
    cds: set[str] = set()
    symbols = symbol_table.get("symbols", [])
    if isinstance(symbols, list):
        for sym in symbols:
            if isinstance(sym, dict):
                cd = sym.get("cd")
                if isinstance(cd, str) and cd:
                    cds.add(cd)
    conditions = condition_set.get("conditions", [])
    if isinstance(conditions, list):
        for cond in conditions:
            if isinstance(cond, dict):
                op = cond.get("op")
                if isinstance(op, str) and "." in op:
                    cds.add(op.split(".", 1)[0])
                cd = cond.get("cd")
                if isinstance(cd, str) and cd:
                    cds.add(cd)
    return frozenset(cds)


def _statement_mentions(statement: str, *needles: str) -> bool:
    """Return True iff ``statement`` contains any of ``needles``."""
    return any(n in statement for n in needles)


# ---------------------------------------------------------------------------
# The explicit rule table. Order matters only for the trace; a profile selected
# by any firing rule is in the result. Each rule is self-contained and pure.
# ---------------------------------------------------------------------------


class _Rule(Protocol):
    """Structural protocol for a classifier rule."""

    id: str
    profiles: tuple[str, ...]

    def applies(
        self,
        claim: dict[str, Any],
        symbol_table: dict[str, Any],
        condition_set: dict[str, Any],
    ) -> bool: ...


class _StatementRule:
    """A rule that fires when the claim statement mentions any of a set of keywords."""

    __slots__ = ("id", "keywords", "profiles")

    def __init__(self, rid: str, keywords: tuple[str, ...], profiles: tuple[str, ...]) -> None:
        self.id = rid
        self.keywords = keywords
        self.profiles = profiles

    def applies(
        self, claim: dict[str, Any], symbol_table: dict[str, Any], condition_set: dict[str, Any]
    ) -> bool:
        del symbol_table, condition_set  # statement rules do not consult inputs
        return _statement_mentions(_claim_statement(claim), *self.keywords)


class _CdRule:
    """A rule that fires when any of a set of MathIR cds is present in the inputs."""

    __slots__ = ("cds", "id", "profiles")

    def __init__(self, rid: str, cds: tuple[str, ...], profiles: tuple[str, ...]) -> None:
        self.id = rid
        self.cds = cds
        self.profiles = profiles

    def applies(
        self, claim: dict[str, Any], symbol_table: dict[str, Any], condition_set: dict[str, Any]
    ) -> bool:
        del claim  # cd rules do not consult the claim
        present = _cds_present(symbol_table, condition_set)
        return any(cd in present for cd in self.cds)


class _SourceRule:
    """A rule that fires on the claim's epistemic_source."""

    __slots__ = ("id", "profiles", "source")

    def __init__(self, rid: str, source: str, profiles: tuple[str, ...]) -> None:
        self.id = rid
        self.source = source
        self.profiles = profiles

    def applies(
        self, claim: dict[str, Any], symbol_table: dict[str, Any], condition_set: dict[str, Any]
    ) -> bool:
        del symbol_table, condition_set
        return _epistemic_source(claim) == self.source


class _ClassRule:
    """A rule that fires on the claim's claim_class."""

    __slots__ = ("claim_class", "id", "profiles")

    def __init__(self, rid: str, claim_class: str, profiles: tuple[str, ...]) -> None:
        self.id = rid
        self.claim_class = claim_class
        self.profiles = profiles

    def applies(
        self, claim: dict[str, Any], symbol_table: dict[str, Any], condition_set: dict[str, Any]
    ) -> bool:
        del symbol_table, condition_set
        return _claim_class(claim) == self.claim_class


# The rule table. Each rule's profiles MUST be known profile names; the module
# constructor below validates this once at import time.
_RULES: Final[list[_Rule]] = [
    # Literature-sourced claims engage the literature + extraction profiles.
    _SourceRule("R-LITERATURE", "literature", ("literature", "literature_extraction")),
    # An established-law reference engages symbolic-law + a proof obligation.
    _ClassRule(
        "R-ESTABLISHED-LAW",
        "established_law_reference",
        ("symbolic_law", "theorem_or_proof_obligation"),
    ),
    # Statement-keyword rules: map scientific vocabulary to profiles.
    _StatementRule(
        "R-TDA",
        ("persistent homology", "topological data analysis", "betti number", "filtration"),
        ("geometry_tda",),
    ),
    _StatementRule(
        "R-ODE",
        (
            "ode",
            "ordinary differential equation",
            "initial value problem",
            "differential-algebraic",
            "dae",
            "sde",
            "stochastic differential",
        ),
        ("executable_ode_dae_sde_model", "dynamics"),
    ),
    _StatementRule(
        "R-PDE",
        ("pde", "partial differential equation", "variational", "finite element", "weak form"),
        ("pde_variational_model", "dynamics"),
    ),
    _StatementRule(
        "R-NONLINEAR-CONSTRAINT",
        ("nonlinear constraint", "hybrid system", "smt", "satisfiability", "constraint solving"),
        ("nonlinear_continuous_or_hybrid_constraint",),
    ),
    _StatementRule(
        "R-CAUSAL",
        ("causal", "granger", "intervention", "do-calculus", "time series", "time-series"),
        ("causal_time_series",),
    ),
    _StatementRule(
        "R-UNCERTAINTY",
        (
            "uncertainty",
            "confidence interval",
            "bayesian",
            "posterior",
            "propagation of uncertainty",
        ),
        ("uncertainty",),
    ),
    _StatementRule(
        "R-OPTIMIZATION",
        ("optimization", "optimal control", "minimize", "maximize", "convex program", "lagrangian"),
        ("optimization",),
    ),
    _StatementRule(
        "R-PROOF",
        ("theorem", "proof", "lemma", "corollary", "conjecture"),
        ("theorem_or_proof_obligation",),
    ),
    _StatementRule(
        "R-ALGEBRA",
        (
            "linear system",
            "eigenvalue",
            "matrix inverse",
            "exact arithmetic",
            "grobner",
            "symbolic",
        ),
        ("algebra_exact",),
    ),
    _StatementRule(
        "R-MODEL-COMPOSITION",
        (
            "composition",
            "coupled model",
            "subsystem",
            "hierarchical model",
            "composition of models",
        ),
        ("model_composition",),
    ),
    _StatementRule(
        "R-PROTOCOL",
        ("protocol", "specification", "refinement", "invariant preservation"),
        ("formal_protocol",),
    ),
    # Content-dictionary rules: map the MathIR cds present in the inputs.
    _CdRule("R-CD-CALCULUS", ("calculus1",), ("dynamics",)),
    _CdRule("R-CD-LINALG", ("linalg1",), ("algebra_exact",)),
    _CdRule("R-CD-LOGIC", ("logic1",), ("theorem_or_proof_obligation", "formal_protocol")),
    _CdRule("R-CD-SET", ("set1",), ("geometry_tda",)),
]


def _validate_rules() -> None:
    """Validate the rule table once at import time: every profile is known."""
    for rule in _RULES:
        for p in rule.profiles:
            if p not in PROFILE_NAMES:
                msg = f"classifier rule {rule.id!r} names unknown profile {p!r}"
                raise ContractError(msg)


_validate_rules()


def classify(
    claim: Any,
    symbol_table: Any,
    condition_set: Any,
) -> tuple[frozenset[str], list[str]]:
    """Classify a claim into a frozenset of capability profiles (deterministic).

    Pure function: the same inputs always yield the same profiles and the same
    ``rule_trace`` (the list of rule ids that fired, in declaration order). A
    claim matching NO rule yields an empty frozenset.

    Parameters
    ----------
    claim:
        A ScientificClaim/v1 wire dict (or any dict with ``statement``,
        ``claim_class``, ``epistemic_source`` keys).
    symbol_table:
        A SymbolTable/v1 wire dict (or any dict with a ``symbols`` list whose
        entries carry a ``cd`` field).
    condition_set:
        A ConditionSet/v1 wire dict (or any dict with a ``conditions`` list
        whose entries carry an ``op`` ``<cd>.<name>`` or a ``cd`` field).

    Returns
    -------
    (frozenset[str], list[str])
        The selected profiles (unordered) and the rule trace (ordered list of
        fired rule ids).

    Raises
    ------
    ContractError
        If ``claim``, ``symbol_table``, or ``condition_set`` is not an object.
    """
    c = _coerce_dict(claim, field="claim")
    st = _coerce_dict(symbol_table, field="symbol_table")
    cs = _coerce_dict(condition_set, field="condition_set")

    selected: set[str] = set()
    trace: list[str] = []
    for rule in _RULES:
        if rule.applies(c, st, cs):
            trace.append(rule.id)
            for p in rule.profiles:
                if p not in PROFILE_NAMES:  # pragma: no cover (validated at import)
                    msg = f"rule {rule.id!r} selected unknown profile {p!r}"
                    raise ContractError(msg)
                selected.add(p)
    return frozenset(selected), trace


def all_profiles() -> frozenset[str]:
    """Return the frozenset of all 15 profile names (convenience for the router)."""
    return frozenset(SCIENCE_LAB_PROFILES)


__all__ = [
    "CLASSIFIER_FAIL_REASON",
    "all_profiles",
    "classify",
]
