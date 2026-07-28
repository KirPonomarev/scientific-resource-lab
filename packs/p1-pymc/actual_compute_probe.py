"""Actual-compute probe for the p1-pymc pack (WP-H71a).

The actual-compute probe runs a deterministic one-chain Bayesian posterior fit
and prints a checkable result. It is the ``actual_compute_probe`` entrypoint
named in the pack manifest and is invoked by the admission pipeline's
``ACTUAL_COMPUTE_PROBED`` stage.

The probe is hermetic: it exercises the PyMC adapter on an in-memory seeded
normal-mean dataset (true ``mu=2.5``) and verifies (a) the posterior recovers
the true mean within tolerance, (b) the one-chain profile is honored, and (c)
two runs with the same seed produce identical summary statistics. The printed
result is deterministic so the admission gate can compare it.

Exit code 0 on success; non-zero on any compute, recovery, or determinism
failure.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Run the deterministic one-chain fit and print the checkable result."""
    import numpy as np  # noqa: PLC0415 (deferred import is the probe's purpose)

    from srl.packs.adapters.pymc_adapter import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        KIND_NORMAL_MEAN,
        REQUIRED_CHAINS,
        arviz_version,
        build_model_spec,
        fit_posterior,
        numpy_version,
        pymc_version,
    )

    # Seeded normal-mean dataset (true mu=2.5, sigma=1.0, n=120).
    rng = np.random.default_rng(42)
    data = rng.normal(loc=2.5, scale=1.0, size=120)

    spec = build_model_spec(
        KIND_NORMAL_MEAN,
        {"mu_prior_mu": 0.0, "mu_prior_sigma": 10.0, "sigma_prior": 5.0},
    )
    result_1 = fit_posterior(data, spec, draws=200, tune=200, seed=7)
    result_2 = fit_posterior(data, spec, draws=200, tune=200, seed=7)

    mu_mean = float(result_1.parameters["mu"].mean)

    # 1. The posterior recovers the true mean within tolerance.
    if not 2.5 - 0.3 <= mu_mean <= 2.5 + 0.3:
        return 1  # pragma: no cover (probe failure path)

    # 2. The one-chain bounded profile is honored.
    if result_1.chains != REQUIRED_CHAINS:
        return 1  # pragma: no cover (probe failure path)

    # 3. Determinism: two runs with the same seed produce identical summaries.
    if result_1.parameters["mu"].mean != result_2.parameters["mu"].mean:
        return 1  # pragma: no cover (probe failure path)

    # 4. The selection-aware note must travel with every result.
    if "NOT" not in result_1.selection_note:
        return 1  # pragma: no cover (probe failure path)

    # Deterministic checkable result for the admission gate.
    print(
        f"p1-pymc compute probe OK; mu_mean={mu_mean:.4f}; chains=1; "
        f"flag={result_1.diagnostics_flag}; div={result_1.divergences}; seed=7; "
        f"pymc={pymc_version()}; arviz={arviz_version()}; numpy={numpy_version()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
