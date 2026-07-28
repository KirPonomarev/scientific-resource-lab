#!/usr/bin/env python3
"""WP-B14 acceptance gate for the deterministic claim router and plan builder.

Runs the four WP-B14 checks and prints a single canonical ``GateReceipt/v1``
JSON line to stdout. Exits 0 only if every check PASSes; any FAIL makes the
exit code non-zero so the gate can be wired into CI and ``make gate-wp14``.

The checks
----------
B14-01 determinism (same inputs -> byte-identical plan)
    The same (request, claim, catalog, policy) yields a byte-identical plan
    across 3 rebuilds, including a variant whose input dict key order is
    shuffled (canonical JSON sorts keys; steps are emitted in a stable order).
    Also replays the 3 positive fixtures and asserts their expected
    routing/plan invariants.

B14-02 decision coverage (all 15 profiles, no silent drops)
    Every relevant capability is either SELECTED or has an explicit typed
    exclusion / wait / not-applicable. The decision covers ALL 15 profiles: no
    profile is silently dropped. Asserts the four selection states are each
    reachable and that EXCLUDED_TYPED always carries a reason.

B14-03 no silent fallback (remote_required never runs local)
    A REMOTE_REQUIRED profile never falls back to a local adapter: absence of
    a local adapter yields WAIT_CAPABILITY, never a fake local substitute.
    Asserts no plan step for a remote_required profile carries a non-null
    adapter_id.

B14-04 unknown capability -> WAIT_CAPABILITY
    A profile absent from the catalog (unknown capability) routes
    WAIT_CAPABILITY (the router never fabricates an adapter). Also covers the
    negative fixtures: cyclic dependency raises PlanError (CONTRACT_INVALID,
    cycle_detected); resource overflow raises ResourceAdmissionError
    (WAIT_REMOTE_EXECUTOR).

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp14-gate.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp14-gate.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import (  # noqa: E402  (path setup must precede import)
    ContractError,
    dumps,
)
from srl.planning import (  # noqa: E402
    DEFAULT_CAPS,
    EXCEPTION_CAPS,
    SCIENCE_LAB_PROFILES,
    AdmissionPolicy,
    CapabilityCatalog,
    PlanError,
    ResourceAdmissionError,
    build_plan,
    build_request,
    classify,
    default_policy,
    load_catalog,
    load_default_catalog,
    route,
    topological_order,
)
from srl.planning.router import (  # noqa: E402
    SELECTION_EXCLUDED_TYPED,
    SELECTION_NOT_APPLICABLE,
    SELECTION_SELECTED,
    SELECTION_WAIT_CAPABILITY,
)

# Receipt identity.
GATE_SCHEMA: Final[str] = "GateReceipt/v1"
WP_ID: Final[str] = "WP-B14"

# Fixtures directory (the evidence conformance vectors).
_FIXTURES: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "planning"

# A canonical sha256 digest used for object ids in the inline proofs.
_DIGEST: Final[str] = "sha256:" + "a" * 64


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _build_request_from_scenario(req_spec: dict[str, Any]) -> dict[str, Any]:
    """Build a ScienceLabRunRequest from a scenario's request block."""
    return build_request(
        claim_id=req_spec["claim_id"],
        requested_profiles=req_spec.get("requested_profiles", []),
        resource_class=req_spec.get("resource_class", "default"),
        seed=req_spec.get("seed", 0),
        threads=req_spec.get("threads", 1),
        output_schemas=req_spec.get("output_schemas", []),
    )


def _shuffle_dict_keys(obj: Any) -> Any:
    """Return a deep copy of obj with dict keys in a (seeded) shuffled order.

    Canonical JSON sorts keys at encode time, so a shuffled-key input must
    produce byte-identical output. This helper builds the shuffled variant by
    re-inserting keys in random order at every dict level.
    """
    # Deterministic shuffle for the determinism proof (NOT cryptographic use).
    rng = random.Random(0xC0FFEE)  # noqa: S311 (deterministic test shuffle, not crypto)
    return _shuffle_dict_keys_with_rng(obj, rng)


def _shuffle_dict_keys_with_rng(obj: Any, rng: random.Random) -> Any:
    """Recursive helper for :func:`_shuffle_dict_keys`."""
    if isinstance(obj, dict):
        items = list(obj.items())
        rng.shuffle(items)
        return {k: _shuffle_dict_keys_with_rng(v, rng) for k, v in items}
    if isinstance(obj, list):
        return [_shuffle_dict_keys_with_rng(v, rng) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# B14-01 determinism (same inputs -> byte-identical plan) + positive fixtures.
# ---------------------------------------------------------------------------


def _check_b14_01() -> dict[str, Any]:
    """B14-01: same inputs yield a byte-identical plan (3 rebuilds + key shuffle)."""
    cases: list[dict[str, Any]] = []
    cat = load_default_catalog()
    pol = default_policy()
    claim = {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": "We compute persistent homology and the Betti numbers of the point cloud.",
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }

    # Variant 1: plain rebuild twice.
    req1 = build_request(claim_id=_DIGEST, requested_profiles=[], resource_class="default")
    dec1 = route(req1, claim, cat, pol)
    plan1 = build_plan(req1, dec1, cat, pol)
    plan1b = build_plan(req1, dec1, cat, pol)
    bytes1 = dumps(plan1)
    bytes1b = dumps(plan1b)
    cases.append(
        {
            "variant": "plain-rebuild",
            "byte_identical": bytes1 == bytes1b,
            "plan_id": plan1["plan_id"],
        }
    )

    # Variant 2: rebuild with a freshly re-routed decision (same inputs).
    dec2 = route(req1, claim, cat, pol)
    plan2 = build_plan(req1, dec2, cat, pol)
    bytes2 = dumps(plan2)
    cases.append(
        {
            "variant": "re-route-rebuild",
            "byte_identical": bytes1 == bytes2,
            "plan_id": plan2["plan_id"],
        }
    )

    # Variant 3: shuffled input dict key order (canonical JSON must sort).
    req_shuffled = _shuffle_dict_keys(req1)
    claim_shuffled = _shuffle_dict_keys(claim)
    dec3 = route(req_shuffled, claim_shuffled, cat, pol)
    plan3 = build_plan(req_shuffled, dec3, cat, pol)
    bytes3 = dumps(plan3)
    cases.append(
        {
            "variant": "shuffled-input-keys",
            "byte_identical": bytes1 == bytes3,
            "plan_id": plan3["plan_id"],
        }
    )

    # Replay the positive fixtures and assert their expected invariants.
    fixture_results = _replay_positive_fixtures(cat, pol)

    failures = []
    for c in cases:
        if not c["byte_identical"]:
            failures.append(f"variant {c['variant']!r} was not byte-identical")
    # All three plan_ids must agree.
    ids = {c["plan_id"] for c in cases}
    if len(ids) != 1:
        failures.append(f"plan_ids differ across variants: {sorted(ids)}")
    if not all(r["status"] == "PASS" for r in fixture_results):
        failures.append("one or more positive fixtures failed to replay")

    if failures:
        return {
            "status": "FAIL",
            "detail": "; ".join(failures),
            "cases": cases,
            "positive_fixtures": fixture_results,
        }
    return {
        "status": "PASS",
        "detail": (
            "3 rebuilds (plain, re-route, shuffled-input-keys) yield byte-identical "
            "plans with one plan_id; positive fixtures replay with expected invariants"
        ),
        "cases": cases,
        "positive_fixtures": fixture_results,
    }


def _assert_classifier(scenario: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Assert the classifier-profiles and classifier-trace expectations."""
    checks: list[str] = []
    claim = scenario["claim"]
    request_block = scenario["request"]
    classified, trace = classify(
        claim,
        request_block.get("symbol_table", {}),
        request_block.get("condition_set", {}),
    )
    if "classifier_profiles" in expected and sorted(classified) != sorted(
        expected["classifier_profiles"]
    ):
        checks.append(
            f"classifier_profiles {sorted(classified)} != {sorted(expected['classifier_profiles'])}"
        )
    if "classifier_trace" in expected and trace != expected["classifier_trace"]:
        checks.append(f"classifier_trace {trace} != {expected['classifier_trace']}")
    return checks


def _assert_selections(dec: Any, expected: dict[str, Any]) -> list[str]:
    """Assert per-profile selections and the selected/waiting/applicable sets."""
    checks: list[str] = []
    for profile, sel in expected.get("selections", {}).items():
        if dec.selection_for(profile) != sel:
            checks.append(f"{profile} selection {dec.selection_for(profile)!r} != {sel!r}")
    for key, getter in (
        ("selected_profiles", dec.selected_profiles),
        ("waiting_profiles", dec.waiting_profiles),
        ("applicable_profiles", dec.applicable_profiles),
    ):
        if key in expected and sorted(getter()) != sorted(expected[key]):
            checks.append(f"{key} {sorted(getter())} != {sorted(expected[key])}")
    return checks


def _assert_counts(dec: Any, expected: dict[str, Any]) -> list[str]:
    """Assert the not_applicable / excluded_typed counts and the exclusion reason."""
    checks: list[str] = []
    for key, sel_state in (
        ("not_applicable_count", SELECTION_NOT_APPLICABLE),
        ("excluded_typed_count", SELECTION_EXCLUDED_TYPED),
    ):
        if key in expected:
            count = sum(1 for p in SCIENCE_LAB_PROFILES if dec.selection_for(p) == sel_state)
            if count != expected[key]:
                checks.append(f"{key} {count} != {expected[key]}")
    if "excluded_typed_reason" in expected:
        for p in SCIENCE_LAB_PROFILES:
            if dec.selection_for(p) == SELECTION_EXCLUDED_TYPED:
                reason = dec.profiles[p].exclusion_reason
                if reason != expected["excluded_typed_reason"]:
                    checks.append(
                        f"{p} exclusion_reason {reason!r} != {expected['excluded_typed_reason']!r}"
                    )
                break
    return checks


def _assert_plan(plan: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Assert the plan-step-count and the DAG depends_on edges."""
    checks: list[str] = []
    if "plan_step_count" in expected and len(plan["steps"]) != expected["plan_step_count"]:
        checks.append(f"plan_step_count {len(plan['steps'])} != {expected['plan_step_count']}")
    for step in plan["steps"]:
        sid = step["step_id"]
        if "dag_edges" in expected and sid in expected["dag_edges"]:
            if sorted(step["depends_on"]) != sorted(expected["dag_edges"][sid]):
                checks.append(
                    f"{sid} depends_on {sorted(step['depends_on'])} != "
                    f"{sorted(expected['dag_edges'][sid])}"
                )
    return checks


def _assert_scenario(scenario: dict[str, Any], dec: Any, plan: dict[str, Any]) -> list[str]:
    """Assert one positive scenario's expected block; return a list of failures.

    Delegates to the per-category helpers so each stays under the complexity
    budget.
    """
    expected = scenario.get("expected", {})
    checks: list[str] = []
    checks += _assert_classifier(scenario, expected)
    checks += _assert_selections(dec, expected)
    checks += _assert_counts(dec, expected)
    checks += _assert_plan(plan, expected)
    return checks


def _replay_positive_fixtures(cat: CapabilityCatalog, pol: AdmissionPolicy) -> list[dict[str, Any]]:
    """Replay each positive scenario fixture and assert its expected block."""
    results: list[dict[str, Any]] = []
    for path in sorted(_FIXTURES.glob("p*.scenario.json")):
        name = path.name.removesuffix(".scenario.json")
        try:
            scenario = json.loads(path.read_text(encoding="utf-8"))
            claim = scenario["claim"]
            req = _build_request_from_scenario(scenario["request"])
            dec = route(req, claim, cat, pol)
            plan = build_plan(req, dec, cat, pol)
            checks = _assert_scenario(scenario, dec, plan)
            if checks:
                results.append({"name": name, "status": "FAIL", "checks": checks})
            else:
                results.append({"name": name, "status": "PASS", "plan_id": plan["plan_id"]})
        except (OSError, json.JSONDecodeError, ContractError, KeyError) as exc:
            results.append({"name": name, "status": "FAIL", "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# B14-02 decision coverage (all 15 profiles, no silent drops).
# ---------------------------------------------------------------------------


def _check_b14_02() -> dict[str, Any]:
    """B14-02: the decision covers all 15 profiles; every state reachable + typed."""
    cat = load_default_catalog()
    pol = default_policy()

    # A claim that auto-classifies to a single profile (NOT_APPLICABLE for rest).
    claim_auto = {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": "Persistent homology of a point cloud.",
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    req_auto = build_request(claim_id=_DIGEST, requested_profiles=[])
    dec_auto = route(req_auto, claim_auto, cat, pol)
    # Coverage: every profile has a decision.
    covered = all(p in dec_auto.profiles for p in SCIENCE_LAB_PROFILES)
    # The four states: WAIT_CAPABILITY reachable (geometry_tda adapterless);
    # NOT_APPLICABLE reachable (the 14 others).
    wait_reachable = any(
        dec_auto.selection_for(p) == SELECTION_WAIT_CAPABILITY for p in SCIENCE_LAB_PROFILES
    )
    na_reachable = any(
        dec_auto.selection_for(p) == SELECTION_NOT_APPLICABLE for p in SCIENCE_LAB_PROFILES
    )

    # SELECTED reachable only with an available adapter; build a synthetic
    # available-adapter catalog so SELECTED is exercised.
    synth_doc = {
        "schema_version": "CapabilityCatalog/v1",
        "capabilities": [
            {
                "capability_id": f"cap.{p}",
                "profile": p,
                "adapter_id": f"adapter-{p}",
                "availability": "available",
            }
            for p in SCIENCE_LAB_PROFILES
        ],
    }
    synth_cat = load_catalog(synth_doc)
    req_explicit = build_request(
        claim_id=_DIGEST, requested_profiles=["algebra_exact", "uncertainty"]
    )
    dec_excl = route(req_explicit, claim_auto, synth_cat, pol)
    selected_reachable = any(
        dec_excl.selection_for(p) == SELECTION_SELECTED for p in SCIENCE_LAB_PROFILES
    )
    excluded_reachable = any(
        dec_excl.selection_for(p) == SELECTION_EXCLUDED_TYPED for p in SCIENCE_LAB_PROFILES
    )
    # Every EXCLUDED_TYPED must carry a non-null reason.
    excl_reasoned = all(
        dec_excl.profiles[p].exclusion_reason
        for p in SCIENCE_LAB_PROFILES
        if dec_excl.selection_for(p) == SELECTION_EXCLUDED_TYPED
    )

    cases = [
        {"case": "coverage-all-15", "pass": covered},
        {"case": "state-WAIT_CAPABILITY-reachable", "pass": wait_reachable},
        {"case": "state-NOT_APPLICABLE-reachable", "pass": na_reachable},
        {"case": "state-SELECTED-reachable", "pass": selected_reachable},
        {"case": "state-EXCLUDED_TYPED-reachable", "pass": excluded_reachable},
        {"case": "EXCLUDED_TYPED-always-reasoned", "pass": excl_reasoned},
    ]
    failures = [c["case"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"coverage/state checks failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "every decision covers all 15 profiles (no silent drops); all four "
            "selection states reachable; EXCLUDED_TYPED always carries a reason"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# B14-03 no silent fallback (remote_required never runs local).
# ---------------------------------------------------------------------------


def _check_b14_03() -> dict[str, Any]:
    """B14-03: a remote_required profile never produces a local step."""
    cat = load_default_catalog()
    pol = default_policy()
    # A claim engaging remote_required profiles (literature + extraction).
    claim_lit = {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": "A literature-sourced established law reference.",
        "claim_class": "established_law_reference",
        "claim_status": "supported",
        "epistemic_source": "literature",
        "support_refs": [_DIGEST],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    req = build_request(claim_id=_DIGEST, requested_profiles=[])
    dec = route(req, claim_lit, cat, pol)
    plan = build_plan(req, dec, cat, pol)

    # Every remote_required profile in the catalog must have NO local step
    # (adapter_id null) in the plan, regardless of selection state.
    remote_profiles = {p for p in SCIENCE_LAB_PROFILES if cat.is_remote_required(p)}
    violations: list[str] = []
    for step in plan["steps"]:
        if step["profile"] in remote_profiles and step["adapter_id"] is not None:
            violations.append(f"{step['profile']} has local adapter_id {step['adapter_id']!r}")
    # Also assert the remote profiles that apply route WAIT_CAPABILITY (not SELECTED).
    remote_waiting = all(
        dec.selection_for(p) == SELECTION_WAIT_CAPABILITY
        for p in remote_profiles
        if p in dec.applicable_profiles()
    )

    # Stronger: build a catalog where a remote_required entry NAMES an adapter_id
    # (ripser-like), and assert the router STILL does not engage it locally.
    tricky_doc = {
        "schema_version": "CapabilityCatalog/v1",
        "capabilities": [
            {
                "capability_id": "cap.literature",
                "profile": "literature",
                "adapter_id": "some-remote-adapter",
                "availability": "remote_required",
            }
        ],
    }
    tricky_cat = load_catalog(tricky_doc)
    dec_tricky = route(req, claim_lit, tricky_cat, pol)
    lit_step = next(
        s
        for s in build_plan(req, dec_tricky, tricky_cat, pol)["steps"]
        if s["profile"] == "literature"
    )
    tricky_no_local = (
        lit_step["adapter_id"] is None and lit_step["selection"] == SELECTION_WAIT_CAPABILITY
    )

    cases = [
        {"case": "no-local-step-for-remote", "pass": not violations, "violations": violations},
        {"case": "remote-applicable-waits", "pass": remote_waiting},
        {"case": "remote-with-named-adapter-still-waits", "pass": tricky_no_local},
    ]
    failures = [c["case"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"silent-fallback checks failed: {failures}",
            "cases": cases,
            "remote_profiles": sorted(remote_profiles),
        }
    return {
        "status": "PASS",
        "detail": (
            "remote_required profiles never produce a local step (adapter_id null); "
            "even a remote_required entry naming an adapter_id routes WAIT_CAPABILITY "
            "(no silent fallback)"
        ),
        "cases": cases,
        "remote_profiles": sorted(remote_profiles),
    }


# ---------------------------------------------------------------------------
# B14-04 unknown capability -> WAIT_CAPABILITY + negative fixtures.
# ---------------------------------------------------------------------------


def _check_b14_04() -> dict[str, Any]:
    """B14-04: unknown capability -> WAIT_CAPABILITY; negative fixtures reject."""
    pol = default_policy()
    cases: list[dict[str, Any]] = []

    # Unknown capability: a catalog with one unrelated entry, so geometry_tda is
    # absent (unknown to the catalog). A profile absent from the catalog routes
    # WAIT_CAPABILITY (the router never fabricates an adapter).
    sparse_cat = load_catalog(
        {
            "schema_version": "CapabilityCatalog/v1",
            "capabilities": [
                {
                    "capability_id": "cap.algebra_exact",
                    "profile": "algebra_exact",
                    "adapter_id": None,
                    "availability": "future",
                }
            ],
        }
    )
    claim = {
        "schema_version": "ScientificClaim/v1",
        "claim_id": _DIGEST,
        "statement": "Persistent homology of a point cloud.",
        "claim_class": "candidate_hypothesis",
        "claim_status": "proposed",
        "epistemic_source": "operator",
        "support_refs": [],
        "created_utc": "2026-07-28T00:00:00Z",
        "canonical_writes": 0,
        "grants_authority": False,
    }
    req = build_request(claim_id=_DIGEST, requested_profiles=["geometry_tda"])
    dec = route(req, claim, sparse_cat, pol)
    plan = build_plan(req, dec, sparse_cat, pol)
    geo_step = next(s for s in plan["steps"] if s["profile"] == "geometry_tda")
    geo_routing = dec.profiles["geometry_tda"]
    unknown_waits = (
        dec.selection_for("geometry_tda") == SELECTION_WAIT_CAPABILITY
        and geo_step["adapter_id"] is None
        and geo_routing.availability == "unknown"
    )
    cases.append({"case": "unknown-capability-waits", "pass": unknown_waits})

    # Negative fixture n01: cyclic dependency -> PlanError (cycle_detected).
    cycle_raised = False
    cycle_invariant = ""
    cycle_reason = ""
    try:
        # a -> b -> a cycle.
        topological_order(
            ["dynamics", "executable_ode_dae_sde_model"],
            {
                "dynamics": {"executable_ode_dae_sde_model"},
                "executable_ode_dae_sde_model": {"dynamics"},
            },
        )
    except PlanError as exc:
        cycle_raised = True
        cycle_invariant = exc.invariant
        cycle_reason = exc.fail_reason
    cases.append(
        {
            "case": "cyclic-dependency-rejected",
            "pass": cycle_raised and cycle_invariant == "cycle_detected",
            "fail_reason": cycle_reason,
            "invariant": cycle_invariant,
        }
    )

    # Negative fixture n02: resource overflow -> ResourceAdmissionError
    # (WAIT_REMOTE_EXECUTOR). Build a synthetic available-adapter catalog so the
    # steps are SELECTED, then engage enough heavy profiles to exceed caps.
    overflow_raised = False
    overflow_reason = ""
    overflow_over: dict[str, dict[str, int]] = {}
    try:
        heavy_doc = {
            "schema_version": "CapabilityCatalog/v1",
            "capabilities": [
                {
                    "capability_id": f"cap.{p}",
                    "profile": p,
                    "adapter_id": f"adapter-{p}",
                    "availability": "available",
                }
                for p in SCIENCE_LAB_PROFILES
            ],
        }
        heavy_cat = load_catalog(heavy_doc)
        # Engage the heaviest profiles under exception caps to force overflow.
        req_heavy = build_request(
            claim_id=_DIGEST,
            requested_profiles=[
                "pde_variational_model",
                "geometry_tda",
                "nonlinear_continuous_or_hybrid_constraint",
                "executable_ode_dae_sde_model",
            ],
            resource_class="exception",
        )
        dec_heavy = route(req_heavy, claim, heavy_cat, pol)
        build_plan(req_heavy, dec_heavy, heavy_cat, pol)
    except ResourceAdmissionError as exc:
        overflow_raised = True
        overflow_reason = exc.fail_reason
        overflow_over = dict(exc.over)
    cases.append(
        {
            "case": "resource-overflow-rejected",
            "pass": overflow_raised and overflow_reason == "WAIT_REMOTE_EXECUTOR",
            "fail_reason": overflow_reason,
            "over": overflow_over,
        }
    )

    failures = [c["case"] for c in cases if not c["pass"]]
    if failures:
        return {
            "status": "FAIL",
            "detail": f"unknown/negative checks failed: {failures}",
            "cases": cases,
        }
    return {
        "status": "PASS",
        "detail": (
            "an unknown capability routes WAIT_CAPABILITY (no fabricated adapter); "
            "a cyclic dependency raises PlanError (CONTRACT_INVALID, cycle_detected); "
            "resource overflow raises ResourceAdmissionError (WAIT_REMOTE_EXECUTOR)"
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Evidence helpers + receipt assembly.
# ---------------------------------------------------------------------------


def _evidence() -> dict[str, Any]:
    """Compact evidence summary: fixture vector counts + profile/schema counts."""
    neg = _FIXTURES / "negative"
    return {
        "positive_vectors": len(list(_FIXTURES.glob("p*.scenario.json"))),
        "negative_vectors": len(list(neg.glob("n*.expected_error.json"))) if neg.is_dir() else 0,
        "profile_count": len(SCIENCE_LAB_PROFILES),
        "default_caps": dict(DEFAULT_CAPS),
        "exception_caps": dict(EXCEPTION_CAPS),
    }


def _build_receipt() -> dict[str, Any]:
    """Run all four checks and assemble the GateReceipt/v1 dict."""
    checks = {
        "B14-01": _check_b14_01(),
        "B14-02": _check_b14_02(),
        "B14-03": _check_b14_03(),
        "B14-04": _check_b14_04(),
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
            **_evidence(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate. Returns 0 iff every check PASSes."""
    args = sys.argv[1:] if argv is None else argv

    # Optional single-check mode for the checks.json invocations.
    if args and args[0] == "--check":
        cid = args[1] if len(args) > 1 else ""
        runners = {
            "B14-01": _check_b14_01,
            "B14-02": _check_b14_02,
            "B14-03": _check_b14_03,
            "B14-04": _check_b14_04,
        }
        runner = runners.get(cid)
        if runner is None:
            _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "error": f"unknown check {cid}"})
            return 2
        result = runner()
        _emit({"schema_version": GATE_SCHEMA, "wp_id": WP_ID, "check": cid, **result})
        return 0 if result["status"] == "PASS" else 1

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
