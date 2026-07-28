# The bounded one-chain PyMC pack (WP-H71a)

This document describes the `p1-pymc` resource pack and the
`srl.packs.adapters.pymc_adapter` bounded Bayesian posterior adapter. It is the
companion to `docs/adr/0008-pymc.md` (the dependency decision) and to
`srl.packs.p1` (the P1 admission framework that produced this candidate's typed
verdict).

> A fitted posterior is **selection-aware evidence**. It is not model
> validation, not causal identification, and — for one chain — not a convergence
> certificate. See `docs/contracts/evidence-model.md`.

## Scope

The `p1-pymc` pack is the **first first-wave P1 candidate** to graduate from a
typed `WAIT_*` admission verdict into a built actual-compute adapter. The
`pymc_arviz` candidate card (`srl.packs.p1.FIRST_WAVE_CANDIDATES[0]`) declares
the upstream SPDX (Apache-2.0 for both PyMC and ArviZ) and a removal/rollback
path; this pack supplies the missing actual-compute adapter and the resource
measurement, moving the candidate toward `ADMIT_TO_PIPELINE`.

The adapter fits a Bayesian posterior over a **restricted declarative model
spec** and returns:

- summary statistics (mean, sd, HDI bounds) as SRL decimal-string policy values;
- diagnostics (`rhat_max`, `ess_min`, `divergences`) and a `diagnostics_flag`;
- a posterior predictive check (observed statistic, predictive statistic, and a
  decimal p-value);
- a resource measurement (wall seconds, rss bytes);
- a `selection_note` stating the selection-aware interpretation.

## The one-chain bounded profile

The adapter runs **exactly one chain, always** (`REQUIRED_CHAINS = 1`). A caller
who asks for `chains > 1` is refused with a typed `CONTRACT_INVALID`
`PymcAdapterError` — the bound is structural, not advisory.

### Why one chain

The profile is bounded for **honest compute, not for speed**:

1. **CI budget.** A single short NUTS chain fits the pack's 15-minute CI budget
   with wide margin (the gate runs in ~10 s). Multi-chain convergence
   diagnostics across many fixtures would blow the budget for a P1 *candidate*
   pack whose job is to prove the capability is wrappable, not to certify
   scientific conclusions.

2. **Honest scope.** A single chain **cannot compute `r_hat`** — the rank-normal
   split-`r_hat` that diagnoses convergence needs ≥ 2 chains. The adapter
   surfaces this honestly: `diagnostics["rhat_max"]` is `None` for every
   one-chain result, never a fabricated value. A one-chain posterior is therefore
   *selection-aware evidence*: it answers "what is the posterior over the
   parameters given these priors and data?" but it does **not** certify that the
   chain has converged.

3. **What the one chain still gives you.** `ess_min` (the minimum bulk effective
   sample size across parameters) *is* computable from a single chain, so the
   adapter reports it. A posterior predictive check (the p-value that the data
   could plausibly have come from the posterior predictive distribution) is also
   single-chain-valid. These are the honest diagnostics the one-chain profile
   can read.

### Bounded dimensions

| bound | value | meaning |
|-------|-------|---------|
| `REQUIRED_CHAINS` | 1 | one chain, always; multi-chain refused |
| `MAX_DRAWS` | 500 | hard ceiling on posterior draws per chain |
| `MAX_TUNE` | 500 | hard ceiling on tuning (warmup) iterations |
| `ESS_FLOOR` | 50 | ess_min below this trips `diagnostics_flag = "warn"` |
| `DEFAULT_TARGET_ACCEPT` | 0.9 | NUTS target acceptance (robust default) |
| `MIN_DATA_LENGTH` | 2 | minimum accepted data length |

## The `diagnostics_flag`

`PosteriorResult.diagnostics_flag` is `"ok"` unless a measurable diagnostic
trips, in which case it is `"warn"`:

- **divergences > 0** — divergent NUTS transitions always trip the flag (a sign
  of a hard posterior geometry, often a reparameterization is needed).
- **`rhat_max > 1.01`** — *would* trip the flag, but `rhat_max` is always `None`
  in the one-chain profile, so this trigger never fires today. It exists for the
  future multi-chain profile.
- **`ess_min < ESS_FLOOR`** — an effective sample size below 50 trips the flag.

The flag never turns a result into an error: a `warn` result is still a valid
posterior, it just carries the honest caveat that a diagnostic signalled
concern. The gate's H71a-03 check asserts that the deliberately misspecified
fixture produces `diagnostics_flag = "warn"`.

## The restricted declarative model spec

`ModelSpec` is **data, not code**. It names a model family and supplies its
scalar hyperparameters; there is no callable, no lambda, no arbitrary
expression. The adapter builds the exact PyMC model from the kind, so a caller
cannot inject code through the spec.

Two families are supported:

- **`normal_mean`** — `y ~ Normal(mu, sigma)` with priors
  `mu ~ Normal(mu_prior_mu, mu_prior_sigma)` and
  `sigma ~ HalfNormal(sigma_prior)`. The normal-normal conjugate case has an
  analytic posterior reference (see the conformance fixtures), so the gate can
  check the adapter recovers the true mean within tolerance.
- **`linear_regression`** — `y ~ Normal(Xβ + intercept, sigma)` with priors
  `β ~ Normal(0, beta_prior_sigma)` and `sigma ~ HalfNormal(sigma_prior)`. The
  design matrix `X` is supplied by the caller; an intercept column is prepended
  automatically.

## Selection-aware interpretation: what a posterior is NOT

This is the load-bearing honesty property of the pack. The `SELECTION_NOTE`
constant (carried verbatim by every `PosteriorResult`) states it; this section
expands it.

A fitted posterior is a **conditional distribution over parameters given the
stated priors and data**. It is:

1. **NOT model validation.** A green run (diagnostics_flag = "ok", good
   posterior predictive p-value) does **not** certify that the model is correct.
   The diagnostics surface the pathologies they can measure; they cannot prove
   the absence of misspecification. Model validation is a separate evidence axis
   (see `docs/contracts/evidence-model.md`).

2. **NOT causal identification.** A posterior is not an identification strategy.
   The mean of `beta[x0]` in a linear regression is the *conditional* association
   of `x0` with the response given the model and priors; it is not a causal
   effect unless the identification assumptions (no unobserved confounding,
   correct adjustment set, etc.) hold — and those are not checked here.
   `causal_identification` is an independent evidence axis.

3. **NOT a convergence certificate (one chain).** A single chain cannot compute
   `r_hat`, so convergence is not certified. `rhat_max` is `None`, not a number;
   no value of `ess_min` — however large — certifies convergence in the
   absence of `r_hat`. A caller who needs a convergence certificate must run the
   (future) multi-chain profile, which the one-chain adapter structurally
   refuses to do.

In the evidence model, a successful one-chain posterior moves at most
`statistical_support` (weakly), and only when an independent validator checks
the output. It moves nothing on the formal, causal, or reproduction axes.

## Precision policy

Summary statistics and the posterior-predictive p-value are rendered as SRL
decimal-string policy values (`^-?[0-9]+(\.[0-9]+)?$`) so they survive a
serialize/parse round trip with no float coercion. The rendering quantises to
six significant digits with round-half-up; that is far beyond the sampling error
of a one-chain profile and keeps the wire form compact.

## Conformance fixtures

`fixtures/conformance/pymc/` ships three synthetic, seeded fixtures:

- `normal_mean_dataset.json` — a seeded normal-mean dataset (true `mu = 2.5`,
  `sigma = 1.0`, `n = 150`).
- `normal_mean_known_answer.json` — the analytic normal-normal conjugate
  posterior reference (plug-in `sigma` from the sample sd). The adapter's
  posterior `mu` mean is compared to this within absolute tolerance `0.15`
  (H71a-01).
- `misspecified_case.json` — extreme data `[100, 101]` with a tight prior under
  low `target_accept`; the adapter must raise `diagnostics_flag = "warn"`
  (H71a-03). Stable across seeds.

The known-answer reference is a *recovery* check, not a convergence certificate:
a single chain cannot compute `r_hat`, so the fixture certifies recovery of the
mean, never convergence.

## Acceptance gate

`scripts/checks/wp71a-gate.py` runs five checks and emits a `GateReceipt/v1`:

- **H71a-01** — posterior recovers true mean within tolerance (vs the analytic
  reference).
- **H71a-02** — `chains == 1` enforced: a `chains > 1` request is refused with
  typed `CONTRACT_INVALID`; a successful fit reports `chains == 1`.
- **H71a-03** — diagnostics flag raised on the misspecified case
  (`diagnostics_flag == "warn"`).
- **H71a-04** — posterior predictive check computed; `p_value_decimal` is a
  decimal in `[0, 1]`.
- **H71a-05** — seed determinism: same seed + data → identical summary stats;
  a different seed changes the summary.

The gate runs under `make gate` (the `p1-pymc-gate (WP-H71a)` CI job) and exits
non-zero on any `FAIL`.
