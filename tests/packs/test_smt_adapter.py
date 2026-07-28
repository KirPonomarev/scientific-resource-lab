"""Tests for :mod:`srl.packs.adapters.smt` (WP-E41 SMT satisfiability adapter).

All tests are hermetic: they exercise the SMT adapter on tiny in-memory
formulas, never touching the network. Z3 is imported only inside the adapter;
an architecture test asserts no other module in the SRL tree imports it (the
isolation boundary documented in ADR-0004).

Honesty invariant
-----------------
These tests assert the load-bearing honesty property of the adapter: a
``sat`` / ``unsat`` answer never becomes ``proven`` without a verified
certificate (the ``FORMAL_CHECK_CEILING`` is ``checked``). They also assert
that a solver disagreement (or the cvc5 license gap) is preserved and never
silently resolved.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.packs.adapters.smt import (
    AVAILABLE_SOLVERS,
    FORMAL_CHECK_CEILING,
    MAX_FORMULA_NODES,
    MAX_WALL_SECONDS,
    SMT_FAIL_REASON,
    SUPPORTED_OPERATORS,
    WAIT_LICENSE_SOLVERS,
    SmtError,
    SmtResult,
    SolverChoice,
    check,
    z3_version,
)

# The repository root, for the architecture scan over the source tree.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "srl"
_ADAPTER_MODULE = _SRC_ROOT / "packs" / "adapters" / "smt.py"

# A tiny SAT formula reused across tests: x > 0 over the integers.
_SAT_FORMULA = [">", ["int-var", "x"], ["int-const", 0]]
# A tiny UNSAT formula: (x > 0) and (x < 0).
_UNSAT_FORMULA = [
    "and",
    [">", ["int-var", "x"], ["int-const", 0]],
    ["<", ["int-var", "x"], ["int-const", 0]],
]


# ---------------------------------------------------------------------------
# check: SAT / UNSAT / UNKNOWN under z3.
# ---------------------------------------------------------------------------


class TestCheckResults:
    """``check`` returns the correct satisfiability verdict."""

    def test_sat_returns_sat_with_witness(self) -> None:
        """A satisfiable formula returns ``sat`` with a witness model."""
        outcome = check(_SAT_FORMULA, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.SAT
        assert outcome.solver == SolverChoice.Z3
        assert outcome.model is not None
        assert "x" in outcome.model
        # The witness must satisfy x > 0.
        assert int(outcome.model["x"]) > 0

    def test_unsat_returns_unsat_with_no_model(self) -> None:
        """An unsatisfiable formula returns ``unsat`` with a null model."""
        outcome = check(_UNSAT_FORMULA, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.UNSAT
        assert outcome.model is None

    def test_unknown_on_timeout(self) -> None:
        """A genuinely hard formula times out to ``unknown`` with reason 'timeout'."""
        # Integer factorization: six ints > 1 multiply to a prime (unsat, but
        # expensive to prove). z3 cannot decide it in 1 s.
        formula = [
            "and",
            [">", ["int-var", "a0"], ["int-const", 1]],
            [">", ["int-var", "a1"], ["int-const", 1]],
            [">", ["int-var", "a2"], ["int-const", 1]],
            [">", ["int-var", "a3"], ["int-const", 1]],
            [">", ["int-var", "a4"], ["int-const", 1]],
            [">", ["int-var", "a5"], ["int-const", 1]],
            [
                "=",
                [
                    "*",
                    [
                        "*",
                        ["*", ["int-var", "a0"], ["int-var", "a1"]],
                        ["*", ["int-var", "a2"], ["int-var", "a3"]],
                    ],
                    ["*", ["int-var", "a4"], ["int-var", "a5"]],
                ],
                ["int-const", 1000003],
            ],
        ]
        outcome = check(formula, solver=SolverChoice.Z3, timeout=1)
        assert outcome.result == SmtResult.UNKNOWN
        assert "timeout" in outcome.unknown_reason

    def test_outcome_is_frozen(self) -> None:
        """The ``SmtOutcome`` is immutable (frozen dataclass)."""
        outcome = check(_SAT_FORMULA, solver=SolverChoice.Z3, timeout=5)
        with pytest.raises((AttributeError, Exception)):
            outcome.result = SmtResult.UNSAT  # type: ignore[misc]

    def test_wall_seconds_non_negative(self) -> None:
        """The wall-clock cost is a non-negative number."""
        outcome = check(_SAT_FORMULA, solver=SolverChoice.Z3, timeout=5)
        assert isinstance(outcome.wall_seconds, float)
        assert outcome.wall_seconds >= 0.0


# ---------------------------------------------------------------------------
# check: real arithmetic and operator coverage.
# ---------------------------------------------------------------------------


class TestRealArithmeticAndOperators:
    """``check`` over the real-arithmetic and multi-operand operators."""

    def test_real_arithmetic_sat(self) -> None:
        """A real-arithmetic system y = 2x and y > 1 is satisfiable."""
        formula = [
            "and",
            ["=", ["real-var", "y"], ["*", ["int-const", 2], ["real-var", "x"]]],
            [">", ["real-var", "y"], ["int-const", 1]],
        ]
        outcome = check(formula, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.SAT
        assert outcome.model is not None

    def test_distinct_operator(self) -> None:
        """``distinct`` over three variables forces them pairwise different."""
        formula = ["distinct", ["int-var", "p"], ["int-var", "q"], ["int-var", "r"]]
        outcome = check(formula, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.SAT
        model = outcome.model
        assert model is not None
        vals = {model["p"], model["q"], model["r"]}
        assert len(vals) == 3

    def test_chained_inequality(self) -> None:
        """A chained strict inequality a < b < c is satisfiable."""
        formula = ["<", ["int-var", "a"], ["int-var", "b"], ["int-var", "c"]]
        outcome = check(formula, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.SAT
        model = outcome.model
        assert model is not None
        assert int(model["a"]) < int(model["b"]) < int(model["c"])

    def test_implies_and_or(self) -> None:
        """``implies`` / ``or`` / ``not`` compose over boolean comparisons.

        Boolean connectives take boolean operands: the grammar produces those
        via comparison operators (``<``, ``=``, ...), not bare typed
        variables. ``(x > 0) implies (x > 5)`` is satisfiable (e.g. x = 10);
        conjoined with ``not (x > 5)`` and ``x > 0`` it becomes unsat.
        """
        # SAT: (x > 0) implies (x > 5), with x = 6 satisfying both.
        sat_formula = [
            "implies",
            [">", ["int-var", "x"], ["int-const", 0]],
            [">", ["int-var", "x"], ["int-const", 5]],
        ]
        outcome = check(sat_formula, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.SAT
        # UNSAT: (x > 0) implies (x > 5), and (x > 0), and not (x > 5).
        unsat_formula = [
            "and",
            [
                "implies",
                [">", ["int-var", "x"], ["int-const", 0]],
                [">", ["int-var", "x"], ["int-const", 5]],
            ],
            [">", ["int-var", "x"], ["int-const", 0]],
            ["not", [">", ["int-var", "x"], ["int-const", 5]]],
        ]
        outcome = check(unsat_formula, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.UNSAT


# ---------------------------------------------------------------------------
# check: formula_spec validation (no raw SMT-LIB eval).
# ---------------------------------------------------------------------------


class TestFormulaSpecValidation:
    """``check`` validates the S-expression shape, operators, and size cap."""

    @pytest.mark.parametrize(
        "bad_spec",
        [
            "not-a-list",
            [],
            ["nonexistent-op", ["int-var", "x"]],
            42,
            None,
        ],
    )
    def test_malformed_spec_rejected(self, bad_spec: object) -> None:
        """A malformed root S-expression raises ``SmtError`` before compute."""
        with pytest.raises(SmtError) as exc_info:
            check(bad_spec, solver=SolverChoice.Z3, timeout=5)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_oversized_formula_rejected(self) -> None:
        """A formula exceeding ``MAX_FORMULA_NODES`` is rejected before compute."""
        big = ["and", *([_SAT_FORMULA] * (MAX_FORMULA_NODES + 1))]
        with pytest.raises(SmtError) as exc_info:
            check(big, solver=SolverChoice.Z3, timeout=5)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_bad_arity_rejected(self) -> None:
        """An operator with the wrong operand count is rejected."""
        with pytest.raises(SmtError):
            check(["not", ["int-var", "x"], ["int-var", "y"]], solver=SolverChoice.Z3, timeout=5)
        with pytest.raises(SmtError):
            check(["and", ["int-var", "x"]], solver=SolverChoice.Z3, timeout=5)

    def test_bool_int_const_rejected(self) -> None:
        """A JSON boolean is not a valid integer constant operand."""
        with pytest.raises(SmtError):
            check([">", ["int-var", "x"], ["int-const", True]], solver=SolverChoice.Z3, timeout=5)

    def test_empty_var_name_rejected(self) -> None:
        """An empty variable name is rejected."""
        with pytest.raises(SmtError):
            check([">", ["int-var", ""], ["int-const", 0]], solver=SolverChoice.Z3, timeout=5)

    def test_timeout_negative_rejected(self) -> None:
        """A negative timeout is a contract error."""
        with pytest.raises(SmtError):
            check(_SAT_FORMULA, solver=SolverChoice.Z3, timeout=-1)

    def test_timeout_non_numeric_rejected(self) -> None:
        """A non-numeric timeout is a contract error."""
        with pytest.raises(SmtError):
            check(_SAT_FORMULA, solver=SolverChoice.Z3, timeout="5")  # type: ignore[arg-type]

    def test_timeout_clamped_to_cap(self) -> None:
        """A timeout above ``MAX_WALL_SECONDS`` is clamped (not rejected)."""
        # A huge timeout must not raise; it is clamped to the cap.
        outcome = check(_SAT_FORMULA, solver=SolverChoice.Z3, timeout=10_000_000)
        assert outcome.result == SmtResult.SAT


# ---------------------------------------------------------------------------
# check: variable memoisation (same name => same z3 const).
# ---------------------------------------------------------------------------


class TestVariableMemoisation:
    """The term builder memoises variable declarations by name."""

    def test_repeated_var_name_unifies(self) -> None:
        """Two ``int-var "x"`` operands refer to the same variable."""
        # x > x is unsatisfiable over the reals (strict), proving the two
        # ``int-var "x"`` operands are the same z3 constant.
        formula = [">", ["real-var", "x"], ["real-var", "x"]]
        outcome = check(formula, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.UNSAT

    def test_distinct_names_do_not_unify(self) -> None:
        """Two differently-named variables are distinct."""
        formula = [">", ["real-var", "x"], ["real-var", "y"]]
        outcome = check(formula, solver=SolverChoice.Z3, timeout=5)
        assert outcome.result == SmtResult.SAT


# ---------------------------------------------------------------------------
# check: solver choice and cvc5 license handling.
# ---------------------------------------------------------------------------


class TestSolverChoice:
    """``check`` honours the solver choice and the cvc5 license gate."""

    def test_string_solver_coerced(self) -> None:
        """A string solver choice is coerced to the enum."""
        outcome = check(_SAT_FORMULA, solver="z3", timeout=5)
        assert outcome.result == SmtResult.SAT

    def test_unknown_solver_rejected(self) -> None:
        """An unknown solver string is rejected."""
        with pytest.raises(SmtError):
            check(_SAT_FORMULA, solver="mathematica", timeout=5)  # type: ignore[arg-type]

    def test_cvc5_alone_rejected(self) -> None:
        """cvc5 as a sole solver is rejected (no cleared license)."""
        with pytest.raises(SmtError) as exc_info:
            check(_SAT_FORMULA, solver=SolverChoice.CVC5, timeout=5)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_both_records_cvc5_unavailable(self) -> None:
        """A ``both`` run records cvc5 as unavailable (WAIT_LICENSE)."""
        outcome = check(_SAT_FORMULA, solver=SolverChoice.BOTH, timeout=5)
        assert outcome.solver == SolverChoice.BOTH
        # cvc5 is unavailable => the outcome is a gap (unknown), not a
        # disagreement, and never silently resolved.
        assert outcome.result == SmtResult.UNKNOWN
        assert outcome.unknown_reason == "cvc5_wait_license"
        assert outcome.disagreement is not None
        assert outcome.disagreement["agreement"] is False
        assert "gap" in outcome.disagreement["note"]


# ---------------------------------------------------------------------------
# check: disagreement preservation (the core honesty property).
# ---------------------------------------------------------------------------


class TestDisagreementPreservation:
    """A disagreement (or the cvc5 gap) is preserved, never silently resolved."""

    def test_both_on_sat_records_gap(self) -> None:
        """A ``both`` run on a SAT formula records the cvc5 gap with sub-outcomes."""
        outcome = check(_SAT_FORMULA, solver=SolverChoice.BOTH, timeout=5)
        assert outcome.disagreement is not None
        # Both sub-outcomes present; cvc5 marked unavailable.
        assert "z3" in outcome.disagreement
        assert outcome.disagreement["cvc5"] is None  # unavailable -> null
        assert outcome.disagreement["agreement"] is False

    def test_stub_injection_forces_disagreement_path(self) -> None:
        """An injected z3 stub forces the disagreement-preservation path.

        The stub makes z3 report ``unsat`` on a SAT formula; the real cvc5 is
        unavailable. The adapter must preserve ``agreement=False`` and
        ``result=unknown`` with the stubbed sub-outcome recorded — never
        silently resolving.
        """
        stub = {"solver": "z3", "result": "unsat", "unknown_reason": "injected-stub"}
        outcome = check(_SAT_FORMULA, solver=SolverChoice.BOTH, timeout=5, stub=stub)
        assert outcome.result == SmtResult.UNKNOWN
        assert outcome.disagreement is not None
        assert outcome.disagreement["agreement"] is False
        z3_sub = outcome.disagreement["z3"]
        assert str(z3_sub.result) == "unsat"
        assert "injected-stub" in z3_sub.unknown_reason

    def test_stub_does_not_override_real_solver(self) -> None:
        """A stub for an absent solver does not override a real z3 result."""
        # Stub cvc5 (which never runs anyway); z3 must still run for real.
        stub = {"solver": "cvc5", "result": "sat", "unknown_reason": "noop"}
        outcome = check(_SAT_FORMULA, solver=SolverChoice.Z3, timeout=5, stub=stub)
        assert outcome.result == SmtResult.SAT  # z3's real result

    def test_both_outcome_serializes_to_json(self) -> None:
        """A ``both`` outcome round-trips as JSON (nested outcomes serialized)."""
        outcome = check(_SAT_FORMULA, solver=SolverChoice.BOTH, timeout=5)
        blob = json.dumps(outcome.to_dict())
        parsed = json.loads(blob)
        assert parsed["solver"] == "both"
        assert parsed["disagreement"]["z3"]["solver"] == "z3"


# ---------------------------------------------------------------------------
# Honesty ceiling: no PROVEN.
# ---------------------------------------------------------------------------


class TestHonestyCeiling:
    """A SMT answer never reaches ``proven`` without a verified certificate."""

    def test_formal_check_ceiling_is_checked(self) -> None:
        """The exported evidence ceiling is ``checked``, not ``proven``."""
        assert FORMAL_CHECK_CEILING == "checked"

    def test_no_proven_marker_in_any_output(self) -> None:
        """No serialized adapter output carries the ``proven`` token."""
        for formula in (_SAT_FORMULA, _UNSAT_FORMULA):
            for solver in (SolverChoice.Z3, SolverChoice.BOTH):
                outcome = check(formula, solver=solver, timeout=5)
                blob = json.dumps(outcome.to_dict())
                assert "proven" not in blob, f"proven leaked into output: {blob}"

    def test_smt_fail_reason_is_contract_invalid(self) -> None:
        """The adapter fail reason is ``CONTRACT_INVALID``."""
        assert SMT_FAIL_REASON == CONTRACT_INVALID_FAIL_REASON


# ---------------------------------------------------------------------------
# Corpus fixture coverage: the committed conformance vectors.
# ---------------------------------------------------------------------------


_CORPUS_DIR = _REPO_ROOT / "fixtures" / "conformance" / "smt"


def _corpus_cases(category: str) -> list[tuple[str, object, str, float]]:
    """Load corpus cases as (case_id, formula_spec, expected_result, timeout)."""
    out: list[tuple[str, object, str, float]] = []
    sub = _CORPUS_DIR / category
    if not sub.is_dir():
        return out
    for path in sorted(sub.glob("*.input.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        out.append(
            (
                doc["case_id"],
                doc["formula_spec"],
                doc["expected_result"],
                doc.get("timeout_seconds", 5),
            )
        )
    return out


_SAT_CASES = _corpus_cases("sat")
_UNSAT_CASES = _corpus_cases("unsat")
_UNKNOWN_CASES = _corpus_cases("unknown")


@pytest.mark.parametrize(
    ("case_id", "formula", "_expected", "_timeout"),
    _SAT_CASES + _UNSAT_CASES,
    ids=[c[0] for c in _SAT_CASES + _UNSAT_CASES],
)
def test_corpus_sat_unsat_golden(
    case_id: str, formula: object, _expected: str, _timeout: float
) -> None:
    """Each committed SAT/UNSAT corpus case matches its golden result."""
    outcome = check(formula, solver=SolverChoice.Z3, timeout=_timeout)
    assert str(outcome.result) == _expected, (
        f"{case_id}: expected {_expected}, got {outcome.result}"
    )


@pytest.mark.parametrize(
    ("case_id", "formula", "_expected", "_timeout"),
    _UNKNOWN_CASES,
    ids=[c[0] for c in _UNKNOWN_CASES],
)
def test_corpus_unknown_golden(
    case_id: str, formula: object, _expected: str, _timeout: float
) -> None:
    """Each committed UNKNOWN corpus case times out to ``unknown``."""
    outcome = check(formula, solver=SolverChoice.Z3, timeout=_timeout)
    assert outcome.result == SmtResult.UNKNOWN, f"{case_id}: expected unknown, got {outcome.result}"
    assert "timeout" in outcome.unknown_reason


def test_corpus_has_expected_counts() -> None:
    """The committed corpus has the required case counts (3/3/2)."""
    assert len(_SAT_CASES) == 3
    assert len(_UNSAT_CASES) == 3
    assert len(_UNKNOWN_CASES) == 2


def test_oversized_corpus_generator_rejects() -> None:
    """The oversized fixture generator materializes a formula above the cap."""
    path = _CORPUS_DIR / "oversized" / "o01-exceeds-size-cap.input.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    gen = doc["formula_spec_generator"]
    big = [gen["operator"], *([gen["operand"]] * gen["repeat"])]
    with pytest.raises(SmtError) as exc_info:
        check(big, solver=SolverChoice.Z3, timeout=5)
    assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


# ---------------------------------------------------------------------------
# Architecture test: z3 is imported only inside the SMT adapter.
# ---------------------------------------------------------------------------


def _imports_z3(path: Path) -> bool:
    """Return True iff ``path`` imports the ``z3`` package at module level."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "z3":
                    return True
        if isinstance(node, ast.ImportFrom) and node.module == "z3":
            return True
    return False


class TestZ3Isolation:
    """ADR-0004: z3 is imported only inside ``srl.packs.adapters.smt``."""

    def test_only_smt_adapter_imports_z3(self) -> None:
        """No module under ``src/srl`` other than the adapter imports ``z3``."""
        offenders: list[str] = []
        for path in _SRC_ROOT.rglob("*.py"):
            if path == _ADAPTER_MODULE:
                continue
            if _imports_z3(path):
                offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert not offenders, f"z3 imported outside the adapter: {offenders}"

    def test_adapter_module_imports_z3(self) -> None:
        """The adapter module itself imports z3 (sanity check)."""
        assert _imports_z3(_ADAPTER_MODULE)


# ---------------------------------------------------------------------------
# Module-level constants and metadata.
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """The exported constants describe the supported surface."""

    def test_supported_operators_is_auditable_set(self) -> None:
        """The operator grammar is a non-empty frozenset of reviewed operators."""
        assert isinstance(SUPPORTED_OPERATORS, frozenset)
        assert len(SUPPORTED_OPERATORS) >= 16
        for op in ("and", "or", "not", "=", "<", "+", "*", "int-var", "real-const"):
            assert op in SUPPORTED_OPERATORS

    def test_available_solvers_is_z3(self) -> None:
        """The only available solver is z3 (cvc5 is license-blocked)."""
        assert AVAILABLE_SOLVERS == frozenset({"z3"})

    def test_wait_license_solvers_is_cvc5(self) -> None:
        """cvc5 is held back on license grounds."""
        assert WAIT_LICENSE_SOLVERS == frozenset({"cvc5"})

    def test_max_wall_seconds_bounded_by_policy(self) -> None:
        """The wall cap is bounded by the M1 policy exception envelope (900 s)."""
        assert isinstance(MAX_WALL_SECONDS, int)
        assert MAX_WALL_SECONDS == 900

    def test_max_formula_nodes_positive(self) -> None:
        """The formula-size cap is a positive integer."""
        assert isinstance(MAX_FORMULA_NODES, int)
        assert MAX_FORMULA_NODES > 0

    def test_z3_version_is_a_string(self) -> None:
        """The resolved z3 version is reported as a non-empty string."""
        version = z3_version()
        assert isinstance(version, str)
        assert version != ""
