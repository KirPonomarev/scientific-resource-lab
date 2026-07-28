"""SMT satisfiability adapter (WP-E41).

This module is the satisfiability-checking layer for the SRL scientific fabric.
It is the **only** module in the SRL tree that imports :mod:`z3` (asserted by
an architecture test in ``tests/packs/test_smt_adapter.py``). Every other
consumer goes through the typed surface defined here:

- :class:`SolverChoice` — the solver an :func:`SmtOutcome` was produced by
  (``z3`` / ``cvc5`` / ``both``).
- :class:`SmtResult` — the satisfiability verdict (``sat`` / ``unsat`` /
  ``unknown``), as a comparable value, never a free string.
- :class:`SmtOutcome` — a frozen, content-addressable record of one solver
  run: result, solver, the model (for SAT) or null, and the wall-clock cost.
- :func:`check` — check a restricted S-expression formula spec under a hard
  timeout and formula-size cap.

Honesty contract (SAT/UNSAT is not empirical truth)
---------------------------------------------------
A SMT-style ``sat`` / ``unsat`` answer yields at most
``formal_check=checked`` on the evidence ladder — **never** ``proven``. The
``proven`` tier requires an independently checked exact certificate (an unsat
core verified by replay, or a proof object checked by a trusted checker),
which this work package does NOT implement. See
``docs/contracts/evidence-model.md`` ("The SMT is not proven rule") and
``docs/architecture/smt-pack.md``. This adapter exposes the SAT/UNSAT answer
and the honest ceiling; it never mints a certificate.

No raw SMT-LIB text eval
------------------------
The ``formula_spec`` is a **restricted S-expression JSON encoding**: a small
AST of ``[operator, *args]`` tuples (see :data:`SUPPORTED_OPERATORS`). The
adapter builds z3 terms through the z3 Python API only — it never calls
``z3.parse_smt2_string`` / ``eval`` / ``exec`` on caller-supplied text, so a
formula cannot smuggle arbitrary solver input. This is the
security-relevant surface: the only formula shapes a caller can express are
the operators an SRL human has reviewed.

Disagreement preservation
-------------------------
When two solvers run on the same formula and disagree, the disagreement is
**preserved** in :attr:`SmtOutcome.disagreement` (``{z3: ..., cvc5: ...,
agreement: false}``) and **never silently resolved**. A disagreement is a
scientifically interesting signal, not an error to paper over. In this
package z3 is the only solver with a cleared license; cvc5 is structurally
supported but ``WAIT_LICENSE`` (its wheels bundle GPLv3/LGPLv3 components —
see ADR-0004), so ``SolverChoice.both`` runs z3 alone and records cvc5 as
unavailable. The disagreement *path* is exercised by the gate via an injected
stub result so the preservation machinery is covered end-to-end.

Resource caps
-------------
:func:`check` enforces two hard caps before any solver runs:

- a **wall-seconds timeout cap** (:data:`MAX_WALL_SECONDS`), bounded by the
  M1 resource policy's exception envelope (900 s); the requested timeout is
  clamped to it and handed to the solver.
- a **formula-size cap** (:data:`MAX_FORMULA_NODES`), bounding the number of
  AST nodes in the ``formula_spec``; an oversized formula is rejected with
  ``SmtError`` (``CONTRACT_INVALID``) before the solver is constructed.

See ``docs/architecture/smt-pack.md`` for the operator table, the precision
of the model render, and the license rationale.
"""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import z3

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# The typed fail reason for an SMT contract violation. Mirrors the
# ``CONTRACT_INVALID`` entry in ``automation/fail-reasons.json`` (class
# ``canonical``, ``hard_stop=true``, ``retriable=false``): an oversized or
# malformed formula, or a timeout out of range, is a deterministic contract
# failure, not a transient one.
SMT_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# ---------------------------------------------------------------------------
# Resource caps. Bounded by the M1 resource policy exception envelope
# (src/srl/execution/policy.py: wall_seconds <= 900). The formula-size cap is
# an admission-time bound so a caller cannot hand the solver an unbounded AST.
# Both are module constants so the resource policy has one auditable home.
# ---------------------------------------------------------------------------

#: The maximum wall-seconds timeout :func:`check` will honour. The M1 policy's
#: exception envelope caps ``wall_seconds`` at 900 (``_EXCEPTION_CAPS``); an
#: SMT check may never exceed the policy's wall ceiling. A requested timeout
#: above this is clamped down (it is a cap, not a rejection — the caller asked
#: for "at most" this many seconds).
MAX_WALL_SECONDS: Final[int] = 900

#: The maximum number of AST nodes a ``formula_spec`` may contain. This is the
#: formula-size cap: an oversized formula is rejected with ``SmtError`` before
#: the solver is constructed, so a caller cannot hand the solver an unbounded
#: problem. 10_000 nodes is far beyond any hand-authored conformance formula
#: and well within the bounded-problem posture.
MAX_FORMULA_NODES: Final[int] = 10_000


# ---------------------------------------------------------------------------
# Enums: the solver choice and the satisfiability verdict.
# ---------------------------------------------------------------------------


class SolverChoice(StrEnum):
    """Which solver(s) to run.

    ``StrEnum`` keeps the serialized form a plain JSON string while giving
    membership tests. ``both`` asks for a dual-solver run; in this package z3
    is the only solver with a cleared license (cvc5 is ``WAIT_LICENSE``), so
    ``both`` runs z3 alone and records cvc5 as unavailable in the outcome.
    """

    Z3 = "z3"
    CVC5 = "cvc5"
    BOTH = "both"


class SmtResult(StrEnum):
    """The satisfiability verdict of one solver run.

    - ``sat`` — the formula is satisfiable; :attr:`SmtOutcome.model` carries a
      witness assignment.
    - ``unsat`` — the formula is unsatisfiable.
    - ``unknown`` — the solver could not decide in the time/resource bound
      (a timeout, or an incompleteness). The result is honest, not a failure.

    A ``sat``/``unsat`` answer yields at most ``formal_check=checked``; it is
    **never** promoted to ``proven`` without an independently checked
    certificate (see the module docstring and ADR-0004).
    """

    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"


#: The set of solver identifiers that have a cleared license in this package.
#: ``cvc5`` is structurally supported by the adapter but its wheels bundle
#: GPLv3/LGPLv3 components and ship no resolvable license expression, so it is
#: excluded on license grounds (see ADR-0004). It is recorded here so callers
#: and the gate can introspect availability without importing the solver.
AVAILABLE_SOLVERS: Final[frozenset[str]] = frozenset({"z3"})

#: Solvers that are structurally supported by the adapter but held back on
#: license grounds. The disagreement-preservation path treats these as
#: "ran but unavailable" rather than "ran and disagreed", so a missing solver
#: is never mistaken for a solver disagreement.
WAIT_LICENSE_SOLVERS: Final[frozenset[str]] = frozenset({"cvc5"})


# ---------------------------------------------------------------------------
# Outcomes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmtOutcome:
    """A frozen, content-addressable record of one (or two) solver run(s).

    The single-solver case carries the verdict on :attr:`result` and the
    witness on :attr:`model`. The dual-solver case (``solver == both``) carries
    the per-solver sub-outcomes on :attr:`disagreement` and, when the two
    agree, folds the agreed verdict onto :attr:`result`.

    Attributes
    ----------
    result:
        The satisfiability verdict. For ``solver == both`` with agreement this
        is the shared verdict; for a disagreement it is ``unknown`` (the
        adapter refuses to pick a winner — see :attr:`disagreement`).
    solver:
        The solver the outcome was produced by (``z3`` / ``cvc5`` / ``both``).
    model:
        A witness assignment for a ``sat`` result, as a ``{var: value_string}``
        mapping of decimal-string policy values; ``None`` for ``unsat`` /
        ``unknown``. For ``solver == both`` with a SAT agreement the model is
        z3's (the cleared solver).
    wall_seconds:
        The wall-clock cost of the run, in seconds, as a JSON-safe float
        rounded to microsecond precision.
    disagreement:
        Present only for ``solver == both``: ``{z3: SmtOutcome, cvc5: SmtOutcome
        | null, agreement: bool}``. When ``agreement`` is ``False`` the
        disagreement is preserved and :attr:`result` is ``unknown``; the
        adapter never silently resolves it.
    unknown_reason:
        For an ``unknown`` result, a short string naming why (``timeout``,
        ``solver_unknown``, ``disagreement``, ``cvc5_wait_license``). Empty for
        a decided ``sat``/``unsat`` result.
    """

    result: SmtResult
    solver: SolverChoice
    model: dict[str, str] | None = None
    wall_seconds: float = 0.0
    disagreement: dict[str, Any] | None = None
    unknown_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the outcome as a plain JSON-serializable dict.

        Nested outcomes (in :attr:`disagreement`) are serialized recursively,
        so a dual-solver outcome round-trips as JSON for receipt evidence.
        """

        def _ser(val: Any) -> Any:
            if isinstance(val, SmtOutcome):
                return val.to_dict()
            if isinstance(val, dict):
                return {k: _ser(v) for k, v in val.items()}
            if isinstance(val, (list, tuple)):
                return [_ser(v) for v in val]
            if isinstance(val, StrEnum):
                return str(val)
            return val

        return {
            "result": str(self.result),
            "solver": str(self.solver),
            "model": self.model,
            "wall_seconds": self.wall_seconds,
            "disagreement": _ser(self.disagreement),
            "unknown_reason": self.unknown_reason,
        }


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class SmtError(ContractError):
    """Raised when a formula spec or solver request is invalid.

    Carries the typed fail reason ``CONTRACT_INVALID``. Raised for: a
    malformed S-expression, an unsupported operator, an oversized formula, a
    timeout out of range, or a requested solver with no cleared license as a
    *sole* solver (``solver=cvc5`` alone is rejected; ``cvc5`` may only appear
    as the second solver in a ``both`` run, where it is recorded as
    unavailable). Always raised *before* any solver runs.
    """


# ---------------------------------------------------------------------------
# The restricted S-expression formula spec.
#
# A formula_spec is a JSON S-expression: a list whose head is an operator
# string and whose tail is zero or more operands. An operand is either a
# nested S-expression (a sub-formula) or an atom. The adapter validates the
# shape and the operator, then builds z3 terms through the z3 API only — no
# raw SMT-LIB text is ever evaluated.
# ---------------------------------------------------------------------------

#: The operators the restricted S-expression grammar admits, grouped by arity.
#: These are the ONLY formula shapes a caller can express; adding one is a
#: documented change to this table. The grammar is deliberately small and
#: auditable (boolean connectives, arithmetic comparisons, and linear
#: arithmetic over integers and reals) so the solver input surface is bounded.
SUPPORTED_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        # Boolean connectives (n-ary And/Or, unary Not, binary Implies).
        "and",
        "or",
        "not",
        "implies",
        # Equality / disequality (n-ary ==, binary !=).
        "=",
        "distinct",
        # Arithmetic comparisons (binary).
        "<",
        "<=",
        ">",
        ">=",
        # Arithmetic operators (n-ary +, *; binary -; binary /).
        "+",
        "-",
        "*",
        "/",
        # Constant/variable atoms (leaf producers).
        "int-const",
        "real-const",
        "int-var",
        "real-var",
    }
)

# Arity rule tags. "n" means variadic (>= the floor); the fixed-arity tags
# name the exact operand count an operator accepts. Kept as named constants
# rather than bare string literals so the grammar check reads by intent.
_ARITY_UNARY: Final[str] = "1"
_ARITY_BINARY: Final[str] = "2"
_ARITY_VARIADIC: Final[str] = "n"

# Exact operand counts for the fixed-arity operators (unary/binary). Named so
# the arity validation reads by intent rather than as bare integer literals.
_UNARY_OPERAND_COUNT: Final[int] = 1
_BINARY_OPERAND_COUNT: Final[int] = 2

# Arity rules per operator. "n" means variadic (>= the floor), the unary/binary
# tags mean exactly that many operands. The grammar check enforces these before
# any term is built.
_ARITY: Final[dict[str, tuple[int, str]]] = {
    "and": (2, _ARITY_VARIADIC),
    "or": (2, _ARITY_VARIADIC),
    "not": (1, _ARITY_UNARY),
    "implies": (2, _ARITY_BINARY),
    "=": (2, _ARITY_VARIADIC),
    "distinct": (2, _ARITY_VARIADIC),
    "<": (2, _ARITY_VARIADIC),
    "<=": (2, _ARITY_VARIADIC),
    ">": (2, _ARITY_VARIADIC),
    ">=": (2, _ARITY_VARIADIC),
    "+": (2, _ARITY_VARIADIC),
    "-": (2, _ARITY_BINARY),
    "*": (2, _ARITY_VARIADIC),
    "/": (2, _ARITY_VARIADIC),
    "int-const": (1, _ARITY_UNARY),
    "real-const": (1, _ARITY_UNARY),
    "int-var": (1, _ARITY_UNARY),
    "real-var": (1, _ARITY_UNARY),
}


def _count_nodes(spec: Any) -> int:
    """Count the AST nodes in ``spec`` for the formula-size cap.

    A node is a list (an S-expression); atoms are not counted separately so
    the count is the number of operator applications. Raises nothing — a
    non-list/non-atom operand is a structural error caught later.
    """
    if isinstance(spec, list):
        return 1 + sum(_count_nodes(child) for child in spec)
    return 0


def _is_atom(spec: Any) -> bool:
    """Return True iff ``spec`` is an atom (a JSON scalar operand)."""
    return isinstance(spec, (str, int, float, bool)) and not isinstance(spec, list)


def _validate_arity(op: str, args: list[Any]) -> None:
    """Validate the operand count for ``op`` against its arity rule."""
    floor, kind = _ARITY[op]
    got = len(args)
    if kind == _ARITY_UNARY and got != _UNARY_OPERAND_COUNT:
        msg = f"operator {op!r} takes exactly 1 operand, got {got}"
        raise SmtError(msg)
    if kind == _ARITY_BINARY and got != _BINARY_OPERAND_COUNT:
        msg = f"operator {op!r} takes exactly 2 operands, got {got}"
        raise SmtError(msg)
    if kind == _ARITY_VARIADIC and got < floor:
        msg = f"operator {op!r} takes at least {floor} operands, got {got}"
        raise SmtError(msg)


def _validate_spec(spec: Any) -> None:
    """Validate the formula-spec shape, operators, and arity, recursively.

    Raises :class:`SmtError` (``CONTRACT_INVALID``) on the first structural
    problem: a non-list root, an unknown operator, a bad arity, or a malformed
    atom. Runs the formula-size cap first so an oversized formula is rejected
    before the recursive walk.
    """
    if not isinstance(spec, list) or len(spec) == 0:
        msg = (
            "formula_spec must be a non-empty list S-expression "
            "[operator, *operands], got a non-list or empty value"
        )
        raise SmtError(msg)
    if _count_nodes(spec) > MAX_FORMULA_NODES:
        msg = (
            f"formula_spec has {_count_nodes(spec)} AST nodes, exceeding the "
            f"size cap of {MAX_FORMULA_NODES}; an oversized formula is rejected "
            "before the solver runs"
        )
        raise SmtError(msg)
    _validate_spec_rec(spec)


def _validate_spec_rec(spec: Any) -> None:
    """Recursive half of :func:`_validate_spec` (post-size-cap)."""
    if _is_atom(spec):
        return
    if not isinstance(spec, list) or len(spec) == 0:
        msg = (
            "formula_spec operand must be an atom or a non-empty [operator, *operands] S-expression"
        )
        raise SmtError(msg)
    op = spec[0]
    args = spec[1:]
    if not isinstance(op, str) or op not in SUPPORTED_OPERATORS:
        msg = (
            f"formula_spec operator {op!r} is not supported; "
            f"must be one of {sorted(SUPPORTED_OPERATORS)}"
        )
        raise SmtError(msg)
    _validate_arity(op, list(args))
    # Leaf operators carry their own atom shape; validate the atom.
    if op in {"int-const", "real-const", "int-var", "real-var"}:
        _validate_leaf(op, args[0])
        return
    for child in args:
        _validate_spec_rec(child)


def _validate_leaf(op: str, atom: Any) -> None:
    """Validate the single atom operand of a leaf operator.

    ``int-const`` takes an int (a JSON number with no fractional part); a JSON
    bool is rejected (a boolean is not a quantity). ``real-const`` takes an int
    or a float. The ``*-var`` operators take a non-empty variable name string.
    """
    if op == "int-const":
        if isinstance(atom, bool) or not isinstance(atom, int):
            msg = f"int-const operand must be a JSON integer, got {atom!r}"
            raise SmtError(msg)
        return
    if op == "real-const":
        if isinstance(atom, bool) or not isinstance(atom, (int, float)):
            msg = f"real-const operand must be a JSON number, got {atom!r}"
            raise SmtError(msg)
        return
    # int-var / real-var: a non-empty variable name.
    if not isinstance(atom, str) or atom == "":
        msg = f"{op} operand must be a non-empty variable name string, got {atom!r}"
        raise SmtError(msg)
    return


# ---------------------------------------------------------------------------
# Term construction. Build z3 terms from the validated S-expression through the
# z3 API only — no parse_smt2_string / eval / exec on caller text. The term
# builder treats all z3 objects as opaque Any (see ADR-0004, isolation).
# ---------------------------------------------------------------------------


def _build_term(spec: Any, var_cache: dict[str, Any]) -> Any:
    """Build a z3 term from a validated S-expression.

    ``var_cache`` memoises z3 constant/variable declarations by name so a
    repeated ``int-var "x"`` yields the *same* z3 constant (otherwise z3 treats
    two separately-constructed consts of the same name as distinct and the
    solver reports ``sat`` trivially). Returns an opaque z3 expr (typed ``Any``
    to keep the isolation boundary clean; mypy checks the adapter's own typed
    contract, not z3's).
    """
    if _is_atom(spec):
        # A bare atom is only valid as an operand of a leaf operator; the
        # validator routes leaves through _validate_leaf before this builder
        # recurses, so a bare atom here is unreachable. Treat defensively.
        msg = "bare atom reached the term builder; expected a leaf S-expression"
        raise SmtError(msg)

    op = spec[0]
    args = spec[1:]

    if op == "int-const":
        return z3.IntVal(int(args[0]))
    if op == "real-const":
        val = args[0]
        # z3.RealVal accepts a Python int or float, or a string. A JSON float
        # round-trips via str() to avoid binary artefacts; an int passes as-is.
        return z3.RealVal(str(val)) if isinstance(val, float) else z3.RealVal(val)
    if op == "int-var":
        name = args[0]
        term = var_cache.get(name)
        if term is None:
            term = z3.Int(name)
            var_cache[name] = term
        return term
    if op == "real-var":
        name = args[0]
        term = var_cache.get(name)
        if term is None:
            term = z3.Real(name)
            var_cache[name] = term
        return term

    children = [_build_term(child, var_cache) for child in args]
    return _apply_operator(op, children)


def _chain_compare(children: list[Any], op: str) -> Any:
    """Build a chained comparison ``c0 <OP> c1 <OP> ... <OP> cn`` as a conjunction.

    Each adjacent pair is one comparison; the whole chain is their AND. This
    matches the arithmetic convention that ``a < b < c`` means ``a < b and
    b < c``. Used by ``<``, ``<=``, ``>``, ``>=``.
    """
    from operator import eq, ge, gt, le, lt  # noqa: PLC0415 (local import; trivial)

    compare = {"<": lt, "<=": le, ">": gt, ">=": ge, "=": eq}[op]
    return z3.And(*[compare(children[i], children[i + 1]) for i in range(len(children) - 1)])


def _build_division(children: list[Any]) -> Any:
    """Build a chained left-fold division ``(a/b)/c`` matching arithmetic habit.

    z3 models real division as a total function; we fold left so
    ``(/ a b c)`` is ``(a/b)/c``.
    """
    acc = children[0]
    for c in children[1:]:
        acc = acc / c
    return acc


def _build_product(children: list[Any]) -> Any:
    """Build a product: binary uses ``*`` directly, n-ary uses ``z3.Product``."""
    if len(children) == _BINARY_OPERAND_COUNT:
        return children[0] * children[1]
    return z3.Product(*children)


# Dispatch table mapping each operator to its z3 builder. Each builder is a
# small, single-purpose function so the dispatch is data-driven (keeping
# ``_apply_operator`` under the complexity branch budget) and each operator's
# build logic is auditable in isolation.
_OPERATOR_BUILDERS: Final[dict[str, Any]] = {
    "and": lambda c: z3.And(*c),
    "or": lambda c: z3.Or(*c),
    "not": lambda c: z3.Not(c[0]),
    "implies": lambda c: z3.Implies(c[0], c[1]),
    "=": lambda c: _chain_compare(c, "="),
    "distinct": lambda c: z3.Distinct(*c),
    "<": lambda c: _chain_compare(c, "<"),
    "<=": lambda c: _chain_compare(c, "<="),
    ">": lambda c: _chain_compare(c, ">"),
    ">=": lambda c: _chain_compare(c, ">="),
    "+": lambda c: z3.Sum(*c),
    "-": lambda c: c[0] - c[1],
    "*": _build_product,
    "/": _build_division,
}


def _apply_operator(op: str, children: list[Any]) -> Any:
    """Apply the z3 operator matching the validated ``op`` to built children."""
    builder = _OPERATOR_BUILDERS.get(op)
    if builder is None:
        # Unreachable: _validate_spec rejected unknown operators.
        msg = f"operator {op!r} passed arity but had no z3 builder (adapter bug)"
        raise SmtError(msg)
    return builder(children)


# ---------------------------------------------------------------------------
# Single-solver run + witness rendering.
# ---------------------------------------------------------------------------


def _render_value(term: Any) -> str:
    """Render a z3 model value as a decimal-string policy value.

    Integers render as their decimal string; reals render as a fraction or
    decimal via z3's ``sexpr``/``as_decimal`` so a rational witness survives a
    round trip without float coercion. Falls back to ``str()`` for any value
    shape the witness rendering does not special-case (e.g. a non-numeric
    sort, which the grammar does not admit).
    """
    # z3 integers carry a .as_long() accessor; reals carry .as_decimal(). Each
    # accessor may raise z3.Z3Exception on a non-numeric value (defensive: the
    # grammar does not admit non-numeric sorts); we suppress and fall through.
    as_long = getattr(term, "as_long", None)
    if callable(as_long):
        with suppress(Exception):
            return str(as_long())
    as_decimal = getattr(term, "as_decimal", None)
    if callable(as_decimal):
        with suppress(Exception):
            return str(as_decimal())
    return str(term)


def _run_z3(formula: Any, timeout_ms: int) -> tuple[SmtResult, dict[str, str] | None, str]:
    """Run z3 on ``formula`` with a millisecond timeout.

    Returns ``(result, model, unknown_reason)``. The model is rendered as a
    ``{var: decimal_string}`` mapping for a ``sat`` result; the unknown_reason
    names why a ``sat``/``unsat`` was not reached (``timeout`` when the solver
    hit the bound, else z3's reported reason).
    """
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(formula)
    outcome = solver.check()
    if outcome == z3.sat:
        model_obj = solver.model()
        witness: dict[str, str] = {}
        for decl in model_obj.decls():
            # Render only 0-arity constant declarations (the variables). The
            # model also exposes interpretations for uninterpreted/total
            # functions (e.g. real division `/`, modelled by z3 as a total
            # function); those have arity >= 1 and are not variable witnesses,
            # so they are skipped. Calling decl() on an arity>=1 decl would
            # raise a Z3Exception, and a function interpretation is not a
            # witness value anyway.
            if decl.arity() != 0:
                continue
            witness[str(decl())] = _render_value(model_obj[decl])
        return SmtResult.SAT, witness, ""
    if outcome == z3.unsat:
        return SmtResult.UNSAT, None, ""
    # unknown — classify the reason.
    reason = "timeout"
    try:
        reported = solver.unknown_reason()
    except Exception:
        reported = ""
    if reported:
        reason = str(reported)
    return SmtResult.UNKNOWN, None, reason


# ---------------------------------------------------------------------------
# Public API: check.
# ---------------------------------------------------------------------------


def _clamp_timeout(timeout: float | int | None) -> int:
    """Clamp a requested timeout to ``[0, MAX_WALL_SECONDS]`` milliseconds.

    ``None`` means "use the full cap". A negative timeout is a contract error
    (a bound cannot be negative). The returned value is the millisecond budget
    handed to the solver.
    """
    if timeout is None:
        return MAX_WALL_SECONDS * 1000
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        msg = f"timeout must be a number or None, got {type(timeout).__name__}"
        raise SmtError(msg)
    if timeout < 0:
        msg = f"timeout must be non-negative, got {timeout!r}"
        raise SmtError(msg)
    capped = min(float(timeout), float(MAX_WALL_SECONDS))
    return int(capped * 1000)


@dataclass(frozen=True, slots=True)
class _RunArtifact:
    """Internal record of a single solver invocation for outcome assembly."""

    result: SmtResult
    model: dict[str, str] | None
    wall_seconds: float
    unknown_reason: str
    available: bool = True
    unavailable_reason: str = ""


def _run_single(
    formula: Any,
    solver: str,
    timeout_ms: int,
    *,
    stub: dict[str, Any] | None,
) -> _RunArtifact:
    """Run one solver (or return a stub) and time it.

    ``stub`` is an optional injected result dict the gate uses to exercise the
    disagreement-preservation path without a real disagreement. When provided
    and ``solver`` matches the stub's ``solver``, the stub's result is returned
    instead of running the real solver — but only for the stubbed solver, so a
    real solver result is never overwritten. This is the documented mechanism
    the WP-E41 gate (E41-03) uses: it asserts the disagreement *path* exists
    via an injected stub, not a fake real disagreement.
    """
    # cvc5 is structurally supported but its license is not cleared.
    if solver == "cvc5":
        return _RunArtifact(
            result=SmtResult.UNKNOWN,
            model=None,
            wall_seconds=0.0,
            unknown_reason="cvc5_wait_license",
            available=False,
            unavailable_reason=(
                "cvc5 wheels bundle GPLv3/LGPLv3 components and ship no "
                "resolvable license expression; excluded on license grounds "
                "(WAIT_LICENSE, see ADR-0004)"
            ),
        )

    # Stub injection for the disagreement-preservation path (gate E41-03).
    if stub is not None and stub.get("solver") == solver:
        return _RunArtifact(
            result=SmtResult(stub["result"]),
            model=stub.get("model"),
            wall_seconds=0.0,
            unknown_reason=str(stub.get("unknown_reason", "injected-stub")),
        )

    start = time.perf_counter()
    result, model, unknown_reason = _run_z3(formula, timeout_ms)
    elapsed = round(time.perf_counter() - start, 6)
    return _RunArtifact(
        result=result,
        model=model,
        wall_seconds=elapsed,
        unknown_reason=unknown_reason,
    )


def _artifact_to_outcome(art: _RunArtifact, solver: SolverChoice) -> SmtOutcome:
    """Lift a single-solver artifact into an :class:`SmtOutcome`."""
    return SmtOutcome(
        result=art.result,
        solver=solver,
        model=art.model,
        wall_seconds=art.wall_seconds,
        unknown_reason=art.unknown_reason,
    )


def check(
    formula_spec: Any,
    solver: SolverChoice | str = SolverChoice.Z3,
    timeout: float | int | None = None,
    *,
    stub: dict[str, Any] | None = None,
) -> SmtOutcome:
    """Check a restricted S-expression formula spec for satisfiability.

    Builds z3 terms from ``formula_spec`` through the z3 API only (no raw
    SMT-LIB text eval), then runs the requested solver under a hard timeout
    bounded by :data:`MAX_WALL_SECONDS`. The formula-size cap
    (:data:`MAX_FORMULA_NODES`) is enforced before the solver is constructed.

    Honesty ceiling
    ---------------
    A ``sat`` / ``unsat`` answer yields at most ``formal_check=checked``. This
    adapter never mints a ``proven`` certificate; that requires an
    independently checked exact certificate (unsat core replay or a checked
    proof object), which is future work (see ADR-0004).

    Solver choice
    -------------
    - ``z3`` (default) — runs z3; the only solver with a cleared license.
    - ``cvc5`` — REJECTED as a sole solver. cvc5's license is not cleared
      (its wheels bundle GPLv3/LGPLv3 components), so it may only appear as the
      second solver in a ``both`` run, where it is recorded as unavailable.
    - ``both`` — runs z3 and (would run) cvc5. Since cvc5 is ``WAIT_LICENSE``,
      z3 runs alone and the outcome records cvc5 as unavailable. If the two
      solvers had run and disagreed, the disagreement would be preserved (see
      :attr:`SmtOutcome.disagreement`); the disagreement *path* is exercised by
      the gate via the ``stub`` parameter.

    Parameters
    ----------
    formula_spec:
        A JSON S-expression: ``[operator, *operands]`` where each operand is an
        atom or a nested S-expression. Operators are listed in
        :data:`SUPPORTED_OPERATORS`.
    solver:
        Which solver to run. Defaults to ``z3``.
    timeout:
        Wall-seconds budget, clamped to ``[0, MAX_WALL_SECONDS]``. ``None``
        means the full cap. Negative is a contract error.
    stub:
        Optional injected result dict (for the disagreement-preservation
        gate). Keys: ``solver`` (the solver name to stub), ``result``
        (``sat``/``unsat``/``unknown``), optional ``model`` and
        ``unknown_reason``. Production callers pass ``None``.

    Returns
    -------
    SmtOutcome
        The frozen outcome. For ``solver == both`` the per-solver artifacts
        are recorded on :attr:`SmtOutcome.disagreement`.

    Raises
    ------
    SmtError
        If ``formula_spec`` is malformed/oversized, ``timeout`` is negative or
        non-numeric, or ``solver == cvc5`` (cvc5 has no cleared license and
        cannot run alone).
    """
    choice = _coerce_solver(solver)
    timeout_ms = _clamp_timeout(timeout)
    _validate_spec(formula_spec)

    # cvc5 alone is unavailable: it has no cleared license and cannot run as
    # the sole solver. It may only ride along in a `both` run (recorded as
    # unavailable there). This is a hard contract failure, not a fallback.
    if choice == SolverChoice.CVC5:
        msg = (
            "solver 'cvc5' is not available as a sole solver: its wheels bundle "
            "GPLv3/LGPLv3 components and ship no resolvable license expression "
            "(excluded on license grounds, WAIT_LICENSE; see ADR-0004). Use "
            "'z3' or 'both'."
        )
        raise SmtError(msg)

    var_cache: dict[str, Any] = {}
    formula = _build_term(formula_spec, var_cache)

    if choice == SolverChoice.Z3:
        art = _run_single(formula, "z3", timeout_ms, stub=stub)
        return _artifact_to_outcome(art, SolverChoice.Z3)

    # solver == both: run z3, then cvc5 (unavailable), preserve the comparison.
    z3_art = _run_single(formula, "z3", timeout_ms, stub=stub)
    cvc5_art = _run_single(formula, "cvc5", timeout_ms, stub=stub)

    z3_outcome = _artifact_to_outcome(z3_art, SolverChoice.Z3)
    cvc5_outcome = _artifact_to_outcome(cvc5_art, SolverChoice.CVC5)

    # Agreement is only meaningful between two AVAILABLE, DECIDED solvers. A
    # missing solver (cvc5 unavailable) is NOT a disagreement — it is a gap.
    both_decided = z3_art.available and cvc5_art.available
    undecided = {z3_art.result, cvc5_art.result} & {SmtResult.UNKNOWN}
    both_known = not undecided
    agreement = both_decided and both_known and z3_art.result == cvc5_art.result

    if not agreement:
        # Preserve the disagreement (or the gap). The adapter never picks a
        # winner: the overall result is `unknown` and the per-solver outcomes
        # are recorded for inspection.
        disagreement: dict[str, Any] = {
            "z3": z3_outcome,
            "cvc5": cvc5_outcome if cvc5_art.available else None,
            "agreement": False,
            "note": ("cvc5 unavailable (WAIT_LICENSE); treated as a gap, not a disagreement"),
        }
        reason = "disagreement" if both_decided and both_known else "cvc5_wait_license"
        return SmtOutcome(
            result=SmtResult.UNKNOWN,
            solver=SolverChoice.BOTH,
            model=None,
            wall_seconds=max(z3_art.wall_seconds, cvc5_art.wall_seconds),
            disagreement=disagreement,
            unknown_reason=reason,
        )

    # Agreement: fold the shared verdict onto the outcome.
    shared_model = z3_art.model if z3_art.result == SmtResult.SAT else None
    return SmtOutcome(
        result=z3_art.result,
        solver=SolverChoice.BOTH,
        model=shared_model,
        wall_seconds=max(z3_art.wall_seconds, cvc5_art.wall_seconds),
        disagreement={
            "z3": z3_outcome,
            "cvc5": cvc5_outcome,
            "agreement": True,
        },
        unknown_reason="",
    )


def _coerce_solver(solver: SolverChoice | str) -> SolverChoice:
    """Coerce a string or enum solver choice into :class:`SolverChoice`."""
    if isinstance(solver, SolverChoice):
        return solver
    # solver is str here (the union is narrowed by the isinstance above).
    try:
        return SolverChoice(solver)
    except ValueError as exc:
        msg = (
            f"solver {solver!r} is not a known solver choice; "
            f"must be one of {sorted(s.value for s in SolverChoice)}"
        )
        raise SmtError(msg) from exc


def z3_version() -> str:
    """Return the resolved z3 version string (for gate evidence)."""
    # z3 ships no py.typed marker, so get_version_string() is typed Any here;
    # cast to str so the adapter's own typed surface stays mypy-strict clean.
    return str(z3.get_version_string())


#: The honest evidence ceiling an SMT answer can reach on the formal_check
#: axis. A ``sat``/``unsat`` verdict yields at most ``checked``; ``proven``
#: requires an independently checked certificate (future work, ADR-0004).
#: Exposed so callers and the gate can introspect the ceiling without importing
#: the evidence module.
FORMAL_CHECK_CEILING: Final[str] = "checked"


__all__ = [
    "AVAILABLE_SOLVERS",
    "FORMAL_CHECK_CEILING",
    "MAX_FORMULA_NODES",
    "MAX_WALL_SECONDS",
    "SMT_FAIL_REASON",
    "SUPPORTED_OPERATORS",
    "WAIT_LICENSE_SOLVERS",
    "SmtError",
    "SmtOutcome",
    "SmtResult",
    "SolverChoice",
    "check",
    "z3_version",
]
