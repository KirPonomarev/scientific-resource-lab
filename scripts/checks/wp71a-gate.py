#!/usr/bin/env python3
"""WP-H71a acceptance gate for the bounded one-chain PyMC adapter.

Runs the five WP-H71a checks, prints a single canonical ``GateReceipt/v1`` JSON
line to stdout, and exits 0 only if every check PASSes. The gate exercises the
PyMC adapter in :mod:`srl.packs.adapters.pymc_adapter` against the seeded
conformance fixtures under ``fixtures/conformance/pymc/``.

Checks
------
H71a-01 posterior recovers true mean within tolerance
    The one-chain posterior ``mu`` mean for the seeded normal-mean dataset
    agrees with the analytic normal-normal conjugate reference within the
    fixture tolerance (absolute ``0.15``).

H71a-02 chains==1 enforced
    A ``chains>1`` request is refused with a typed ``CONTRACT_INVALID``
    ``PymcAdapterError``; the one-chain bounded profile is structural, not
    advisory. Also confirms the successful fit reports ``chains == 1``.

H71a-03 diagnostics flag raised on the misspecified case
    The deliberately misspecified fixture (extreme data, tight prior, low
    ``target_accept``) yields ``diagnostics_flag == "warn"`` (divergences and/or
    ``ess_min`` below the floor).

H71a-04 posterior predictive check computed and p in [0,1] decimal
    The posterior predictive check is present with a ``p_value_decimal`` that
    parses as a decimal in ``[0, 1]``.

H71a-05 seed determinism
    Two fits with the same seed and same data produce identical summary
    statistics (byte-identical ``mean``/``sd`` decimal strings for ``mu``).

The gate is hermetic (seeded, in-memory) and bounded: draw/tune dimensions are
small so the whole gate finishes well under the 240 s budget.
"""

from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

import numpy as np

# Make the in-repo srl package importable when run as a bare script.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp71a-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402
from srl.packs.adapters.pymc_adapter import (  # noqa: E402
    ESS_FLOOR,
    KIND_NORMAL_MEAN,
    PYMC_FAIL_REASON,
    REQUIRED_CHAINS,
    PymcAdapterError,
    arviz_version,
    build_model_spec,
    fit_posterior,
    numpy_version,
    pymc_version,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-H71a"

# Decimal-string policy regex (mirrors srl.contracts.canonical).
_DECIMAL_RE: Final[re.Pattern[str]] = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")

# Sampler dimensions for the gate. Small enough to keep the whole gate well
# under the 240 s budget; large enough for a stable posterior mean.
_GATE_DRAWS: Final[int] = 200
_GATE_TUNE: Final[int] = 200
_GATE_SEED: Final[int] = 7


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture from fixtures/conformance/pymc/."""
    path = _REPO_ROOT / "fixtures" / "conformance" / "pymc" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _normal_mean_dataset() -> tuple[np.ndarray, dict[str, float]]:
    """Return (data, prior) from the seeded normal-mean fixture.

    The fixture stores prior values as SRL decimal-string policy values; they
    are parsed to floats here so :func:`build_model_spec` receives numbers.
    """
    fixture = _load_fixture("normal_mean_dataset.json")
    data = np.asarray([float(x) for x in fixture["data"]], dtype=float)
    prior = _coerce_prior(fixture["prior"])
    return data, prior


def _coerce_prior(raw: dict[str, Any]) -> dict[str, float]:
    """Coerce a fixture prior block (decimal strings) to a float params dict."""
    return {key: float(value) for key, value in raw.items()}


def _is_decimal_in_unit_interval(value: str) -> bool:
    """True iff ``value`` is a decimal-string policy value in ``[0, 1]``."""
    if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
        return False
    try:
        d = Decimal(value)
    except InvalidOperation:
        return False
    return Decimal("0") <= d <= Decimal("1")


# ---------------------------------------------------------------------------
# H71a-01: posterior recovers true mean within tolerance.
# ---------------------------------------------------------------------------


def _check_h71a_01() -> dict[str, Any]:
    """H71a-01: the posterior mu mean agrees with the analytic reference."""
    try:
        data, prior_raw = _normal_mean_dataset()
        spec = build_model_spec(KIND_NORMAL_MEAN, prior_raw)
        result = fit_posterior(data, spec, draws=_GATE_DRAWS, tune=_GATE_TUNE, seed=_GATE_SEED)
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    known = _load_fixture("normal_mean_known_answer.json")
    ref_mean = Decimal(known["posterior_mu_mean"])
    tolerance = Decimal(known["comparison"]["tolerance_abs"])
    got_mean = Decimal(result.parameters["mu"].mean)
    diff = abs(got_mean - ref_mean)

    if diff > tolerance:
        return {
            "status": "FAIL",
            "detail": (
                f"posterior mu mean {got_mean} differs from analytic reference "
                f"{ref_mean} by {diff} > tolerance {tolerance}"
            ),
        }
    return {
        "status": "PASS",
        "detail": (
            f"posterior mu mean {got_mean} agrees with analytic reference "
            f"{ref_mean} within tolerance {tolerance} (diff {diff})"
        ),
        "evidence": {
            "posterior_mu_mean": result.parameters["mu"].mean,
            "analytic_mu_mean": known["posterior_mu_mean"],
            "diff": str(diff),
            "tolerance": str(tolerance),
            "chains": result.chains,
            "draws": result.draws,
            "seed": result.seed,
        },
    }


# ---------------------------------------------------------------------------
# H71a-02: chains==1 enforced.
# ---------------------------------------------------------------------------


def _check_h71a_02() -> dict[str, Any]:
    """H71a-02: chains>1 is refused with typed CONTRACT_INVALID; success is 1 chain."""
    data, prior_raw = _normal_mean_dataset()
    spec = build_model_spec(KIND_NORMAL_MEAN, prior_raw)
    errors: list[str] = []

    # A chains>1 request must be refused with the typed fail reason.
    try:
        fit_posterior(data, spec, draws=20, tune=20, chains=2, seed=_GATE_SEED)
        errors.append("chains=2 request was not refused")
    except PymcAdapterError as exc:
        if exc.fail_reason != PYMC_FAIL_REASON:
            errors.append(
                f"chains=2 fail_reason={exc.fail_reason!r}, expected {PYMC_FAIL_REASON!r}"
            )
    except Exception as exc:
        errors.append(f"chains=2 raised {type(exc).__name__}, expected PymcAdapterError")

    # A successful fit must report exactly one chain.
    try:
        result = fit_posterior(data, spec, draws=20, tune=20, seed=_GATE_SEED)
        if result.chains != REQUIRED_CHAINS:
            errors.append(f"result.chains={result.chains}, expected {REQUIRED_CHAINS}")
    except Exception as exc:  # gate must capture and report any failure.
        errors.append(f"unexpected exception on chains==1 fit: {type(exc).__name__}: {exc}")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": (
            "chains>1 refused with typed CONTRACT_INVALID; successful fit reports chains==1"
        ),
    }


# ---------------------------------------------------------------------------
# H71a-03: diagnostics flag raised on the misspecified case.
# ---------------------------------------------------------------------------


def _check_h71a_03() -> dict[str, Any]:
    """H71a-03: the misspecified fixture yields diagnostics_flag==warn."""
    fixture = _load_fixture("misspecified_case.json")
    try:
        data = np.asarray([float(x) for x in fixture["data"]], dtype=float)
        spec = build_model_spec(KIND_NORMAL_MEAN, _coerce_prior(fixture["prior"]))
        sampler = fixture["sampler"]
        result = fit_posterior(
            data,
            spec,
            draws=int(sampler["draws"]),
            tune=int(sampler["tune"]),
            seed=int(sampler["seed"]),
            target_accept=float(sampler["target_accept"]),
        )
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    if result.diagnostics_flag != "warn":
        return {
            "status": "FAIL",
            "detail": (
                f"misspecified case diagnostics_flag={result.diagnostics_flag!r}, expected 'warn' "
                f"(divergences={result.divergences}, ess_min={result.diagnostics['ess_min']})"
            ),
        }
    # At least one measurable diagnostic must justify the flag.
    justified = result.divergences > 0 or (
        result.diagnostics["ess_min"] is not None and result.diagnostics["ess_min"] < ESS_FLOOR
    )
    if not justified:
        return {
            "status": "FAIL",
            "detail": "diagnostics_flag=warn but no measurable diagnostic justifies it",
        }
    return {
        "status": "PASS",
        "detail": (
            f"misspecified case raised diagnostics_flag=warn "
            f"(divergences={result.divergences}, ess_min={result.diagnostics['ess_min']}, "
            "rhat_max is None for one chain)"
        ),
        "evidence": {
            "divergences": result.divergences,
            "ess_min": result.diagnostics["ess_min"],
            "rhat_max": result.diagnostics["rhat_max"],
            "diagnostics_flag": result.diagnostics_flag,
        },
    }


# ---------------------------------------------------------------------------
# H71a-04: posterior predictive check computed and p in [0,1] decimal.
# ---------------------------------------------------------------------------


def _check_h71a_04() -> dict[str, Any]:
    """H71a-04: the posterior predictive check carries a decimal p-value in [0,1]."""
    try:
        data, prior_raw = _normal_mean_dataset()
        spec = build_model_spec(KIND_NORMAL_MEAN, prior_raw)
        result = fit_posterior(data, spec, draws=_GATE_DRAWS, tune=_GATE_TUNE, seed=_GATE_SEED)
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    ppc = result.posterior_predictive_check
    errors: list[str] = []
    for field in ("observed_stat", "predictive_stat", "p_value_decimal"):
        value = getattr(ppc, field)
        if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
            errors.append(f"ppc.{field}={value!r} is not a decimal-string policy value")
    if not errors and not _is_decimal_in_unit_interval(ppc.p_value_decimal):
        errors.append(f"ppc.p_value_decimal={ppc.p_value_decimal!r} is not in [0, 1]")
    if ppc.statistic != "mean":
        errors.append(f"ppc.statistic={ppc.statistic!r}, expected 'mean'")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": (
            f"posterior predictive check computed; p_value_decimal={ppc.p_value_decimal} in [0,1]"
        ),
        "evidence": {
            "statistic": ppc.statistic,
            "observed_stat": ppc.observed_stat,
            "predictive_stat": ppc.predictive_stat,
            "p_value_decimal": ppc.p_value_decimal,
        },
    }


# ---------------------------------------------------------------------------
# H71a-05: seed determinism.
# ---------------------------------------------------------------------------


def _check_h71a_05() -> dict[str, Any]:
    """H71a-05: same seed + data -> identical summary statistics."""
    try:
        data, prior_raw = _normal_mean_dataset()
        spec = build_model_spec(KIND_NORMAL_MEAN, prior_raw)
        r1 = fit_posterior(data, spec, draws=_GATE_DRAWS, tune=_GATE_TUNE, seed=_GATE_SEED)
        r2 = fit_posterior(data, spec, draws=_GATE_DRAWS, tune=_GATE_TUNE, seed=_GATE_SEED)
    except Exception as exc:  # gate must capture and report any failure.
        return {"status": "FAIL", "detail": f"unexpected exception: {type(exc).__name__}: {exc}"}

    # A different seed must NOT reproduce the same summary (sanity: the seed
    # actually drives the sampler, not a no-op).
    try:
        r3 = fit_posterior(data, spec, draws=_GATE_DRAWS, tune=_GATE_TUNE, seed=_GATE_SEED + 1)
    except Exception as exc:  # gate must capture and report any failure.
        return {
            "status": "FAIL",
            "detail": f"unexpected exception on alt seed: {type(exc).__name__}: {exc}",
        }

    errors: list[str] = []
    for param in ("mu", "sigma"):
        for field in ("mean", "sd", "hdi_low", "hdi_high"):
            v1 = getattr(r1.parameters[param], field)
            v2 = getattr(r2.parameters[param], field)
            if v1 != v2:
                errors.append(f"{param}.{field}: run1={v1!r} != run2={v2!r}")
    # Sanity: a different seed should change the mu mean (the posterior is
    # randomised; identical across seeds would mean the seed is ignored).
    if r1.parameters["mu"].mean == r3.parameters["mu"].mean:
        errors.append("different seed produced identical mu.mean (seed may be ignored)")

    if errors:
        return {"status": "FAIL", "detail": "; ".join(errors)}
    return {
        "status": "PASS",
        "detail": (
            "same seed + data -> identical summary stats; different seed changes the summary"
        ),
        "evidence": {
            "mu_mean_seed": r1.parameters["mu"].mean,
            "mu_mean_alt_seed": r3.parameters["mu"].mean,
            "seed": r1.seed,
        },
    }


# ---------------------------------------------------------------------------
# Receipt assembly.
# ---------------------------------------------------------------------------


def _build_receipt() -> dict[str, Any]:
    """Run all five checks and assemble the gate receipt."""
    checks = {
        "H71a-01": _check_h71a_01(),
        "H71a-02": _check_h71a_02(),
        "H71a-03": _check_h71a_03(),
        "H71a-04": _check_h71a_04(),
        "H71a-05": _check_h71a_05(),
    }

    statuses = {cid: result["status"] for cid, result in checks.items()}
    overall = "PASS" if all(s == "PASS" for s in statuses.values()) else "FAIL"
    return {
        "schema_version": GATE_SCHEMA,
        "wp_id": WP_ID,
        "overall": overall,
        "checks": checks,
        "evidence": {
            "statuses": statuses,
            "engine_versions": {
                "pymc": pymc_version(),
                "arviz": arviz_version(),
                "numpy": numpy_version(),
            },
            "one_chain_profile": {
                "required_chains": REQUIRED_CHAINS,
                "gate_draws": _GATE_DRAWS,
                "gate_tune": _GATE_TUNE,
                "gate_seed": _GATE_SEED,
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    if args and args[0] == "--check":
        receipt = _build_receipt()
        _emit(receipt)
        return 0 if receipt["overall"] == "PASS" else 1

    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
