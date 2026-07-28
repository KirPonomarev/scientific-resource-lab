"""Tests for :mod:`srl.packs.adapters.pymc_adapter` (WP-H71a).

All tests are hermetic: they exercise the PyMC adapter on in-memory seeded data
and never touch the network. ``pymc`` and ``arviz`` are imported only inside the
adapter; an architecture test asserts no other module in the SRL tree imports
them.

The sampler is bounded (draws/tune small) so the whole module runs comfortably
inside the CI budget while still exercising the real NUTS path.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# The PyMC adapter lives behind the optional ``bayesian`` extra
# (``uv sync --extra bayesian``). When the extra is not installed the whole
# module is skipped, so the default ``pytest`` run (no extra) is unaffected.
pytest.importorskip("pymc")
pytest.importorskip("arviz")

import numpy as np

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.packs.adapters.pymc_adapter import (
    DEFAULT_TARGET_ACCEPT,
    ESS_FLOOR,
    KIND_LINEAR_REGRESSION,
    KIND_NORMAL_MEAN,
    MAX_DRAWS,
    MAX_TUNE,
    PYMC_FAIL_REASON,
    REQUIRED_CHAINS,
    SELECTION_NOTE,
    PosteriorPredictiveCheck,
    PymcAdapterError,
    SummaryStats,
    arviz_version,
    build_model_spec,
    fit_posterior,
    numpy_version,
    pymc_version,
)

# The repository root, for the architecture scan over the source tree.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "srl"
_ADAPTER_MODULE = _SRC_ROOT / "packs" / "adapters" / "pymc_adapter.py"

# Decimal-string policy regex (mirrors srl.contracts.canonical).
_DECIMAL_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")

# Sampler dimensions for tests. 200/200 is the smallest size at which the
# one-chain ESS diagnostic is stable (shorter chains make ESS noisy and can
# spuriously trip the ESS floor); 200/200 keeps the whole module fast while
# making the diagnostics_flag assertions reliable.
_DRAWS = 200
_TUNE = 200
_SEED = 7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normal_mean_data(
    n: int = 120, mu: float = 2.5, sigma: float = 1.0, seed: int = 42
) -> np.ndarray:
    """Return a seeded normal-mean response array."""
    rng = np.random.default_rng(seed)
    return rng.normal(loc=mu, scale=sigma, size=n)


def _normal_mean_spec() -> object:
    """Return a validated normal_mean ModelSpec."""
    return build_model_spec(
        KIND_NORMAL_MEAN,
        {"mu_prior_mu": 0.0, "mu_prior_sigma": 10.0, "sigma_prior": 5.0},
    )


def _assert_decimal_string(value: str, *, context: str) -> None:
    """Assert a value is a valid SRL decimal-string policy string."""
    assert isinstance(value, str), f"{context}: not a string, got {type(value).__name__}"
    assert _DECIMAL_RE.fullmatch(value), (
        f"{context}: {value!r} is not a decimal-string policy value"
    )


# ---------------------------------------------------------------------------
# Model-spec validation
# ---------------------------------------------------------------------------


class TestModelSpecValidation:
    """The model spec is restricted data; bad kinds and params are rejected."""

    def test_unsupported_kind_rejected(self) -> None:
        """An unsupported kind raises PymcAdapterError with CONTRACT_INVALID."""
        with pytest.raises(PymcAdapterError) as exc_info:
            build_model_spec("lasso", {"alpha": 1.0})
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_normal_mean_missing_param_rejected(self) -> None:
        """A missing normal_mean param raises PymcAdapterError."""
        with pytest.raises(PymcAdapterError):
            build_model_spec(KIND_NORMAL_MEAN, {"mu_prior_mu": 0.0, "mu_prior_sigma": 10.0})

    def test_normal_mean_extra_param_rejected(self) -> None:
        """An unexpected normal_mean param raises PymcAdapterError."""
        with pytest.raises(PymcAdapterError):
            build_model_spec(
                KIND_NORMAL_MEAN,
                {"mu_prior_mu": 0.0, "mu_prior_sigma": 10.0, "sigma_prior": 5.0, "extra": 1.0},
            )

    def test_non_positive_scale_rejected(self) -> None:
        """A non-positive prior scale raises PymcAdapterError."""
        with pytest.raises(PymcAdapterError):
            build_model_spec(
                KIND_NORMAL_MEAN,
                {"mu_prior_mu": 0.0, "mu_prior_sigma": 0.0, "sigma_prior": 5.0},
            )

    def test_non_finite_param_rejected(self) -> None:
        """A non-finite param value raises PymcAdapterError."""
        with pytest.raises(PymcAdapterError):
            build_model_spec(
                KIND_NORMAL_MEAN,
                {"mu_prior_mu": float("inf"), "mu_prior_sigma": 10.0, "sigma_prior": 5.0},
            )

    def test_params_not_object_rejected(self) -> None:
        """A non-dict params raises PymcAdapterError."""
        with pytest.raises(PymcAdapterError):
            build_model_spec(KIND_NORMAL_MEAN, [1, 2, 3])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Data validation
# ---------------------------------------------------------------------------


class TestDataValidation:
    """The adapter rejects bad data shapes before any compute."""

    def test_data_too_short_rejected(self) -> None:
        """A single-element dataset raises PymcAdapterError."""
        spec = _normal_mean_spec()
        with pytest.raises(PymcAdapterError):
            fit_posterior(np.array([1.0]), spec, seed=_SEED)  # type: ignore[arg-type]

    def test_data_non_finite_rejected(self) -> None:
        """A NaN in the data raises PymcAdapterError."""
        spec = _normal_mean_spec()
        with pytest.raises(PymcAdapterError):
            fit_posterior(np.array([1.0, float("nan"), 3.0]), spec, draws=20, tune=20, seed=_SEED)  # type: ignore[arg-type]

    def test_data_2d_rejected(self) -> None:
        """A 2D data array raises PymcAdapterError for the normal-mean model."""
        spec = _normal_mean_spec()
        with pytest.raises(PymcAdapterError):
            fit_posterior(np.zeros((4, 2)), spec, seed=_SEED)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The one-chain bounded profile (chains==1 is structural)
# ---------------------------------------------------------------------------


class TestOneChainProfile:
    """The adapter runs exactly one chain; multi-chain requests are refused."""

    def test_constants_are_the_bounded_profile(self) -> None:
        """The bounded-profile constants have their documented values."""
        assert REQUIRED_CHAINS == 1
        assert MAX_DRAWS == 500
        assert MAX_TUNE == 500
        assert ESS_FLOOR == 50
        assert DEFAULT_TARGET_ACCEPT == 0.9

    def test_chains_gt_one_refused_with_contract_invalid(self) -> None:
        """A chains=2 request raises PymcAdapterError with CONTRACT_INVALID."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=30)
        with pytest.raises(PymcAdapterError) as exc_info:
            fit_posterior(data, spec, draws=20, tune=20, chains=2, seed=_SEED)
        assert exc_info.value.fail_reason == PYMC_FAIL_REASON

    def test_chains_zero_refused(self) -> None:
        """A chains=0 request raises PymcAdapterError."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=30)
        with pytest.raises(PymcAdapterError):
            fit_posterior(data, spec, draws=20, tune=20, chains=0, seed=_SEED)

    def test_draws_over_ceiling_refused(self) -> None:
        """A draws value over MAX_DRAWS raises PymcAdapterError."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=30)
        with pytest.raises(PymcAdapterError):
            fit_posterior(data, spec, draws=MAX_DRAWS + 1, tune=20, seed=_SEED)

    def test_tune_over_ceiling_refused(self) -> None:
        """A tune value over MAX_TUNE raises PymcAdapterError."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=30)
        with pytest.raises(PymcAdapterError):
            fit_posterior(data, spec, draws=20, tune=MAX_TUNE + 1, seed=_SEED)

    def test_seed_required_and_validated(self) -> None:
        """A non-integer or negative seed raises PymcAdapterError."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=30)
        with pytest.raises(PymcAdapterError):
            fit_posterior(data, spec, draws=20, tune=20, seed=-1)  # type: ignore[arg-type]

    def test_successful_fit_reports_one_chain(self) -> None:
        """A successful fit reports chains == REQUIRED_CHAINS."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=40)
        result = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        assert result.chains == REQUIRED_CHAINS


# ---------------------------------------------------------------------------
# Posterior fit: recovery, summary shape, decimal strings
# ---------------------------------------------------------------------------


class TestPosteriorFit:
    """The one-chain fit recovers the true mean and reports decimal strings."""

    def test_recovers_true_mean_within_tolerance(self) -> None:
        """The posterior mu mean is within 0.3 of the true mean 2.5."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=120)
        result = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        mu_mean = float(result.parameters["mu"].mean)
        assert abs(mu_mean - 2.5) < 0.3

    def test_summary_stats_are_decimal_strings(self) -> None:
        """Every summary stat is a valid decimal-string policy value."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=80)
        result = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        for param_name, stats in result.parameters.items():
            assert isinstance(stats, SummaryStats)
            for field in ("mean", "sd", "hdi_low", "hdi_high"):
                _assert_decimal_string(getattr(stats, field), context=f"{param_name}.{field}")

    def test_diagnostics_carry_honest_single_chain_rhat(self) -> None:
        """rhat_max is None for one chain (cannot be computed; not faked)."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=80)
        result = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        assert result.diagnostics["rhat_max"] is None
        assert result.diagnostics["ess_min"] is not None and result.diagnostics["ess_min"] > 0
        assert result.diagnostics["divergences"] == 0
        assert result.diagnostics_flag == "ok"

    def test_selection_note_is_honest(self) -> None:
        """The selection note states what a posterior is NOT."""
        assert "NOT" in SELECTION_NOTE
        assert "causal" in SELECTION_NOTE.lower()
        assert "convergence" in SELECTION_NOTE.lower()
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=40)
        result = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        assert result.selection_note == SELECTION_NOTE


# ---------------------------------------------------------------------------
# Posterior predictive check
# ---------------------------------------------------------------------------


class TestPosteriorPredictiveCheck:
    """The posterior predictive check carries a decimal p-value in [0, 1]."""

    def test_ppc_fields_present_and_decimal(self) -> None:
        """The PPC fields are decimal strings with a p-value in [0, 1]."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=80)
        result = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        ppc = result.posterior_predictive_check
        assert isinstance(ppc, PosteriorPredictiveCheck)
        assert ppc.statistic == "mean"
        for field in ("observed_stat", "predictive_stat", "p_value_decimal"):
            _assert_decimal_string(getattr(ppc, field), context=f"ppc.{field}")
        p_value = float(ppc.p_value_decimal)
        assert 0.0 <= p_value <= 1.0


# ---------------------------------------------------------------------------
# Misspecified case: diagnostics flag is raised
# ---------------------------------------------------------------------------


class TestMisspecifiedCase:
    """A deliberately hard geometry raises diagnostics_flag=warn."""

    def test_misspecified_case_raises_warn_flag(self) -> None:
        """Extreme data with a tight prior yields diagnostics_flag=warn."""
        spec = build_model_spec(
            KIND_NORMAL_MEAN,
            {"mu_prior_mu": 0.0, "mu_prior_sigma": 0.01, "sigma_prior": 0.01},
        )
        data = np.array([100.0, 101.0])
        result = fit_posterior(data, spec, draws=50, tune=50, seed=_SEED, target_accept=0.3)
        assert result.diagnostics_flag == "warn"
        # At least one measurable diagnostic justifies the flag.
        assert result.divergences > 0 or (
            result.diagnostics["ess_min"] is not None and result.diagnostics["ess_min"] < ESS_FLOOR
        )


# ---------------------------------------------------------------------------
# Seed determinism
# ---------------------------------------------------------------------------


class TestSeedDeterminism:
    """Same seed + data produce identical summary statistics."""

    def test_same_seed_identical_summary(self) -> None:
        """Two fits with the same seed produce identical mu summary stats."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=80)
        r1 = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        r2 = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        assert r1.parameters["mu"].mean == r2.parameters["mu"].mean
        assert r1.parameters["mu"].sd == r2.parameters["mu"].sd
        assert r1.parameters["mu"].hdi_low == r2.parameters["mu"].hdi_low
        assert r1.parameters["mu"].hdi_high == r2.parameters["mu"].hdi_high


# ---------------------------------------------------------------------------
# Linear regression
# ---------------------------------------------------------------------------


class TestLinearRegression:
    """The linear_regression spec fits a design matrix and recovers the slope."""

    def test_linear_regression_recovers_slope(self) -> None:
        """The posterior slope is within 0.4 of the true slope 2.0."""
        spec = build_model_spec(
            KIND_LINEAR_REGRESSION,
            {"beta_prior_sigma": 10.0, "sigma_prior": 5.0},
        )
        rng = np.random.default_rng(7)
        x = rng.uniform(-3, 3, size=80)
        design = x.reshape(-1, 1)
        y = 3.0 + 2.0 * x + rng.normal(0, 1.0, size=80)
        result = fit_posterior(y, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED, design=design)
        assert "beta[x0]" in result.parameters
        assert "beta[intercept]" in result.parameters
        assert "sigma" in result.parameters
        slope = float(result.parameters["beta[x0]"].mean)
        assert abs(slope - 2.0) < 0.4

    def test_linear_regression_requires_design(self) -> None:
        """A linear_regression fit without a design matrix raises PymcAdapterError."""
        spec = build_model_spec(
            KIND_LINEAR_REGRESSION,
            {"beta_prior_sigma": 10.0, "sigma_prior": 5.0},
        )
        data = _normal_mean_data(n=30)
        with pytest.raises(PymcAdapterError):
            fit_posterior(data, spec, draws=20, tune=20, seed=_SEED)

    def test_design_row_mismatch_rejected(self) -> None:
        """A design matrix with the wrong row count raises PymcAdapterError."""
        spec = build_model_spec(
            KIND_LINEAR_REGRESSION,
            {"beta_prior_sigma": 10.0, "sigma_prior": 5.0},
        )
        data = _normal_mean_data(n=30)
        design = np.zeros((10, 1))
        with pytest.raises(PymcAdapterError):
            fit_posterior(data, spec, draws=20, tune=20, seed=_SEED, design=design)


# ---------------------------------------------------------------------------
# Resource measurement
# ---------------------------------------------------------------------------


class TestResourceMeasurement:
    """The result carries a wall-time and rss measurement."""

    def test_resource_fields_present(self) -> None:
        """The resource measurement has a decimal wall_seconds and rss_bytes."""
        spec = _normal_mean_spec()
        data = _normal_mean_data(n=40)
        result = fit_posterior(data, spec, draws=_DRAWS, tune=_TUNE, seed=_SEED)
        _assert_decimal_string(result.resource.wall_seconds, context="resource.wall_seconds")
        assert float(result.resource.wall_seconds) > 0.0
        assert isinstance(result.resource.rss_bytes, int) and result.resource.rss_bytes > 0


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


class TestVersionHelpers:
    """The version helpers return non-empty strings for the gate receipt."""

    def test_versions_are_non_empty_strings(self) -> None:
        """pymc_version, arviz_version, numpy_version return non-empty strings."""
        assert isinstance(pymc_version(), str) and pymc_version()
        assert isinstance(arviz_version(), str) and arviz_version()
        assert isinstance(numpy_version(), str) and numpy_version()


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


def test_adapter_is_only_pymc_import_site() -> None:
    """Only the adapter imports pymc, arviz, and pytensor.

    This test scans every Python file under ``src/srl`` and fails if any file
    other than the adapter imports ``pymc``, ``arviz``, or ``pytensor``. The
    adapter is the isolation boundary (ADR-0008); the rest of the SRL surface
    operates on the typed PosteriorResult, not on upstream objects.
    """
    forbidden = ("pymc", "arviz", "pytensor")
    for path in _SRC_ROOT.rglob("*.py"):
        if path == _ADAPTER_MODULE:
            continue
        imports = _imports_in_file(path, forbidden)
        assert not imports, f"{path} imports forbidden Bayesian deps: {imports}"


def test_adapter_exposed_symbols_match_public_surface() -> None:
    """The adapter module exposes the documented typed surface."""
    import srl.packs.adapters.pymc_adapter as mod  # noqa: PLC0415

    for name in (
        "ModelSpec",
        "PosteriorResult",
        "SummaryStats",
        "PosteriorPredictiveCheck",
        "ResourceMeasurement",
        "PymcAdapterError",
        "build_model_spec",
        "fit_posterior",
        "pymc_version",
        "arviz_version",
        "numpy_version",
        "REQUIRED_CHAINS",
        "SELECTION_NOTE",
    ):
        assert hasattr(mod, name), f"adapter missing public symbol {name!r}"
