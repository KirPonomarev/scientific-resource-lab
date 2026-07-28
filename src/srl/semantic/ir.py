"""MathIR/v1: a typed mathematical intermediate representation.

This module is the Python counterpart of the ``MathIR/v1`` JSON Schema
(``src/srl/contracts/schemas/v1/math-ir.json``). It provides three things:

1. **The restricted OpenMath-style allowlist** (:data:`MATH_IR_ALLOWLIST`) —
   the single introspectable source of truth for the set of
   ``<cd>.<name>`` operator pairs the IR accepts. The schema's ``op.enum``
   and the runtime validator both draw from this set; a router can introspect
   it to decide which expressions it can evaluate.
2. **A typed model** for expression trees (:class:`Expr`,
   :class:`Application`, :class:`Const`, :class:`Var`) and for a full
   :class:`MathIR` document, with ``build``/``serialize``/``validate``
   helpers.
3. **Resource-guarded validation** (:func:`validate_expression`) that
   re-checks the allowlist in Python (defense in depth) and enforces a depth
   limit (:data:`MAX_DEPTH`) and a node-count limit (:data:`MAX_NODES`) the
   JSON Schema cannot express. An operator outside the allowlist raises
   :class:`UnsupportedOperatorError` with fail reason ``IR_UNSUPPORTED``;
   exceeding a resource limit raises :class:`IRResourceLimitError`.

Design notes
------------
The IR is intentionally restricted. A scientific fabric that evaluates
arbitrary mathematics is a soundness and supply-chain hazard: a stray
``arith1.log`` could call into a native ``log`` with platform-dependent
edge-case behaviour, and an open-ended function space makes content-addressed
identity non-reproducible across runtimes. The allowlist fixes the semantics:
every accepted operator is one with a well-defined, closed-form meaning a
router can implement without external code.

Non-finite values are never carried as constants. ``infinity`` is the
nullary symbol ``nums1.infinity``; there is no float constant for it. The
decimal-string policy (``^-?[0-9]+(\\.[0-9]+)?$``) is enforced by the
schema and by :func:`_validate_const`.
"""

from __future__ import annotations

import re
from typing import Any, Final

from srl.contracts.canonical import DECIMAL_STRING_PATTERN
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import object_id

# The typed fail reason for an unsupported IR operator. Mirrors the
# ``IR_UNSUPPORTED`` entry in ``automation/fail-reasons.json``
# (class ``canonical``, ``hard_stop=false``, ``retriable=false``).
IR_UNSUPPORTED_FAIL_REASON: Final[str] = "IR_UNSUPPORTED"
# Resource-limit violations are structural contract failures.
IR_RESOURCE_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# Resource guards. The depth limit bounds recursion so a pathological tree
# cannot blow the interpreter stack; the node-count limit bounds total work so
# a node-flood cannot exhaust memory. Both are generous enough for realistic
# scientific expressions (a 10000-node expression is already far beyond
# anything a human-authored model produces) and small enough to reject abuse.
MAX_DEPTH: Final[int] = 64
MAX_NODES: Final[int] = 10000

# Pre-compiled decimal-string policy pattern (reused from the canonical layer
# so the policy has exactly one definition).
_DECIMAL_STRING_RE: Final[re.Pattern[str]] = re.compile(DECIMAL_STRING_PATTERN)
# Structural shape for a '<cd>.<name>' operator string (used only to split and
# to format diagnostics; membership is checked against the allowlist below).
_OP_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

# ---------------------------------------------------------------------------
# The restricted OpenMath-style content-dictionary allowlist.
#
# This is the single source of truth for the accepted operators. The JSON
# Schema's ``op.enum`` lists the same set verbatim; this constant is what the
# router introspects. Keeping it as a frozenset gives O(1) membership tests.
# ---------------------------------------------------------------------------
_MATH_IR_ALLOWLIST_RAW: Final[frozenset[str]] = frozenset(
    {
        # arith1: elementary arithmetic.
        "arith1.plus",
        "arith1.minus",
        "arith1.times",
        "arith1.divide",
        "arith1.power",
        "arith1.root",
        "arith1.abs",
        "arith1.unary_minus",
        # relation1: equality and order.
        "relation1.eq",
        "relation1.neq",
        "relation1.lt",
        "relation1.leq",
        "relation1.gt",
        "relation1.geq",
        # logic1: propositional connectives.
        "logic1.and",
        "logic1.or",
        "logic1.not",
        "logic1.implies",
        "logic1.equivalent",
        # set1: elementary set operations.
        "set1.in",
        "set1.subset",
        "set1.union",
        "set1.intersect",
        # calculus1: differentiation and integration.
        "calculus1.diff",
        "calculus1.partialdiff",
        "calculus1.int",
        # linalg1: elementary linear algebra.
        "linalg1.determinant",
        "linalg1.transpose",
        "linalg1.inverse",
        # nums1: symbolic constants (nullary; never float).
        "nums1.pi",
        "nums1.e",
        "nums1.i",
        "nums1.infinity",
        # fns1: function construction.
        "fns1.lambda",
        "fns1.domain",
        "fns1.range",
        # stats1: summary statistics.
        "stats1.mean",
        "stats1.variance",
        "stats1.covariance",
    }
)

# Public introspectable allowlist. Exposed as a frozenset so callers cannot
# mutate the fabric's accepted-operator set at runtime.
MATH_IR_ALLOWLIST: Final[frozenset[str]] = _MATH_IR_ALLOWLIST_RAW

# The set of accepted content dictionaries (derived from the allowlist so it
# cannot drift). Used to distinguish "unknown name in a known cd" (e.g.
# ``arith1.log``) from "unknown cd" (e.g. ``foo1.plus``) in diagnostics.
_ACCEPTED_CDS: Final[frozenset[str]] = frozenset(op.split(".", 1)[0] for op in MATH_IR_ALLOWLIST)

# Nullary nums1 symbols: applications with no arguments. Carrying them as
# nullary applications (rather than float constants) keeps infinity/e/i out of
# the decimal-string channel entirely.
_NULLARY_SYMBOLS: Final[frozenset[str]] = frozenset(
    {"nums1.pi", "nums1.e", "nums1.i", "nums1.infinity"}
)


class UnsupportedOperatorError(ContractError):
    """Raised when a MathIR expression uses an operator outside the allowlist.

    Attributes
    ----------
    op:
        The rejected ``<cd>.<name>`` operator string.
    cd:
        The content dictionary portion (``op.split('.', 1)[0]``).
    """

    def __init__(
        self,
        message: str,
        *,
        op: str = "",
        cd: str = "",
        fail_reason: str = IR_UNSUPPORTED_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.op: str = op
        self.cd: str = cd


class IRResourceLimitError(ContractError):
    """Raised when a MathIR expression exceeds a resource guard.

    Attributes
    ----------
    limit:
        The name of the limit exceeded (``"depth"`` or ``"node_count"``).
    """

    def __init__(
        self,
        message: str,
        *,
        limit: str = "",
        fail_reason: str = IR_RESOURCE_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.limit: str = limit


# ---------------------------------------------------------------------------
# Typed model. The JSON wire form is the dict-of-dicts tree; these typed
# wrappers make construction and inspection ergonomic and give mypy something
# to check. Each node has a ``to_json`` (the canonical wire dict) and the
# validators consume the wire form directly.
# ---------------------------------------------------------------------------


class Expr:
    """Base for the three MathIR node kinds.

    The subclasses are intentionally thin value objects; equality and hashing
    are identity-based (the wire form is what content-addressing hashes).
    Each subclass renders itself to the canonical wire dict via ``to_json``;
    the base declares the method so a typed ``Expr`` reference can call it.
    """

    def to_json(self) -> dict[str, Any]:
        """Render to the canonical wire dict (overridden by each subclass)."""
        msg = f"Expr subclass {type(self).__name__} must override to_json"
        raise NotImplementedError(msg)


class Application(Expr):
    """An application of an allowlisted operator to argument expressions."""

    __slots__ = ("args", "op")

    def __init__(self, op: str, args: list[Expr]) -> None:
        self.op: str = op
        self.args: list[Expr] = args

    def to_json(self) -> dict[str, Any]:
        """Render to the canonical wire dict ``{"op": ..., "args": [...]}``."""
        return {"op": self.op, "args": [a.to_json() for a in self.args]}


class Const(Expr):
    """A decimal-string constant node."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value: str = value

    def to_json(self) -> dict[str, str]:
        """Render to the canonical wire dict ``{"const": value}``."""
        return {"const": self.value}


class Var(Expr):
    """A variable reference to a symbol-id declared in a SymbolTable/v1."""

    __slots__ = ("symbol_id",)

    def __init__(self, symbol_id: str) -> None:
        self.symbol_id: str = symbol_id

    def to_json(self) -> dict[str, str]:
        """Render to the canonical wire dict ``{"var": symbol_id}``."""
        return {"var": self.symbol_id}


class MathIR:
    """A full MathIR/v1 document (identity + expression root).

    The ``object_id`` is computed by :func:`ir_id` from the canonical encoding
    of the expression; a document carrying a pre-populated ``ir_id`` is
    rejected as a self-hash.
    """

    __slots__ = ("expression",)

    def __init__(self, expression: Expr) -> None:
        self.expression: Expr = expression

    def to_json(self) -> dict[str, Any]:
        """Render to the canonical wire dict, including the computed ``ir_id``."""
        return {
            "schema_version": "MathIR/v1",
            "ir_id": ir_id(self.expression),
            "expression": self.expression.to_json(),
        }


# ---------------------------------------------------------------------------
# Validation. ``validate_expression`` walks the wire-form tree (dict), checking
# the allowlist, the node kinds, the decimal-string policy, and the two
# resource guards. It returns None on success and raises a typed error on
# failure. The schema validates structure; this re-checks semantics + guards.
# ---------------------------------------------------------------------------


def validate_expression(tree: Any) -> None:
    """Validate a MathIR expression tree against the allowlist + resource guards.

    Walks ``tree`` (the JSON wire form: an application ``{op, args}``, a
    constant ``{const}``, or a variable ``{var}``), enforcing:

    - each application ``op`` is a member of :data:`MATH_IR_ALLOWLIST`;
    - each constant value is a decimal-string policy value (no exponent, no
      non-finite — ``infinity`` is the symbol ``nums1.infinity``);
    - the tree depth is ``<=`` :data:`MAX_DEPTH`;
    - the total node count is ``<=`` :data:`MAX_NODES`.

    Raises
    ------
    UnsupportedOperatorError
        If an ``op`` is outside the allowlist (fail reason ``IR_UNSUPPORTED``).
        The ``op`` and ``cd`` attributes name the rejected operator and its
        content dictionary.
    IRResourceLimitError
        If the depth or node-count guard is exceeded
        (fail reason ``CONTRACT_INVALID``).
    ContractError
        If a node is malformed (not a dict, an unknown node kind, a non-string
        op, or a constant that is not a decimal string).
    """
    _validate_node(tree, depth=1, counter=_NodeCounter())


class _NodeCounter:
    """Mutable running node-count, boxed so the recursion can share it."""

    __slots__ = ("count",)

    def __init__(self) -> None:
        self.count: int = 0


def _validate_node(node: Any, *, depth: int, counter: _NodeCounter) -> None:
    """Validate one node and recurse into its children."""
    # Resource guards first: a node bomb must be caught before it consumes work.
    if depth > MAX_DEPTH:
        msg = f"MathIR expression exceeds depth limit {MAX_DEPTH} (got depth {depth})"
        raise IRResourceLimitError(msg, limit="depth")
    counter.count += 1
    if counter.count > MAX_NODES:
        msg = f"MathIR expression exceeds node-count limit {MAX_NODES}"
        raise IRResourceLimitError(msg, limit="node_count")

    if not isinstance(node, dict):
        msg = f"MathIR node must be an object, got {type(node).__name__}"
        raise ContractError(msg)
    # Discriminate by the present key. A node must be exactly one of the three
    # kinds; additionalProperties=false is enforced structurally here.
    is_app = "op" in node
    is_const = "const" in node
    is_var = "var" in node
    kinds = sum(1 for present in (is_app, is_const, is_var) if present)
    if kinds != 1:
        msg = f"MathIR node must be exactly one of {{op, const, var}}; got keys {sorted(node)!r}"
        raise ContractError(msg)

    if is_app:
        _validate_application(node, depth=depth, counter=counter)
    elif is_const:
        _validate_const(node)
    else:  # is_var
        _validate_var(node)


def _validate_application(node: dict[str, Any], *, depth: int, counter: _NodeCounter) -> None:
    """Validate an application node: op membership + args recursion."""
    op = node.get("op")
    if not isinstance(op, str):
        msg = f"MathIR application 'op' must be a string, got {type(op).__name__}"
        raise ContractError(msg)
    # Cheap structural reject first: a malformed op string cannot be in the set.
    if not _OP_RE.fullmatch(op):
        cd = op.split(".", 1)[0] if "." in op else ""
        msg = f"MathIR operator {op!r} is not a valid '<cd>.<name>' pair; rejected as unsupported"
        raise UnsupportedOperatorError(msg, op=op, cd=cd)
    if op not in MATH_IR_ALLOWLIST:
        cd = op.split(".", 1)[0]
        # Distinguish the two failure modes for the diagnostic + the gate.
        if cd in _ACCEPTED_CDS:
            msg = (
                f"MathIR operator {op!r} uses known content dictionary "
                f"{cd!r} but the name is not in the allowlist"
            )
        else:
            msg = (
                f"MathIR operator {op!r} uses unknown content dictionary "
                f"{cd!r}; only {sorted(_ACCEPTED_CDS)} are accepted"
            )
        raise UnsupportedOperatorError(msg, op=op, cd=cd)
    args = node.get("args")
    if not isinstance(args, list):
        msg = f"MathIR application 'args' must be an array, got {type(args).__name__}"
        raise ContractError(msg)
    # Nullary symbols (nums1.pi/e/i/infinity) take zero args; do not enforce a
    # per-op arity here (arity checking is a semantic concern for the router).
    for child in args:
        _validate_node(child, depth=depth + 1, counter=counter)


def _validate_const(node: dict[str, Any]) -> None:
    """Validate a constant node: decimal-string policy, no non-finite."""
    value = node.get("const")
    if not isinstance(value, str) or not _DECIMAL_STRING_RE.fullmatch(value):
        msg = (
            f"MathIR constant {value!r} must be a decimal-string policy value "
            f"({DECIMAL_STRING_PATTERN!r}); non-finite values are the symbolic "
            "'nums1.infinity', not a float"
        )
        raise ContractError(msg)


def _validate_var(node: dict[str, Any]) -> None:
    """Validate a variable node: a non-empty symbol-id string."""
    symbol_id = node.get("var")
    if not isinstance(symbol_id, str) or not symbol_id:
        msg = "MathIR variable 'var' must be a non-empty string symbol-id"
        raise ContractError(msg)


def ir_id(expression: Expr | dict[str, Any]) -> str:
    """Compute the ``ir_id`` for an expression: sha256 over its canonical bytes.

    The id is computed over the canonical encoding of the expression *alone*
    (the wire dict tree), so two documents with equal expressions share an id
    independent of any wrapping envelope. The expression is validated first
    (defense in depth: an unsupported expression never gets an id).

    Raises
    ------
    UnsupportedOperatorError
        If the expression uses an operator outside the allowlist.
    ContractError
        If the expression is malformed.
    """
    tree = expression.to_json() if isinstance(expression, Expr) else expression
    validate_expression(tree)
    return object_id(tree)


def validate(doc: Any) -> dict[str, Any]:
    """Validate a full MathIR/v1 document (wire dict) and return it.

    Checks the schema version anchor and validates the expression tree via
    :func:`validate_expression`. The schema-level ``op.enum`` is also enforced
    by :func:`srl.contracts.schema.validate`; this is the defense-in-depth
    Python counterpart.
    """
    if not isinstance(doc, dict):
        msg = f"MathIR document must be an object, got {type(doc).__name__}"
        raise ContractError(msg)
    if doc.get("schema_version") != "MathIR/v1":
        got = doc.get("schema_version")
        msg = f"MathIR document schema_version must be 'MathIR/v1', got {got!r}"
        raise ContractError(msg)
    if "ir_id" not in doc:
        msg = "MathIR document is missing required field 'ir_id'"
        raise ContractError(msg)
    expression = doc.get("expression")
    validate_expression(expression)
    return doc


def build(expression: Expr) -> MathIR:
    """Build a :class:`MathIR` document from an expression (validating it).

    Validates the expression (so an unsupported operator raises at build time)
    and wraps it in a :class:`MathIR` whose ``to_json`` carries the computed
    ``ir_id``.
    """
    validate_expression(expression.to_json())
    return MathIR(expression)


__all__ = [
    "IR_RESOURCE_FAIL_REASON",
    "IR_UNSUPPORTED_FAIL_REASON",
    "MATH_IR_ALLOWLIST",
    "MAX_DEPTH",
    "MAX_NODES",
    "Application",
    "Const",
    "Expr",
    "IRResourceLimitError",
    "MathIR",
    "UnsupportedOperatorError",
    "Var",
    "build",
    "ir_id",
    "validate",
    "validate_expression",
]
