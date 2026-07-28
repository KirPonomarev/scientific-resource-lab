"""pyRiemann-backed SPD geometry adapter (WP-E43).

This module is the geometry layer for the symmetric positive definite (SPD)
manifold. It wraps `pyriemann` for Riemannian/log-Euclidean means and distances,
and adds SRL's fail-fast SPD validation, trivial-covariance rejection, and a
train-only shrinkage API.

The adapter is the **only** module in the SRL tree that imports `pyriemann`,
`numpy`, and `scipy` for geometry work (asserted by an architecture test in
``tests/packs/test_pyriemann_adapter.py``). Every other consumer goes through the
typed surface defined here:

- :class:`Metric` -- enum selecting ``riemann`` or ``logeuclid`` for distances.
- :class:`SpdError` -- raised for non-SPD, malformed, or trivial 1x1 inputs
  (fail reason ``CONTRACT_INVALID``).
- :func:`riemannian_mean` -- affine-invariant Riemannian mean of SPD matrices.
- :func:`log_euclidean_mean` -- log-Euclidean mean of SPD matrices.
- :func:`distance` -- Riemannian or log-Euclidean distance between two SPD
  matrices.
- :func:`shrinkage` -- shrink a single SPD covariance toward its isotropic
  target.
- :func:`fit_transform` / :func:`transform` -- train-only shrinkage API whose
  state carries only training-derived statistics.

See ``docs/architecture/pyriemann-pack.md`` for the train-only discipline and
``docs/adr/0006-pyriemann.md`` for the dependency rationale.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

import numpy as np
import pyriemann  # type: ignore[import-untyped]
import scipy.linalg  # type: ignore[import-untyped]
from pyriemann.geometry.distance import (  # type: ignore[import-untyped]
    distance_logeuclid,
    distance_riemann,
)
from pyriemann.geometry.mean import (  # type: ignore[import-untyped]
    mean_logeuclid,
    mean_riemann,
)

from srl.contracts.errors import ContractError

#: Number of dimensions for a single matrix.
MATRIX_NDIM: Final[int] = 2

#: Number of dimensions for a stack of matrices.
STACK_NDIM: Final[int] = 3

#: Minimum accepted matrix size. Trivial 1x1 covariances are rejected because they
#: carry no off-diagonal geometry and collapse every SPD metric to a scalar ratio.
MIN_MATRIX_SIZE: Final[int] = 2

#: Tolerance for the SPD eigenvalue check. A matrix is accepted as SPD only when
#: every eigenvalue is strictly greater than this bound. The value is small
#: enough to absorb benign floating-point round-off but large enough to reject
#: numerically singular inputs.
SPD_EIG_TOL: Final[float] = 1e-7

#: Default shrinkage coefficient used by the train-only API when none is given.
#: Matches the sklearn ``shrunk_covariance`` default so the behaviour is familiar
#: to scientific callers.
DEFAULT_SHRINKAGE: Final[float] = 0.1


class SpdError(ContractError):
    """Raised when an input fails the SPD contract.

    Carries the typed fail reason ``CONTRACT_INVALID``. Raised for: non-square
    matrices, non-symmetric matrices, matrices with non-positive eigenvalues, or
    trivial 1x1 covariances.
    """


class Metric(StrEnum):
    """Distance metric selector for the SPD manifold.

    The values are lowercase strings so the enum serializes cleanly to JSON.
    """

    RIEMANN = "riemann"
    LOGEUCLID = "logeuclid"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_array(value: Any, *, context: str) -> np.ndarray:
    """Convert ``value`` to a float NumPy array, rejecting unsupported types."""
    if isinstance(value, np.ndarray):
        arr = value
    elif isinstance(value, (list, tuple)):
        arr = np.asarray(value, dtype=float)
    else:
        msg = f"{context} must be a NumPy ndarray or nested list, got {type(value).__name__}"
        raise SpdError(msg)
    if not np.issubdtype(arr.dtype, np.floating) and not np.issubdtype(arr.dtype, np.integer):
        msg = f"{context} must be numeric, got dtype {arr.dtype}"
        raise SpdError(msg)
    return arr.astype(float, copy=False)


def _assert_spd(matrix: np.ndarray, *, context: str) -> None:
    """Validate that ``matrix`` is a non-trivial SPD matrix.

    Checks: square, at least 2x2, symmetric within tolerance, and all
    eigenvalues strictly positive within :data:`SPD_EIG_TOL`. Raises
    :class:`SpdError` (`CONTRACT_INVALID`) on any violation.
    """
    if matrix.ndim != MATRIX_NDIM:
        msg = f"{context} must be a 2D matrix, got shape {matrix.shape}"
        raise SpdError(msg)
    rows, cols = matrix.shape
    if rows != cols:
        msg = f"{context} must be square, got shape {matrix.shape}"
        raise SpdError(msg)
    if rows < MIN_MATRIX_SIZE:
        msg = (
            f"{context} is a trivial 1x1 covariance; "
            f"only matrices of size >= {MIN_MATRIX_SIZE} are accepted"
        )
        raise SpdError(msg)
    if not np.allclose(matrix, matrix.T, atol=SPD_EIG_TOL):
        msg = f"{context} is not symmetric within tolerance {SPD_EIG_TOL}"
        raise SpdError(msg)
    eigenvalues = scipy.linalg.eigvalsh(matrix, check_finite=False)
    if eigenvalues[0] <= SPD_EIG_TOL:
        msg = (
            f"{context} is not positive definite within tolerance {SPD_EIG_TOL}; "
            f"smallest eigenvalue is {eigenvalues[0]:.3e}"
        )
        raise SpdError(msg)


def _validate_stack(value: Any, *, context: str) -> np.ndarray:
    """Convert ``value`` to an ndarray and validate every matrix as SPD."""
    arr = _as_array(value, context=context)
    if arr.ndim == MATRIX_NDIM:
        _assert_spd(arr, context=context)
        return arr
    if arr.ndim == STACK_NDIM:
        if arr.shape[1] != arr.shape[2]:
            msg = f"{context} stack must contain square matrices, got shape {arr.shape}"
            raise SpdError(msg)
        for idx in range(arr.shape[0]):
            _assert_spd(arr[idx], context=f"{context}[{idx}]")
        return arr
    msg = f"{context} must be a 2D SPD matrix or a 3D stack of SPD matrices, got shape {arr.shape}"
    raise SpdError(msg)


def _validate_weights(weights: Any | None, n: int, *, context: str) -> np.ndarray | None:
    """Validate and normalize sample weights for mean computation."""
    if weights is None:
        return None
    arr = _as_array(weights, context=f"{context}.weights")
    if arr.ndim != 1 or arr.shape[0] != n:
        msg = f"{context}.weights must be a 1D array of length {n}, got shape {arr.shape}"
        raise SpdError(msg)
    if np.any(arr < 0):
        msg = f"{context}.weights must be non-negative"
        raise SpdError(msg)
    total = arr.sum()
    if total <= 0:
        msg = f"{context}.weights must sum to a positive value, got {total}"
        raise SpdError(msg)
    return arr


def _isotropic_target(cov: np.ndarray) -> np.ndarray:
    """Return the isotropic target ``(trace(cov) / n) * I`` for shrinkage."""
    n = cov.shape[0]
    scale = float(np.trace(cov) / n)
    return scale * np.eye(n, dtype=float)


def _shrink_toward(cov: np.ndarray, alpha: float, target: np.ndarray) -> np.ndarray:
    """Shrink ``cov`` toward ``target`` with coefficient ``alpha``.

    ``alpha`` is clamped to ``[0, 1]``; values outside that range would not
    preserve the SPD guarantee. The caller already validated ``cov`` as SPD.
    """
    if not 0.0 <= alpha <= 1.0:
        msg = f"shrinkage alpha must be in [0, 1], got {alpha}"
        raise SpdError(msg)
    return (1.0 - alpha) * cov + alpha * target


# ---------------------------------------------------------------------------
# Distance metric dispatch table
# ---------------------------------------------------------------------------

_DISTANCE_FN: Final[dict[Metric, Any]] = {
    Metric.RIEMANN: distance_riemann,
    Metric.LOGEUCLID: distance_logeuclid,
}


# ---------------------------------------------------------------------------
# Public API: means and distances
# ---------------------------------------------------------------------------


def riemannian_mean(mats: Any, weights: Any | None = None) -> np.ndarray:
    """Compute the Riemannian mean of a stack of SPD matrices.

    Parameters
    ----------
    mats:
        A ``(n_matrices, n, n)`` array-like stack of SPD matrices, or a single
        ``(n, n)`` matrix (in which case it is returned unchanged).
    weights:
        Optional ``(n_matrices,)`` non-negative weights summing to a positive
        value. If ``None``, the mean is unweighted.

    Returns
    -------
    np.ndarray
        The ``(n, n)`` Riemannian mean matrix.

    Raises
    ------
    SpdError
        If ``mats`` contains a non-SPD or trivial 1x1 matrix, or if ``weights``
        is malformed (fail reason ``CONTRACT_INVALID``).
    """
    arr = _validate_stack(mats, context="mats")
    if arr.ndim == MATRIX_NDIM:
        return arr.copy()
    w = _validate_weights(weights, arr.shape[0], context="riemannian_mean")
    return np.asarray(mean_riemann(arr, sample_weight=w), dtype=float)


def log_euclidean_mean(mats: Any, weights: Any | None = None) -> np.ndarray:
    """Compute the log-Euclidean mean of a stack of SPD matrices.

    Parameters
    ----------
    mats:
        A ``(n_matrices, n, n)`` array-like stack of SPD matrices, or a single
        ``(n, n)`` matrix (in which case it is returned unchanged).
    weights:
        Optional ``(n_matrices,)`` non-negative weights summing to a positive
        value. If ``None``, the mean is unweighted.

    Returns
    -------
    np.ndarray
        The ``(n, n)`` log-Euclidean mean matrix.

    Raises
    ------
    SpdError
        If ``mats`` contains a non-SPD or trivial 1x1 matrix, or if ``weights``
        is malformed (fail reason ``CONTRACT_INVALID``).
    """
    arr = _validate_stack(mats, context="mats")
    if arr.ndim == MATRIX_NDIM:
        return arr.copy()
    w = _validate_weights(weights, arr.shape[0], context="log_euclidean_mean")
    return np.asarray(mean_logeuclid(arr, sample_weight=w), dtype=float)


def distance(a: Any, b: Any, metric: Metric) -> float:
    """Compute the SPD distance between two matrices under ``metric``.

    Parameters
    ----------
    a, b:
        Two ``(n, n)`` SPD matrices.
    metric:
        Either :attr:`Metric.RIEMANN` or :attr:`Metric.LOGEUCLID`.

    Returns
    -------
    float
        The scalar distance.

    Raises
    ------
    SpdError
        If either matrix is non-SPD or trivial 1x1 (fail reason
        ``CONTRACT_INVALID``).
    """
    a_arr = _validate_stack(a, context="a")
    b_arr = _validate_stack(b, context="b")
    if a_arr.ndim != MATRIX_NDIM or b_arr.ndim != MATRIX_NDIM:
        msg = "distance expects two 2D SPD matrices, not stacks"
        raise SpdError(msg)
    if a_arr.shape != b_arr.shape:
        msg = f"distance matrix shapes must match, got {a_arr.shape} and {b_arr.shape}"
        raise SpdError(msg)
    fn = _DISTANCE_FN.get(metric)
    if fn is None:
        msg = f"unknown metric {metric!r}"
        raise SpdError(msg)
    return float(fn(a_arr, b_arr))


# ---------------------------------------------------------------------------
# Public API: shrinkage
# ---------------------------------------------------------------------------


def shrinkage(cov: Any, alpha: float) -> np.ndarray:
    """Shrink an SPD covariance matrix toward its isotropic target.

    The shrunk matrix is ``(1 - alpha) * cov + alpha * (trace(cov)/n) * I``.
    For ``alpha`` in ``[0, 1]`` the result is guaranteed SPD.

    Parameters
    ----------
    cov:
        A single ``(n, n)`` SPD matrix with ``n >= 2``.
    alpha:
        Shrinkage coefficient in ``[0, 1]``.

    Returns
    -------
    np.ndarray
        The shrunk ``(n, n)`` SPD matrix.

    Raises
    ------
    SpdError
        If ``cov`` is non-SPD, trivial 1x1, or ``alpha`` is outside ``[0, 1]``
        (fail reason ``CONTRACT_INVALID``).
    """
    arr = _validate_stack(cov, context="cov")
    if arr.ndim != MATRIX_NDIM:
        msg = "shrinkage expects a single 2D SPD matrix, not a stack"
        raise SpdError(msg)
    target = _isotropic_target(arr)
    return _shrink_toward(arr, alpha, target)


def fit_transform(
    train: Any, alpha: float = DEFAULT_SHRINKAGE
) -> tuple[dict[str, Any], np.ndarray]:
    """Fit a train-only shrinkage target and transform the training matrices.

    The returned ``state`` is a JSON-serializable dict containing only statistics
    derived from ``train``:

    - ``alpha``: the shrinkage coefficient used;
    - ``n_features``: the matrix dimension ``n``;
    - ``target``: the isotropic target (mean trace scaling across ``train``
      times the identity) as a nested list.

    ``transform(state, new)`` applies the same target to new matrices without
    recomputing any statistic from ``new``. This guarantees that test data
    cannot leak into the fitted state.

    Parameters
    ----------
    train:
        A ``(n_train, n, n)`` stack of SPD matrices with ``n >= 2``.
    alpha:
        Shrinkage coefficient in ``[0, 1]``; defaults to
        :data:`DEFAULT_SHRINKAGE`.

    Returns
    -------
    tuple[dict[str, Any], np.ndarray]
        ``(state, transformed_train)``.

    Raises
    ------
    SpdError
        If ``train`` contains a non-SPD or trivial 1x1 matrix, or ``alpha`` is
        outside ``[0, 1]`` (fail reason ``CONTRACT_INVALID``).
    """
    arr = _validate_stack(train, context="train")
    if arr.ndim != STACK_NDIM:
        msg = f"fit_transform expects a 3D stack of SPD matrices, got shape {arr.shape}"
        raise SpdError(msg)
    if arr.shape[0] == 0:
        msg = "fit_transform requires at least one training matrix"
        raise SpdError(msg)
    n = arr.shape[1]
    mean_scale = float(np.mean([np.trace(m) / n for m in arr]))
    target = mean_scale * np.eye(n, dtype=float)
    state: dict[str, Any] = {
        "alpha": alpha,
        "n_features": n,
        "target": target.tolist(),
    }
    transformed = np.stack([_shrink_toward(m, alpha, target) for m in arr])
    return state, transformed


def transform(state: dict[str, Any], new: Any) -> np.ndarray:
    """Apply a previously fitted shrinkage target to new SPD matrices.

    The ``state`` must be the dict returned by :func:`fit_transform`. This
    function reads only ``state``; it never mutates it and never recomputes any
    statistic from ``new``.

    Parameters
    ----------
    state:
        JSON-serializable state dict from :func:`fit_transform`.
    new:
        A ``(n_new, n, n)`` stack of SPD matrices (or a single ``(n, n)`` matrix),
        with ``n`` matching ``state["n_features"]``.

    Returns
    -------
    np.ndarray
        The shrunk new matrices.

    Raises
    ------
    SpdError
        If ``state`` is malformed, ``new`` is non-SPD/trivial 1x1, or the
        dimensions mismatch (fail reason ``CONTRACT_INVALID``).
    """
    _validate_state(state)
    alpha = state["alpha"]
    n = state["n_features"]
    target = np.asarray(state["target"], dtype=float)
    if target.shape != (n, n):
        msg = f"state['target'] shape {target.shape} does not match n_features {n}"
        raise SpdError(msg)

    arr = _validate_stack(new, context="new")
    if arr.ndim == MATRIX_NDIM:
        if arr.shape != (n, n):
            msg = f"new matrix shape {arr.shape} does not match state n_features {n}"
            raise SpdError(msg)
        return _shrink_toward(arr, alpha, target)
    if arr.shape[1] != n:
        msg = f"new stack matrix dimension {arr.shape[1]} does not match state n_features {n}"
        raise SpdError(msg)
    return np.stack([_shrink_toward(m, alpha, target) for m in arr])


def _validate_state(state: Any) -> None:
    """Validate the structural shape of a shrinkage state dict."""
    if not isinstance(state, dict):
        msg = f"state must be a dict, got {type(state).__name__}"
        raise SpdError(msg)
    required = {"alpha", "n_features", "target"}
    missing = required - set(state.keys())
    if missing:
        msg = f"state missing required key(s): {sorted(missing)}"
        raise SpdError(msg)
    extra = set(state.keys()) - required
    if extra:
        msg = f"state has unexpected key(s): {sorted(extra)}"
        raise SpdError(msg)
    alpha = state["alpha"]
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool):
        msg = f"state['alpha'] must be a float, got {type(alpha).__name__}"
        raise SpdError(msg)
    n_features = state["n_features"]
    if (
        not isinstance(n_features, int)
        or isinstance(n_features, bool)
        or n_features < MIN_MATRIX_SIZE
    ):
        msg = f"state['n_features'] must be an integer >= {MIN_MATRIX_SIZE}, got {n_features!r}"
        raise SpdError(msg)
    target = state["target"]
    if not isinstance(target, list):
        msg = f"state['target'] must be a list, got {type(target).__name__}"
        raise SpdError(msg)


# ---------------------------------------------------------------------------
# Version evidence helpers
# ---------------------------------------------------------------------------


def pyriemann_version() -> str:
    """Return the resolved pyriemann version string (for gate evidence)."""
    return str(pyriemann.__version__)


def numpy_version() -> str:
    """Return the resolved NumPy version string (for gate evidence)."""
    return str(np.__version__)


def scipy_version() -> str:
    """Return the resolved SciPy version string (for gate evidence)."""
    return str(scipy.__version__)


__all__ = [
    "DEFAULT_SHRINKAGE",
    "MATRIX_NDIM",
    "MIN_MATRIX_SIZE",
    "SPD_EIG_TOL",
    "STACK_NDIM",
    "Metric",
    "SpdError",
    "distance",
    "fit_transform",
    "log_euclidean_mean",
    "numpy_version",
    "pyriemann_version",
    "riemannian_mean",
    "scipy_version",
    "shrinkage",
    "transform",
]
