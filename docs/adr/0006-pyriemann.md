# ADR 0006: pyRiemann for the SPD geometry pack

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-E43 (pyRiemann SPD geometry pack)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

WP-E43 introduces a geometry adapter for symmetric positive definite (SPD)
matrices: the Riemannian manifold of covariance-like matrices, with the
Riemannian and log-Euclidean metrics. The adapter
(`src/srl/packs/adapters/pyriemann_adapter.py`) must:

1. Compute Riemannian and log-Euclidean means of a stack of SPD matrices.
2. Compute distances between two SPD matrices under either metric.
3. Apply shrinkage regularisation to an SPD covariance matrix while preserving
   positive definiteness.
4. Validate inputs as SPD (symmetric, all eigenvalues strictly positive within
   tolerance) and reject trivial 1×1 covariances, raising `SpdError`
   (`CONTRACT_INVALID`) before any compute.
5. Offer a train-only scaling/shrinkage API (`fit_transform` / `transform`)
   whose state carries only statistics derived from the training set, so test
   data can never leak into the fitted state.

The adapter is a pack-scoped dependency behind `srl.packs.adapters.pyriemann_adapter`;
no other module in the SRL tree imports `pyriemann`, `numpy`, or `scipy` for
geometry work. The relevant capability profile is `geometry_tda` (the only
geometry profile in `src/srl/planning/profiles.py`; existing SPD corpus tasks
`task-17-spd-valid-distance` and `task-18-spd-non-spd-rejection` already route
through it).

## Alternatives considered

### 1. `pyriemann` (chosen)

- Reference Python library for Riemannian geometry on SPD matrices, maintained
  at `pyRiemann/pyRiemann` since 2015.
- Ships `pyriemann.geometry.mean` (`mean_riemann`, `mean_logeuclid`) and
  `pyriemann.geometry.distance` (`distance_riemann`, `distance_logeuclid`) with
  NumPy array I/O — exactly the operations WP-E43 needs.
- Version 0.12 is current and stable; distributed under **BSD-3-Clause**
  (Copyright (c) 2015-2024, authors of pyRiemann), compatible with the project's
  Apache-2.0 license and the SRL pack allowlist.
- Pulls in `numpy` and `scipy` (declared explicitly in `pyproject.toml` so the
  SRL surface controls their lower bounds) and `scikit-learn` plus `joblib`
  (transitive, both BSD-3-Clause). All are pinned in `uv.lock`.

### 2. `geomstats`

- General differential-geometry library covering SPD matrices among many other
  manifolds.
- Much larger scope and dependency surface (autograd backends, optional
  PyTorch/TensorFlow, larger transitive closure) than WP-E43 needs.
- BSD-3-Clause licensed, but the extra surface is disproportionate for a
  single-metric adapter and increases supply-chain risk.

### 3. Hand-rolled Riemannian/log-Euclidean operators

- Implement matrix exponential, logarithm, and the affine-invariant metric
  directly with `scipy.linalg.expm` / `logm` / `sqrtm`.
- Avoids a runtime geometry dependency entirely.
- But: correct Riemannian mean requires iterative minimisation, careful handling
  of numerical precision near the SPD boundary, and extensive validation. Re-
  implementing this is error-prone and duplicates a well-tested reference
  implementation. pyriemann's authors have published and maintained the exact
  algorithms SRL needs.

## Decision

Adopt **`pyriemann>=0.12`** as the SPD geometry engine for WP-E43, **fully
isolated behind the adapter** `src/srl/packs/adapters/pyriemann_adapter.py`. The
adapter is the only SRL module that imports `pyriemann`, `numpy`, and `scipy` for
geometry; every other consumer goes through the typed surface
(`riemannian_mean`, `log_euclidean_mean`, `distance`, `shrinkage`,
`fit_transform`, `transform`, `Metric`, `SpdError`).

Configuration (see `pyproject.toml`):

```toml
[project]
dependencies = [
    "jsonschema>=4.23",
    "numpy>=1.26",
    "pint>=0.25.3",
    "pyriemann>=0.12",
    "scipy>=1.11",
]
```

`numpy` and `scipy` are declared explicitly so the adapter can validate arrays
and eigenvalues with pinned lower bounds rather than relying solely on pyriemann's
transitive resolution.

The adapter:

- Validates every matrix as SPD before passing it to pyriemann; non-SPD and
  trivial 1×1 inputs raise `SpdError` with fail reason `CONTRACT_INVALID`.
- Uses the modern `pyriemann.geometry.*` subpackages introduced in 0.12, avoiding
  the deprecated `pyriemann.utils.*` import paths (which emit `DeprecationWarning`
  and would fail under pytest's `filterwarnings = ["error"]`).
- Exposes a `Metric` enum (`riemann`, `logeuclid`) so callers cannot pass raw
  metric strings.
- Keeps the `fit_transform` / `transform` state as a plain JSON-serializable
  dict computed solely from the training inputs; `transform` applies the saved
  target to new inputs without recomputing statistics.

## Consequences

### Positive

- SPD mean and distance computations are delegated to a peer-reviewed reference
  implementation; the SRL gate proves the geometry on deterministic golden
  fixtures rather than reimplementing it.
- The adapter's fail-fast contract catches non-SPD and degenerate inputs before
  any pyriemann compute, preventing undefined-manifold behaviour from becoming
  silent NaN or numerical instability.
- Train-only discipline is enforced structurally: `fit_transform` returns an
  immutable state dict, and `transform` cannot mutate it or refit on test data.
- The WP-E43 pack manifest (`packs/geometry-pyriemann/manifest.json`) declares
  `geometry_tda` as its capability profile, making the adapter discoverable by
  the router for existing SPD corpus tasks.

### Negative

- Adds `pyriemann` plus `numpy`, `scipy`, `scikit-learn`, and `joblib` to the
  runtime dependency closure. All are pinned in `uv.lock`.
- The adapter imports compiled extensions indirectly via NumPy/SciPy, so it
  must declare platform support in the pack manifest (linux/macos, x86_64/arm64)
  and run on those platforms in CI.

### Security impact

`pyriemann`, `numpy`, and `scipy` are imported only inside the adapter and
operate on in-memory NumPy arrays. The adapter performs no network I/O, no
shell execution, and no deserialization of untrusted formats. Input arrays are
validated for shape, symmetry, and positive definiteness before any compute.
Pinning `pyriemann>=0.12` and recording resolved versions in `uv.lock` bounds the
supply-chain surface.

### Resource impact

Moderate. NumPy/SciPy bring native extensions, but the adapter is intended for
small-to-medium SPD matrices at admission/validation time, not for streaming
high-frequency inference. The 15-minute CI budget is comfortable.

Installed size (measured on the resolved 0.12 closure, CPython 3.12):

| package         | notes                              |
| --------------- | ---------------------------------- |
| `pyriemann`     | pure-Python SPD geometry reference |
| `numpy`         | BLAS/LAPACK-backed arrays          |
| `scipy`         | linear algebra and special funcs   |
| `scikit-learn`  | transitive via pyriemann estimators  |
| `joblib`        | transitive via scikit-learn        |

### License impact

`pyriemann` is distributed under the **BSD-3-Clause** License. The PyPI metadata
records the license text as "BSD (3-clause)"; the canonical three-clause text is
present in the installed distribution and matches the SRL allowlist
(`BSD-3-Clause`).

The transitive dependencies are permissive:

- `numpy` — BSD-3-Clause
- `scipy` — BSD-3-Clause
- `scikit-learn` — BSD-3-Clause
- `joblib` — BSD-3-Clause

The CI license inventory (`scripts/checks/license_inventory.py`) classifies all of
them as allowed; no `denied` or `unknown` entries are introduced.

The pack manifest for the geometry pack (`packs/geometry-pyriemann/manifest.json`)
declares the license as `BSD-3-Clause` for the bundled pyriemann distribution and
the adapter source.

## Reversibility

Reversible. pyriemann is isolated behind
`src/srl/packs/adapters/pyriemann_adapter.py`: that module is the only import
site of `pyriemann`, `numpy`, and `scipy` for geometry in the SRL tree (asserted
by an architecture test in `tests/packs/test_pyriemann_adapter.py`). Removing
pyriemann is:

1. a `pyproject.toml` change (drop `pyriemann>=0.12`, and optionally `numpy>=1.26`
   and `scipy>=1.11` if no other consumer exists);
2. a `uv lock` to drop the transitive closure;
3. replacing the body of `pyriemann_adapter.py` with an alternative SPD geometry
   implementation behind the same typed surface
   (`riemannian_mean`, `log_euclidean_mean`, `distance`, `shrinkage`,
   `fit_transform`, `transform`, `Metric`, `SpdError`).

Because the public surface is stable and is the only consumer, callers
(`wp43-gate.py`, the pack runtime probe, future routers) would not need to
change.

## Evidence

- `pyproject.toml` declares `pyriemann>=0.12`, `numpy>=1.26`, and `scipy>=1.11`
  in `[project].dependencies`.
- `uv.lock` pins `pyriemann==0.12` and its transitive closure.
- `src/srl/packs/adapters/pyriemann_adapter.py` is the sole pyriemann/numpy/scipy
  import site for geometry; the architecture test
  `tests/packs/test_pyriemann_adapter.py` asserts no other module imports them.
- `scripts/checks/wp43-gate.py` reports the resolved pyriemann/numpy/scipy
  versions in its `GateReceipt/v1` evidence block.
- The CI license inventory (`scripts/checks/license_inventory.py`) classifies
  pyriemann and its transitive dependencies as allowed (BSD-3-Clause family).
- `docs/architecture/pyriemann-pack.md` documents the train-only discipline,
  the trivial-covariance rejection rationale, and the honesty note that geometry
  computation is not validation.
