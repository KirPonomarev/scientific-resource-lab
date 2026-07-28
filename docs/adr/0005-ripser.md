# ADR 0005: Ripser.py + numpy for the TDA pack

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-E42 (Ripser TDA pack)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

WP-E42 introduces the topological-data-analysis (TDA) capability: a real
persistent-homology layer that computes the persistence diagrams of a point
cloud and renders them as decimal-string birth/death pairs, consistent with the
SRL precision policy. The TDA adapter
(`src/srl/packs/adapters/ripser_adapter.py`) must:

1. **Compute** persistent homology (H0 connected components, H1 loops, H2 voids)
   of a bounded point cloud via the Vietoris-Rips complex.
2. **Bound** the compute before it starts: hard limits on point count, ambient
   dimension, and homology degree, each rejecting with `RESOURCE_LIMIT` before
   any compute runs.
3. **Render** the persistence diagrams as decimal-string policy values so they
   survive a serialize/parse round trip with no float coercion or exponent
   drift, and carry a deterministic preprocessing receipt (seed, center/scale
   flags, input sha256).
4. **Control** the null hypothesis: a phase-randomized surrogate helper for
   TDA on time series, so a topological feature can be compared against the
   distribution of features across a surrogate ensemble.

Through WP-E40 the package had two runtime third-party dependencies
(`jsonschema`, ADR-0002; `pint`, ADR-0003), both pure Python. The TDA pack is
the fabric's **first numerical closure**: ripser.py binds to the Ripser C++
core, and it pulls in numpy (its array substrate) plus a transitive scientific
closure (scipy, scikit-learn). The choice affects:

1. Whether persistent homology is correct (the Vietoris-Rips reduction is
   intricate and exactly the kind of code where a silent bug corrupts every
   downstream topological claim).
2. The supply-chain surface (a C++ extension and a large scientific closure
   are imported wherever the adapter runs).
3. The platform story (native wheels must exist for every SRL target: linux
   and macos, x86_64 and arm64).
4. Lockfile and reproducibility posture (`uv.lock` must pin the library and its
   transitive closure).

## Alternatives considered

### 1. `ripser.py` + `numpy` (chosen)

- `ripser.py` (`scikit-tda/ripser.py`) is the de-facto Python binding to the
  Ripser C++ core, the fastest open-source Vietoris-Rips engine. Maintained
  under the scikit-tda organization, in continuous development since 2018.
- MIT-licensed (see *License impact*); compatible with the project's
  Apache-2.0 license and the SRL pack allowlist.
- Pre-built wheels for every SRL target (linux/macos, x86_64/arm64) on Python
  3.11+, so no compilation is needed at install time.
- The API is a single function (`ripser.ripser`) returning persistence
  diagrams as numpy arrays, which the adapter renders to decimal-string policy
  values. The core is deterministic (no RNG, no wall-clock dependence) for a
  fixed cloud and fixed parameters.
- numpy is required transitively by ripser and is required explicitly by
  several Phase E packs (SMT, pyriermann); adding it as a direct dependency
  makes the requirement auditable rather than implicit.
- Pulls a transitive scientific closure (scipy, scikit-learn, joblib, ...);
  see *Resource impact* and *Supply-chain discipline* for the size and the
  persim/hopcroftkarp override.

### 2. `gudhi`

- A comprehensive C++ TDA library with Python bindings, covering far more than
  Vietoris-Rips (alpha complexes, cubical complexes, witness complexes,
  bottleneck/wasserstein distances).
- GPL/proprietary dual-licensed: the open-source build is **GPL-3.0**, which is
  **incompatible** with the SRL pack policy (`GPL-` is a denied prefix). A
  commercial license would be required for Apache-2.0 compatibility, which is a
  non-starter for an open-source fabric.
- Rejected on license grounds regardless of capability.

### 3. `scipy.spatial` + hand-rolled reduction

- Implement the Vietoris-Rips complex and the persistence reduction by hand,
  using scipy only for the distance matrix and sparse-matrix primitives.
- Avoids the ripser dependency but re-introduces exactly the maintenance burden
  ADR-0003 rejected for the units algebra: the reduction is intricate, easy to
  get subtly wrong, and a hand-rolled version must be re-tested against known
  topology (the circle, two-cluster, uniform goldens) on every change.
- The Ripser core is the result of years of optimization (the cohomology
  reduction, the clearing optimization, the implicit matrix representation); a
  hand-rolled version would be orders of magnitude slower on the same input.
- Trades one well-tested dependency for a permanent in-house maintenance burden
  with no headroom.

### 4. `giotto-tda`

- A higher-level TDA pipeline library built on top of scikit-learn and
  gudhi-like primitives.
- Apache-2.0 licensed, but it is a thick pipeline layer (embeddings, filtrations,
  diagram vectorizations) rather than a focused Vietoris-Rips engine. The SRL
  adapter wants the raw diagrams, not a pre-baked pipeline, so most of
  giotto-tda's surface is unused overhead.
- Pulls an even larger closure than ripser.py for functionality the adapter
  does not use.

## Decision

Adopt **`ripser.py`** as the persistent-homology engine and **`numpy`** as its
array substrate, **fully isolated behind the adapter**
`src/srl/packs/adapters/ripser_adapter.py`. That module is the only module in
the SRL tree that imports `ripser`, `numpy`, or `np`; every other consumer goes
through the adapter's typed surface (`compute_persistence`,
`PersistenceResult`, `PreprocessingReceipt`, `phase_randomized_surrogate`,
`long_lived_classes`, `max_finite_persistence`, `RipserInputError`,
`RipserResourceLimitError`).

Configuration (see `pyproject.toml`):

```toml
[project]
dependencies = [
    "jsonschema>=4.23",
    "pint>=0.25.3",
    "ripser>=0.6.15",
    "numpy>=2.0",
]
```

A dev-group stub is not viable (ripser.py has no stub package and does not ship
`py.typed`); instead a `[[tool.mypy.overrides]]` entry sets
`ignore_missing_imports = true` for the `ripser` module only. The adapter
treats the ripser import as opaque (typed as `Any`), exactly as the units
adapter treats Pint (ADR-0003), so mypy strict still covers the adapter body
end-to-end. numpy ships `py.typed` and type-checks natively.

The adapter enforces hard resource limits **before** any compute
(`MAX_POINTS = 500`, `MAX_AMBIENT_DIM = 32`, `MAX_HOMOLOGY_DIM = 2`), each
rejecting with `RipserResourceLimitError` (`RESOURCE_LIMIT`). Structural input
violations raise `RipserInputError` (`CONTRACT_INVALID`). Persistence times are
rendered to the SRL decimal-string policy via `decimal.Decimal`; essential
classes are rendered with the sentinel `"inf"`.

## Consequences

### Positive

- Persistent homology is correct by construction: the Ripser core is the
  result of years of optimization and peer-reviewed algorithmic work
  (Bauer, "Ripser: a efficient C++ code for computation of Vietoris-Rips
  persistence barcodes", 2021).
- The WP-E42 gate (`scripts/checks/wp42-gate.py`) proves the topology goldens
  (circle H1, two-cluster H0) and the null controls (uniform-square H1,
  surrogate) on the synthetic fixtures.
- Headroom for future TDA work: bottleneck distances, diagram vectorizations,
  and higher-dimensional filtrations are available via the transitive closure
  (scipy, scikit-learn) without re-authoring an in-house engine.
- `mypy --strict` covers the adapter end-to-end; the ripser import is isolated.

### Negative

- Adds `ripser` and `numpy` as the third and fourth runtime third-party
  dependencies, with a transitive scientific closure (scipy, scikit-learn,
  joblib, threadpoolctl). All are pinned in `uv.lock`.
- The `srl.packs.adapters` layer now carries a native (C++/C) closure; the
  WP-E42 gate runs under `uv run python` (the WP-A03 autonomy gate remains
  stdlib-only under bare `python3`).
- ripser.py does not ship type stubs; the adapter uses an `Any`-typed import
  with a mypy override, matching the Pint pattern.

### Security impact

ripser.py is imported only inside the TDA adapter and performs no I/O of its
own in SRL's usage: it operates on in-memory numpy arrays. It does not touch
the runner boundary, the content-addressed store, pack materialization, or the
disclosure sanitizer. numpy likewise operates on in-memory arrays. Pinning a
lower bound (`ripser>=0.6.15`, `numpy>=2.0`) and recording the resolved
versions in `uv.lock` bounds the supply-chain surface. Reversibility is covered
below.

### Resource impact

Moderate. The adapter enforces `MAX_POINTS = 500` and `MAX_AMBIENT_DIM = 32`
**before** compute, so a single `compute_persistence` call is bounded (well
under a second on commodity hardware for the worst-case 500-point, 32-D, H2
cloud). The WP-E42 gate runs in <10s on the synthetic fixtures, well within the
<60s gate budget.

Installed size (the new closure, CPython 3.12, measured via `uv pip list`):

| package          | version | notes                                  |
| ---------------- | ------- | -------------------------------------- |
| `ripser`         | 0.6.15  | the C++-backed Vietoris-Rips engine    |
| `numpy`          | 2.5.1   | array substrate (required by several E packs) |
| `scipy`          | 1.18.0  | transitive (distance matrices, sparse matrices) |
| `scikit-learn`   | 1.9.0   | transitive (ripser uses its pairwise-distance machinery) |
| `joblib`         | 1.5.3   | transitive (scikit-learn parallelism)  |
| `threadpoolctl`  | 3.6.0   | transitive (native thread management)  |
| `cython` + misc  | various | transitive build/runtime utilities     |

The closure is bounded by a uv override (see *Supply-chain discipline* below)
that drops `persim` — a ripser.py hard dependency the core `ripser()` function
never imports — and with it the GPL-licensed `hopcroftkarp`, `matplotlib`,
`pillow`, and the plotting stack. The resolved closure adds ~120 MiB of
installed packages (numpy and scipy dominate). The adapter itself imports only
`ripser` and `numpy` at module level; the rest of the closure is loaded
lazily by ripser's internals and is not in the adapter's hot path.

### Supply-chain discipline (persim / hopcroftkarp override)

`ripser.py` declares `persim` as a hard runtime dependency, but the core
`ripser.ripser()` function — the only surface the SRL adapter uses — does not
import it (`persim` is imported lazily inside the optional `Rips.plot()` method,
which the adapter never calls). `persim` pulls in `hopcroftkarp`, which is
**GPL-3.0** and therefore incompatible with the SRL Apache-2.0 policy (the
`GPL-` prefix is a denied family in both the pack license allowlist and the CI
license inventory). Dropping `persim` from ripser's resolved closure removes
the GPL transitive without affecting the adapter's compute path:

```toml
[tool.uv]
override-dependencies = [
    "persim ; python_version < '0'",  # never resolve: always-false marker
]
```

This also drops `matplotlib`, `pillow`, `fonttools`, `kiwisolver`, `pyparsing`,
`python-dateutil`, `six`, and `wrapt` — the entire plotting stack that `persim`
dragged in. The architecture test in `tests/packs/test_ripser_adapter.py`
asserts the adapter imports neither `persim` nor `hopcroftkarp`. If a future
SRL feature needs `persim` (e.g. bottleneck distances), a dedicated evaluation
must first replace `hopcroftkarp` with a permissive matching library.

### License impact

`ripser.py` is distributed under the **MIT** License. The full text (Copyright
(c) 2018 Christopher Tralie, Nathaniel Saul; C++ core Copyright (c) 2015
Ulrich Bauer) is bundled in `packs/tda-ripser/LICENSE.txt` and its sha256 is
recorded in the pack manifest's `license.texts_sha256`. MIT is present in the
SRL pack allowlist.

`numpy` is distributed under a compound **BSD-3-Clause AND 0BSD AND MIT AND
Zlib AND CC0-1.0** expression — all permissive, OSI-approved licenses. The CI
license inventory (`scripts/checks/license_inventory.py`) was extended to
recognize `0BSD` and `Zlib` (both in the allowlist) and to pattern-match
free-text BSD-3-Clause license bodies (scipy carries the full disclaimer text
rather than a short SPDX string). With these additions the inventory
classifies every package in the resolved closure as allowed; no `denied` or
`unknown` entries are introduced. The transitive dependencies are likewise
permissive: `scipy` (BSD-3-Clause), `scikit-learn` (BSD-3-Clause), `joblib`
(BSD-3-Clause), `threadpoolctl` (BSD-3-Clause), `cython` (Apache-2.0).

The pack manifest for the TDA pack (`packs/tda-ripser/manifest.json`) declares
the license as `MIT` for the bundled ripser distribution and the adapter
source.

## Reversibility

Reversible. ripser and numpy are isolated behind
`src/srl/packs/adapters/ripser_adapter.py`: that module is the only import
site of `ripser`, `numpy`, or `np` in the SRL tree (asserted by architecture
tests in `tests/packs/test_ripser_adapter.py`). Removing the dependency is:

1. a `pyproject.toml` change (drop `ripser>=0.6.15` and `numpy>=2.0` from
   `[project].dependencies`);
2. a `uv lock` to drop the transitive closure;
3. replacing the body of `ripser_adapter.py` with a hand-rolled or alternative
   engine behind the same typed surface (`compute_persistence`,
   `PersistenceResult`, `PreprocessingReceipt`,
   `phase_randomized_surrogate`, `long_lived_classes`,
   `max_finite_persistence`, `RipserInputError`, `RipserResourceLimitError`).

Because the public surface is stable and is the only consumer, callers
(`wp42-gate.py`, future routers) would not need to change. The shipped fixtures
and the topology goldens are independent of the implementation.

## Evidence

- `pyproject.toml` declares `ripser>=0.6.15` and `numpy>=2.0` in
  `[project].dependencies`.
- `uv.lock` pins `ripser==0.6.15`, `numpy==2.5.1`, and the transitive closure.
- `src/srl/packs/adapters/ripser_adapter.py` is the sole `ripser`/`numpy`
  import site; the architecture tests in `tests/packs/test_ripser_adapter.py`
  assert no other module imports either.
- `scripts/checks/wp42-gate.py` reports the resolved ripser and numpy versions
  in its `GateReceipt/v1` evidence block.
- The CI license inventory (`scripts/checks/license_inventory.py`) classifies
  ripser and its transitive dependencies as allowed (MIT/BSD family).
- `docs/architecture/ripser-pack.md` documents the resource bounds, the
  determinism guarantees, and the null/surrogate discipline.
