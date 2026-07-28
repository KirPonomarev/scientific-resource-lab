"""Tests for :mod:`srl.packs.adapters.pyriemann_adapter` (WP-E43).

All tests are hermetic: they exercise the pyriemann adapter on in-memory NumPy
arrays and the in-repo conformance fixtures, never touching the network.
`pyriemann`, `numpy`, and `scipy` are imported only inside the adapter; an
architecture test asserts no other module in the SRL tree imports them.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.packs.adapters.pyriemann_adapter import (
    DEFAULT_SHRINKAGE,
    SPD_EIG_TOL,
    Metric,
    SpdError,
    distance,
    fit_transform,
    log_euclidean_mean,
    numpy_version,
    pyriemann_version,
    riemannian_mean,
    scipy_version,
    shrinkage,
    transform,
)

# The repository root, for the architecture scan over the source tree.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "srl"
_ADAPTER_MODULE = _SRC_ROOT / "packs" / "adapters" / "pyriemann_adapter.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spd_2x3() -> np.ndarray:
    """Return a 2x2 SPD matrix."""
    return np.array([[2.0, 0.5], [0.5, 1.5]])


def _spd_2x3_b() -> np.ndarray:
    """Return a second 2x2 SPD matrix."""
    return np.array([[3.0, -0.2], [-0.2, 2.0]])


# ---------------------------------------------------------------------------
# Validation: SPD contract and trivial-covariance rejection
# ---------------------------------------------------------------------------


class TestSpdValidation:
    """The adapter rejects non-SPD and trivial 1x1 inputs before compute."""

    def test_non_symmetric_rejected(self) -> None:
        """A non-symmetric matrix raises SpdError with CONTRACT_INVALID."""
        bad = np.array([[1.0, 2.0], [3.0, 4.0]])
        with pytest.raises(SpdError) as exc_info:
            distance(bad, _spd_2x3(), Metric.RIEMANN)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_negative_eigenvalue_rejected(self) -> None:
        """An indefinite matrix raises SpdError with CONTRACT_INVALID."""
        bad = np.array([[1.0, 2.0], [2.0, -3.0]])
        with pytest.raises(SpdError) as exc_info:
            shrinkage(bad, DEFAULT_SHRINKAGE)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_singular_rejected(self) -> None:
        """A singular matrix raises SpdError with CONTRACT_INVALID."""
        bad = np.array([[1.0, 1.0], [1.0, 1.0]])
        with pytest.raises(SpdError) as exc_info:
            log_euclidean_mean([bad])
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_non_square_rejected(self) -> None:
        """A non-square array raises SpdError with CONTRACT_INVALID."""
        bad = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        with pytest.raises(SpdError) as exc_info:
            riemannian_mean([bad])
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_trivial_1x1_rejected(self) -> None:
        """A trivial 1x1 covariance raises SpdError with CONTRACT_INVALID."""
        trivial = np.array([[2.5]])
        with pytest.raises(SpdError) as exc_info:
            shrinkage(trivial, DEFAULT_SHRINKAGE)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_stack_validation_checks_each_matrix(self) -> None:
        """A stack containing one bad matrix is rejected."""
        good = _spd_2x3()
        bad = np.array([[1.0, 2.0], [3.0, 4.0]])
        stack = np.stack([good, bad])
        with pytest.raises(SpdError) as exc_info:
            log_euclidean_mean(stack)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


# ---------------------------------------------------------------------------
# Means
# ---------------------------------------------------------------------------


class TestMeans:
    """Riemannian and log-Euclidean means over SPD matrices."""

    def test_riemannian_mean_returns_spd(self) -> None:
        """The Riemannian mean of SPD matrices is SPD."""
        mean = riemannian_mean([_spd_2x3(), _spd_2x3_b()])
        assert mean.shape == (2, 2)
        eigenvalues = np.linalg.eigvalsh(mean)
        assert eigenvalues[0] > SPD_EIG_TOL

    def test_log_euclidean_mean_closed_form(self) -> None:
        """Log-Euclidean mean of commuting diagonal matrices is geometric mean."""
        a = np.array([[2.0, 0.0], [0.0, 3.0]])
        b = np.array([[8.0, 0.0], [0.0, 12.0]])
        expected = np.array([[4.0, 0.0], [0.0, 6.0]])
        mean = log_euclidean_mean([a, b])
        assert np.allclose(mean, expected)

    def test_single_matrix_mean_is_identity(self) -> None:
        """A single-matrix mean returns a copy of that matrix."""
        a = _spd_2x3()
        mean = log_euclidean_mean(a)
        assert np.allclose(mean, a)
        assert not np.shares_memory(mean, a)

    def test_weighted_mean(self) -> None:
        """Weights bias the mean toward the higher-weighted matrix."""
        a = _spd_2x3()
        b = _spd_2x3_b()
        mean_weighted = riemannian_mean([a, b], weights=np.array([0.9, 0.1]))
        mean_unweighted = riemannian_mean([a, b])
        # Weighted mean should be closer to `a` than unweighted mean.
        assert distance(a, mean_weighted, Metric.RIEMANN) < distance(
            a, mean_unweighted, Metric.RIEMANN
        )

    def test_negative_weights_rejected(self) -> None:
        """Negative sample weights raise SpdError."""
        with pytest.raises(SpdError):
            riemannian_mean([_spd_2x3(), _spd_2x3_b()], weights=np.array([1.0, -1.0]))

    def test_zero_sum_weights_rejected(self) -> None:
        """Weights summing to zero raise SpdError."""
        with pytest.raises(SpdError):
            riemannian_mean([_spd_2x3(), _spd_2x3_b()], weights=np.array([0.0, 0.0]))


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------


class TestDistance:
    """Riemannian and log-Euclidean distances satisfy metric axioms."""

    def test_identity(self) -> None:
        """Distance from a matrix to itself is zero."""
        a = _spd_2x3()
        assert np.isclose(distance(a, a, Metric.RIEMANN), 0.0)
        assert np.isclose(distance(a, a, Metric.LOGEUCLID), 0.0)

    def test_symmetry(self) -> None:
        """Riemannian distance is symmetric."""
        a = _spd_2x3()
        b = _spd_2x3_b()
        assert np.isclose(
            distance(a, b, Metric.RIEMANN),
            distance(b, a, Metric.RIEMANN),
        )

    def test_triangle_inequality(self) -> None:
        """Riemannian distance satisfies the triangle inequality."""
        a = _spd_2x3()
        b = _spd_2x3_b()
        c = np.array([[2.5, 0.1], [0.1, 1.8]])
        d_ab = distance(a, b, Metric.RIEMANN)
        d_bc = distance(b, c, Metric.RIEMANN)
        d_ac = distance(a, c, Metric.RIEMANN)
        assert d_ac <= d_ab + d_bc + 1e-9

    def test_mismatched_shapes_rejected(self) -> None:
        """Distance requires matching matrix shapes."""
        a = _spd_2x3()
        b = np.array([[2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        with pytest.raises(SpdError):
            distance(a, b, Metric.RIEMANN)

    def test_stacks_rejected_for_distance(self) -> None:
        """Distance does not accept stacks."""
        stack = np.stack([_spd_2x3(), _spd_2x3_b()])
        with pytest.raises(SpdError):
            distance(stack, stack, Metric.RIEMANN)


# ---------------------------------------------------------------------------
# Shrinkage
# ---------------------------------------------------------------------------


class TestShrinkage:
    """Per-matrix shrinkage preserves positive definiteness."""

    def test_shrinkage_preserves_spd(self) -> None:
        """Shrinking an SPD matrix yields an SPD matrix."""
        cov = _spd_2x3()
        shrunk = shrinkage(cov, 0.3)
        eigenvalues = np.linalg.eigvalsh(shrunk)
        assert eigenvalues[0] > SPD_EIG_TOL

    def test_shrinkage_alpha_bounds_enforced(self) -> None:
        """Alpha outside [0, 1] is rejected."""
        with pytest.raises(SpdError):
            shrinkage(_spd_2x3(), -0.1)
        with pytest.raises(SpdError):
            shrinkage(_spd_2x3(), 1.1)

    def test_shrinkage_changes_matrix(self) -> None:
        """Positive alpha moves the matrix toward its isotropic target."""
        cov = _spd_2x3()
        shrunk = shrinkage(cov, 0.5)
        assert not np.allclose(shrunk, cov)


# ---------------------------------------------------------------------------
# Train-only fit_transform / transform
# ---------------------------------------------------------------------------


class TestTrainOnlyShrinkage:
    """fit_transform and transform enforce train-only discipline."""

    def test_state_is_deterministic(self) -> None:
        """The state dict is identical for repeated fits on the same data."""
        train = np.stack([_spd_2x3(), _spd_2x3_b()])
        state1, _ = fit_transform(train)
        state2, _ = fit_transform(train)
        assert state1 == state2

    def test_transform_uses_train_state(self) -> None:
        """transform applies the train-derived target without recomputing it."""
        train = np.stack([_spd_2x3(), _spd_2x3_b()])
        test = np.array([[2.5, 0.1], [0.1, 1.8]])
        alpha = 0.3
        state, _ = fit_transform(train, alpha=alpha)
        target = np.asarray(state["target"], dtype=float)
        expected = (1.0 - alpha) * test + alpha * target
        transformed = transform(state, test)
        assert np.allclose(transformed, expected)

    def test_state_is_json_serializable(self) -> None:
        """The state dict round-trips through JSON unchanged."""
        train = np.stack([_spd_2x3(), _spd_2x3_b()])
        state, _ = fit_transform(train)
        serialized = json.dumps(state)
        assert json.loads(serialized) == state

    def test_transform_rejects_mismatched_dimension(self) -> None:
        """transform rejects matrices whose dimension differs from state."""
        train = np.stack([_spd_2x3(), _spd_2x3_b()])
        state, _ = fit_transform(train)
        test_3x3 = np.array([[2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        with pytest.raises(SpdError):
            transform(state, test_3x3)

    def test_empty_train_rejected(self) -> None:
        """fit_transform on an empty stack raises SpdError."""
        with pytest.raises(SpdError):
            fit_transform(np.zeros((0, 2, 2)))


# ---------------------------------------------------------------------------
# Conformance fixtures
# ---------------------------------------------------------------------------


class TestConformanceFixtures:
    """The shipped pyriemann conformance fixtures load and validate as expected."""

    _FIXTURES = _REPO_ROOT / "fixtures" / "conformance" / "pyriemann"

    def test_goldens_log_euclidean_closed_form(self) -> None:
        """The golden fixture's closed-form log-Euclidean check holds."""
        goldens = json.loads((self._FIXTURES / "goldens.json").read_text())
        a = np.array(goldens["log_euclidean_mean_closed_form"]["a"])
        b = np.array(goldens["log_euclidean_mean_closed_form"]["b"])
        expected = np.array(goldens["log_euclidean_mean_closed_form"]["expected"])
        tolerance = goldens["log_euclidean_mean_closed_form"]["tolerance"]
        mean = log_euclidean_mean([a, b])
        assert np.max(np.abs(mean - expected)) <= tolerance

    def test_non_spd_fixtures_rejected(self) -> None:
        """Every non-SPD fixture is rejected with CONTRACT_INVALID."""
        non_spd = json.loads((self._FIXTURES / "non-spd.json").read_text())
        for case in non_spd["cases"]:
            with pytest.raises(SpdError) as exc_info:
                distance(case["matrix"], case["matrix"], Metric.RIEMANN)
            assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_trivial_1x1_fixtures_rejected(self) -> None:
        """Every trivial 1x1 fixture is rejected with CONTRACT_INVALID."""
        trivial = json.loads((self._FIXTURES / "trivial-1x1.json").read_text())
        for case in trivial["cases"]:
            with pytest.raises(SpdError) as exc_info:
                shrinkage(case["matrix"], DEFAULT_SHRINKAGE)
            assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON


# ---------------------------------------------------------------------------
# Version evidence helpers
# ---------------------------------------------------------------------------


def test_version_helpers_report_non_empty_strings() -> None:
    """Version helpers return non-empty strings for gate evidence."""
    assert isinstance(pyriemann_version(), str) and pyriemann_version()
    assert isinstance(numpy_version(), str) and numpy_version()
    assert isinstance(scipy_version(), str) and scipy_version()


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


def test_adapter_is_only_geometry_import_site() -> None:
    """Only the adapter imports pyriemann, numpy, and scipy for geometry.

    This test scans every Python file under ``src/srl`` and fails if any file
    other than the adapter imports ``pyriemann`` or ``scipy``. ``numpy`` is
    allowed only in test modules and in the adapter itself, because the rest of
    the SRL surface operates on scalar decimal strings and JSON.
    """
    geometry_names = ("pyriemann", "scipy")
    numpy_name = ("numpy",)
    for path in _SRC_ROOT.rglob("*.py"):
        if path == _ADAPTER_MODULE:
            continue
        imports = _imports_in_file(path, geometry_names)
        assert not imports, f"{path} imports forbidden geometry deps: {imports}"
        np_imports = _imports_in_file(path, numpy_name)
        assert not np_imports, f"{path} imports numpy outside the adapter: {np_imports}"
