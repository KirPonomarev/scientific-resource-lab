"""Runtime probe for the p1-pymc pack (WP-H71a).

The runtime probe verifies the PyMC adapter loads and its typed surface is
reachable. It is the ``runtime_probe`` entrypoint named in the pack manifest
and is invoked by the admission pipeline's ``RUNTIME_PROBED`` stage.

Exit code 0 on success; non-zero on any import or surface failure. The probe is
hermetic: it imports only the in-repo ``srl`` package and performs no I/O.
"""

from __future__ import annotations

import sys


def main() -> int:  # noqa: C901 (the probe is a flat self-check; splitting hurts readability)
    """Load the PyMC adapter and verify its typed surface is reachable."""
    from srl.packs.adapters.pymc_adapter import (  # noqa: PLC0415 (deferred import is the probe's purpose)
        DEFAULT_TARGET_ACCEPT,
        ESS_FLOOR,
        KIND_LINEAR_REGRESSION,
        KIND_NORMAL_MEAN,
        MAX_DRAWS,
        MAX_TUNE,
        REQUIRED_CHAINS,
        SELECTION_NOTE,
        PymcAdapterError,
        arviz_version,
        build_model_spec,
        pymc_version,
    )

    # The documented values the bounded-profile constants must equal. Named so
    # the comparisons self-document and do not trip the magic-value lint.
    expected_chains = 1
    expected_max = 500
    expected_ess_floor = 50
    expected_target_accept = 0.9
    failures: list[str] = []

    # The one-chain bounded profile invariants must be the documented values.
    if REQUIRED_CHAINS != expected_chains:
        failures.append(f"REQUIRED_CHAINS={REQUIRED_CHAINS} != {expected_chains}")
    if MAX_DRAWS != expected_max or MAX_TUNE != expected_max:
        failures.append(f"MAX_DRAWS/TUNE={MAX_DRAWS}/{MAX_TUNE} != {expected_max}")
    if ESS_FLOOR != expected_ess_floor:
        failures.append(f"ESS_FLOOR={ESS_FLOOR} != {expected_ess_floor}")
    if DEFAULT_TARGET_ACCEPT != expected_target_accept:
        failures.append(
            f"DEFAULT_TARGET_ACCEPT={DEFAULT_TARGET_ACCEPT} != {expected_target_accept}"
        )

    # The model-spec kinds must be the two supported families.
    expected_kinds = {"normal_mean", "linear_regression"}
    if {KIND_NORMAL_MEAN, KIND_LINEAR_REGRESSION} != expected_kinds:
        failures.append(f"kinds != {expected_kinds}")

    # The selection-aware note must carry the honesty statement.
    if "NOT" not in SELECTION_NOTE or "convergence" not in SELECTION_NOTE:
        failures.append("SELECTION_NOTE missing honesty statement")

    # A malformed spec must raise PymcAdapterError before any compute.
    try:
        build_model_spec("not_a_kind", {})
    except PymcAdapterError:
        pass
    else:
        failures.append("malformed spec was not rejected")

    if failures:  # pragma: no cover (probe failure path)
        for f in failures:
            print(f"p1-pymc runtime probe FAIL: {f}", file=sys.stderr)
        return 1

    # Report the resolved engine versions for admission evidence.
    print(f"p1-pymc runtime probe OK; pymc={pymc_version()}; arviz={arviz_version()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
