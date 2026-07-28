# PyMC one-chain adapter conformance fixtures (WP-H71a)

This directory holds the conformance fixtures for the bounded one-chain PyMC
adapter (`src/srl/packs/adapters/pymc_adapter.py`). All fixtures are synthetic
and seeded; there is no network I/O.

## Fixtures

- `normal_mean_dataset.json` (`P1PyMCFixture/v1`) — a seeded synthetic
  normal-mean dataset (true `mu=2.5`, `sigma=1.0`, `n=150`, seed 42). The
  `data` array is the response the adapter fits; the `prior` block matches the
  `ModelSpec` used by the gate and tests.
- `normal_mean_known_answer.json` (`P1PyMCKnownAnswer/v1`) — the analytic
  normal-normal conjugate posterior reference for the seeded dataset, computed
  with a plug-in `sigma` from the sample standard deviation (ddof=1). The
  adapter's posterior `mu` mean is compared to this reference within an absolute
  tolerance of `0.15` (H71a-01).
- `misspecified_case.json` (`P1PyMCFixture/v1`) — a deliberately misspecified
  case: extreme data `[100, 101]` fit with a tight prior under a low
  `target_accept` produces a hard posterior geometry. The adapter must raise
  `diagnostics_flag=warn` (divergences and/or `ess_min` below the `ESS_FLOOR`).
  Stable across seeds (H71a-03).

## Honest note

A known-answer reference for the posterior **mean** of the conjugate
normal-normal model exists analytically; the adapter's one-chain sample is
compared to it within tolerance. This is a *recovery* check, not a convergence
certificate: a single chain cannot compute `r_hat`, so `rhat_max` is `None` in
the adapter result and convergence is never certified by this fixture.
