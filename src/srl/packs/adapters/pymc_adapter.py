"""PyMC-backed bounded Bayesian posterior adapter (WP-H71a).

This module is the uncertainty layer for the SRL scientific fabric. It wraps
``pymc`` and ``arviz`` to fit a Bayesian posterior over a *restricted
declarative model spec* and return summary statistics, diagnostics, a posterior
predictive check, and a resource measurement. It is the P1 actual-compute
adapter for the ``pymc_arviz`` candidate (see :mod:`srl.packs.p1`): the first
first-wave candidate to graduate from a typed ``WAIT_*`` verdict into a built
adapter.

The adapter is the **only** module in the SRL tree that imports ``pymc`` or
``arviz`` (asserted by an architecture test in
``tests/packs/test_pymc_adapter.py``). Every other consumer goes through the
typed surface defined here:

- :class:`ModelSpec` -- the restricted declarative model specification. Two
  families are supported: a normal-mean model and a linear regression. The spec
  is data, not code: there is no arbitrary ``eval``, no lambdas, no callable.
- :class:`PosteriorResult` -- the frozen result of a fit, carrying summary
  statistics as SRL decimal-string policy values, diagnostics, a posterior
  predictive check, a resource measurement, and a ``selection_note``.
- :func:`fit_posterior` -- fit a posterior for a model spec and observed data.

The one-chain bounded profile
-----------------------------
The adapter runs **exactly one chain, always**. The policy rationale (see
``docs/architecture/p1-pymc.md`` and ``docs/adr/0008-pymc.md``) is to bound
compute so the profile stays within the CI budget while still producing an
honest posterior: a single chain cannot certify convergence (it cannot compute
``r_hat``), so a one-chain posterior is *selection-aware evidence*, not a
convergence certificate. A caller who asks for ``chains>1`` is refused with a
typed ``CONTRACT_INVALID`` error -- the bound is structural, not advisory.

Selection-aware interpretation
------------------------------
A fitted posterior answers "given these priors and these data, what is the
posterior over the parameters?" It does **not** answer any of:

- *Is the model correct?* (model misspecification is reported only through
  diagnostics; a green run is not a validation that the model is right).
- *Is the effect causal?* (a posterior is a conditional distribution, not an
  identification strategy; see ``docs/contracts/evidence-model.md``).
- *Has the chain converged?* (a single chain cannot compute ``r_hat``, so
  ``rhat_max`` is ``None``; convergence is not certified).

The :attr:`PosteriorResult.selection_note` states this explicitly, and
:attr:`PosteriorResult.diagnostics_flag` is ``"warn"`` whenever a measurable
diagnostic trips (divergences, or -- when a future multi-chain profile exists --
``r_hat`` above its floor or ``ess`` below its floor).

Precision policy
----------------
Summary statistics (mean, sd, HDI bounds) and the posterior-predictive p-value
are rendered as SRL decimal-string policy values
(``^-?[0-9]+(\\.[0-9]+)?$``) so they survive a serialize/parse round trip with
no float coercion. See :mod:`srl.contracts.canonical`.
"""

from __future__ import annotations

import resource as _resource
import time
import warnings
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any, Final

import arviz as az
import numpy as np
import pymc as pm

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# The typed fail reason for a posterior-contract violation. Mirrors the
# ``CONTRACT_INVALID`` entry in ``automation/fail-reasons.json``.
PYMC_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# The one-chain bounded profile pins the chain count to exactly one. This is
# structural: a caller who asks for more is refused, not silently downgraded.
REQUIRED_CHAINS: Final[int] = 1

# Hard ceilings on the sampler budget. The gate and tests stay well inside these
# bounds; they exist so a misconfigured caller cannot blow the CI budget.
MAX_DRAWS: Final[int] = 500
MAX_TUNE: Final[int] = 500

# Default target_accept. Higher values shrink step size and reduce divergence
# risk at the cost of more leapfrog steps; 0.9 is the standard robust default.
DEFAULT_TARGET_ACCEPT: Final[float] = 0.9

# The minimum data length accepted. A posterior over a degenerate (n<=1) sample
# is not meaningful; the bound keeps the adapter honest about its support.
MIN_DATA_LENGTH: Final[int] = 2

# ESS floor (effective sample size below which a measurable diagnostics flag is
# raised). With one chain r_hat is unavailable; ess is the only rank-deficiency
# signal the one-chain profile can read, so it carries this floor.
ESS_FLOOR: Final[int] = 50

# r_hat floor. A rank-normal split-r_hat above this signals non-convergence.
# Only measurable with >= 2 chains (it is None under the one-chain profile), so
# this constant is the documented trigger for a future multi-chain profile.
RHAT_FLOOR: Final[float] = 1.01

# Expected number of dimensions for a linear-regression design matrix.
_DESIGN_NDIM: Final[int] = 2

# The supported declarative model spec kinds.
KIND_NORMAL_MEAN: Final[str] = "normal_mean"
KIND_LINEAR_REGRESSION: Final[str] = "linear_regression"
_ALLOWED_KINDS: Final[frozenset[str]] = frozenset({KIND_NORMAL_MEAN, KIND_LINEAR_REGRESSION})

# Significant digits for the decimal-string rendering of summary statistics.
# Six digits is far beyond the sampling error of a one-chain profile and keeps
# the wire form compact and policy-conformant.
_SUMMARY_SIG_DIGITS: Final[int] = 6


class PymcAdapterError(ContractError):
    """Raised when a model spec, data, or policy argument violates the contract.

    Carries the typed fail reason ``CONTRACT_INVALID`` by default. Raised for: an
    unsupported model kind, a malformed spec, data of the wrong shape or length,
    a chains/draws/tune request outside the one-chain bounded profile, a missing
    seed, or a wall-time budget breach. Always raised before or during compute.
    """


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A restricted declarative Bayesian model specification.

    The spec is **data, not code**: it names a model family and supplies its
    scalar hyperparameters. There is no callable, no lambda, no arbitrary
    expression -- the adapter builds the exact PyMC model from the kind, so a
    caller cannot inject code through the spec.

    Attributes
    ----------
    kind:
        One of :data:`KIND_NORMAL_MEAN` or :data:`KIND_LINEAR_REGRESSION`.
    params:
        The scalar hyperparameters for the model family. For
        ``normal_mean``: ``mu_prior_mu``, ``mu_prior_sigma``, ``sigma_prior``.
        For ``linear_regression``: ``beta_prior_sigma``, ``sigma_prior``, and
        ``n_covariates`` (inferred from the design matrix at fit time).

    Notes
    -----
    Both families use conjugate-friendly priors (Normal for locations,
    HalfNormal for scales) so the normal-mean case has an analytic
    normal-normal reference the conformance fixtures compare against.
    """

    kind: str
    params: dict[str, float]


@dataclass(frozen=True, slots=True)
class SummaryStats:
    """Summary statistics for one model parameter, as decimal strings.

    Each value matches the SRL decimal-string policy
    (``^-?[0-9]+(\\.[0-9]+)?$``). The HDI bounds are the highest-density
    interval at the requested probability mass (default 94%).

    Attributes
    ----------
    mean, sd:
        Posterior mean and standard deviation.
    hdi_low, hdi_high:
        Highest-density interval bounds.
    """

    mean: str
    sd: str
    hdi_low: str
    hdi_high: str


@dataclass(frozen=True, slots=True)
class PosteriorPredictiveCheck:
    """A posterior predictive check.

    The observed statistic and the mean of the per-replicate predictive
    statistic are both rendered as decimal strings. The p-value is the fraction
    of replicates whose statistic is at least the observed statistic (a
    two-sided tail is not taken; this is a directional posterior-predictive
    tail probability), also as a decimal string in ``[0, 1]``.

    Attributes
    ----------
    statistic:
        The name of the test statistic used (e.g. ``"mean"``).
    observed_stat:
        The test statistic computed on the observed data (decimal string).
    predictive_stat:
        The mean of the test statistic across posterior predictive replicates
        (decimal string).
    p_value_decimal:
        The posterior-predictive tail probability (decimal string in ``[0,1]``).
    """

    statistic: str
    observed_stat: str
    predictive_stat: str
    p_value_decimal: str


@dataclass(frozen=True, slots=True)
class ResourceMeasurement:
    """The resource cost of a fit.

    Attributes
    ----------
    wall_seconds:
        Wall-clock seconds elapsed during sampling (and the predictive draw),
        rendered as a decimal string.
    rss_bytes:
        The resident-set size high-water mark in bytes, read from
        :func:`resource.getrusage` (ru_maxrss). On macOS this is in bytes; on
        Linux it is in kilobytes -- the field reports the raw ``ru_maxrss``
        value and the unit is platform-dependent, documented here honestly.
    """

    wall_seconds: str
    rss_bytes: int


@dataclass(frozen=True, slots=True)
class PosteriorResult:
    """The frozen result of a one-chain bounded posterior fit.

    Attributes
    ----------
    model_kind:
        The :attr:`ModelSpec.kind` that was fit.
    parameters:
        Mapping of parameter name to :class:`SummaryStats`.
    diagnostics:
        Mapping with ``rhat_max`` (``None`` for one chain -- ArviZ cannot
        compute it), ``ess_min`` (the minimum ``ess_bulk`` across parameters),
        and ``divergences`` (the integer divergence count).
    diagnostics_flag:
        ``"ok"`` unless a measurable diagnostic tripped, in which case
        ``"warn"``. Divergences > 0 always trip the flag; an ``ess_min`` below
        :data:`ESS_FLOOR` trips it; ``r_hat`` above 1.01 would trip it but is
        never measurable in the one-chain profile.
    divergences:
        The number of divergent transitions during sampling.
    selection_note:
        The selection-aware interpretation note (what a posterior is and is
        not). Constant across results so consumers can assert on it.
    posterior_predictive_check:
        The :class:`PosteriorPredictiveCheck` (posterior-predictive p-value).
    resource:
        The :class:`ResourceMeasurement` (wall seconds, rss bytes).
    chains:
        Always :data:`REQUIRED_CHAINS` (1). Exposed so a receipt can assert the
        one-chain profile was honored.
    draws, tune:
        The sampler dimensions actually used.
    seed:
        The integer seed the sampler was seeded with.
    """

    model_kind: str
    parameters: dict[str, SummaryStats]
    diagnostics: dict[str, Any]
    diagnostics_flag: str
    divergences: int
    selection_note: str
    posterior_predictive_check: PosteriorPredictiveCheck
    resource: ResourceMeasurement
    chains: int
    draws: int
    tune: int
    seed: int


# The selection-aware interpretation note. Identical across results so a
# consumer (gate, receipt, docs) can assert on it and so the honesty statement
# travels with every posterior. It states what a posterior IS (a conditional
# distribution over parameters given priors and data) and what it is NOT (not
# model validation, not causal identification, and -- for one chain -- not a
# convergence certificate).
SELECTION_NOTE: Final[str] = (
    "Selection-aware interpretation: this posterior is a conditional "
    "distribution over parameters given the stated priors and data. It is NOT "
    "(a) model validation -- a green run does not certify the model is "
    "correct; (b) causal identification -- a posterior is not an identification "
    "strategy; (c) a convergence certificate -- a single chain cannot compute "
    "r_hat, so convergence is not certified. Treat as proposal-only evidence."
)


# ---------------------------------------------------------------------------
# Decimal-string rendering (SRL decimal-string policy, no float coercion).
# ---------------------------------------------------------------------------


def _to_decimal_string(value: float, *, context: str) -> str:
    """Render a float to a bounded-significant-digit decimal-string policy value.

    The float is taken through :class:`decimal.Decimal` from its shortest
    round-trip ``repr``, then quantised to :data:`_SUMMARY_SIG_DIGITS`
    significant digits with round-half-up. Trailing zeros are stripped so a
    whole number renders without a trailing dot. A literal ``0`` renders as
    ``"0"``.

    Non-finite values (NaN, Inf) are rejected: they must never enter the wire
    form. ``r_hat`` under one chain is reported as ``None`` upstream rather than
    rendered here.
    """
    if not np.isfinite(value):
        msg = f"{context}: non-finite value {value!r} cannot be a decimal policy string"
        raise PymcAdapterError(msg)
    d = Decimal(str(value))
    if d == 0:
        return "0"
    ctx = Context(prec=_SUMMARY_SIG_DIGITS + 2, rounding=ROUND_HALF_UP)
    # The Decimal tuple is (sign, digits, exponent); the sign is folded back in
    # by format() below, so only digits and exponent are read here.
    _sign, digits, exponent = d.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover (guarded by isfinite)
        msg = f"{context}: non-finite Decimal reached rendering"
        raise PymcAdapterError(msg)
    first_sig_pos = len(digits) + exponent
    target_exponent = first_sig_pos - _SUMMARY_SIG_DIGITS
    quantiser = Decimal(1).scaleb(target_exponent)
    quantised = ctx.quantize(d, quantiser)
    normalised = quantised.normalize()
    rendered = format(normalised, "f")
    if rendered in {"-0", "-0.0", "+0"}:
        return "0"
    return rendered


def _p_value_to_decimal_string(p_value: float, *, context: str) -> str:
    """Render a posterior-predictive p-value to a decimal string in ``[0, 1]``.

    The p-value is a fraction of integer counts (replicates at least the
    observed statistic), so it is exactly representable; it is rendered to the
    policy precision and clamped into ``[0, 1]``. Degenerate edges (all-above
    or all-below) render as ``"0"`` or ``"1"`` exactly.
    """
    if not np.isfinite(p_value):
        msg = f"{context}: non-finite p_value {p_value!r}"
        raise PymcAdapterError(msg)
    if p_value <= 0.0:
        return "0"
    if p_value >= 1.0:
        return "1"
    return _to_decimal_string(p_value, context=context)


# ---------------------------------------------------------------------------
# Model-spec validation.
# ---------------------------------------------------------------------------


def _require_float(value: Any, field: str) -> float:
    """Validate that ``value`` is a finite real number; return it as float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"params.{field} must be a number, got {type(value).__name__}"
        raise PymcAdapterError(msg)
    f = float(value)
    if not np.isfinite(f):
        msg = f"params.{field} must be finite, got {f!r}"
        raise PymcAdapterError(msg)
    return f


def _validate_params_dict(raw: Any, kind: str) -> dict[str, Any]:
    """Validate that ``raw`` is a dict and return it as ``dict[str, Any]``.

    Accepts ``Any`` (not the typed dict) so a non-dict from an untyped caller is
    caught here with a clear :class:`PymcAdapterError` rather than a later
    ``AttributeError``. ``build_model_spec``'s annotation is ``dict[str, Any]``
    for its typed callers; this guard protects the untyped path.
    """
    if not isinstance(raw, dict):
        msg = f"{kind} params must be an object, got {type(raw).__name__}"
        raise PymcAdapterError(msg)
    return raw


def _validate_normal_mean_params(raw: dict[str, Any]) -> dict[str, float]:
    """Validate the normal_mean hyperparameters and return them as floats."""
    required = {"mu_prior_mu", "mu_prior_sigma", "sigma_prior"}
    _check_keys(set(raw.keys()), required, "normal_mean params")
    mu_prior_mu = _require_float(raw["mu_prior_mu"], "mu_prior_mu")
    mu_prior_sigma = _require_float(raw["mu_prior_sigma"], "mu_prior_sigma")
    sigma_prior = _require_float(raw["sigma_prior"], "sigma_prior")
    if mu_prior_sigma <= 0.0:
        msg = f"params.mu_prior_sigma must be > 0, got {mu_prior_sigma!r}"
        raise PymcAdapterError(msg)
    if sigma_prior <= 0.0:
        msg = f"params.sigma_prior must be > 0, got {sigma_prior!r}"
        raise PymcAdapterError(msg)
    return {
        "mu_prior_mu": mu_prior_mu,
        "mu_prior_sigma": mu_prior_sigma,
        "sigma_prior": sigma_prior,
    }


def _validate_linear_regression_params(raw: dict[str, Any]) -> dict[str, float]:
    """Validate the linear_regression hyperparameters and return them as floats."""
    required = {"beta_prior_sigma", "sigma_prior"}
    _check_keys(set(raw.keys()), required, "linear_regression params")
    beta_prior_sigma = _require_float(raw["beta_prior_sigma"], "beta_prior_sigma")
    sigma_prior = _require_float(raw["sigma_prior"], "sigma_prior")
    if beta_prior_sigma <= 0.0:
        msg = f"params.beta_prior_sigma must be > 0, got {beta_prior_sigma!r}"
        raise PymcAdapterError(msg)
    if sigma_prior <= 0.0:
        msg = f"params.sigma_prior must be > 0, got {sigma_prior!r}"
        raise PymcAdapterError(msg)
    return {"beta_prior_sigma": beta_prior_sigma, "sigma_prior": sigma_prior}


def _check_keys(actual: set[str], expected: set[str], what: str) -> None:
    """Raise PymcAdapterError if ``actual`` is missing or has extra keys."""
    missing = expected - actual
    if missing:
        msg = f"{what} missing required key(s): {sorted(missing)}"
        raise PymcAdapterError(msg)
    extra = actual - expected
    if extra:
        msg = f"{what} has unexpected key(s): {sorted(extra)}"
        raise PymcAdapterError(msg)


def build_model_spec(kind: str, params: dict[str, Any]) -> ModelSpec:
    """Build and validate a :class:`ModelSpec` from a kind and raw params.

    Parameters
    ----------
    kind:
        One of :data:`KIND_NORMAL_MEAN` or :data:`KIND_LINEAR_REGRESSION`.
    params:
        The scalar hyperparameters for the model family (see
        :class:`ModelSpec`).

    Returns
    -------
    ModelSpec
        A validated, immutable model spec.

    Raises
    ------
    PymcAdapterError
        With ``CONTRACT_INVALID`` if the kind is unsupported or the params are
        malformed (missing keys, extra keys, non-finite or non-positive scale
        parameters).
    """
    if kind not in _ALLOWED_KINDS:
        msg = f"kind {kind!r} is not supported; must be one of {sorted(_ALLOWED_KINDS)}"
        raise PymcAdapterError(msg)
    # Validate params is a dict via an Any-typed helper (not a redundant
    # isinstance on the already-typed annotation) so an untyped caller passing a
    # list/tuple gets a clear PymcAdapterError, not an AttributeError.
    params_dict = _validate_params_dict(params, kind)
    if kind == KIND_NORMAL_MEAN:
        validated = _validate_normal_mean_params(params_dict)
    else:
        validated = _validate_linear_regression_params(params_dict)
    return ModelSpec(kind=kind, params=validated)


# ---------------------------------------------------------------------------
# Data validation.
# ---------------------------------------------------------------------------


def _as_1d_float_array(value: Any, *, context: str) -> np.ndarray:
    """Convert ``value`` to a 1D finite float ndarray, rejecting bad shapes."""
    if isinstance(value, np.ndarray):
        arr = value
    elif isinstance(value, (list, tuple)):
        arr = np.asarray(value, dtype=float)
    else:
        msg = f"{context} must be a NumPy ndarray or list, got {type(value).__name__}"
        raise PymcAdapterError(msg)
    if arr.ndim != 1:
        msg = f"{context} must be 1D, got shape {arr.shape}"
        raise PymcAdapterError(msg)
    if arr.shape[0] < MIN_DATA_LENGTH:
        msg = f"{context} must have length >= {MIN_DATA_LENGTH}, got {arr.shape[0]}"
        raise PymcAdapterError(msg)
    arr = arr.astype(float, copy=False)
    if not np.all(np.isfinite(arr)):
        msg = f"{context} contains non-finite values"
        raise PymcAdapterError(msg)
    return arr


def _as_2d_float_array(value: Any, *, context: str) -> np.ndarray:
    """Convert ``value`` to a 2D finite float ndarray (a design matrix)."""
    if isinstance(value, np.ndarray):
        arr = value
    elif isinstance(value, (list, tuple)):
        arr = np.asarray(value, dtype=float)
    else:
        msg = f"{context} must be a NumPy ndarray or nested list, got {type(value).__name__}"
        raise PymcAdapterError(msg)
    if arr.ndim != _DESIGN_NDIM:
        msg = f"{context} must be 2D (n_samples, n_covariates), got shape {arr.shape}"
        raise PymcAdapterError(msg)
    if arr.shape[0] < MIN_DATA_LENGTH:
        msg = f"{context} must have >= {MIN_DATA_LENGTH} rows, got {arr.shape[0]}"
        raise PymcAdapterError(msg)
    arr = arr.astype(float, copy=False)
    if not np.all(np.isfinite(arr)):
        msg = f"{context} contains non-finite values"
        raise PymcAdapterError(msg)
    return arr


# ---------------------------------------------------------------------------
# Sampler-budget validation (the one-chain bounded profile).
# ---------------------------------------------------------------------------


def _validate_chains(chains: Any) -> int:
    """Validate that ``chains`` equals the required one-chain profile value."""
    if isinstance(chains, bool) or not isinstance(chains, int):
        msg = f"chains must be an integer, got {type(chains).__name__}"
        raise PymcAdapterError(msg)
    if chains != REQUIRED_CHAINS:
        msg = (
            f"chains must be {REQUIRED_CHAINS} (the one-chain bounded profile); "
            f"got {chains}. A single chain cannot certify convergence, so "
            "multi-chain requests are refused -- see docs/architecture/p1-pymc.md."
        )
        raise PymcAdapterError(msg)
    return chains


def _validate_budget(draws: Any, tune: Any) -> tuple[int, int]:
    """Validate and clamp ``draws``/``tune`` to the hard ceilings."""
    if isinstance(draws, bool) or not isinstance(draws, int):
        msg = f"draws must be an integer, got {type(draws).__name__}"
        raise PymcAdapterError(msg)
    if isinstance(tune, bool) or not isinstance(tune, int):
        msg = f"tune must be an integer, got {type(tune).__name__}"
        raise PymcAdapterError(msg)
    if draws <= 0:
        msg = f"draws must be > 0, got {draws!r}"
        raise PymcAdapterError(msg)
    if tune < 0:
        msg = f"tune must be >= 0, got {tune!r}"
        raise PymcAdapterError(msg)
    if draws > MAX_DRAWS:
        msg = f"draws={draws} exceeds the one-chain profile ceiling {MAX_DRAWS}"
        raise PymcAdapterError(msg)
    if tune > MAX_TUNE:
        msg = f"tune={tune} exceeds the one-chain profile ceiling {MAX_TUNE}"
        raise PymcAdapterError(msg)
    return draws, tune


def _validate_seed(seed: Any) -> int:
    """Validate that an explicit integer seed was supplied (required)."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        msg = f"seed must be an integer, got {type(seed).__name__}"
        raise PymcAdapterError(msg)
    if seed < 0:
        msg = f"seed must be non-negative, got {seed!r}"
        raise PymcAdapterError(msg)
    return seed


# ---------------------------------------------------------------------------
# Model construction. The spec is data; the model is built here, not by the
# caller, so no arbitrary code enters the sampler.
# ---------------------------------------------------------------------------


def _build_pymc_model(
    spec: ModelSpec,
    observed: np.ndarray,
    design: np.ndarray | None,
) -> tuple[Any, list[str]]:
    """Build the PyMC model for the spec and return (model, param_names).

    ``param_names`` is the canonical ordering of the model's stochastic
    parameters (the variables summary statistics are reported for).
    """
    if spec.kind == KIND_NORMAL_MEAN:
        p = spec.params
        with pm.Model() as model:
            mu = pm.Normal("mu", mu=p["mu_prior_mu"], sigma=p["mu_prior_sigma"])
            sigma = pm.HalfNormal("sigma", sigma=p["sigma_prior"])
            pm.Normal("obs", mu=mu, sigma=sigma, observed=observed)
        return model, ["mu", "sigma"]

    # KIND_LINEAR_REGRESSION. An intercept column is prepended so the design
    # the caller passes is the covariate block only; beta[0] is the intercept.
    # ``fit_posterior`` validates design is non-None for this branch before the
    # call; the guard here narrows the type for the reader and for mypy.
    if design is None:  # pragma: no cover (invariant: caller validated design)
        msg = "linear_regression requires a design matrix"
        raise PymcAdapterError(msg)
    n_covariates = design.shape[1]
    p = spec.params
    coords = {"covariate": [f"x{i}" for i in range(n_covariates)] + ["intercept"]}
    with pm.Model(coords=coords) as model:
        beta = pm.Normal("beta", mu=0.0, sigma=p["beta_prior_sigma"], dims="covariate")
        sigma = pm.HalfNormal("sigma", sigma=p["sigma_prior"])
        # Design with an intercept column prepended.
        design_with_intercept = np.column_stack([design, np.ones(design.shape[0])])
        mu_obs = pm.math.dot(design_with_intercept, beta)
        pm.Normal("obs", mu=mu_obs, sigma=sigma, observed=observed)
    names = [f"beta[{i}]" for i in range(n_covariates)] + ["beta[intercept]", "sigma"]
    return model, names


def _flatten_param_names(idata: Any, spec: ModelSpec) -> list[str]:
    """Return the canonical parameter names reported in the summary.

    For the normal-mean model these are ``mu`` and ``sigma``. For the linear
    regression the ``beta`` vector is flattened into per-coordinate names
    (``beta[x0]``, ..., ``beta[intercept]``) and ``sigma``.
    """
    posterior = idata.posterior
    if spec.kind == KIND_NORMAL_MEAN:
        return ["mu", "sigma"]
    # Linear regression: beta is a dims variable; flatten in coordinate order.
    beta_coords = list(posterior.beta.coords["covariate"].values)
    names = [f"beta[{c}]" for c in beta_coords]
    names.append("sigma")
    return names


# ---------------------------------------------------------------------------
# Diagnostics.
# ---------------------------------------------------------------------------


def _compute_rhat(idata: Any) -> float | None:
    """Return max r_hat across parameters, or None if it cannot be computed.

    With one chain ArviZ returns NaN for r_hat (it needs >= 2 chains). We
    surface this honestly as ``None`` rather than fabricating a value: a single
    chain cannot certify convergence.
    """
    try:
        summary = az.rhat(idata)
    except Exception:  # pragma: no cover (defensive; arviz warns + returns NaN)
        return None
    values: list[float] = []
    for var in summary.data_vars:
        arr = np.asarray(summary[var].values, dtype=float).ravel()
        values.extend(float(v) for v in arr if np.isfinite(v))
    if not values:
        return None
    return float(np.max(values))


def _compute_ess_min(idata: Any) -> float | None:
    """Return the minimum ess_bulk across parameters, or None if unavailable."""
    try:
        summary = az.ess(idata, method="bulk")
    except Exception:  # pragma: no cover (defensive)
        return None
    values: list[float] = []
    for var in summary.data_vars:
        arr = np.asarray(summary[var].values, dtype=float).ravel()
        values.extend(float(v) for v in arr if np.isfinite(v))
    if not values:
        return None
    return float(np.min(values))


def _compute_divergences(idata: Any) -> int:
    """Return the number of divergent transitions recorded in sample_stats."""
    try:
        stats = idata.sample_stats
        if "diverging" in stats:
            return int(np.asarray(stats["diverging"].values).sum())
    except Exception:  # noqa: S110, pragma: no cover (absent divergences field -> 0)
        # sample_stats/diverging is always present for a NUTS run; the bare pass
        # is intentional: a structurally absent field is reported as 0
        # divergences, never as a hard error.
        pass
    return 0


def _resolve_diagnostics_flag(
    rhat_max: float | None,
    ess_min: float | None,
    divergences: int,
) -> str:
    """Return ``"ok"`` or ``"warn"`` based on the measurable diagnostics."""
    if divergences > 0:
        return "warn"
    if rhat_max is not None and rhat_max > RHAT_FLOOR:
        return "warn"
    if ess_min is not None and ess_min < ESS_FLOOR:
        return "warn"
    return "ok"


def _build_summary_stats(
    idata: Any, model_spec: ModelSpec, hdi_prob: float
) -> dict[str, SummaryStats]:
    """Build the per-parameter decimal-string summary stats from the posterior.

    Reads the ArviZ summary frame and renders mean/sd/HDI bounds to SRL
    decimal-string policy values. Raises :class:`PymcAdapterError` if a parameter
    is missing from the summary or a value is non-finite.
    """
    param_names = _flatten_param_names(idata, model_spec)
    # ArviZ's summary is a pandas DataFrame whose .loc indexer mypy types
    # narrowly (it expects a Mapping); the adapter treats it as opaque Any so
    # the scalar-name indexing reads cleanly.
    summary_df: Any = az.summary(idata, hdi_prob=hdi_prob)
    hdi_low_col = _hdi_low_col(summary_df)
    hdi_high_col = _hdi_high_col(summary_df)
    parameters: dict[str, SummaryStats] = {}
    for name in param_names:
        row = summary_df.loc[_posterior_var_for_summary(name, summary_df)]
        parameters[name] = SummaryStats(
            mean=_to_decimal_string(float(row["mean"]), context=f"{name}.mean"),
            sd=_to_decimal_string(float(row["sd"]), context=f"{name}.sd"),
            hdi_low=_to_decimal_string(float(row[hdi_low_col]), context=f"{name}.hdi_low"),
            hdi_high=_to_decimal_string(float(row[hdi_high_col]), context=f"{name}.hdi_high"),
        )
    return parameters


def _build_ppc_check(observed: np.ndarray, ppc: dict[str, Any]) -> PosteriorPredictiveCheck:
    """Build the posterior predictive check (test statistic = mean of response).

    The p-value is the fraction of replicates whose mean is at least the observed
    mean (a directional posterior-predictive tail probability). All values are
    rendered to SRL decimal-string policy values.
    """
    observed_stat = float(np.mean(observed))
    pred = np.asarray(ppc["obs"]).reshape(-1, observed.shape[0])
    pred_means = pred.mean(axis=1)
    predictive_stat = float(np.mean(pred_means))
    p_value = float(np.mean(pred_means >= observed_stat))
    return PosteriorPredictiveCheck(
        statistic="mean",
        observed_stat=_to_decimal_string(observed_stat, context="ppc.observed_stat"),
        predictive_stat=_to_decimal_string(predictive_stat, context="ppc.predictive_stat"),
        p_value_decimal=_p_value_to_decimal_string(p_value, context="ppc.p_value"),
    )


# ---------------------------------------------------------------------------
# Public API: fit_posterior.
# ---------------------------------------------------------------------------


def fit_posterior(  # noqa: PLR0913 (the kw-only set IS the bounded profile's config surface)
    data: Any,
    model_spec: ModelSpec,
    *,
    draws: int = 200,
    tune: int = 200,
    chains: int = REQUIRED_CHAINS,
    seed: int,
    max_wall: float = 120.0,
    target_accept: float = DEFAULT_TARGET_ACCEPT,
    design: Any = None,
    hdi_prob: float = 0.94,
    seed_predictive: int | None = None,
) -> PosteriorResult:
    """Fit a one-chain bounded Bayesian posterior and return its result.

    Parameters
    ----------
    data:
        The observed data. A 1D array-like of finite reals (the response for
        the normal-mean model, or the response vector for linear regression).
    model_spec:
        A validated :class:`ModelSpec` (built via :func:`build_model_spec`).
    draws:
        Posterior draws per chain. Must be in ``[1, 500]``. Default 200.
    tune:
        Tuning (warmup) iterations. Must be in ``[0, 500]``. Default 200.
    chains:
        **Must be 1.** The one-chain bounded profile refuses multi-chain
        requests with ``CONTRACT_INVALID`` (a single chain cannot certify
        convergence; the bound is structural, not advisory).
    seed:
        Required non-negative integer seed for the sampler. Same seed + same
        data produce the same posterior (determinism is asserted by the gate).
    max_wall:
        Wall-clock budget in seconds. If sampling exceeds it, a
        :class:`PymcAdapterError` is raised. Default 120.
    target_accept:
        NUTS target acceptance. Default 0.9.
    design:
        For linear regression: the ``(n_samples, n_covariates)`` design matrix.
        Ignored for the normal-mean model.
    hdi_prob:
        Highest-density-interval probability mass for the summary. Default 0.94.
    seed_predictive:
        Seed for the posterior predictive draw. Defaults to ``seed``.

    Returns
    -------
    PosteriorResult
        The frozen result with summary stats (decimal strings), diagnostics,
        a posterior predictive check, resource measurement, and the
        selection-aware note.

    Raises
    ------
    PymcAdapterError
        With ``CONTRACT_INVALID`` for any contract violation: unsupported kind,
        bad data shape/length, ``chains != 1``, draws/tune out of bounds,
        missing seed, wall-budget breach, or a non-finite summary statistic.

    Notes
    -----
    The result is **selection-aware evidence**, not validation, not causal
    identification, and -- because the profile runs one chain -- not a
    convergence certificate. See :data:`SELECTION_NOTE`.
    """
    # Validate everything before touching the sampler (fail-fast contract).
    observed = _as_1d_float_array(data, context="data")
    validated_chains = _validate_chains(chains)
    draws_v, tune_v = _validate_budget(draws, tune)
    seed_v = _validate_seed(seed)
    if not 0.0 < hdi_prob < 1.0:
        msg = f"hdi_prob must be in (0, 1), got {hdi_prob!r}"
        raise PymcAdapterError(msg)
    if not 0.0 < target_accept <= 1.0:
        msg = f"target_accept must be in (0, 1], got {target_accept!r}"
        raise PymcAdapterError(msg)
    if max_wall <= 0.0:
        msg = f"max_wall must be > 0, got {max_wall!r}"
        raise PymcAdapterError(msg)

    design_arr: np.ndarray | None = None
    if model_spec.kind == KIND_LINEAR_REGRESSION:
        if design is None:
            msg = "linear_regression requires a design matrix"
            raise PymcAdapterError(msg)
        design_arr = _as_2d_float_array(design, context="design")
        if design_arr.shape[0] != observed.shape[0]:
            msg = (
                f"design rows ({design_arr.shape[0]}) must match data length ({observed.shape[0]})"
            )
            raise PymcAdapterError(msg)

    seed_pred = seed_predictive if seed_predictive is not None else seed_v

    # Suppress the one-chain NUTS warnings (expected) and ArviZ shape-check
    # warnings (r_hat needs 2 chains by design). The honesty is carried by the
    # diagnostics fields, not by stdout. The warnings are still routed through
    # the logging system; only the noisy stderr/text progress is suppressed.
    model, _names = _build_pymc_model(model_spec, observed, design_arr)

    rss_before = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
    t0 = time.perf_counter()
    with _suppress_pymc_warnings():
        idata = pm.sample(
            model=model,
            draws=draws_v,
            tune=tune_v,
            chains=validated_chains,
            cores=validated_chains,
            random_seed=seed_v,
            progressbar=False,
            target_accept=target_accept,
            return_inferencedata=True,
        )
    wall_sample = time.perf_counter() - t0
    if wall_sample > max_wall:
        msg = f"sampling wall time {wall_sample:.1f}s exceeded max_wall {max_wall:.1f}s"
        raise PymcAdapterError(msg)

    # Posterior predictive draw for the p-value check.
    with _suppress_pymc_warnings():
        ppc = pm.sample_posterior_predictive(
            idata,
            model=model,
            var_names=["obs"],
            random_seed=seed_pred,
            progressbar=False,
            return_inferencedata=False,
        )
    wall_total = time.perf_counter() - t0
    rss_after = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
    rss_high = max(rss_before, rss_after)

    parameters = _build_summary_stats(idata, model_spec, hdi_prob)
    rhat_max = _compute_rhat(idata)
    ess_min = _compute_ess_min(idata)
    divergences = _compute_divergences(idata)
    diagnostics_flag = _resolve_diagnostics_flag(rhat_max, ess_min, divergences)
    ppc_check = _build_ppc_check(observed, ppc)

    return PosteriorResult(
        model_kind=model_spec.kind,
        parameters=parameters,
        diagnostics={
            "rhat_max": rhat_max,
            "ess_min": ess_min,
            "divergences": divergences,
        },
        diagnostics_flag=diagnostics_flag,
        divergences=divergences,
        selection_note=SELECTION_NOTE,
        posterior_predictive_check=ppc_check,
        resource=ResourceMeasurement(
            wall_seconds=_to_decimal_string(wall_total, context="resource.wall_seconds"),
            rss_bytes=int(rss_high),
        ),
        chains=validated_chains,
        draws=draws_v,
        tune=tune_v,
        seed=seed_v,
    )


def _posterior_var_for_summary(name: str, summary_df: Any) -> str:
    """Map a flattened parameter name to its row label in the ArviZ summary.

    For scalar parameters (``mu``, ``sigma``) the label is the name itself. For
    a flattened beta component (``beta[x0]``) the ArviZ summary indexes it as
    ``beta[x0]``; we verify the label exists and return it.
    """
    if name in summary_df.index:
        return name
    msg = f"parameter {name!r} not found in posterior summary index {list(summary_df.index)!r}"
    raise PymcAdapterError(msg)


def _hdi_low_col(summary_df: Any) -> str:
    """Return the HDI lower-bound column name present in the summary frame."""
    for candidate in ("hdi_3%", "hdi_2.5%"):
        if candidate in summary_df.columns:
            return candidate
    msg = f"no HDI lower-bound column found in summary columns {list(summary_df.columns)!r}"
    raise PymcAdapterError(msg)


def _hdi_high_col(summary_df: Any) -> str:
    """Return the HDI upper-bound column name present in the summary frame."""
    for candidate in ("hdi_97%", "hdi_97.5%"):
        if candidate in summary_df.columns:
            return candidate
    msg = f"no HDI upper-bound column found in summary columns {list(summary_df.columns)!r}"
    raise PymcAdapterError(msg)


# ---------------------------------------------------------------------------
# Warning suppression context.
# ---------------------------------------------------------------------------


class _suppress_pymc_warnings:
    """Suppress the expected one-chain NUTS / ArviZ shape-check warnings.

    A single chain legitimately cannot compute ``r_hat``; PyMC and ArviZ emit
    user-facing warnings about this on every run. The honesty is carried by the
    diagnostics fields (``rhat_max`` is ``None``), not by the warning text, so
    we silence the noise so a gate or test run does not drown in warnings. The
    context is narrow: it suppresses only ``warnings`` during the block.
    """

    def __enter__(self) -> _suppress_pymc_warnings:
        self._ctx = warnings.catch_warnings()
        self._ctx.__enter__()
        warnings.simplefilter("ignore")
        return self

    def __exit__(self, *exc: object) -> None:
        self._ctx.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Version evidence helpers (for the gate receipt).
# ---------------------------------------------------------------------------


def pymc_version() -> str:
    """Return the resolved PyMC version string (for gate evidence)."""
    return str(pm.__version__)


def arviz_version() -> str:
    """Return the resolved ArviZ version string (for gate evidence)."""
    return str(az.__version__)


def numpy_version() -> str:
    """Return the resolved NumPy version string (for gate evidence)."""
    return str(np.__version__)


__all__ = [
    "DEFAULT_TARGET_ACCEPT",
    "ESS_FLOOR",
    "KIND_LINEAR_REGRESSION",
    "KIND_NORMAL_MEAN",
    "MAX_DRAWS",
    "MAX_TUNE",
    "MIN_DATA_LENGTH",
    "PYMC_FAIL_REASON",
    "REQUIRED_CHAINS",
    "SELECTION_NOTE",
    "ModelSpec",
    "PosteriorPredictiveCheck",
    "PosteriorResult",
    "PymcAdapterError",
    "ResourceMeasurement",
    "SummaryStats",
    "arviz_version",
    "build_model_spec",
    "fit_posterior",
    "numpy_version",
    "pymc_version",
]
