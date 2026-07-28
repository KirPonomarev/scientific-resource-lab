# Ripser TDA pack (WP-E42)

This document covers the persistent-homology capability shipped in WP-E42: the
adapter surface, the resource bounds, the determinism guarantees, and — most
importantly — the honesty discipline that separates a topological *computation*
from a scientific *validation*. The dependency choice is in
[ADR 0005](../adr/0005-ripser.md).

## The adapter

The ripser adapter (`src/srl/packs/adapters/ripser_adapter.py`) is the only
module in the SRL tree that imports `ripser` or `numpy`. Every other consumer
goes through its typed surface:

| Symbol | Purpose |
| --- | --- |
| `compute_persistence(point_cloud, *, maxdim, metric, thresh, seed, center, scale)` | Compute persistent homology of a bounded point cloud; returns a `PersistenceResult`. |
| `PersistenceResult` | Frozen bundle: diagrams (decimal-string birth/death pairs per dimension), `n_points`, `maxdim`, `preprocessing_receipt`. |
| `PreprocessingReceipt` | Deterministic record: `seed`, `centered`, `scaled`, `input_sha256`. |
| `phase_randomized_surrogate(signal, seed)` | A phase-randomized surrogate of a 1-D signal for null-hypothesis controls. |
| `long_lived_classes(result, dimension, threshold)` | Count classes with persistence > threshold (essential classes always count). |
| `max_finite_persistence(result, dimension)` | The maximum finite persistence in a dimension (excludes essential classes). |
| `RipserInputError` | Structural input violation (`CONTRACT_INVALID`). |
| `RipserResourceLimitError` | Hard-limit violation (`RESOURCE_LIMIT`). |

The adapter mirrors the units adapter's isolation pattern (ADR-0003): the
underlying library is imported in exactly one module, treated as opaque
(typed `Any` for the ripser import), and surfaced through a pure-Python,
fully-typed, mypy-strict API.

## Honesty: computation is not validation

A persistence diagram is a **computation**: it reports the birth and death
scales of topological features (components, loops, voids) in a point cloud
under a chosen filtration (here, Vietoris-Rips). It is not, by itself, a
**validation** that the underlying phenomenon is topologically non-trivial.

A prominent H1 class in a point cloud sampled near a circle is *evidence* that
the data is consistent with a loop at the scale the diagram resolves. But:

- A finite sample of a circle always produces some H1 noise alongside the
  dominant class; the threshold that separates "signal" from "noise" is a
  modeling choice, not a mathematical fact.
- A point cloud can have a prominent H1 class for non-topological reasons
  (density gradients, sampling bias, projection artefacts).
- The Vietoris-Rips complex is sensitive to the metric; a different metric
  yields a different diagram.

The SRL evidence model (`docs/contracts/evidence-model.md`) draws this
distinction explicitly: *computation* produces a result; *validation* requires
orthogonal evidence (statistical support, null-hypothesis rejection, external
corroboration). The ripser adapter renders the diagram faithfully and records
the exact preprocessing it applied; the caller (a planner, a gate, a human
reviewer) decides what the diagram means.

### Null and surrogate discipline

The WP-E42 gate enforces this discipline through two controls:

1. **The topology-free control** (`p03-uniform-square-h1-control`): a point
   cloud with no topological structure (a uniform square) must **not** produce
   a long-lived H1 class above the threshold. If it did, the threshold would be
   too loose or the compute would be producing spurious features.

2. **The surrogate control** (`p04-surrogate-control`): a phase-randomized
   surrogate of a 1-D signal preserves the power spectrum (hence the
   autocorrelation) while randomizing the Fourier phases. Comparing a
   topological feature in the original signal to the distribution of features
   across an ensemble of surrogates is the standard null-hypothesis test for
   TDA on time series. The adapter's `phase_randomized_surrogate` helper is
   reproducible (same seed → same surrogate) so the ensemble is deterministic.

A topological claim that has not survived comparison to these controls is a
computation, not evidence.

## Resource bounds

The adapter enforces three hard limits **before** any compute runs, each
rejecting with `RipserResourceLimitError` (`RESOURCE_LIMIT`):

| Limit | Value | Rationale |
| --- | --- | --- |
| `MAX_POINTS` | 500 | Ripser is O(n³) worst-case on the VR complex; 500 points keeps a single computation well under a second. The synthetic circle fixture has 100. |
| `MAX_AMBIENT_DIM` | 32 | The fixtures are 2-D; 32 admits high-dimensional embeddings without admitting the case where the distance matrix alone is gigabytes. |
| `MAX_HOMOLOGY_DIM` | 2 | H0 (components), H1 (loops), H2 (voids). Beyond H2 the interpretation is fragile and the compute expensive. |

These bounds are module-level constants (`Final[int]`) so a change is a
visible, reviewed decision. The gate's E42-04 check asserts that each bound is
enforced with the typed `RESOURCE_LIMIT` rejection. The adapter never silently
truncates, samples, or downsamples an oversized cloud.

## Determinism

Ripser's Vietoris-Rips computation is **deterministic** for a fixed point cloud
and fixed parameters: the C++ core has no RNG and no wall-clock dependence.
Two calls to `compute_persistence` with the same cloud and parameters always
produce identical diagrams (asserted by the test suite and the gate's E42-05
check).

The only stochastic surface is:

- **The optional preprocessing** (centering, scaling) — currently deterministic
  (no RNG), but the `seed` parameter is threaded through and recorded in the
  `PreprocessingReceipt` so future stochastic preprocessing can be added
  without changing the receipt shape.
- **The surrogate helper** — `phase_randomized_surrogate` uses
  `numpy.random.default_rng(seed)`; two calls with the same signal and seed
  produce byte-identical surrogates.

The `PreprocessingReceipt` carries the `seed`, the `centered`/`scaled` flags,
and an `input_sha256` (the canonical-JSON hash of the input array). Two runs
with the same seed and the same input produce byte-identical receipt bytes,
which is the determinism guarantee the gate checks.

## Precision policy

Persistence birth/death times are floats in ripser; the adapter renders them to
the SRL decimal-string policy (`^-?[0-9]+(\.[0-9]+)?$`) via `decimal.Decimal`:

- Each value is quantised to `PERSISTENCE_SIG_DIGITS = 12` significant digits
  (round-half-up), well below float64 precision (~15-16 digits) and far above
  any physically meaningful resolution.
- Insignificant trailing zeros are stripped so a clean value renders compactly.
- Essential classes (infinite death) are rendered with the sentinel string
  `"inf"`, which is clearly distinguished from the finite decimal-string
  values.

This matches the units adapter's precision policy (ADR-0003): precision-
sensitive values survive a JSON round trip with no float coercion or exponent
drift.

## Thresholds

The gate uses two persistence thresholds, each sitting in a wide gap between
the topology signal and the noise floor:

| Threshold | Value | Signal above | Noise below |
| --- | --- | --- | --- |
| `_H1_THRESHOLD` | 0.5 | Circle dominant H1 ≈ 1.24 | Uniform-square max H1 ≈ 0.28; circle H1 noise < 0.004 |
| `_H0_THRESHOLD` | 0.8 | Two-cluster inter-cluster merge ≈ 1.16 | Next-largest H0 ≈ 0.29 |

These are documented module-level constants in `scripts/checks/wp42-gate.py`;
changing them is a visible, reviewed decision. The thresholds are deliberately
generous (the gaps are ~4× wide) so minor changes to the synthetic fixtures or
the ripser version do not flip the gate.

## The pack

The pack (`packs/tda-ripser/`) declares:

- `manifest.json` — `ResourcePackManifest/v1`, `pack_id: "tda-ripser.0.1.0"`,
  `capability_profiles: ["geometry_tda"]`, `license.spdx: "MIT"`,
  `canonical_writes: 0`, `grants_authority: false`. Two entrypoints: `runtime`
  (the adapter module) and `compute` (the actual-compute probe).
- `LICENSE.txt` — the MIT license text (ripser.py); its sha256 is recorded in
  the manifest's `license.texts_sha256`.
- `runtime_probe.py` — the runtime probe: loads the adapter, verifies the
  typed surface, checks the hard limits.
- `actual_compute_probe.py` — the actual-compute probe: runs a deterministic
  persistent-homology computation (an equilateral triangle), verifies the
  preprocessing receipt is deterministic.

The capability profile `geometry_tda` is already declared in the SRL capability
registry seed (`src/srl/catalog/seed_entries.json`) with
`adapter_id: "ripser"`; this pack fills that slot.

## Conformance fixtures

The conformance vectors (`fixtures/conformance/ripser/`) encode the topology of
the synthetic point clouds in `fixtures/public/`:

- `p01-circle-h1-golden` — the circle has exactly one long-lived H1 (the loop).
- `p02-two-cluster-h0-golden` — the two-cluster cloud has exactly two
  long-lived H0 (1 essential + 1 inter-cluster merge).
- `p03-uniform-square-h1-control` — the uniform square has no long-lived H1
  (the topology-free control).
- `p04-surrogate-control` — the surrogate is reproducible and seed-distinct
  (the null-hypothesis control).
- `n01-oversized-cloud` — a cloud above `MAX_POINTS` is rejected with
  `RESOURCE_LIMIT` before compute.

The golden values (max persistence, long-lived counts) are computed from the
actual ripser output by
`fixtures/conformance/packs/make_ripser_fixtures.py`, so the gate asserts
against real topology, not hand-waved numbers. See
`fixtures/conformance/ripser/README.md` for the full rationale.
