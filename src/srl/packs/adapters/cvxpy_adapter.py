"""CVXPY bounded optimization adapter (WP-H71b).

This module is the only SRL import site for ``cvxpy``. It exposes a small,
declarative problem spec and a typed ``SolveResult`` so that callers never
pass raw solver strings or unbounded problem objects. The adapter enforces
three hard boundaries:

1. **License matrix**: only Apache-2.0 solvers (``clarabel``, ``osqp``) are
   allowed. GPL-family solvers (``glpk``, ``cbc``) raise
   :class:`CvxpyLicenseError` with fail reason ``LICENSE_INCOMPATIBLE`` before
   any CVXPY object is built.
2. **Resource bounds**: at most 100 variables and 200 scalar constraints are
   accepted. Larger specs raise :class:`CvxpyResourceError` with fail reason
   ``RESOURCE_LIMIT`` before any solve.
3. **Honest statuses**: ``infeasible`` and ``unbounded`` are returned as first-
   class status values, never swallowed or re-raised as generic exceptions.

Supported problem types are deliberately narrow: least-squares with box
constraints, ridge, lasso, small linear programs, and small quadratic programs.

See ``docs/architecture/p1-cvxpy.md`` for the solver/license matrix and the
honest-status contract, and ``docs/adr/0009-cvxpy.md`` for the dependency
rationale.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import warnings
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

import cvxpy as cp
import numpy as np

from srl.contracts.canonical import decimal_to_str, dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.packs.manifest import LICENSE_INCOMPATIBLE_REASON

#: Schema identity for the result object.
SOLVE_RESULT_SCHEMA_VERSION: Final[str] = "SolveResult/v1"

#: Fail reason for a resource-limit violation.
RESOURCE_LIMIT_REASON: Final[str] = "RESOURCE_LIMIT"

#: Maximum number of optimization variables accepted by the adapter.
MAX_VARIABLES: Final[int] = 100

#: Maximum number of scalar constraints accepted by the adapter.
MAX_CONSTRAINTS: Final[int] = 200

#: Significant digits used when rendering CVXPY floats to decimal strings.
_SIG_DIGITS: Final[int] = 12


class CvxpyAdapterError(ContractError):
    """Raised when a CVXPY adapter contract is violated.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default; subclasses
    narrow it to ``LICENSE_INCOMPATIBLE`` or ``RESOURCE_LIMIT``.
    """


class CvxpyLicenseError(CvxpyAdapterError):
    """Raised when a requested solver is excluded by the license matrix.

    Carries the typed fail reason ``LICENSE_INCOMPATIBLE``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=LICENSE_INCOMPATIBLE_REASON)


class CvxpySpecError(CvxpyAdapterError):
    """Raised when a problem spec is malformed or unsupported.

    Carries the typed fail reason ``CONTRACT_INVALID``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=CONTRACT_INVALID_FAIL_REASON)


class CvxpyResourceError(CvxpyAdapterError):
    """Raised when a problem exceeds the bounded resource caps.

    Carries the typed fail reason ``RESOURCE_LIMIT``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, fail_reason=RESOURCE_LIMIT_REASON)


class Solver(StrEnum):
    """Allowed CVXPY solver selector.

    Only Apache-2.0 solvers are exposed. GPL-family solvers are rejected by
    :func:`is_solver_allowed` and :func:`solve` before any compute.
    """

    CLARABEL = "clarabel"
    OSQP = "osqp"


class SolveStatus(StrEnum):
    """Honest terminal status of a bounded optimization solve.

    ``infeasible`` and ``unbounded`` are first-class statuses: they are
    returned in the result, not raised as exceptions. A solver crash or an
    unrecognized status maps to ``solver_error``.
    """

    OPTIMAL = "optimal"
    OPTIMAL_INACCURATE = "optimal_inaccurate"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    SOLVER_ERROR = "solver_error"


#: Solver names that are excluded by the license matrix (GPL family).
_GPL_SOLVER_NAMES: Final[frozenset[str]] = frozenset({"glpk", "cbc"})

#: Allowed CVXPY problem types.
_ALLOWED_PROBLEM_TYPES: Final[frozenset[str]] = frozenset(
    {"least_squares", "ridge", "lasso", "lp", "qp"}
)


@dataclass(frozen=True, slots=True)
class SolveResult:
    """Typed result of a bounded CVXPY solve.

    Precision-sensitive fields are carried as SRL decimal strings; the solution
    is recorded both as a list of decimal strings and as a content digest so the
    result object is reproducible and content-addressable. ``objective_decimal``
    and ``solution`` are ``None`` for honest non-optimal statuses and for solver
    errors.
    """

    schema_version: str
    status: SolveStatus
    objective_decimal: str | None
    solution: list[str] | None
    solution_digest: str | None
    duality_gap_decimal: str | None
    solver: str
    license_verified: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the result as a JSON-serializable dict."""
        return {
            "schema_version": self.schema_version,
            "status": str(self.status),
            "objective_decimal": self.objective_decimal,
            "solution": self.solution,
            "solution_digest": self.solution_digest,
            "duality_gap_decimal": self.duality_gap_decimal,
            "solver": self.solver,
            "license_verified": self.license_verified,
        }


def is_solver_allowed(solver: str) -> bool:
    """Return ``True`` iff ``solver`` is an allowed Apache-2.0 solver."""
    return solver.lower() in {Solver.CLARABEL.value, Solver.OSQP.value}


def _float_to_decimal(value: float, sig_digits: int = _SIG_DIGITS) -> str:
    """Render a finite float as an SRL decimal string, rounded to ``sig_digits``."""
    if not np.isfinite(value):
        msg = f"cannot render non-finite value {value!r} as a decimal string"
        raise CvxpySpecError(msg)
    rounded = float(f"{value:.{sig_digits}g}")
    return decimal_to_str(Decimal(str(rounded)))


def _rounded_solution(solution: np.ndarray, sig_digits: int = _SIG_DIGITS) -> list[str]:
    """Return the solution as a list of SRL decimal strings, rounded for stability."""
    return [_float_to_decimal(float(v), sig_digits) for v in solution.tolist()]


def _solution_digest(solution: list[str]) -> str:
    """Return a ``sha256:`` digest of the canonical decimal-string solution."""
    canonical = dumps(solution)
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _duality_gap_decimal(problem: Any) -> str | None:
    """Extract a duality gap decimal from CVXPY solver stats, if available."""
    stats = getattr(problem, "solver_stats", None)
    if stats is None:
        return None
    extra = getattr(stats, "extra_stats", None)
    if not isinstance(extra, dict):
        return None
    gap = extra.get("duality_gap")
    if gap is None:
        return None
    try:
        return _float_to_decimal(float(gap), _SIG_DIGITS)
    except Exception:
        return None


def _as_array(value: Any, expected_ndim: int, context: str) -> np.ndarray:
    """Convert a spec value to a float NumPy array with the expected rank."""
    if not isinstance(value, (list, tuple, np.ndarray)):
        msg = (
            f"{context} must be an array-like (list, tuple, or ndarray), got {type(value).__name__}"
        )
        raise CvxpySpecError(msg)
    arr = np.asarray(value, dtype=float)
    if arr.ndim != expected_ndim:
        msg = f"{context} must be {expected_ndim}D, got shape {arr.shape}"
        raise CvxpySpecError(msg)
    return arr


def _validate_problem_type(spec: dict[str, Any]) -> str:
    """Validate and return the problem type."""
    problem_type = spec.get("problem_type")
    if not isinstance(problem_type, str):
        msg = f"problem_type must be a string, got {type(problem_type).__name__}"
        raise CvxpySpecError(msg)
    if problem_type not in _ALLOWED_PROBLEM_TYPES:
        msg = (
            f"problem_type {problem_type!r} is not supported; "
            f"must be one of {sorted(_ALLOWED_PROBLEM_TYPES)}"
        )
        raise CvxpySpecError(msg)
    return problem_type


def _variable_count(spec: dict[str, Any], problem_type: str) -> int:
    """Infer the number of variables from the spec data and check consistency."""
    if problem_type in {"least_squares", "ridge", "lasso"}:
        a = _as_array(spec.get("A"), 2, "A")
        if a.shape[0] == 0 or a.shape[1] == 0:
            msg = f"A must have positive dimensions, got shape {a.shape}"
            raise CvxpySpecError(msg)
        b = _as_array(spec.get("b"), 1, "b")
        if b.shape[0] != a.shape[0]:
            msg = f"b length {b.shape[0]} does not match A rows {a.shape[0]}"
            raise CvxpySpecError(msg)
        return int(a.shape[1])
    if problem_type == "lp":
        c = _as_array(spec.get("c"), 1, "c")
        if c.shape[0] == 0:
            msg = "c must have at least one element"
            raise CvxpySpecError(msg)
        return int(c.shape[0])
    if problem_type == "qp":
        p = _as_array(spec.get("P"), 2, "P")
        q = _as_array(spec.get("q"), 1, "q")
        if p.shape[0] == 0 or p.shape[1] == 0:
            msg = f"P must have positive dimensions, got shape {p.shape}"
            raise CvxpySpecError(msg)
        if p.shape[0] != p.shape[1]:
            msg = f"P must be square, got shape {p.shape}"
            raise CvxpySpecError(msg)
        if q.shape[0] != p.shape[0]:
            msg = f"q length {q.shape[0]} does not match P dimension {p.shape[0]}"
            raise CvxpySpecError(msg)
        return int(p.shape[0])
    msg = f"cannot infer variable count for problem_type {problem_type!r}"
    raise CvxpySpecError(msg)


def _count_scalar_constraints(spec: dict[str, Any], n: int) -> int:
    """Count the scalar constraints declared in the spec."""
    constraints = spec.get("constraints")
    if constraints is None:
        return 0
    if not isinstance(constraints, list):
        msg = f"constraints must be a list, got {type(constraints).__name__}"
        raise CvxpySpecError(msg)
    total = 0
    for idx, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            msg = f"constraints[{idx}] must be an object, got {type(constraint).__name__}"
            raise CvxpySpecError(msg)
        kind = constraint.get("kind")
        if kind == "box":
            if "lower" in constraint:
                total += n
            if "upper" in constraint:
                total += n
        elif kind in {"leq", "eq", "geq"}:
            rhs = _as_array(constraint.get("rhs"), 1, f"constraints[{idx}].rhs")
            total += int(rhs.shape[0])
        else:
            msg = f"constraints[{idx}].kind {kind!r} is not supported"
            raise CvxpySpecError(msg)
    return total


def _build_objective(x: Any, spec: dict[str, Any], problem_type: str) -> Any:
    """Build a CVXPY objective expression from the spec."""
    if problem_type == "least_squares":
        a = _as_array(spec["A"], 2, "A")
        b = _as_array(spec["b"], 1, "b")
        return cp.Minimize(cp.sum_squares(a @ x - b))
    if problem_type == "ridge":
        a = _as_array(spec["A"], 2, "A")
        b = _as_array(spec["b"], 1, "b")
        lam = _regularization_parameter(spec)
        return cp.Minimize(cp.sum_squares(a @ x - b) + lam * cp.sum_squares(x))
    if problem_type == "lasso":
        a = _as_array(spec["A"], 2, "A")
        b = _as_array(spec["b"], 1, "b")
        lam = _regularization_parameter(spec)
        return cp.Minimize(cp.sum_squares(a @ x - b) + lam * cp.norm1(x))
    if problem_type == "lp":
        c = _as_array(spec["c"], 1, "c")
        return cp.Minimize(c @ x)
    if problem_type == "qp":
        p = _as_array(spec["P"], 2, "P")
        q = _as_array(spec["q"], 1, "q")
        return cp.Minimize(0.5 * cp.quad_form(x, p) + q @ x)
    msg = f"unknown problem_type {problem_type!r}"
    raise CvxpySpecError(msg)


def _regularization_parameter(spec: dict[str, Any]) -> float:
    """Extract and validate the regularization parameter for ridge/lasso."""
    lam = spec.get("lambda")
    if isinstance(lam, (int, float)) and not isinstance(lam, bool):
        if lam < 0:
            msg = f"lambda must be non-negative, got {lam}"
            raise CvxpySpecError(msg)
        return float(lam)
    msg = f"lambda must be a non-negative number, got {lam!r}"
    raise CvxpySpecError(msg)


def _build_constraints(x: Any, spec: dict[str, Any], n: int) -> list[Any]:
    """Build CVXPY constraints from the spec."""
    constraints = spec.get("constraints")
    if constraints is None:
        return []
    if not isinstance(constraints, list):
        msg = f"constraints must be a list, got {type(constraints).__name__}"
        raise CvxpySpecError(msg)
    built: list[Any] = []
    for idx, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            msg = f"constraints[{idx}] must be an object, got {type(constraint).__name__}"
            raise CvxpySpecError(msg)
        kind = constraint.get("kind")
        if kind == "box":
            built.extend(_build_box_constraints(x, constraint, n, idx))
        elif kind == "leq":
            built.append(_build_matrix_constraint(x, n, idx, constraint, cp.le))
        elif kind == "geq":
            built.append(_build_matrix_constraint(x, n, idx, constraint, cp.ge))
        elif kind == "eq":
            built.append(_build_matrix_constraint(x, n, idx, constraint, cp.eq))
        else:
            msg = f"constraints[{idx}].kind {kind!r} is not supported"
            raise CvxpySpecError(msg)
    return built


def _build_box_constraints(x: Any, constraint: dict[str, Any], n: int, idx: int) -> list[Any]:
    """Build lower and/or upper box constraints."""
    out: list[Any] = []
    if "lower" in constraint:
        lower = constraint["lower"]
        lower_arr = _broadcast_bound(lower, n, f"constraints[{idx}].lower")
        out.append(x >= lower_arr)
    if "upper" in constraint:
        upper = constraint["upper"]
        upper_arr = _broadcast_bound(upper, n, f"constraints[{idx}].upper")
        out.append(x <= upper_arr)
    if not out:
        msg = f"constraints[{idx}] box constraint must specify lower or upper"
        raise CvxpySpecError(msg)
    return out


def _broadcast_bound(value: Any, n: int, context: str) -> np.ndarray:
    """Broadcast a scalar or length-n bound to an ndarray of length ``n``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return np.full(n, float(value), dtype=float)
    arr = _as_array(value, 1, context)
    if arr.shape[0] != n:
        msg = f"{context} length {arr.shape[0]} does not match variable count {n}"
        raise CvxpySpecError(msg)
    return arr


def _build_matrix_constraint(
    x: Any,
    n: int,
    idx: int,
    constraint: dict[str, Any],
    cp_op: Any,
) -> Any:
    """Build a matrix inequality/equality constraint: M x op rhs."""
    matrix = _as_array(constraint.get("matrix"), 2, f"constraints[{idx}].matrix")
    rhs = _as_array(constraint.get("rhs"), 1, f"constraints[{idx}].rhs")
    if matrix.shape[1] != n:
        msg = f"constraints[{idx}].matrix has {matrix.shape[1]} columns, expected {n}"
        raise CvxpySpecError(msg)
    if matrix.shape[0] != rhs.shape[0]:
        msg = (
            f"constraints[{idx}].matrix rows {matrix.shape[0]} do not match "
            f"rhs length {rhs.shape[0]}"
        )
        raise CvxpySpecError(msg)
    return cp_op(matrix @ x, rhs)


def _map_cvxpy_status(status: str | None) -> SolveStatus:
    """Map a CVXPY status string to a typed :class:`SolveStatus`."""
    if status is None:
        return SolveStatus.SOLVER_ERROR
    mapped = {
        "optimal": SolveStatus.OPTIMAL,
        "optimal_inaccurate": SolveStatus.OPTIMAL_INACCURATE,
        "infeasible": SolveStatus.INFEASIBLE,
        "unbounded": SolveStatus.UNBOUNDED,
    }
    return mapped.get(status.lower(), SolveStatus.SOLVER_ERROR)


def _cvxpy_solver_token(solver_name: str) -> Any:
    """Return the CVXPY solver object for an allowed solver name."""
    if solver_name == Solver.CLARABEL.value:
        return cp.CLARABEL
    if solver_name == Solver.OSQP.value:
        return cp.OSQP
    msg = f"internal error: no CVXPY token for {solver_name!r}"
    raise CvxpySpecError(msg)


def solve(
    problem_spec: dict[str, Any],
    *,
    solver: Solver | str = Solver.CLARABEL,
    max_wall: float = 30.0,
) -> SolveResult:
    """Solve a bounded, declarative CVXPY problem and return a typed result.

    Parameters
    ----------
    problem_spec:
        Declarative problem description. Must include ``problem_type`` and the
        data required for that type (``A``/``b`` for least_squares/ridge/lasso,
        ``c`` for lp, ``P``/``q`` for qp). Optionally includes ``constraints``.
    solver:
        Solver selector. Defaults to ``clarabel`` (Apache-2.0). ``osqp`` is the
        allowed alternate. GPL-family solvers (``glpk``, ``cbc``) raise
        :class:`CvxpyLicenseError` before any compute.
    max_wall:
        Wall-clock budget passed to the solver as a time limit.

    Returns
    -------
    SolveResult
        Typed solve result with first-class honest statuses.

    Raises
    ------
    CvxpyLicenseError
        If the solver is excluded by the license matrix.
    CvxpySpecError
        If the problem spec is malformed or unsupported.
    CvxpyResourceError
        If the spec exceeds the variable or constraint caps.
    """
    solver_name = solver.value if isinstance(solver, Solver) else str(solver).lower()

    if not is_solver_allowed(solver_name):
        if solver_name in _GPL_SOLVER_NAMES:
            msg = f"solver {solver_name!r} is GPL-family and is excluded by the license matrix"
            raise CvxpyLicenseError(msg)
        msg = f"solver {solver_name!r} is not in the allowed solver set"
        raise CvxpyLicenseError(msg)

    problem_type = _validate_problem_type(problem_spec)
    n = _variable_count(problem_spec, problem_type)
    if n > MAX_VARIABLES:
        msg = f"variable count {n} exceeds the adapter cap of {MAX_VARIABLES}"
        raise CvxpyResourceError(msg)

    scalar_constraints = _count_scalar_constraints(problem_spec, n)
    if scalar_constraints > MAX_CONSTRAINTS:
        msg = (
            f"scalar constraint count {scalar_constraints} exceeds the adapter "
            f"cap of {MAX_CONSTRAINTS}"
        )
        raise CvxpyResourceError(msg)

    x = cp.Variable(n)
    objective = _build_objective(x, problem_spec, problem_type)
    constraints = _build_constraints(x, problem_spec, n)
    problem = cp.Problem(objective, constraints)

    cp_solver = _cvxpy_solver_token(solver_name)
    solve_kwargs: dict[str, Any] = {"verbose": False}
    if max_wall > 0:
        solve_kwargs["time_limit"] = max_wall

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            problem.solve(solver=cp_solver, **solve_kwargs)
    except Exception:
        return SolveResult(
            schema_version=SOLVE_RESULT_SCHEMA_VERSION,
            status=SolveStatus.SOLVER_ERROR,
            objective_decimal=None,
            solution=None,
            solution_digest=None,
            duality_gap_decimal=None,
            solver=solver_name,
            license_verified=True,
        )

    status = _map_cvxpy_status(problem.status)

    if status in {SolveStatus.OPTIMAL, SolveStatus.OPTIMAL_INACCURATE}:
        objective_value = problem.value
        if objective_value is None or not np.isfinite(float(objective_value)):
            return SolveResult(
                schema_version=SOLVE_RESULT_SCHEMA_VERSION,
                status=SolveStatus.SOLVER_ERROR,
                objective_decimal=None,
                solution=None,
                solution_digest=None,
                duality_gap_decimal=None,
                solver=solver_name,
                license_verified=True,
            )
        solution = np.asarray(x.value).flatten()
        solution_strings = _rounded_solution(solution)
        return SolveResult(
            schema_version=SOLVE_RESULT_SCHEMA_VERSION,
            status=status,
            objective_decimal=_float_to_decimal(float(objective_value), _SIG_DIGITS),
            solution=solution_strings,
            solution_digest=_solution_digest(solution_strings),
            duality_gap_decimal=_duality_gap_decimal(problem),
            solver=solver_name,
            license_verified=True,
        )

    return SolveResult(
        schema_version=SOLVE_RESULT_SCHEMA_VERSION,
        status=status,
        objective_decimal=None,
        solution=None,
        solution_digest=None,
        duality_gap_decimal=None,
        solver=solver_name,
        license_verified=True,
    )


def cvxpy_version() -> str:
    """Return the resolved ``cvxpy`` version string (for gate evidence)."""
    return importlib.metadata.version("cvxpy")


def clarabel_version() -> str:
    """Return the resolved ``clarabel`` version string (for gate evidence)."""
    return importlib.metadata.version("clarabel")


def osqp_version() -> str:
    """Return the resolved ``osqp`` version string (for gate evidence)."""
    return importlib.metadata.version("osqp")


__all__ = [
    "MAX_CONSTRAINTS",
    "MAX_VARIABLES",
    "SOLVE_RESULT_SCHEMA_VERSION",
    "CvxpyAdapterError",
    "CvxpyLicenseError",
    "CvxpyResourceError",
    "CvxpySpecError",
    "SolveResult",
    "SolveStatus",
    "Solver",
    "clarabel_version",
    "cvxpy_version",
    "is_solver_allowed",
    "osqp_version",
    "solve",
]
