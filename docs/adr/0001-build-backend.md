# ADR 0001: Build backend for the `srlab` package

- Status: Accepted
- Date: 2026-07-28
- Work package: WP-A02 (Python skeleton and quality baseline)
- Decider: SRL maintainers
- Supersedes: none
- Superseded by: none

## Context

Scientific Resource Lab ships a Python package (`srlab`) with a `src/` layout,
a console script (`srlab`), and a deterministic build requirement: two clean
builds of the same source must produce byte-equivalent wheels under a fixed
`SOURCE_DATE_EPOCH` (see `scripts/build/reproducible-check.py` and the
`repro-check` Makefile target). The backend choice affects:

1. Whether `src/` layout is supported out of the box.
2. Whether the wheel RECORD/metadata are emitted deterministically.
3. How much non-standard configuration the project must carry.
4. How easily new contributors can build locally (`uv build`).
5. The supply-chain surface (backend is a build-time dependency).

The project standardizes on `uv` for environment and dependency management,
and the lock file (`uv.lock`) must resolve the build backend alongside runtime
needs. PEP 517 / PEP 621 compliance is mandatory.

## Alternatives considered

### 1. `hatchling` (chosen)

- Pure-Python, fast, PEP 517/621 compliant, the default for many modern
  projects and for `hatch`.
- Supports `src/` layout and console scripts via PEP 621 `[project.scripts]`
  with zero non-standard config.
- Deterministic wheel generation is well-supported and exercised by the
  reproducible-check script added in this WP.
- Actively maintained under `pypa/hatch` (PyPA).

### 2. `setuptools`

- The historical default; extremely widely understood.
- Requires more configuration for a `src/` layout and PEP 621 metadata, and
  its defaults drift toward legacy behavior unless explicitly pinned.
- Determinism is achievable but needs more care (dynamic version files,
  generated metadata). Heavier for a minimal skeleton.

### 3. `pdm-backend`

- PEP 621 native and supports `src/` layout cleanly.
- Strong fit for PDM-centric workflows; SRL standardizes on `uv`, not PDM, so
  some of its value (PEP 621 edit flow) is unused.
- Viable, but offers no decisive advantage over `hatchling` for this project
  and adds a second ecosystem association.

### 4. `flit-core`

- Minimal and deterministic-friendly; excellent for tiny pure-Python packages.
- Lacks first-class support for including non-Python data (e.g. `py.typed`
  alongside explicit include rules) without extra conventions, and console
  script wiring is more manual.
- Acceptable, but `hatchling` covers the same ground with broader feature head
  room as the package grows.

## Decision

Adopt **`hatchling`** as the build backend for `srlab`.

Configuration (see `pyproject.toml`):

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"
```

Static version `0.1.0` is declared in `[project]` (PEP 621). The `src/srl`
package and the `srlab` console script are discovered automatically.

## Consequences

### Positive

- Minimal, standard configuration; `[project]` is the single source of truth
  for name, version, license, description, and entry point.
- `src/` layout works with no path configuration beyond convention.
- `uv build` produces an sdist and a wheel with no project-specific build code.
- Deterministic builds are verified by `make repro-check` / CI `package` job.

### Negative

- Adds `hatchling` as a build-time dependency (resolved into `uv.lock`).
- Contributors building with plain `pip` without `uv` must allow PEP 517
  isolated builds (the default on modern `pip`).

### Security impact

`hatchling` runs only at build time and is a PyPA-maintained pure-Python
backend. It does not touch the SRL runner boundary, the content-addressed
store, pack materialization, or the disclosure sanitizer. Pinning a lower
bound (`>=1.27`) and recording the resolved version in `uv.lock` bounds the
supply-chain surface. Reversibility is covered below.

### Resource impact

Build-time only. Wheel builds complete in well under the 15-minute CI budget on
both `ubuntu-24.04` and `macos-15`. No runtime overhead.

### License impact

`hatchling` is distributed under the Apache-2.0 license, compatible with this
project. No third-party attribution is required in `NOTICE` for a build-time
tool dependency, consistent with the WP-A01 NOTICE baseline.

## Reversibility

Reversible. Switching backends is a `pyproject.toml`-only change (the
`[build-system]` table and, if needed, an explicit package include), followed
by `uv lock`. Because metadata is static (no dynamic version file, no
generated sources), no migration of source files is required. The
reproducible-check script is backend-agnostic and continues to apply.

## Evidence

- `pyproject.toml` carries the `[build-system]` table selecting `hatchling`.
- `make build` produces `dist/srlab-0.1.0-*.whl` and `dist/srlab-0.1.0.tar.gz`.
- `make repro-check` returns a `ReproducibleWheelManifest/v1` with a stable
  `content_manifest_sha256`; the manifest hash is recorded in the WP-A02 PR
  body.
- The CI `package` job runs the same check on `ubuntu-24.04` and `macos-15`.
