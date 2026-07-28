# pyRiemann SPD geometry pack (WP-E43)

WP-E43 adds a geometry adapter for symmetric positive definite (SPD) matrices.
The adapter lives in `src/srl/packs/adapters/pyriemann_adapter.py` and is the
only SRL module that imports `pyriemann`, `numpy`, and `scipy` for geometry
work. The accompanying resource pack is declared in
`packs/geometry-pyriemann/manifest.json` under the `geometry_tda` capability
profile.

## Honesty note: geometry is computation, not validation

The adapter performs Riemannian/log-Euclidean geometry on SPD matrices. A green
result from `distance`, `riemannian_mean`, or `log_euclidean_mean` means the
computation finished and the inputs satisfied the SPD contract; it does **not**
mean the matrices are scientifically meaningful, physically correct, or
statistically appropriate. Geometry is a computational service, not a
validation of the scientific claim that produced the matrices.

## Capability profile

`src/srl/planning/profiles.py` defines only one geometry profile:
`geometry_tda`. Existing SRL corpus tasks (`task-17-spd-valid-distance`,
`task-18-spd-non-spd-rejection`) already route SPD-geometry claims through this
profile, so WP-E43 declares the pack under `geometry_tda` to make the adapter
discoverable for those tasks.

## Public surface

- `Metric` — `StrEnum` selecting `riemann` or `logeuclid`.
- `SpdError` — `ContractError` with fail reason `CONTRACT_INVALID`, raised for
  malformed, non-symmetric, non-positive-definite, or trivial 1x1 inputs.
- `riemannian_mean(mats, weights=None)` — affine-invariant Riemannian mean.
- `log_euclidean_mean(mats, weights=None)` — log-Euclidean mean.
- `distance(a, b, metric)` — Riemannian or log-Euclidean distance.
- `shrinkage(cov, alpha)` — shrink one SPD matrix toward its isotropic target.
- `fit_transform(train, alpha=0.1)` — fit a train-only shrinkage target and
  return `(state, transformed_train)`.
- `transform(state, new)` — apply the fitted target to new matrices.

## Validation contract

Every public function validates inputs before calling `pyriemann`:

1. The array must be numeric and either 2D (single matrix) or 3D (stack).
2. Each matrix must be square and at least `2x2`.
3. Each matrix must be symmetric within `SPD_EIG_TOL`.
4. Each matrix must have all eigenvalues strictly greater than `SPD_EIG_TOL`.

Trivial 1x1 covariances are rejected because they carry no off-diagonal
geometry: every SPD metric collapses to a scalar ratio, which is not useful for
manifold computation and is easy to misuse as a "variance" without admitting
the geometric scope is empty.

## Train-only discipline

`fit_transform(train)` returns a state dict containing only statistics derived
from `train`:

- `alpha`: the shrinkage coefficient used;
- `n_features`: the matrix dimension;
- `target`: the mean isotropic target (mean trace scaling across `train` times
  the identity), stored as a nested list so the state is JSON-serializable.

`transform(state, new)` reads `state` and applies the saved target. It never
recomputes any statistic from `new` and never mutates `state`. This makes test-
point leakage structurally impossible: the fitted state is unchanged regardless
of what test data is later transformed.

## Dependency isolation

`pyriemann>=0.12` is the geometry engine. The adapter imports from the modern
`pyriemann.geometry.*` subpackages introduced in 0.12, avoiding the deprecated
`pyriemann.utils.*` paths (which would emit `DeprecationWarning` and fail under
pytest's `filterwarnings = ["error"]`).

`numpy>=1.26` and `scipy>=1.11` are declared explicitly in `pyproject.toml` so
the SRL surface controls their lower bounds rather than relying solely on
pyriemann's transitive resolution. The architecture test in
`tests/packs/test_pyriemann_adapter.py` scans `src/srl` and asserts that no
module other than the adapter imports `pyriemann`, `numpy`, or `scipy`.

## License

`pyriemann` is distributed under the BSD-3-Clause License. The pack manifest
and `packs/geometry-pyriemann/LICENSE.txt` declare the pack license as
BSD-3-Clause (the more restrictive of pyriemann's BSD-3-Clause and the SRL
adapter's Apache-2.0). The CI license inventory classifies pyriemann and its
transitive dependencies (numpy, scipy, scikit-learn, joblib) as allowed.

## Acceptance gate

`scripts/checks/wp43-gate.py` emits a `GateReceipt/v1` with five checks:

- **E43-01**: log-euclidean mean matches the closed-form geometric mean for two
  commuting diagonal SPD matrices.
- **E43-02**: Riemannian distance satisfies identity, symmetry, and triangle
  inequality on a small golden set.
- **E43-03**: non-SPD and trivial 1x1 inputs are rejected with
  `CONTRACT_INVALID`.
- **E43-04**: `fit_transform` state is deterministic, train-only, and
  reusable by `transform` without test-point leakage.
- **E43-05**: shrinkage preserves positive definiteness for `alpha` in `[0, 1]`.

## Reversibility

The adapter is a drop-in geometry module. To replace pyriemann:

1. Update or remove the dependencies in `pyproject.toml`.
2. Regenerate `uv.lock`.
3. Replace the body of `src/srl/packs/adapters/pyriemann_adapter.py` behind the
   same typed surface.

Callers (`wp43-gate.py`, the pack probes, future routers) depend only on the
public surface, not on pyriemann internals.
