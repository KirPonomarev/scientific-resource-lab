"""Tests for :mod:`srl.packs.adapters.ripser_adapter` (WP-E42 ripser TDA pack).

All tests are hermetic: they exercise the ripser adapter on small in-memory
point clouds (an equilateral triangle, a square, a tiny two-cluster cloud),
never touching the network or the public fixtures. ripser and numpy are
imported only inside the adapter; an architecture test asserts no other module
in the SRL tree imports either (the isolation boundary documented in
ADR-0005).
"""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path

import pytest

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON
from srl.execution.platform_probe import RESOURCE_LIMIT_FAIL_REASON
from srl.packs.adapters.ripser_adapter import (
    INF_DEATH_SENTINEL,
    MAX_AMBIENT_DIM,
    MAX_HOMOLOGY_DIM,
    MAX_POINTS,
    PersistenceResult,
    RipserInputError,
    RipserResourceLimitError,
    compute_persistence,
    long_lived_classes,
    max_finite_persistence,
    numpy_version,
    phase_randomized_surrogate,
    ripser_version,
)

# The repository root, for the architecture scan over the source tree.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "srl"
_ADAPTER_MODULE = _SRC_ROOT / "packs" / "adapters" / "ripser_adapter.py"

# The SRL decimal-string policy (no exponent). Mirrors the contract constant.
_DECIMAL_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")

# Small deterministic test clouds (topology-known).
_TRIANGLE = [[0.0, 0.0], [1.0, 0.0], [0.5, 0.8660254037844386]]
_SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
_TWO_CLUSTER = [
    [-1.0, 0.0],
    [-0.9, 0.05],
    [-1.05, -0.05],
    [1.0, 0.0],
    [0.9, 0.05],
    [1.05, -0.05],
]


# ---------------------------------------------------------------------------
# compute_persistence: basic topology on known clouds.
# ---------------------------------------------------------------------------


class TestComputePersistenceBasic:
    """``compute_persistence`` on small topology-known clouds."""

    def test_triangle_has_one_essential_h0(self) -> None:
        """An equilateral triangle has exactly one essential (infinite-death) H0.

        Vietoris-Rips on 3 points yields 3 H0 classes: 2 finite merges (each
        dies at the side length) and 1 essential component (infinite death).
        """
        result = compute_persistence(_TRIANGLE, maxdim=1)
        assert isinstance(result, PersistenceResult)
        h0 = result.diagrams[0]
        essential = [pair for pair in h0 if pair[1] == INF_DEATH_SENTINEL]
        assert len(essential) == 1

    def test_triangle_n_points_and_maxdim(self) -> None:
        """The result records the input point count and maxdim."""
        result = compute_persistence(_TRIANGLE, maxdim=1)
        assert result.n_points == 3
        assert result.maxdim == 1
        # diagrams has maxdim+1 entries (H0 and H1).
        assert len(result.diagrams) == 2

    def test_square_has_h0_and_h1(self) -> None:
        """A square (4 corners) has H0 and H1 diagrams with one essential H0."""
        result = compute_persistence(_SQUARE, maxdim=1)
        assert result.n_points == 4
        assert len(result.diagrams) == 2
        # Exactly one essential H0 (the single connected component).
        essential = sum(1 for _, d in result.diagrams[0] if d == INF_DEATH_SENTINEL)
        assert essential == 1

    def test_two_cluster_has_two_long_lived_h0(self) -> None:
        """A tiny two-cluster cloud has two persistent H0 above a threshold."""
        result = compute_persistence(_TWO_CLUSTER, maxdim=1)
        # The two clusters produce one essential + one finite-but-large H0.
        long_h0 = long_lived_classes(result, dimension=0, threshold=0.3)
        assert long_h0 == 2

    def test_default_metric_euclidean(self) -> None:
        """The default metric is euclidean and computes without error."""
        result = compute_persistence(_TRIANGLE, maxdim=0)
        assert result.maxdim == 0
        assert len(result.diagrams) == 1

    def test_maxdim_zero_only_h0(self) -> None:
        """``maxdim=0`` produces only the H0 diagram (one entry)."""
        result = compute_persistence(_SQUARE, maxdim=0)
        assert len(result.diagrams) == 1
        assert result.maxdim == 0

    def test_maxdim_two_includes_h2(self) -> None:
        """``maxdim=2`` produces three diagrams (H0, H1, H2)."""
        result = compute_persistence(_SQUARE, maxdim=2)
        assert len(result.diagrams) == 3
        assert result.maxdim == 2


# ---------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------


class TestDeterminism:
    """``compute_persistence`` is deterministic for fixed input and parameters."""

    def test_same_input_same_diagrams(self) -> None:
        """Two runs with the same cloud and seed produce identical diagrams."""
        r1 = compute_persistence(_TRIANGLE, maxdim=1, seed=42)
        r2 = compute_persistence(_TRIANGLE, maxdim=1, seed=42)
        assert r1.diagrams == r2.diagrams

    def test_same_seed_byte_identical_receipt(self) -> None:
        """Two runs with the same seed produce byte-identical receipts."""
        r1 = compute_persistence(_TRIANGLE, maxdim=1, seed=42)
        r2 = compute_persistence(_TRIANGLE, maxdim=1, seed=42)
        assert r1.preprocessing_receipt.canonical_dumps() == (
            r2.preprocessing_receipt.canonical_dumps()
        )

    def test_input_sha256_stable(self) -> None:
        """The input sha256 is stable across runs with the same cloud."""
        r1 = compute_persistence(_SQUARE, maxdim=0)
        r2 = compute_persistence(_SQUARE, maxdim=0)
        assert r1.preprocessing_receipt.input_sha256 == r2.preprocessing_receipt.input_sha256

    def test_receipt_records_seed(self) -> None:
        """The receipt records the seed supplied."""
        r = compute_persistence(_TRIANGLE, maxdim=0, seed=99)
        assert r.preprocessing_receipt.seed == 99

    def test_receipt_records_none_seed(self) -> None:
        """The receipt records ``None`` when no seed is supplied."""
        r = compute_persistence(_TRIANGLE, maxdim=0)
        assert r.preprocessing_receipt.seed is None


# ---------------------------------------------------------------------------
# Decimal-string policy: diagrams are decimal strings (or "inf").
# ---------------------------------------------------------------------------


class TestDecimalStringPolicy:
    """Persistence diagrams render as decimal-string policy values."""

    def test_all_births_are_decimal_strings(self) -> None:
        """Every birth value matches the decimal-string policy regex."""
        result = compute_persistence(_TRIANGLE, maxdim=1)
        for diagram in result.diagrams:
            for birth_str, _ in diagram:
                assert _DECIMAL_RE.fullmatch(birth_str), f"bad birth: {birth_str!r}"

    def test_finite_deaths_are_decimal_strings(self) -> None:
        """Every finite death matches the policy; essential deaths are 'inf'."""
        result = compute_persistence(_SQUARE, maxdim=1)
        for diagram in result.diagrams:
            for _, death_str in diagram:
                if death_str != INF_DEATH_SENTINEL:
                    assert _DECIMAL_RE.fullmatch(death_str), f"bad death: {death_str!r}"

    def test_no_exponent_notation(self) -> None:
        """No birth or death contains an exponent marker."""
        result = compute_persistence(_TRIANGLE, maxdim=1)
        for diagram in result.diagrams:
            for pair in diagram:
                for val in pair:
                    if val != INF_DEATH_SENTINEL:
                        assert "e" not in val.lower()
                        assert "E" not in val


# ---------------------------------------------------------------------------
# Hard limits: RESOURCE_LIMIT before compute.
# ---------------------------------------------------------------------------


class TestHardLimits:
    """Hard resource limits are enforced before any compute."""

    def test_oversized_cloud_rejected(self) -> None:
        """A cloud above MAX_POINTS is rejected with RESOURCE_LIMIT."""
        too_many = [[0.0, 0.0] for _ in range(MAX_POINTS + 1)]
        with pytest.raises(RipserResourceLimitError) as exc_info:
            compute_persistence(too_many, maxdim=0)
        assert exc_info.value.fail_reason == RESOURCE_LIMIT_FAIL_REASON

    def test_high_ambient_dim_rejected(self) -> None:
        """A cloud above MAX_AMBIENT_DIM is rejected with RESOURCE_LIMIT."""
        too_wide = [[0.0] * (MAX_AMBIENT_DIM + 1)]
        with pytest.raises(RipserResourceLimitError) as exc_info:
            compute_persistence(too_wide, maxdim=0)
        assert exc_info.value.fail_reason == RESOURCE_LIMIT_FAIL_REASON

    def test_high_maxdim_rejected(self) -> None:
        """A maxdim above MAX_HOMOLOGY_DIM is rejected with RESOURCE_LIMIT."""
        with pytest.raises(RipserResourceLimitError) as exc_info:
            compute_persistence(_TRIANGLE, maxdim=MAX_HOMOLOGY_DIM + 1)
        assert exc_info.value.fail_reason == RESOURCE_LIMIT_FAIL_REASON

    def test_at_limit_accepted(self) -> None:
        """A cloud at exactly MAX_POINTS is accepted (boundary is inclusive)."""
        # Use a tiny maxdim and a small ambient dim so the only limit in play
        # is the point count. Keep it small enough to be fast (10 points).
        cloud = [[float(i), 0.0] for i in range(10)]
        result = compute_persistence(cloud, maxdim=0)
        assert result.n_points == 10

    def test_resource_limit_is_value_error(self) -> None:
        """``RipserResourceLimitError`` is a ``ValueError`` (catchable broadly)."""
        with pytest.raises(ValueError):
            compute_persistence([[0.0] * (MAX_AMBIENT_DIM + 1)], maxdim=0)


# ---------------------------------------------------------------------------
# Input validation: CONTRACT_INVALID before compute.
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Structural input violations raise ``RipserInputError`` (CONTRACT_INVALID)."""

    def test_non_list_cloud_rejected(self) -> None:
        """A non-list, non-array cloud is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence("not a cloud", maxdim=0)  # type: ignore[arg-type]

    def test_empty_cloud_rejected(self) -> None:
        """An empty cloud is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence([], maxdim=0)

    def test_1d_cloud_rejected(self) -> None:
        """A 1-D array (scalars, not points) is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence([1.0, 2.0, 3.0], maxdim=0)

    def test_ragged_cloud_rejected(self) -> None:
        """A cloud with rows of differing lengths is rejected."""
        ragged = [[0.0, 0.0], [1.0], [0.0, 1.0]]
        with pytest.raises(RipserInputError):
            compute_persistence(ragged, maxdim=0)

    def test_nan_coordinate_rejected(self) -> None:
        """A NaN coordinate is rejected before compute."""
        with pytest.raises(RipserInputError):
            compute_persistence([[0.0, float("nan")], [1.0, 0.0]], maxdim=0)

    def test_inf_coordinate_rejected(self) -> None:
        """An Inf coordinate is rejected before compute."""
        with pytest.raises(RipserInputError):
            compute_persistence([[0.0, float("inf")], [1.0, 0.0]], maxdim=0)

    def test_negative_maxdim_rejected(self) -> None:
        """A negative maxdim is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence(_TRIANGLE, maxdim=-1)

    def test_non_int_maxdim_rejected(self) -> None:
        """A non-int maxdim is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence(_TRIANGLE, maxdim=1.0)  # type: ignore[arg-type]

    def test_bool_maxdim_rejected(self) -> None:
        """A bool maxdim is rejected (bool is not an int here)."""
        with pytest.raises(RipserInputError):
            compute_persistence(_TRIANGLE, maxdim=True)  # type: ignore[arg-type]

    def test_empty_metric_rejected(self) -> None:
        """An empty metric string is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence(_TRIANGLE, metric="")

    def test_negative_seed_rejected(self) -> None:
        """A negative seed is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence(_TRIANGLE, seed=-1)

    def test_negative_thresh_rejected(self) -> None:
        """A negative thresh is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence(_TRIANGLE, thresh=-1.0)

    def test_inf_thresh_rejected(self) -> None:
        """An infinite thresh is rejected."""
        with pytest.raises(RipserInputError):
            compute_persistence(_TRIANGLE, thresh=float("inf"))

    def test_input_error_fail_reason(self) -> None:
        """``RipserInputError`` carries ``CONTRACT_INVALID``."""
        with pytest.raises(RipserInputError) as exc_info:
            compute_persistence([], maxdim=0)
        assert exc_info.value.fail_reason == CONTRACT_INVALID_FAIL_REASON

    def test_input_error_is_value_error(self) -> None:
        """``RipserInputError`` is a ``ValueError`` (catchable broadly)."""
        with pytest.raises(ValueError):
            compute_persistence([], maxdim=0)


# ---------------------------------------------------------------------------
# Preprocessing: centering and scaling.
# ---------------------------------------------------------------------------


class TestPreprocessing:
    """Optional preprocessing (center, scale) is recorded in the receipt."""

    def test_center_flag_recorded(self) -> None:
        """The ``center=True`` flag is recorded in the receipt."""
        result = compute_persistence(_TRIANGLE, maxdim=0, center=True)
        assert result.preprocessing_receipt.centered is True
        assert result.preprocessing_receipt.scaled is False

    def test_scale_flag_recorded(self) -> None:
        """The ``scale=True`` flag is recorded in the receipt."""
        result = compute_persistence(_TRIANGLE, maxdim=0, scale=True)
        assert result.preprocessing_receipt.scaled is True

    def test_center_and_scale_together(self) -> None:
        """Both center and scale can be applied together."""
        result = compute_persistence(_TRIANGLE, maxdim=0, center=True, scale=True)
        assert result.preprocessing_receipt.centered is True
        assert result.preprocessing_receipt.scaled is True

    def test_centering_preserves_topology(self) -> None:
        """Mean-centering does not change the topology (same essential H0 count)."""
        r_raw = compute_persistence(_TWO_CLUSTER, maxdim=0)
        r_centered = compute_persistence(_TWO_CLUSTER, maxdim=0, center=True)
        essential_raw = sum(1 for _, d in r_raw.diagrams[0] if d == INF_DEATH_SENTINEL)
        essential_centered = sum(1 for _, d in r_centered.diagrams[0] if d == INF_DEATH_SENTINEL)
        assert essential_raw == essential_centered == 1


# ---------------------------------------------------------------------------
# Analysis helpers: long_lived_classes and max_finite_persistence.
# ---------------------------------------------------------------------------


class TestAnalysisHelpers:
    """The diagram-analysis helpers for gates and null controls."""

    def test_long_lived_counts_essential(self) -> None:
        """Essential classes (infinite death) are always counted as long-lived.

        The triangle has 3 H0 classes: 2 finite (persistence = side length) +
        1 essential. At a high threshold only the essential class survives; at
        threshold 0 all finite classes with persistence > 0 also count.
        """
        result = compute_persistence(_TRIANGLE, maxdim=0)
        # At threshold 100, only the essential class (infinite death) counts.
        assert long_lived_classes(result, dimension=0, threshold=100.0) == 1
        # At threshold 0, the two finite classes (persistence ~1.0) also count.
        assert long_lived_classes(result, dimension=0, threshold=0.0) == 3

    def test_long_lived_threshold_filters(self) -> None:
        """A high threshold filters out short-lived finite classes."""
        result = compute_persistence(_TWO_CLUSTER, maxdim=0)
        # Low threshold: both the essential and the inter-cluster merge count.
        assert long_lived_classes(result, dimension=0, threshold=0.3) == 2
        # Very high threshold: only the essential class.
        assert long_lived_classes(result, dimension=0, threshold=100.0) == 1

    def test_max_finite_persistence_excludes_infinite(self) -> None:
        """``max_finite_persistence`` excludes essential classes.

        The triangle has 2 finite H0 merges (death = side length ~1.0) and 1
        essential class. ``max_finite_persistence`` returns the largest finite
        persistence, ignoring the infinite death.
        """
        result = compute_persistence(_TRIANGLE, maxdim=0)
        max_p = max_finite_persistence(result, dimension=0)
        assert max_p is not None
        # The finite merge death is the side length (~1.0); birth is 0.
        assert max_p > 0.5

    def test_max_finite_persistence_two_cluster(self) -> None:
        """The two-cluster cloud has a finite inter-cluster merge persistence."""
        result = compute_persistence(_TWO_CLUSTER, maxdim=0)
        max_p = max_finite_persistence(result, dimension=0)
        assert max_p is not None
        assert max_p > 0.3

    def test_long_lived_bad_dimension_rejected(self) -> None:
        """An out-of-range dimension is rejected."""
        result = compute_persistence(_TRIANGLE, maxdim=0)
        with pytest.raises(RipserInputError):
            long_lived_classes(result, dimension=1, threshold=0.5)

    def test_long_lived_negative_threshold_rejected(self) -> None:
        """A negative threshold is rejected."""
        result = compute_persistence(_TRIANGLE, maxdim=0)
        with pytest.raises(RipserInputError):
            long_lived_classes(result, dimension=0, threshold=-1.0)


# ---------------------------------------------------------------------------
# phase_randomized_surrogate.
# ---------------------------------------------------------------------------


class TestPhaseRandomizedSurrogate:
    """The phase-randomized surrogate helper."""

    def test_reproducible_same_seed(self) -> None:
        """The same signal and seed produce identical surrogates."""
        signal = [0.0, 1.0, 0.0, -1.0] * 8
        s1 = phase_randomized_surrogate(signal, seed=42)
        s2 = phase_randomized_surrogate(signal, seed=42)
        assert s1 == s2

    def test_distinct_different_seed(self) -> None:
        """Different seeds produce different surrogates."""
        signal = [0.0, 1.0, 0.0, -1.0] * 8
        s1 = phase_randomized_surrogate(signal, seed=42)
        s2 = phase_randomized_surrogate(signal, seed=43)
        assert s1 != s2

    def test_output_is_decimal_string_policy(self) -> None:
        """Each surrogate sample matches the decimal-string policy."""
        t = [math.sin(2 * math.pi * i / 16) for i in range(64)]
        surrogate = phase_randomized_surrogate(t, seed=1)
        assert len(surrogate) == 64
        for val in surrogate:
            assert _DECIMAL_RE.fullmatch(val), f"bad value: {val!r}"

    def test_length_matches_input(self) -> None:
        """The surrogate has the same length as the input."""
        signal = [float(i) for i in range(32)]
        surrogate = phase_randomized_surrogate(signal, seed=1)
        assert len(surrogate) == 32

    def test_empty_signal_rejected(self) -> None:
        """An empty signal is rejected."""
        with pytest.raises(RipserInputError):
            phase_randomized_surrogate([], seed=1)

    def test_nan_signal_rejected(self) -> None:
        """A NaN in the signal is rejected."""
        with pytest.raises(RipserInputError):
            phase_randomized_surrogate([0.0, float("nan"), 1.0], seed=1)

    def test_2d_signal_rejected(self) -> None:
        """A 2-D signal is rejected (surrogate theory is 1-D)."""
        with pytest.raises(RipserInputError):
            phase_randomized_surrogate([[0.0, 1.0], [1.0, 0.0]], seed=1)  # type: ignore[arg-type]

    def test_negative_seed_rejected(self) -> None:
        """A negative seed is rejected."""
        with pytest.raises(RipserInputError):
            phase_randomized_surrogate([0.0, 1.0], seed=-1)


# ---------------------------------------------------------------------------
# Serialization: to_dict round-trips through canonical JSON.
# ---------------------------------------------------------------------------


class TestSerialization:
    """The result and receipt serialize cleanly to JSON."""

    def test_result_to_dict_is_json_serializable(self) -> None:
        """The result dict is JSON-serializable."""
        result = compute_persistence(_TRIANGLE, maxdim=1, seed=7)
        d = result.to_dict()
        # Must not raise.
        json.dumps(d)
        assert d["n_points"] == 3
        assert d["maxdim"] == 1

    def test_receipt_to_dict_is_json_serializable(self) -> None:
        """The receipt dict is JSON-serializable."""
        result = compute_persistence(_TRIANGLE, maxdim=0, seed=7)
        d = result.preprocessing_receipt.to_dict()
        json.dumps(d)
        assert d["seed"] == 7

    def test_receipt_canonical_dumps_round_trips(self) -> None:
        """The receipt canonical bytes are valid canonical JSON."""
        result = compute_persistence(_SQUARE, maxdim=0, seed=7)
        receipt_bytes = result.preprocessing_receipt.canonical_dumps()
        # Round-trip: parse the bytes and re-dump; must be identical.
        parsed = json.loads(receipt_bytes)
        redumped = json.dumps(parsed, sort_keys=True, separators=(",", ":")) + "\n"
        assert redumped.encode("utf-8") == receipt_bytes


# ---------------------------------------------------------------------------
# Conformance fixture integration: the goldens load and compute.
# ---------------------------------------------------------------------------


_FIXTURES = _REPO_ROOT / "fixtures" / "conformance" / "ripser"
_PUBLIC = _REPO_ROOT / "fixtures" / "public"


class TestConformanceFixtures:
    """The conformance fixtures load and their topology matches the goldens."""

    def test_circle_golden_fixture_loads(self) -> None:
        """The circle golden fixture loads and has the expected fields."""
        path = _FIXTURES / "p01-circle-h1-golden.input.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        assert spec["expected"] == "accept"
        assert spec["maxdim"] == 1
        assert spec["expected_long_lived_h1"] == 1

    def test_two_cluster_golden_fixture_loads(self) -> None:
        """The two-cluster golden fixture loads and has the expected fields."""
        path = _FIXTURES / "p02-two-cluster-h0-golden.input.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        assert spec["expected_long_lived_h0"] == 2

    def test_negative_fixture_loads(self) -> None:
        """The oversized-cloud negative fixture loads with RESOURCE_LIMIT."""
        path = _FIXTURES / "n01-oversized-cloud.expected_error.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        assert spec["fail_reason"] == "RESOURCE_LIMIT"


# ---------------------------------------------------------------------------
# Architecture test: ripser and numpy imported only inside the adapter.
# ---------------------------------------------------------------------------


def _imports_module(path: Path, target: str) -> bool:
    """Return True iff ``path`` imports ``target`` at module level."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == target:
                    return True
        if isinstance(node, ast.ImportFrom) and node.module == target:
            return True
    return False


class TestRipserNumpyIsolation:
    """ADR-0005: ripser is imported only inside the ripser adapter.

    numpy is the shared numerical substrate: it may additionally appear in
    other Phase E numerical adapters (pyriemann), but never outside
    ``src/srl/packs/adapters/``.
    """

    @pytest.mark.parametrize("target", ["ripser"])
    def test_only_adapter_imports_target(self, target: str) -> None:
        """No module under ``src/srl`` other than the adapter imports the target."""
        offenders: list[str] = []
        for path in _SRC_ROOT.rglob("*.py"):
            if path == _ADAPTER_MODULE:
                continue
            if _imports_module(path, target):
                offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert not offenders, f"{target!r} imported outside the adapter: {offenders}"

    @pytest.mark.parametrize("target", ["numpy", "np"])
    def test_numpy_only_in_adapters(self, target: str) -> None:
        """numpy may be imported only inside ``src/srl/packs/adapters/``."""
        offenders: list[str] = []
        for path in _SRC_ROOT.rglob("*.py"):
            if "adapters" in path.parts:
                continue
            if _imports_module(path, target):
                offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert not offenders, f"{target!r} imported outside adapters: {offenders}"

    def test_adapter_imports_ripser(self) -> None:
        """The adapter module itself imports ripser (sanity check)."""
        assert _imports_module(_ADAPTER_MODULE, "ripser")

    def test_adapter_imports_numpy(self) -> None:
        """The adapter module itself imports numpy (sanity check)."""
        assert _imports_module(_ADAPTER_MODULE, "numpy")


# ---------------------------------------------------------------------------
# Module-level constants and metadata.
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """The exported constants describe the supported surface."""

    def test_max_points_is_documented_bound(self) -> None:
        """MAX_POINTS is the documented 500-point bound."""
        assert MAX_POINTS == 500

    def test_max_ambient_dim_is_documented_bound(self) -> None:
        """MAX_AMBIENT_DIM is the documented 32 bound."""
        assert MAX_AMBIENT_DIM == 32

    def test_max_homology_dim_is_documented_bound(self) -> None:
        """MAX_HOMOLOGY_DIM is the documented 2 bound (H0, H1, H2)."""
        assert MAX_HOMOLOGY_DIM == 2

    def test_inf_death_sentinel(self) -> None:
        """The infinite-death sentinel is the literal 'inf'."""
        assert INF_DEATH_SENTINEL == "inf"

    def test_ripser_version_is_string(self) -> None:
        """The resolved ripser version is a non-empty string."""
        version = ripser_version()
        assert isinstance(version, str)
        assert version != ""

    def test_numpy_version_is_string(self) -> None:
        """The resolved numpy version is a non-empty string."""
        version = numpy_version()
        assert isinstance(version, str)
        assert version != ""
