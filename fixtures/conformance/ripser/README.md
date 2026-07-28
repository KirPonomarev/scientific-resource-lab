# Ripser TDA conformance vectors (WP-E42)

This directory holds the conformance vectors for the SRL topological-data-
analysis core (`srl.packs.adapters.ripser_adapter`), introduced in WP-E42. The
vectors encode the topology of the synthetic point clouds in
`fixtures/public/` (the circle, two-cluster, and uniform-square clouds) and
assert the null-hypothesis / hard-limit discipline.

A persistence diagram is **computation, not validation** (see
`docs/contracts/evidence-model.md`). The goldens here assert that the adapter
*computes* the expected topology faithfully; they do not assert that the
underlying phenomenon is scientifically circular or clustered. The controls
assert the null: a topology-free cloud should not produce a spurious loop, and a
surrogate should be reproducible but distinct from the original.

## Layout

- `manifest.json` — `ConformanceVectorManifest/v1` index.
- `p*.input.json` — positive vectors (the adapter MUST accept: the goldens and
  the null controls).
- `n*.input.json` + `n*.expected_error.json` — negative vectors (the adapter
  MUST reject, with the contract reason named in each expected-error file).

## Positive vectors (goldens + controls)

- `p01-circle-h1-golden.input.json` — the synthetic unit-radius circle
  (`fixtures/public/cloud-circle.json`, 100 points) has exactly **one** long-
  lived H1 class above the threshold (`H1_THRESHOLD = 0.5`). The dominant H1
  persistence is ~1.24 (the loop); all other H1 classes are below 0.004. This
  is the canonical topology signal: a point cloud sampled near a circle
  produces a single prominent 1-cycle.
- `p02-two-cluster-h0-golden.input.json` — the synthetic two-cluster cloud
  (`fixtures/public/cloud-two-cluster.json`, 128 points) has exactly **two**
  long-lived H0 classes above the threshold (`H0_THRESHOLD = 0.8`): one
  essential component (infinite death) and one inter-cluster merge (finite
  persistence ~1.16). Two clusters → two persistent components.
- `p03-uniform-square-h1-control.input.json` — the synthetic uniform square
  (`fixtures/public/cloud-uniform-square.json`, 128 points) has **no** long-
  lived H1 class above the threshold. The max finite H1 persistence is ~0.28,
  well below 0.5. This is the topology-free control: a non-topological cloud
  must not produce a spurious loop.
- `p04-surrogate-control.input.json` — a phase-randomized surrogate of a 1-D
  signal (sum of two sinusoids) is **reproducible** (same seed → same surrogate
  byte-for-byte) and **distinct** from the original. This is the null-
  hypothesis control for TDA on time series.

## Negative vectors

- `n01-oversized-cloud.input.json` + `n01-oversized-cloud.expected_error.json` —
  a point cloud with `MAX_POINTS + 1` (501) points is rejected with
  `RESOURCE_LIMIT` **before** any compute. The adapter never silently truncates
  or samples an oversized cloud.

## Regeneration

The fixtures are authored by
`fixtures/conformance/packs/make_ripser_fixtures.py`, which computes the golden
values (max persistence, long-lived counts) from the actual ripser output on the
public fixtures. Re-run it after changing the adapter, the limits, or the
fixtures:

```bash
uv run python3 fixtures/conformance/packs/make_ripser_fixtures.py
```

## Threshold rationale

The H1 threshold of `0.5` sits in the wide gap between the circle's dominant
H1 persistence (~1.24) and the uniform square's max H1 persistence (~0.28). The
H0 threshold of `0.8` sits in the gap between the two-cluster inter-cluster
merge (~1.16) and the next-largest H0 (~0.29). Both thresholds are documented
constants in `scripts/checks/wp42-gate.py` so a change is a visible, reviewed
decision.
