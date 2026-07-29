# A13 Applied Science Activation

A13 closes the applied-science lane with bounded local workloads and explicit
receipt semantics. It does not add heavy default dependencies, perform provider
calls, write canonical state, or promote scientific claims.

Activated components:

- `ripser`: persistent homology on a unit-circle signal with a topology-free
  control cloud.
- `pyriemann`: SPD geometry diagnostics with log-Euclidean closed-form and
  metric checks.
- `cvxpy`: bounded convex optimization through the admitted solver matrix.
- `native_bayesian_conjugate`: closed-form Bayesian posterior diagnostics with
  no MCMC convergence claim.
- `native_causal_backdoor`: synthetic backdoor identification and permutation
  falsification.

Formal replacements for v2.0.0:

- topology and geometry wishlist packs are covered by `ripser` and `pyriemann`;
- PyMC/ArviZ are replaced by analytic Bayesian diagnostics for this release and
  remain optional/license-disclosed outside the default closure;
- DoWhy/Tigramite/EconML are replaced by native bounded causal checks;
- JAXopt/BoTorch and optimal-transport/manifold packs are replaced by CVXPY and
  native uncertainty diagnostics for this release.

The A13 gate emits a `StageCompletionReceipt/v1` that embeds an
`AppliedScienceActivationReceipt/v1`. The capability truth ledger consumes only
that committed receipt offline. Ledger projection must not import applied
engines, spawn subprocesses, fetch network resources or repeat the workloads.
