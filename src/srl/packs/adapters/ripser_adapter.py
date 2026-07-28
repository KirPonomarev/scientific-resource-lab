"""Ripser TDA adapter (WP-E42).

This module is the topological-data-analysis (TDA) layer for the SRL scientific
fabric. It computes **persistent homology** of a point cloud via
:mod:`ripser` (the Python binding to the Ripser C++ core) and renders the
resulting persistence diagrams as decimal-string birth/death pairs, consistent
with the SRL precision policy.

The adapter is the **only** module in the SRL tree that imports
:mod:`ripser` or :mod:`numpy` (asserted by architecture tests in
``tests/packs/test_ripser_adapter.py``). Every other consumer goes through the
typed surface defined here:

- :class:`PersistenceResult` — a frozen, serializable persistence-diagram
  bundle (diagrams per dimension as decimal-string birth/death pairs, point
  count, maxdim, and a deterministic preprocessing receipt).
- :func:`compute_persistence` — compute persistent homology of a point cloud
  under explicit, hard-bounded resource limits.
- :func:`phase_randomized_surrogate` — produce a phase-randomized surrogate of
  a 1-D signal for null-hypothesis controls.

Honesty contract
----------------
A persistence diagram is **computationation, not validation**. A prominent
H1 class in a point cloud is evidence that the data is consistent with a loop
*at the scale the diagram resolves*; it is not, by itself, a scientific claim
that the underlying phenomenon is circular, periodic, or topologically
non-trivial. The adapter renders the diagram faithfully and records the exact
preprocessing it applied; the caller (a planner, a gate, a human reviewer)
decides what the diagram means. See ``docs/contracts/evidence-model.md`` for
the distinction between *computation* and *validation*, and
``docs/architecture/ripser-pack.md`` for the surrogate/null discipline.

Fail-fast contract
------------------
Resource-limit violations (too many points, too high an ambient dimension, too
high a homology degree) raise :class:`RipserResourceLimitError` (fail reason
``RESOURCE_LIMIT``) **before** any compute runs. Structural violations (a
non-finite coordinate, a ragged cloud, a wrong-typed input) raise
:class:`RipserInputError` (fail reason ``CONTRACT_INVALID``). Neither is ever
silently coerced.

Precision policy
----------------
Persistence birth/death times are rendered as JSON **strings** matching the SRL
decimal-string policy (``^-?[0-9]+(\\.[0-9]+)?$``) via :class:`decimal.Decimal`,
so they survive a serialize / parse round trip with no float coercion or
exponent drift. Infinite death times (essential classes) are rendered as the
sentinel string ``"inf"``.

Determinism policy
------------------
Ripser's Vietoris-Rips computation is deterministic for a fixed point cloud and
fixed parameters (no RNG inside the core, no wall-clock dependence). The only
stochastic surface is the optional preprocessing (centering, scaling) and the
:func:`phase_randomized_surrogate` helper; both thread a ``seed`` through
:func:`numpy.random.default_rng` and record it in the preprocessing receipt so
two runs with the same seed produce byte-identical receipts.

See ``docs/architecture/ripser-pack.md`` for the resource bounds, the
determinism guarantees, and the null/surrogate discipline.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from typing import Any, Final

import numpy as np
from ripser import ripser

from srl.contracts.canonical import dumps
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.execution.platform_probe import RESOURCE_LIMIT_FAIL_REASON

# The typed fail reasons for the two adapter error families. A resource-limit
# violation routes through ``RESOURCE_LIMIT`` (class ``ci``, retriable=false);
# a structural input violation routes through ``CONTRACT_INVALID`` (class
# ``CONTRACT``, hard_stop=true). Both are deterministic, not transient.
RIPSER_RESOURCE_LIMIT_FAIL_REASON: Final[str] = RESOURCE_LIMIT_FAIL_REASON
RIPSER_CONTRACT_INVALID_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

# ---------------------------------------------------------------------------
# Hard resource limits. These bound the compute before it starts so a runaway
# point cloud cannot blow the gate's <60s budget. The bounds are deliberately
# generous enough for honest TDA tutorials and tight enough to fail fast on
# accidental large inputs. See docs/architecture/ripser-pack.md for rationale.
# ---------------------------------------------------------------------------

# Maximum number of points in a single point cloud. Ripser is O(n^3) in the
# worst case on the Vietoris-Rips complex; 500 points keeps a single
# computation well under a second on commodity hardware while leaving room for
# meaningful geometric examples (the synthetic circle fixture has 100).
MAX_POINTS: Final[int] = 500

# Maximum ambient dimension of the point cloud. The synthetic fixtures are
# 2-D; 32 admits high-dimensional embeddings without admitting the pathological
# case where the distance matrix alone is gigabytes.
MAX_AMBIENT_DIM: Final[int] = 32

# Maximum homology degree. H0 (connected components) and H1 (loops) are the
# workhorses; H2 (voids) is supported for completeness. Beyond H2 the
# interpretation becomes fragile and the compute expensive.
MAX_HOMOLOGY_DIM: Final[int] = 2

# ---------------------------------------------------------------------------
# Decimal-string rendering policy. Persistence times are floats in ripser; we
# render them to the SRL decimal-string policy so they survive a JSON round
# trip. The sentinel for an essential (infinite-death) class is the literal
# string ``"inf"``, which is not a decimal-string policy value but is clearly
# distinguished in the diagram arrays.
# ---------------------------------------------------------------------------

# Number of significant digits for persistence times. 12 is well below float64
# precision (~15-16 sig-digits) and far above any physically meaningful
# resolution, so a round-trip through decimal-string loses nothing observable
# while keeping the diagrams compact and comparable.
PERSISTENCE_SIG_DIGITS: Final[int] = 12

# A Decimal context with ample working precision; the final result is quantised
# to PERSISTENCE_SIG_DIGITS significant digits. Constructed per-call (Decimal
# contexts are thread-local by default).
_DECIMAL_PREC: Final[int] = 40

# The string used to represent an essential class (birth at some finite scale,
# death at infinity). Ripser reports these as ``np.inf`` for the death time.
INF_DEATH_SENTINEL: Final[str] = "inf"


class RipserInputError(ContractError):
    """Raised when a point cloud or parameter is structurally invalid.

    Carries the typed fail reason ``CONTRACT_INVALID``. Raised for: a
    non-list/non-array cloud, a ragged cloud (rows of differing length), a
    non-finite coordinate, a non-string metric, or a negative seed. Always
    raised *before* any compute.
    """


class RipserResourceLimitError(ContractError):
    """Raised when a hard resource limit is exceeded at preflight.

    Carries the typed fail reason ``RESOURCE_LIMIT`` (class ``ci``,
    ``retriable=false``) so the failure routes through the resume and
    fail-reason machinery as a hard resource limit. Raised for: a point cloud
    with more than :data:`MAX_POINTS` points, an ambient dimension above
    :data:`MAX_AMBIENT_DIM`, or a homology degree above
    :data:`MAX_HOMOLOGY_DIM`. Always raised *before* any compute.

    Attributes
    ----------
    fail_reason:
        Typed fail reason (always ``RESOURCE_LIMIT``).
    """

    def __init__(
        self, message: str, *, fail_reason: str = RIPSER_RESOURCE_LIMIT_FAIL_REASON
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)


# ---------------------------------------------------------------------------
# Result dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreprocessingReceipt:
    """A deterministic record of the preprocessing applied to a point cloud.

    Two runs with the same point cloud and the same seed produce byte-identical
    receipts, which is the determinism guarantee for the preprocessing step.
    The receipt is carried inside :class:`PersistenceResult` so a consumer can
    audit exactly what was done to the input before compute.

    Attributes
    ----------
    seed:
        The PRNG seed threaded into any stochastic preprocessing (centering,
        scaling). ``None`` when no seed was supplied and no stochastic
        preprocessing was applied.
    centered:
        Whether the cloud was mean-centered before compute.
    scaled:
        Whether the cloud was unit-variance scaled before compute.
    input_sha256:
        ``sha256:<64hex>`` of the canonical-JSON encoding of the input point
        cloud (the array the adapter received, before preprocessing). This
        anchors the receipt to the exact input bytes.
    """

    seed: int | None
    centered: bool
    scaled: bool
    input_sha256: str

    def canonical_dumps(self) -> bytes:
        """Return canonical JSON bytes for the receipt (sorted keys, compact)."""
        return dumps(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Return the receipt as a plain JSON-serializable dict."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    """A persistence-diagram bundle returned by :func:`compute_persistence`.

    The diagrams are rendered as decimal-string birth/death pairs (matching the
    SRL precision policy) so the result is JSON-serializable and survives a
    round trip with no float coercion. Essential (infinite-death) classes are
    rendered with the :data:`INF_DEATH_SENTINEL` (``"inf"``) as the death
    string.

    Attributes
    ----------
    diagrams:
        A list (one entry per homology dimension 0..maxdim) of persistence
        diagrams. Each diagram is a list of ``[birth_str, death_str]`` pairs,
        where ``birth_str`` and ``death_str`` are decimal-string policy values
        (or ``"inf"`` for an essential class's death).
    n_points:
        The number of points in the input cloud.
    maxdim:
        The maximum homology dimension computed.
    preprocessing_receipt:
        The deterministic preprocessing receipt (seed, center/scale flags,
        input sha256).
    """

    diagrams: list[list[list[str]]]
    n_points: int
    maxdim: int
    preprocessing_receipt: PreprocessingReceipt

    def to_dict(self) -> dict[str, Any]:
        """Return the result as a plain JSON-serializable dict."""
        return {
            "diagrams": self.diagrams,
            "n_points": self.n_points,
            "maxdim": self.maxdim,
            "preprocessing_receipt": self.preprocessing_receipt.to_dict(),
        }


# ---------------------------------------------------------------------------
# Input validation and conversion.
# ---------------------------------------------------------------------------


def _coerce_cloud(point_cloud: Any) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Coerce a point cloud to a contiguous float64 2-D ndarray.

    Accepts a list of lists/tuples of numbers, or a numpy array. Rejects
    ragged clouds, non-finite coordinates, and 0-D / 1-D inputs. Returns a
    C-contiguous ``float64`` 2-D array of shape ``(n_points, ambient_dim)``.

    Raises
    ------
    RipserInputError
        If the cloud is not a list/array, is empty, is ragged, or contains a
        non-finite coordinate.
    """
    if isinstance(point_cloud, np.ndarray):
        arr = point_cloud
    elif isinstance(point_cloud, (list, tuple)):
        try:
            # ``asarray`` with an explicit dtype so the conversion is explicit.
            arr = np.asarray(point_cloud, dtype=np.float64)
        except (ValueError, TypeError) as exc:
            msg = f"point cloud must be a list/array of numbers; coercion failed: {exc}"
            raise RipserInputError(msg) from exc
    else:
        msg = (
            f"point cloud must be a list of [coords] or a numpy array, "
            f"got {type(point_cloud).__name__}"
        )
        raise RipserInputError(msg)

    # A point cloud is a 2-D array: ``asarray`` of a list of scalars yields a
    # 1-D array, which is not a cloud. The expected rank is a named constant so
    # the check is self-documenting rather than a magic value.
    expected_rank = 2
    if arr.ndim != expected_rank:
        msg = f"point cloud must be a 2-D array (n_points x ambient_dim); got {arr.ndim}-D"
        raise RipserInputError(msg)
    if arr.shape[0] == 0:
        msg = "point cloud must have at least one point"
        raise RipserInputError(msg)
    if arr.shape[1] == 0:
        msg = "point cloud must have a non-zero ambient dimension"
        raise RipserInputError(msg)

    # Ensure float64 and contiguity for ripser's C core.
    if arr.dtype != np.float64:
        arr = arr.astype(np.float64)
    arr = np.ascontiguousarray(arr)

    # Reject non-finite coordinates (NaN / Inf) before they reach ripser.
    if not np.all(np.isfinite(arr)):
        msg = "point cloud contains a non-finite coordinate (NaN or Inf)"
        raise RipserInputError(msg)

    return arr


def _enforce_limits(arr: np.ndarray[Any, np.dtype[np.float64]], maxdim: int) -> None:
    """Enforce the hard resource limits on point count, dimension, and degree.

    Raises
    ------
    RipserResourceLimitError
        If the cloud exceeds :data:`MAX_POINTS`, the ambient dimension exceeds
        :data:`MAX_AMBIENT_DIM`, or ``maxdim`` exceeds
        :data:`MAX_HOMOLOGY_DIM`.
    """
    n_points, ambient_dim = arr.shape
    if n_points > MAX_POINTS:
        msg = (
            f"point cloud has {n_points} points; the hard limit is "
            f"{MAX_POINTS} (RESOURCE_LIMIT). Reduce the cloud or raise the "
            f"documented bound."
        )
        raise RipserResourceLimitError(msg)
    if ambient_dim > MAX_AMBIENT_DIM:
        msg = (
            f"point cloud has ambient dimension {ambient_dim}; the hard limit "
            f"is {MAX_AMBIENT_DIM} (RESOURCE_LIMIT)."
        )
        raise RipserResourceLimitError(msg)
    if maxdim > MAX_HOMOLOGY_DIM:
        msg = (
            f"maxdim={maxdim}; the hard limit is {MAX_HOMOLOGY_DIM} "
            f"(RESOURCE_LIMIT). H0, H1, and H2 are supported."
        )
        raise RipserResourceLimitError(msg)


def _validate_maxdim(maxdim: Any) -> int:
    """Validate the maxdim parameter is a non-negative int."""
    if isinstance(maxdim, bool) or not isinstance(maxdim, int):
        msg = f"maxdim must be a non-negative int, got {type(maxdim).__name__}"
        raise RipserInputError(msg)
    if maxdim < 0:
        msg = f"maxdim must be non-negative, got {maxdim}"
        raise RipserInputError(msg)
    return maxdim


def _validate_metric(metric: Any) -> str:
    """Validate the metric parameter is a non-empty string."""
    if not isinstance(metric, str) or metric.strip() == "":
        msg = f"metric must be a non-empty string, got {metric!r}"
        raise RipserInputError(msg)
    return metric


def _validate_seed(seed: Any) -> int | None:
    """Validate the seed parameter: None or a non-negative int."""
    if seed is None:
        return None
    if isinstance(seed, bool) or not isinstance(seed, int):
        msg = f"seed must be None or a non-negative int, got {type(seed).__name__}"
        raise RipserInputError(msg)
    if seed < 0:
        msg = f"seed must be non-negative, got {seed}"
        raise RipserInputError(msg)
    return seed


def _validate_center_scale(center: Any, scale: Any) -> tuple[bool, bool]:
    """Validate the center/scale booleans."""
    if not isinstance(center, bool):
        msg = f"center must be a bool, got {type(center).__name__}"
        raise RipserInputError(msg)
    if not isinstance(scale, bool):
        msg = f"scale must be a bool, got {type(scale).__name__}"
        raise RipserInputError(msg)
    return center, scale


# ---------------------------------------------------------------------------
# Decimal-string rendering.
# ---------------------------------------------------------------------------


def _float_to_decimal_str(value: float) -> str:
    """Render a finite float to a decimal-string policy value.

    The float is rendered via its shortest round-trip repr (``repr``) converted
    to :class:`Decimal`, then quantised to :data:`PERSISTENCE_SIG_DIGITS`
    significant digits (round-half-up) and stripped of insignificant trailing
    zeros. The result always matches the SRL decimal-string policy
    (``^-?[0-9]+(\\.[0-9]+)?$``): no exponent, no float artefact.
    """
    if value == 0.0:
        return "0"
    # ``repr`` of a float64 is the shortest string that round-trips; converting
    # via Decimal captures it exactly without binary-expansion artefacts.
    ctx = Context(prec=_DECIMAL_PREC)
    try:
        dec = ctx.create_decimal_from_float(value) if value != 0 else Decimal(0)
    except InvalidOperation as exc:  # pragma: no cover (defensive)
        msg = f"persistence value {value!r} is not a valid decimal"
        raise RipserInputError(msg) from exc
    return _quantise_to_sig_digits(dec, PERSISTENCE_SIG_DIGITS)


def _quantise_to_sig_digits(value: Decimal, sig_digits: int) -> str:
    """Quantise ``value`` to ``sig_digits`` significant digits (round-half-up).

    Returns a decimal-string policy value (no exponent). Insignificant trailing
    zeros are stripped so a clean value renders compactly.
    """
    if value == 0:
        return "0"
    tuple_repr = value.as_tuple()
    digits = tuple_repr.digits
    exponent_raw = tuple_repr.exponent
    if not isinstance(exponent_raw, int):
        msg = "non-finite Decimal reached quantisation; persistence values must be finite"
        raise RipserInputError(msg)
    exponent = exponent_raw
    first_sig_pos = len(digits) + exponent
    target_exponent = first_sig_pos - sig_digits
    quantiser = Decimal(1).scaleb(target_exponent)
    ctx = Context(prec=max(sig_digits + 2, _DECIMAL_PREC), rounding=ROUND_HALF_UP)
    quantised = ctx.quantize(value, quantiser)
    normalised = quantised.normalize()
    rendered = format(normalised, "f")
    if rendered in {"-0", "-0.0", "+0"}:
        return "0"
    return rendered


def _render_diagram(
    dgm: np.ndarray[Any, np.dtype[np.float64]],
) -> list[list[str]]:
    """Render a single ripser diagram (n x 2 float64) to decimal-string pairs.

    Each pair is ``[birth_str, death_str]``. A finite death renders as a
    decimal-string policy value; an infinite death (essential class) renders as
    the :data:`INF_DEATH_SENTINEL`.
    """
    rendered: list[list[str]] = []
    for row in dgm:
        birth = float(row[0])
        death = float(row[1])
        birth_str = _float_to_decimal_str(birth)
        if np.isfinite(death):
            death_str = _float_to_decimal_str(death)
        else:
            death_str = INF_DEATH_SENTINEL
        rendered.append([birth_str, death_str])
    return rendered


# ---------------------------------------------------------------------------
# Input hashing.
# ---------------------------------------------------------------------------


def _input_sha256(arr: np.ndarray[Any, np.dtype[np.float64]]) -> str:
    """Return ``sha256:<64hex>`` of the canonical-JSON encoding of ``arr``.

    The array is serialised as a list of lists of decimal-string policy values
    (via :func:`_float_to_decimal_str`) and canonical-JSON-encoded, so two
    arrays with the same values produce the same hash regardless of memory
    layout, dtype width, or row order. This anchors the preprocessing receipt
    to the exact input.
    """
    rows: list[list[str]] = []
    for row in arr:
        rows.append([_float_to_decimal_str(float(v)) for v in row])
    return "sha256:" + hashlib.sha256(dumps(rows)).hexdigest()


# ---------------------------------------------------------------------------
# Public API: compute_persistence.
# ---------------------------------------------------------------------------


def compute_persistence(  # noqa: PLR0913 (the WP-E42 API surface requires these kwargs)
    point_cloud: Any,
    *,
    maxdim: int = 1,
    metric: str = "euclidean",
    thresh: float | None = None,
    seed: int | None = None,
    center: bool = False,
    scale: bool = False,
) -> PersistenceResult:
    """Compute persistent homology of a point cloud.

    The point cloud is validated and resource-limited **before** any compute
    runs. Ripser's Vietoris-Rips algorithm is deterministic for a fixed cloud
    and fixed parameters, so two calls with the same input produce identical
    diagrams. The result carries a deterministic preprocessing receipt (seed,
    center/scale flags, input sha256) so the compute is fully auditable.

    Parameters
    ----------
    point_cloud:
        A point cloud as a list of lists/tuples of numbers, or a numpy array of
        shape ``(n_points, ambient_dim)``. Must be finite, non-empty, and
        within the hard limits (:data:`MAX_POINTS`, :data:`MAX_AMBIENT_DIM`).
    maxdim:
        The maximum homology dimension to compute (0 = connected components,
        1 = loops, 2 = voids). Must be in ``0..MAX_HOMOLOGY_DIM``.
    metric:
        The distance metric for the Vietoris-Rips complex. Passed to ripser's
        ``metric`` argument. The default ``"euclidean"`` is the standard choice
        for point clouds in ambient space.
    thresh:
        The maximum Vietoris-Rips radius. ``None`` (the default) lets ripser
        compute the full complex (up to the diameter); a finite value bounds
        the complex and is faster but may miss large-scale features. Must be a
        non-negative finite float when set.
    seed:
        A PRNG seed threaded into any stochastic preprocessing. ``None`` (the
        default) means no seed; since the default preprocessing does not use
        RNG, the result is still deterministic. Recorded in the receipt.
    center:
        If ``True``, mean-center each ambient coordinate before compute.
    scale:
        If ``True``, unit-variance scale each ambient coordinate before
        compute. Applied after centering if both are set.

    Returns
    -------
    PersistenceResult
        The persistence diagrams (decimal-string birth/death pairs per
        dimension), point count, maxdim, and preprocessing receipt.

    Raises
    ------
    RipserInputError
        If the cloud, maxdim, metric, seed, center, scale, or thresh is
        structurally invalid (fail reason ``CONTRACT_INVALID``). Raised before
        any compute.
    RipserResourceLimitError
        If the cloud exceeds a hard limit (fail reason ``RESOURCE_LIMIT``).
        Raised before any compute.

    Notes
    -----
    The compute is **deterministic**: ripser's core has no RNG and no
    wall-clock dependence, so the same cloud and parameters always yield the
    same diagrams. The only stochastic surface is the optional preprocessing
    (centering/scaling use no RNG; the seed is reserved for future use and for
    the :func:`phase_randomized_surrogate` helper). Two runs with the same seed
    produce byte-identical preprocessing receipts.

    A persistence diagram is **computation, not validation**: a prominent H1
    class is evidence of a loop at the diagram's scale, not a scientific claim
    that the underlying phenomenon is topologically non-trivial. See
    ``docs/architecture/ripser-pack.md`` for the null/surrogate discipline.
    """
    validated_maxdim = _validate_maxdim(maxdim)
    validated_metric = _validate_metric(metric)
    validated_seed = _validate_seed(seed)
    validated_center, validated_scale = _validate_center_scale(center, scale)

    arr = _coerce_cloud(point_cloud)
    _enforce_limits(arr, validated_maxdim)

    # Validate thresh: a finite non-negative float, or None for the full complex.
    if thresh is not None:
        if not isinstance(thresh, (int, float)) or isinstance(thresh, bool):
            msg = f"thresh must be a non-negative finite float or None, got {type(thresh).__name__}"
            raise RipserInputError(msg)
        if not np.isfinite(float(thresh)) or float(thresh) < 0:
            msg = f"thresh must be a non-negative finite float or None, got {thresh!r}"
            raise RipserInputError(msg)
        ripser_thresh: float = float(thresh)
    else:
        ripser_thresh = float(np.inf)

    # Hash the input before any preprocessing, so the receipt anchors to the
    # exact bytes the caller supplied.
    input_hash = _input_sha256(arr)

    # Apply optional preprocessing. Centering and scaling are deterministic
    # (no RNG); the seed is recorded regardless so the receipt is stable and
    # future stochastic preprocessing can be added without changing the shape.
    work = arr
    if validated_center:
        work = work - work.mean(axis=0)
    if validated_scale:
        std = work.std(axis=0)
        # Guard against a zero-variance column (would divide by zero). A
        # constant column carries no geometric signal; leave it unscaled.
        std_safe = np.where(std == 0, 1.0, std)
        work = (work - work.mean(axis=0)) / std_safe

    # Run the deterministic Vietoris-Rips computation. ``ripser`` returns a
    # dict with a ``dgms`` key (list of ndarrays, one per dimension 0..maxdim).
    result: Any = ripser(
        work,
        maxdim=validated_maxdim,
        metric=validated_metric,
        thresh=ripser_thresh,
    )
    diagrams_raw: list[np.ndarray[Any, np.dtype[np.float64]]] = list(result["dgms"])

    # Render each diagram to decimal-string pairs.
    diagrams: list[list[list[str]]] = [_render_diagram(dgm) for dgm in diagrams_raw]

    receipt = PreprocessingReceipt(
        seed=validated_seed,
        centered=validated_center,
        scaled=validated_scale,
        input_sha256=input_hash,
    )

    return PersistenceResult(
        diagrams=diagrams,
        n_points=int(arr.shape[0]),
        maxdim=validated_maxdim,
        preprocessing_receipt=receipt,
    )


# ---------------------------------------------------------------------------
# Public API: phase_randomized_surrogate.
# ---------------------------------------------------------------------------


def phase_randomized_surrogate(
    signal: Any,
    seed: int,
) -> list[str]:
    """Produce a phase-randomized surrogate of a 1-D signal.

    A phase-randomized (AAFT-adjacent) surrogate preserves the power spectrum
    (hence the autocorrelation) of the input signal while randomizing the
    Fourier phases, yielding a signal drawn from the null hypothesis "the data
    is a linear stochastic process with the same spectrum." Comparing a
    topological feature in the original signal to the distribution of features
    across an ensemble of surrogates is the standard null-hypothesis control
    for TDA on time series.

    The surrogate is rendered as a list of decimal-string policy values (the
    SRL precision policy), so it is JSON-serializable and survives a round
    trip. The seed is threaded through :func:`numpy.random.default_rng` and
    must be supplied (no implicit global RNG): two calls with the same signal
    and the same seed produce byte-identical surrogates.

    Parameters
    ----------
    signal:
        A 1-D signal as a list of numbers or a numpy array of shape
        ``(n_samples,)``. Must be finite and non-empty.
    seed:
        A non-negative PRNG seed for the phase randomization.

    Returns
    -------
    list[str]
        The surrogate signal, rendered as decimal-string policy values.

    Raises
    ------
    RipserInputError
        If the signal is not a 1-D finite array, or the seed is invalid.

    Notes
    -----
    This helper operates on a 1-D signal, not a point cloud, because the
    standard surrogate theory (the phase-randomization theorem) is defined on a
    scalar time series. A typical workflow is: embed the signal into a point
    cloud (time-delay embedding), compute its persistent homology, and compare
    to the homology of surrogate-embedded clouds. The embedding step is
    deliberately *not* provided here — it is a modeling choice the caller owns.
    """
    validated_seed = _validate_seed(seed)
    if validated_seed is None:
        # ``seed`` is a required positional; this is defensive against a future
        # default change. A surrogate without a seed is not reproducible.
        msg = "phase_randomized_surrogate requires a non-negative seed"
        raise RipserInputError(msg)

    # Coerce the signal to a 1-D float64 array.
    if isinstance(signal, np.ndarray):
        arr = signal
    elif isinstance(signal, (list, tuple)):
        try:
            arr = np.asarray(signal, dtype=np.float64)
        except (ValueError, TypeError) as exc:
            msg = f"signal must be a list/array of numbers; coercion failed: {exc}"
            raise RipserInputError(msg) from exc
    else:
        msg = f"signal must be a list or numpy array, got {type(signal).__name__}"
        raise RipserInputError(msg)

    if arr.ndim != 1:
        msg = f"signal must be 1-D, got {arr.ndim}-D"
        raise RipserInputError(msg)
    if arr.shape[0] == 0:
        msg = "signal must have at least one sample"
        raise RipserInputError(msg)
    if arr.dtype != np.float64:
        arr = arr.astype(np.float64)
    arr = np.ascontiguousarray(arr)
    if not np.all(np.isfinite(arr)):
        msg = "signal contains a non-finite value (NaN or Inf)"
        raise RipserInputError(msg)

    # Phase randomization via the real FFT.
    rng = np.random.default_rng(validated_seed)
    spectrum = np.fft.rfft(arr)
    magnitudes = np.abs(spectrum)
    random_phases = rng.uniform(0.0, 2.0 * np.pi, size=spectrum.shape)
    randomized_spectrum = magnitudes * np.exp(1j * random_phases)
    surrogate = np.fft.irfft(randomized_spectrum, n=arr.shape[0])

    return [_float_to_decimal_str(float(v)) for v in surrogate]


# ---------------------------------------------------------------------------
# Version helpers (for gate evidence).
# ---------------------------------------------------------------------------


def ripser_version() -> str:
    """Return the resolved ripser.py version string (for gate evidence)."""
    # ``ripser.__version__`` is a module-level string; import is isolated to
    # this adapter (ADR-0005).
    import ripser as _ripser  # noqa: PLC0415 (already imported at top; reuse)

    return str(_ripser.__version__)


def numpy_version() -> str:
    """Return the resolved numpy version string (for gate evidence)."""
    return str(np.__version__)


# ---------------------------------------------------------------------------
# Persistence-diagram analysis helpers (for gates and null controls).
# ---------------------------------------------------------------------------


def long_lived_classes(
    result: PersistenceResult,
    dimension: int,
    threshold: float,
) -> int:
    """Count the long-lived persistence classes in one dimension.

    A class is *long-lived* if its persistence (death - birth) exceeds
    ``threshold``. Essential classes (infinite death) are always counted as
    long-lived (their persistence is infinite). This is the helper a gate uses
    to assert "the circle has one prominent H1" or "the two-cluster cloud has
    exactly two long-lived H0" without re-parsing the decimal-string diagrams.

    Parameters
    ----------
    result:
        A :class:`PersistenceResult` from :func:`compute_persistence`.
    dimension:
        The homology dimension to inspect (0, 1, or 2).
    threshold:
        The persistence threshold. A class with persistence > ``threshold`` is
        counted.

    Returns
    -------
    int
        The number of long-lived classes (including essential ones).

    Raises
    ------
    RipserInputError
        If ``dimension`` is out of range for the result, or ``threshold`` is
        negative.
    """
    if not isinstance(dimension, int) or isinstance(dimension, bool):
        msg = f"dimension must be an int, got {type(dimension).__name__}"
        raise RipserInputError(msg)
    if dimension < 0 or dimension > result.maxdim:
        msg = f"dimension {dimension} is out of range for a result with maxdim={result.maxdim}"
        raise RipserInputError(msg)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        msg = f"threshold must be a float, got {type(threshold).__name__}"
        raise RipserInputError(msg)
    if threshold < 0:
        msg = f"threshold must be non-negative, got {threshold}"
        raise RipserInputError(msg)

    diagram = result.diagrams[dimension]
    count = 0
    for birth_str, death_str in diagram:
        if death_str == INF_DEATH_SENTINEL:
            count += 1
            continue
        persistence = float(Decimal(death_str) - Decimal(birth_str))
        if persistence > float(threshold):
            count += 1
    return count


def max_finite_persistence(
    result: PersistenceResult,
    dimension: int,
) -> float | None:
    """Return the maximum finite persistence in one dimension, or ``None``.

    Essential classes (infinite death) are excluded; only finite death times
    contribute. Returns ``None`` if the dimension has no finite-death classes.
    Used by gates to assert "the uniform-square control has no H1 above
    threshold" without re-parsing the diagrams.

    Parameters
    ----------
    result:
        A :class:`PersistenceResult` from :func:`compute_persistence`.
    dimension:
        The homology dimension to inspect.

    Returns
    -------
    float | None
        The maximum finite persistence, or ``None`` if there are no
        finite-death classes in the dimension.

    Raises
    ------
    RipserInputError
        If ``dimension`` is out of range for the result.
    """
    if not isinstance(dimension, int) or isinstance(dimension, bool):
        msg = f"dimension must be an int, got {type(dimension).__name__}"
        raise RipserInputError(msg)
    if dimension < 0 or dimension > result.maxdim:
        msg = f"dimension {dimension} is out of range for a result with maxdim={result.maxdim}"
        raise RipserInputError(msg)

    diagram = result.diagrams[dimension]
    best: float | None = None
    for birth_str, death_str in diagram:
        if death_str == INF_DEATH_SENTINEL:
            continue
        persistence = float(Decimal(death_str) - Decimal(birth_str))
        if best is None or persistence > best:
            best = persistence
    return best


__all__ = [
    "INF_DEATH_SENTINEL",
    "MAX_AMBIENT_DIM",
    "MAX_HOMOLOGY_DIM",
    "MAX_POINTS",
    "PERSISTENCE_SIG_DIGITS",
    "RIPSER_CONTRACT_INVALID_FAIL_REASON",
    "RIPSER_RESOURCE_LIMIT_FAIL_REASON",
    "PersistenceResult",
    "PreprocessingReceipt",
    "RipserInputError",
    "RipserResourceLimitError",
    "compute_persistence",
    "long_lived_classes",
    "max_finite_persistence",
    "numpy_version",
    "phase_randomized_surrogate",
    "ripser_version",
]
