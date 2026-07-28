"""Tests for :mod:`srl.packs.adapters.cvxpy_adapter` (WP-H71b).

All tests are hermetic: they exercise the CVXPY adapter on in-memory problem
specs and the in-repo conformance fixtures, never touching the network.
``cvxpy`` is imported only inside the adapter; an architecture test asserts no
other module in the SRL tree imports it.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

import srl.packs.adapters.cvxpy_adapter as _adapter
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.packs.adapters.cvxpy_adapter import (
    MAX_VARIABLES,
    SOLVE_RESULT_SCHEMA_VERSION,
    CvxpyLicenseError,
    CvxpyResourceError,
    CvxpySpecError,
    Solver,
    SolveResult,
    SolveStatus,
    clarabel_version,
    cvxpy_version,
    is_solver_allowed,
    osqp_version,
    solve,
)
from srl.packs.manifest import LICENSE_INCOMPATIBLE_REASON

# The repository root, for the architecture scan over the source tree.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "srl"
_ADAPTER_MODULE = _SRC_ROOT / "packs" / "adapters" / "cvxpy_adapter.py"

# In-repo CVXPY conformance fixtures.
_CVXPY_FIXTURES = _REPO_ROOT / "fixtures" / "conformance" / "cvxpy"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ridge_closed_form(a: np.ndarray, b: np.ndarray, lam: float) -> np.ndarray:
    """Return the closed-form ridge regression solution."""
    return np.linalg.solve(a.T @ a + lam * np.eye(a.shape[1]), a.T @ b)


# ---------------------------------------------------------------------------
# Surface and solver matrix
# ---------------------------------------------------------------------------


class TestSolverMatrix:
    """The allowed/denied solver matrix is enforced at the adapter surface."""

    def test_allowed_solvers(self) -> None:
        """Apache-2.0 solvers are allowed."""
        assert is_solver_allowed("clarabel")
        assert is_solver_allowed("osqp")
        assert is_solver_allowed("CLARABEL")

    def test_denied_gpl_solvers(self) -> None:
        """GPL-family solvers are denied."""
        assert not is_solver_allowed("glpk")
        assert not is_solver_allowed("cbc")
        assert not is_solver_allowed("GLPK")

    def test_solver_enum_values(self) -> None:
        """Solver enum values match the allowed solver strings."""
        assert Solver.CLARABEL == "clarabel"
        assert Solver.OSQP == "osqp"


class TestStatusEnum:
    """SolveStatus enumerates the honest terminal statuses."""

    def test_status_values(self) -> None:
        """Status enum values are the lowercase strings the gate expects."""
        assert SolveStatus.OPTIMAL == "optimal"
        assert SolveStatus.OPTIMAL_INACCURATE == "optimal_inaccurate"
        assert SolveStatus.INFEASIBLE == "infeasible"
        assert SolveStatus.UNBOUNDED == "unbounded"
        assert SolveStatus.SOLVER_ERROR == "solver_error"


# ---------------------------------------------------------------------------
# Problem spec validation and resource bounds
# ---------------------------------------------------------------------------


class TestSpecValidation:
    """Malformed or oversized specs are rejected before any CVXPY solve."""

    def test_missing_problem_type(self) -> None:
        """A spec without problem_type is rejected."""
        with pytest.raises(CvxpySpecError) as exc_info:
            solve({})
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_unknown_problem_type(self) -> None:
        """An unsupported problem type is rejected."""
        with pytest.raises(CvxpySpecError) as exc_info:
            solve({"problem_type": "milp"})
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_ridge_missing_b(self) -> None:
        """A ridge spec missing required data is rejected."""
        with pytest.raises(CvxpySpecError) as exc_info:
            solve({"problem_type": "ridge", "A": [[1, 2]], "lambda": 0.1})
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_inconsistent_a_b_shapes(self) -> None:
        """Mismatched A/b dimensions are rejected."""
        with pytest.raises(CvxpySpecError) as exc_info:
            solve({"problem_type": "least_squares", "A": [[1, 2], [3, 4]], "b": [1]})
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_negative_lambda(self) -> None:
        """A negative regularization parameter is rejected."""
        with pytest.raises(CvxpySpecError) as exc_info:
            solve({"problem_type": "ridge", "A": [[1, 2]], "b": [3], "lambda": -0.1})
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_variable_cap(self) -> None:
        """A spec exceeding the variable cap raises CvxpyResourceError."""
        spec = {
            "problem_type": "lp",
            "c": [1.0] * (MAX_VARIABLES + 1),
        }
        with pytest.raises(CvxpyResourceError) as exc_info:
            solve(spec)
        assert exc_info.value.fail_reason == "RESOURCE_LIMIT"

    def test_constraint_cap(self) -> None:
        """A spec exceeding the scalar constraint cap raises CvxpyResourceError."""
        spec = {
            "problem_type": "lp",
            "c": [1.0, 1.0],
            "constraints": [
                {
                    "kind": "box",
                    "lower": [0.0, 0.0],
                }
            ],
        }
        # Override the cap for this test by monkeypatching the module constant.
        original_cap = _adapter.MAX_CONSTRAINTS
        try:
            _adapter.MAX_CONSTRAINTS = 1
            with pytest.raises(CvxpyResourceError) as exc_info:
                solve(spec)
            assert exc_info.value.fail_reason == "RESOURCE_LIMIT"
        finally:
            _adapter.MAX_CONSTRAINTS = original_cap


# ---------------------------------------------------------------------------
# Successful solves
# ---------------------------------------------------------------------------


class TestSolve:
    """Optimal solves return typed results with decimal solution values."""

    def test_ridge_closed_form(self) -> None:
        """A small ridge problem matches the closed-form solution."""
        a = np.array([[1, 1], [1, 2], [1, 3]], dtype=float)
        b = np.array([1, 2, 3], dtype=float)
        lam = 0.1
        spec = {
            "problem_type": "ridge",
            "A": a.tolist(),
            "b": b.tolist(),
            "lambda": lam,
        }
        result = solve(spec)
        assert result.status == SolveStatus.OPTIMAL
        assert result.license_verified is True
        assert result.solver == "clarabel"
        assert result.solution is not None
        expected = _ridge_closed_form(a, b, lam)
        actual = np.asarray([float(v) for v in result.solution], dtype=float)
        assert np.allclose(actual, expected, atol=1e-6, rtol=1e-6)
        assert result.objective_decimal is not None

    def test_least_squares_with_box_constraints(self) -> None:
        """A least-squares problem with inactive box constraints stays optimal."""
        a = np.array([[1, 1], [1, 2], [1, 3]], dtype=float)
        b = np.array([1, 2, 3], dtype=float)
        spec = {
            "problem_type": "least_squares",
            "A": a.tolist(),
            "b": b.tolist(),
            "constraints": [
                {
                    "kind": "box",
                    "lower": [-10, -10],
                    "upper": [10, 10],
                }
            ],
        }
        result = solve(spec)
        assert result.status == SolveStatus.OPTIMAL
        assert result.solution is not None
        actual = np.asarray([float(v) for v in result.solution], dtype=float)
        expected = np.linalg.lstsq(a, b, rcond=None)[0]
        assert np.allclose(actual, expected, atol=1e-6, rtol=1e-6)

    def test_lasso(self) -> None:
        """A small lasso problem returns an optimal solution."""
        a = np.array([[1, 0], [0, 1], [1, 1]], dtype=float)
        b = np.array([1, 2, 3], dtype=float)
        spec = {
            "problem_type": "lasso",
            "A": a.tolist(),
            "b": b.tolist(),
            "lambda": 0.01,
        }
        result = solve(spec)
        assert result.status == SolveStatus.OPTIMAL
        assert result.solution is not None
        assert len(result.solution) == 2

    def test_lp(self) -> None:
        """A tiny linear program returns an optimal solution."""
        spec = {
            "problem_type": "lp",
            "c": [1.0, -1.0],
            "constraints": [
                {
                    "kind": "box",
                    "lower": [0.0, 0.0],
                    "upper": [5.0, 5.0],
                }
            ],
        }
        result = solve(spec)
        assert result.status == SolveStatus.OPTIMAL
        assert result.solution is not None
        actual = np.asarray([float(v) for v in result.solution], dtype=float)
        # Minimise x0 - x1 on [0,5]^2 -> x0=0, x1=5.
        assert np.allclose(actual, [0.0, 5.0], atol=1e-6, rtol=1e-6)

    def test_qp(self) -> None:
        """A tiny quadratic program returns an optimal solution."""
        spec = {
            "problem_type": "qp",
            "P": [[2.0, 0.0], [0.0, 2.0]],
            "q": [-2.0, -6.0],
            "constraints": [
                {
                    "kind": "box",
                    "lower": [0.0, 0.0],
                    "upper": [2.0, 2.0],
                }
            ],
        }
        result = solve(spec)
        assert result.status == SolveStatus.OPTIMAL
        assert result.solution is not None

    def test_osqp_alternate_solver(self) -> None:
        """The allowed alternate solver ``osqp`` produces an optimal result."""
        a = np.array([[1, 1], [1, 2], [1, 3]], dtype=float)
        b = np.array([1, 2, 3], dtype=float)
        spec = {
            "problem_type": "ridge",
            "A": a.tolist(),
            "b": b.tolist(),
            "lambda": 0.1,
        }
        result = solve(spec, solver=Solver.OSQP)
        assert result.status == SolveStatus.OPTIMAL
        assert result.solver == "osqp"
        assert result.license_verified is True


# ---------------------------------------------------------------------------
# Honest non-optimal statuses
# ---------------------------------------------------------------------------


class TestHonestStatuses:
    """Infeasible and unbounded problems return statuses, not exceptions."""

    def test_infeasible_lp(self) -> None:
        """A contradictory LP returns INFEASIBLE."""
        spec = {
            "problem_type": "lp",
            "c": [1.0],
            "constraints": [
                {
                    "kind": "box",
                    "lower": [1.0],
                    "upper": [0.0],
                }
            ],
        }
        result = solve(spec)
        assert result.status == SolveStatus.INFEASIBLE
        assert result.objective_decimal is None
        assert result.solution is None

    def test_unbounded_lp(self) -> None:
        """An unbounded LP returns UNBOUNDED."""
        spec = {
            "problem_type": "lp",
            "c": [-1.0],
            "constraints": [
                {
                    "kind": "box",
                    "lower": [0.0],
                }
            ],
        }
        result = solve(spec)
        assert result.status == SolveStatus.UNBOUNDED
        assert result.objective_decimal is None
        assert result.solution is None


# ---------------------------------------------------------------------------
# License rejection
# ---------------------------------------------------------------------------


class TestLicenseRejection:
    """GPL-family solver requests are rejected before any compute."""

    @pytest.mark.parametrize("solver", ["glpk", "cbc", "GLPK", "CBC"])
    def test_gpl_solver_rejected(self, solver: str) -> None:
        """Each GPL-family solver raises CvxpyLicenseError."""
        spec = {"problem_type": "lp", "c": [1.0]}
        with pytest.raises(CvxpyLicenseError) as exc_info:
            solve(spec, solver=solver)
        assert exc_info.value.fail_reason == LICENSE_INCOMPATIBLE_REASON


# ---------------------------------------------------------------------------
# Conformance fixtures
# ---------------------------------------------------------------------------


class TestConformanceFixtures:
    """The shipped CVXPY conformance fixtures behave as documented."""

    def test_constrained_fit_golden(self) -> None:
        """The ridge golden matches its closed-form reference."""
        fixture = json.loads((_CVXPY_FIXTURES / "constrained-fit-golden.json").read_text())
        result = solve(fixture["problem_spec"])
        assert result.status == SolveStatus.OPTIMAL
        expected = np.asarray(fixture["expected_solution"], dtype=float)
        actual = np.asarray([float(v) for v in result.solution], dtype=float)
        assert np.allclose(actual, expected, atol=fixture["tolerance"], rtol=fixture["tolerance"])

    def test_infeasible_fixture(self) -> None:
        """The infeasible fixture returns INFEASIBLE."""
        fixture = json.loads((_CVXPY_FIXTURES / "infeasible.json").read_text())
        result = solve(fixture["problem_spec"])
        assert result.status == SolveStatus.INFEASIBLE

    def test_unbounded_fixture(self) -> None:
        """The unbounded fixture returns UNBOUNDED."""
        fixture = json.loads((_CVXPY_FIXTURES / "unbounded.json").read_text())
        result = solve(fixture["problem_spec"])
        assert result.status == SolveStatus.UNBOUNDED

    def test_gpl_solver_rejection_fixture(self) -> None:
        """The GPL-solver fixture is rejected with LICENSE_INCOMPATIBLE."""
        fixture = json.loads((_CVXPY_FIXTURES / "gpl-solver-rejection.json").read_text())
        with pytest.raises(CvxpyLicenseError) as exc_info:
            solve(fixture["problem_spec"], solver=fixture["solver"])
        assert exc_info.value.fail_reason == fixture["expected_fail_reason"]


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------


class TestSolveResult:
    """SolveResult serializes to a stable dict and carries required fields."""

    def test_result_to_dict(self) -> None:
        """A result dict carries the schema and required fields."""
        result = SolveResult(
            schema_version=SOLVE_RESULT_SCHEMA_VERSION,
            status=SolveStatus.OPTIMAL,
            objective_decimal="1.0",
            solution=["1.0"],
            solution_digest="sha256:abc",
            duality_gap_decimal=None,
            solver="clarabel",
            license_verified=True,
        )
        d = result.to_dict()
        assert d["schema_version"] == SOLVE_RESULT_SCHEMA_VERSION
        assert d["status"] == "optimal"
        assert d["objective_decimal"] == "1.0"
        assert d["solution"] == ["1.0"]
        assert d["solution_digest"] == "sha256:abc"
        assert d["duality_gap_decimal"] is None
        assert d["solver"] == "clarabel"
        assert d["license_verified"] is True


# ---------------------------------------------------------------------------
# Version evidence helpers
# ---------------------------------------------------------------------------


class TestVersionHelpers:
    """Version helpers return non-empty strings for gate evidence."""

    def test_versions(self) -> None:
        """Version helpers report installed package versions."""
        assert isinstance(cvxpy_version(), str) and cvxpy_version()
        assert isinstance(clarabel_version(), str) and clarabel_version()
        assert isinstance(osqp_version(), str) and osqp_version()


# ---------------------------------------------------------------------------
# Architecture: isolation boundary
# ---------------------------------------------------------------------------


def _imports_in_file(path: Path, names: tuple[str, ...]) -> list[str]:
    """Return any import aliases in ``path`` that resolve to ``names``."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in names:
                    found.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(names):
                for alias in node.names:
                    found.append(alias.asname or alias.name)
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                if full.startswith(names):
                    found.append(alias.asname or alias.name)
    return found


def test_adapter_is_only_cvxpy_import_site() -> None:
    """Only the adapter imports cvxpy anywhere in the SRL source tree.

    The CVXPY dependency is isolated behind the adapter so that the solver/license
    matrix and the bounded problem surface are the only contract exposure points.
    """
    cvxpy_names = ("cvxpy",)
    for path in _SRC_ROOT.rglob("*.py"):
        if path == _ADAPTER_MODULE:
            continue
        imports = _imports_in_file(path, cvxpy_names)
        assert not imports, f"{path} imports forbidden cvxpy dep: {imports}"
