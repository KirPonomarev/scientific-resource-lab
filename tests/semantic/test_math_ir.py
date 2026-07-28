"""Unit + property tests for the MathIR/v1 expression IR (srl.semantic.ir).

Pins:

1. **Restricted OpenMath allowlist**: every allowlisted ``<cd>.<name>`` op
   validates; an op outside the allowlist raises :class:`UnsupportedOperatorError`
   (fail reason ``IR_UNSUPPORTED``), and the error names the rejected op and
   its content dictionary.
2. **Two failure modes**: an unknown name in a known cd (``arith1.log``) and an
   entirely unknown cd (``foo1.plus``) both raise with a diagnostic that
   distinguishes the case.
3. **Resource guards**: an expression deeper than :data:`MAX_DEPTH` (64) raises
   :class:`IRResourceLimitError` (``limit='depth'``); an expression with more
   than :data:`MAX_NODES` (10000) nodes raises with ``limit='node_count'``.
4. **Const policy**: a constant must be a decimal-string policy value; a bool
   (``True``) is rejected (bool-as-int is not a quantity); non-finite is never
   carried (infinity is the ``nums1.infinity`` symbol).
5. **Identity**: ``ir_id`` is the sha256 over the canonical bytes of the
   expression and is key-order independent.
6. **Hypothesis**: a random tree built only from allowlisted ops always
   validates; a random ``<cd>.<name>`` op outside the allowlist always raises
   ``IR_UNSUPPORTED``.
"""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from srl.contracts.canonical import dumps
from srl.contracts.errors import ContractError
from srl.semantic.ir import (
    IR_RESOURCE_FAIL_REASON,
    IR_UNSUPPORTED_FAIL_REASON,
    MATH_IR_ALLOWLIST,
    MAX_DEPTH,
    MAX_NODES,
    Application,
    Const,
    IRResourceLimitError,
    UnsupportedOperatorError,
    Var,
    build,
    ir_id,
    validate,
    validate_expression,
)

# ---------------------------------------------------------------------------
# Strategies for the property tests.
# ---------------------------------------------------------------------------

# The accepted content dictionaries, derived from the allowlist (mirrors the
# module's own derivation so the test cannot drift).
_ACCEPTED_CDS = sorted({op.split(".", 1)[0] for op in MATH_IR_ALLOWLIST})
# A plausible-looking but NEVER-allowed name suffix. Joined with each accepted
# cd this yields "known cd, unknown name" cases; on its own it yields the
# "unknown cd" case when the cd itself is not accepted.
_BAD_NAME = "log"


def _allowlisted_ops() -> list[str]:
    return sorted(MATH_IR_ALLOWLIST)


# Recursive tree strategy using only allowlisted ops. ``max_leaves`` keeps the
# generated trees well under the node-count guard so the guard is never the
# reason a generated tree fails.
def _allowlist_tree(stops):
    return st.recursive(
        stops,
        lambda children: st.builds(
            lambda op, args: {"op": op, "args": args},
            st.sampled_from(_allowlisted_ops()),
            st.lists(children, max_size=3),
        ),
        max_leaves=8,
    )


_allowlist_trees = _allowlist_tree(
    st.one_of(
        st.from_regex(r"^-?[0-9]+(\.[0-9]+)?$", fullmatch=True).map(lambda v: {"const": v}),
        st.text(
            min_size=1,
            max_size=3,
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        ).map(lambda v: {"var": v}),
    )
)


# --- Pins: allowlist -------------------------------------------------------


@pytest.mark.parametrize("op", _allowlisted_ops())
def test_every_allowlisted_op_validates(op: str) -> None:
    """Every op in MATH_IR_ALLOWLIST validates as a nullary application."""
    validate_expression({"op": op, "args": []})


def test_allowlist_has_expected_size() -> None:
    """The allowlist carries the WP-B11 op set (39 ops across 9 cds)."""
    assert len(MATH_IR_ALLOWLIST) == 39
    assert sorted(_ACCEPTED_CDS) == [
        "arith1",
        "calculus1",
        "fns1",
        "linalg1",
        "logic1",
        "nums1",
        "relation1",
        "set1",
        "stats1",
    ]


def test_nullary_symbol_validates() -> None:
    """nums1.pi is a nullary application (not a float constant)."""
    validate_expression({"op": "nums1.pi", "args": []})
    validate_expression({"op": "nums1.infinity", "args": []})


def test_nested_application_validates() -> None:
    """F = m*a validates as relation1.eq(F, arith1.times(m, a))."""
    tree = {
        "op": "relation1.eq",
        "args": [{"var": "F"}, {"op": "arith1.times", "args": [{"var": "m"}, {"var": "a"}]}],
    }
    validate_expression(tree)


# --- Pins: unsupported operator (two failure modes) -----------------------


def test_unknown_name_in_known_cd_rejects() -> None:
    """arith1.log is a known cd but an unknown name -> IR_UNSUPPORTED."""
    with pytest.raises(UnsupportedOperatorError) as exc_info:
        validate_expression({"op": "arith1.log", "args": [{"var": "x"}]})
    assert exc_info.value.fail_reason == IR_UNSUPPORTED_FAIL_REASON
    assert exc_info.value.op == "arith1.log"
    assert exc_info.value.cd == "arith1"
    assert "arith1" in str(exc_info.value)


def test_unknown_cd_rejects() -> None:
    """foo1.plus is an unknown cd -> IR_UNSUPPORTED."""
    with pytest.raises(UnsupportedOperatorError) as exc_info:
        validate_expression({"op": "foo1.plus", "args": [{"const": "1"}, {"const": "2"}]})
    assert exc_info.value.fail_reason == IR_UNSUPPORTED_FAIL_REASON
    assert exc_info.value.op == "foo1.plus"
    assert exc_info.value.cd == "foo1"
    assert "foo1" in str(exc_info.value)


@pytest.mark.parametrize(
    "op",
    [
        "arith1.log",  # known cd, unknown name
        "foo1.plus",  # unknown cd
        "transc1.exp",  # unknown cd
        "nums1.tau",  # known cd, unknown name
    ],
)
def test_outside_allowlist_ops_reject(op: str) -> None:
    """Every op outside the allowlist raises IR_UNSUPPORTED."""
    with pytest.raises(UnsupportedOperatorError) as exc_info:
        validate_expression({"op": op, "args": []})
    assert exc_info.value.fail_reason == IR_UNSUPPORTED_FAIL_REASON
    assert exc_info.value.op == op


def test_malformed_op_string_rejects() -> None:
    """An op that is not a '<cd>.<name>' pair is rejected as unsupported."""
    with pytest.raises(UnsupportedOperatorError):
        validate_expression({"op": "not_a_pair", "args": []})


# --- Pins: const / var / node shape ---------------------------------------


@pytest.mark.parametrize("value", ["0", "3.14", "-1.5", "100", "-0.000123"])
def test_decimal_const_validates(value: str) -> None:
    """A decimal-string policy constant validates."""
    validate_expression({"const": value})


@pytest.mark.parametrize("value", ["1.5e2", "1E3", "abc", ""])
def test_bad_const_rejects(value: str) -> None:
    """A non-policy const is rejected with CONTRACT_INVALID."""
    with pytest.raises(ContractError):
        validate_expression({"const": value})


def test_bool_const_rejects() -> None:
    """A bool is not a decimal-string constant (bool-as-int is not a quantity)."""
    with pytest.raises(ContractError):
        validate_expression({"const": True})  # type: ignore[dict-item]


def test_non_string_const_rejects() -> None:
    """A numeric (non-string) const is rejected (only decimal strings are accepted)."""
    with pytest.raises(ContractError):
        validate_expression({"const": 3.14})  # type: ignore[dict-item]


def test_non_object_node_rejects() -> None:
    """A non-object node is rejected."""
    with pytest.raises(ContractError):
        validate_expression([1, 2])  # type: ignore[arg-type]


def test_multi_kind_node_rejects() -> None:
    """A node carrying two of {op, const, var} is rejected."""
    with pytest.raises(ContractError):
        validate_expression({"op": "arith1.plus", "const": "1"})


def test_empty_var_rejects() -> None:
    """An empty var symbol-id is rejected."""
    with pytest.raises(ContractError):
        validate_expression({"var": ""})


# --- Pins: resource guards -------------------------------------------------


def test_depth_bomb_rejects() -> None:
    """An expression deeper than MAX_DEPTH raises IRResourceLimitError(limit='depth')."""
    deep: object = {"const": "1"}
    for _ in range(MAX_DEPTH + 5):
        deep = {"op": "arith1.plus", "args": [deep, {"const": "1"}]}
    with pytest.raises(IRResourceLimitError) as exc_info:
        validate_expression(deep)
    assert exc_info.value.fail_reason == IR_RESOURCE_FAIL_REASON
    assert exc_info.value.limit == "depth"


def test_node_flood_rejects() -> None:
    """A breadth-heavy expression with > MAX_NODES nodes raises node_count guard."""
    # One plus application with MAX_NODES+1 const args: depth 2, count MAX_NODES+2.
    flood = {
        "op": "arith1.plus",
        "args": [{"const": "1"} for _ in range(MAX_NODES + 1)],
    }
    with pytest.raises(IRResourceLimitError) as exc_info:
        validate_expression(flood)
    assert exc_info.value.fail_reason == IR_RESOURCE_FAIL_REASON
    assert exc_info.value.limit == "node_count"


def test_just_under_depth_limit_validates() -> None:
    """An expression at exactly MAX_DEPTH depth validates."""
    deep: object = {"const": "1"}
    for _ in range(MAX_DEPTH - 1):  # root at depth 1, leaves at depth MAX_DEPTH
        deep = {"op": "arith1.plus", "args": [deep, {"const": "1"}]}
    validate_expression(deep)  # should not raise


# --- Pins: identity --------------------------------------------------------


def test_ir_id_is_sha256_of_canonical_bytes() -> None:
    """ir_id is 'sha256:' + sha256 of the canonical bytes of the expression."""
    expr = Application("arith1.plus", [Const("1"), Const("2")])
    tree = expr.to_json()
    expected = "sha256:" + hashlib.sha256(dumps(tree)).hexdigest()
    assert ir_id(expr) == expected


def test_ir_id_is_key_order_independent() -> None:
    """Two arg orderings of the same expression share an ir_id."""
    tree_a = {"op": "arith1.plus", "args": [{"const": "1"}, {"const": "2"}]}
    tree_b = {"op": "arith1.plus", "args": [{"const": "2"}, {"const": "1"}]}
    # Args are ordered (semantically a+b vs b+a); identity is over the tree as
    # given, so distinct arg orders yield distinct ids. Key-order independence
    # is about object keys, not array order:
    same = {"op": "arith1.plus", "args": [{"const": "1"}, {"var": "x"}]}
    reordered = {"args": [{"const": "1"}, {"var": "x"}], "op": "arith1.plus"}
    assert ir_id(same) == ir_id(reordered)
    # sanity: different content yields different id
    assert ir_id(tree_a) != ir_id(tree_b)


def test_ir_id_rejects_unsupported_expression() -> None:
    """ir_id validates first; an unsupported expression gets no id."""
    with pytest.raises(UnsupportedOperatorError):
        ir_id({"op": "arith1.log", "args": []})


# --- Pins: typed model + build/validate ------------------------------------


def test_build_returns_mathir_with_ir_id() -> None:
    """build validates and wraps an expression in a MathIR carrying a real ir_id."""
    expr = Application(
        "relation1.eq", [Var("F"), Application("arith1.times", [Var("m"), Var("a")])]
    )
    doc = build(expr)
    rendered = doc.to_json()
    assert rendered["schema_version"] == "MathIR/v1"
    assert rendered["ir_id"].startswith("sha256:")
    assert rendered["expression"] == expr.to_json()


def test_build_rejects_unsupported() -> None:
    """build rejects an unsupported operator at build time."""
    expr = Application("arith1.log", [Var("x")])
    with pytest.raises(UnsupportedOperatorError):
        build(expr)


def test_validate_doc_accepts_valid() -> None:
    """validate accepts a well-formed MathIR/v1 document."""
    expr = Application("arith1.plus", [Const("1"), Const("2")])
    doc = {"schema_version": "MathIR/v1", "ir_id": ir_id(expr), "expression": expr.to_json()}
    assert validate(doc) == doc


def test_validate_doc_rejects_wrong_version() -> None:
    """A wrong schema_version is rejected."""
    bad = {
        "schema_version": "MathIR/v2",
        "ir_id": "sha256:" + "0" * 64,
        "expression": {"const": "1"},
    }
    with pytest.raises(ContractError):
        validate(bad)


def test_validate_doc_rejects_unsupported_expression() -> None:
    """validate propagates an unsupported-operator error from the expression."""
    with pytest.raises(UnsupportedOperatorError):
        validate(
            {
                "schema_version": "MathIR/v1",
                "ir_id": "sha256:" + "0" * 64,
                "expression": {"op": "arith1.log", "args": []},
            }
        )


# --- Hypothesis: allowlist-only trees validate ----------------------------


@given(_allowlist_trees)
@settings(max_examples=200)
def test_random_allowlist_tree_validates(tree: object) -> None:
    """A random tree built only from allowlisted ops always validates."""
    validate_expression(tree)


@given(st.text(min_size=1, max_size=4, alphabet=st.characters(min_codepoint=97, max_codepoint=122)))
@settings(max_examples=100)
def test_random_cd_name_outside_allowlist_rejects(suffix: str) -> None:
    """A random '<cd>.<name>' op outside the allowlist always raises IR_UNSUPPORTED.

    Constructed to be outside the allowlist: we pair a deliberately unknown cd
    ('zz') with the candidate name; whatever the name, 'zz.<name>' is not
    allowlisted, so it must raise IR_UNSUPPORTED.
    """
    op = f"zz.{suffix}" if suffix else "zz.x"
    # Guard against the (effectively impossible) collision with an allowlisted op.
    if op in MATH_IR_ALLOWLIST:
        return
    with pytest.raises(UnsupportedOperatorError) as exc_info:
        validate_expression({"op": op, "args": []})
    assert exc_info.value.fail_reason == IR_UNSUPPORTED_FAIL_REASON
    assert exc_info.value.op == op


@given(_allowlist_trees)
@settings(max_examples=100)
def test_ir_id_is_deterministic(tree: object) -> None:
    """ir_id is deterministic for the same tree across calls."""
    assert ir_id(tree) == ir_id(tree)
