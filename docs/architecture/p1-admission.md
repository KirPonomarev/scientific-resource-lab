# P1 admission framework (WP-H70)

WP-H70 defines the **P1** layer of pack admission: the machine-checkable
decision to invest in building an actual-compute adapter for an *external
scientific capability* before any pack exists. It sits one layer above the P0
admission pipeline (WP-C23, `srl.packs.admission`), which moves an *already
built* pack through nine stages from `DISCOVERED` to `EXPERIMENTAL_ACCEPTED`.

The framework is implemented in three places:

- `policies/p1-admission.json` — the canonical `P1AdmissionPolicy/v1` policy
  document: the eight admission requirements as machine-checkable fields.
- `src/srl/packs/p1.py` — `evaluate_p1_candidate(candidate, policy) -> P1Verdict`,
  the typed-verdict evaluator, plus the four first-wave candidate cards as
  honest data.
- `scripts/checks/wp70-gate.py` — the `GateReceipt/v1` acceptance gate.

## The eight P1 admission requirements

A candidate capability is admitted to the P1 pipeline only when **all eight**
requirements carry honest evidence. Each requirement is a single
machine-checkable field in the policy document, pinning the kind of evidence it
expects.

| Requirement | Evidence kind | What it asserts |
| --- | --- | --- |
| `unique_capability` | document | The capability fills a distinct slot in the SRL capability registry; it is not a duplicate of an admitted capability. |
| `concrete_hypothesis` | document | A concrete, falsifiable scientific hypothesis names the capability and the experiment that would test it. |
| `license_closure` | receipt | The upstream SPDX has been identified and cleared against the SRL pack license policy (the receipt issued by the P0 `LICENSE_CLEARED` stage). |
| `platform_build` | test | The candidate builds and runs on at least one declared SRL platform (`linux`/`macos`, `x86_64`/`arm64`). |
| `resource_measurement` | measurement | An honest measured resource footprint (expanded bytes, RSS, wall seconds) exists for the candidate. |
| `actual_compute_adapter` | receipt | A real actual-compute adapter exists for the capability (not a stub). |
| `independent_scientific_role` | document | The capability plays a role that is not already covered by another admitted capability; it earns its place in the fabric. |
| `removal_rollback_path` | document | A documented, tested path to cleanly remove the capability (uninstall the adapter and drop it from the registry). |

Evidence is **never inferred**. A requirement id present in a candidate card's
`evidence` block means the requirement carries honest evidence; an id absent
means the evidence is missing and the requirement is reported in the verdict's
`missing` list.

## Typed verdicts

`evaluate_p1_candidate(candidate, policy)` returns a `P1Verdict` with a typed
outcome and the explicit list of missing requirement ids. The verdict is typed
by the **most severe** gap, in this order of severity (most severe last):

1. `ADMIT_TO_PIPELINE` — every required requirement carries evidence.
2. `WAIT_RESOURCE` — only `resource_measurement` is missing.
3. `WAIT_CAPABILITY` — a capability-class requirement is missing
   (`unique_capability`, `concrete_hypothesis`, `platform_build`,
   `actual_compute_adapter`, or `independent_scientific_role`).
4. `WAIT_LICENSE` — `license_closure` is missing: the upstream license has not
   been identified or cleared.
5. `REJECT_CONTRACT` — `removal_rollback_path` is missing: the candidate has no
   documented clean-removal path and must never enter the fabric.

Severity is ordered so that the hardest blockers dominate. A candidate with no
rollback path is rejected outright even if it also has a license gap; a
candidate with a license gap is held at `WAIT_LICENSE` even if it also has
capability gaps. The `missing` list is always emitted in canonical requirement
order, independent of which verdict dominates.

## Honest WAIT semantics

The four first-wave P1 candidate cards (`pymc_arviz`, `cvxpy`,
`tigramite_dowhy`, `pyoperon`) are filled to their **honest current state**:
none of them has a built actual-compute adapter, a measured resource footprint,
a passing platform build test, or a registered unique capability yet, so most
requirements carry no evidence. Their verdicts are `WAIT_*`, and that is
correct and intentional.

The P1 framework and its machine-checkable gate **exist before any of the
first-wave packs are built**. An admission decision is never faked: no card is
pushed into `ADMIT_TO_PIPELINE` until every requirement genuinely carries
evidence. The WAIT verdicts are not failures; they are the framework doing its
job — naming exactly which evidence is still owed before adapter work begins.

The first-wave cards do carry two pieces of honest partial evidence so the
verdict type is meaningful rather than vacuous:

- `license_closure` records the **declared** upstream SPDX and the honest flag
  `cleared_against_policy: false` (the SPDX is known but no P0 clearance
  receipt has been issued yet).
- `removal_rollback_path` records a documented `pip-uninstall + drop-from-
  registry` rollback mechanism.

With rollback present, the capability-class gaps dominate, so the first-wave
verdicts are `WAIT_CAPABILITY` listing the six capability/resource/adapter
requirements still owed. `tigramite_dowhy` additionally records an honest
`GPL-3.0-or-later` upstream SPDX: the GPL family is barred by the SRL pack
policy, so a future clearance attempt on that candidate would move its verdict
toward `REJECT_CONTRACT`.

## The removal-rollback-path requirement

`removal_rollback_path` is the only requirement whose absence forces
`REJECT_CONTRACT` rather than a `WAIT_*`. The rationale is operational, not
scientific:

- A capability admitted to the SRL fabric becomes a dependency of experiments,
  adapters, and downstream receipts. Removing one later is expensive and
  error-prone unless the removal path was designed before admission.
- A capability we **cannot** cleanly remove must never enter the fabric, even if
  its science and license are perfect. A missing rollback path is a contract
  gap with the fabric, not a deficiency we can wait out; hence it is the most
  severe verdict and the only one that rejects outright.
- A documented rollback path (e.g. "uninstall the adapter via `pip uninstall`,
  then drop the capability id from the registry") makes the capability
  reversible: it can be added, and if it turns out to be wrong, removed without
  orphaned state. This mirrors the P0 pipeline's append-only receipt chain:
  admission is reversible-by-removal even though receipts are immutable.

## `P1AdmissionPolicy/v1`

The canonical policy is `policies/p1-admission.json`, encoded as canonical JSON
(sorted keys, compact separators, trailing newline) matching the
`ResourcePolicy/v1` convention. All eight requirements are `required: true`;
each pins its `evidence_kind` from the allowlist `["receipt", "document",
"test", "measurement"]`. `canonical_writes` is always `0` (a policy is a
read-only contract document) and `grants_authority` is always `false` (a policy
declaration grants no scientific authority).

## Acceptance gate

`scripts/checks/wp70-gate.py` runs four checks and emits a `GateReceipt/v1`:

- **H70-01** a fully-evidenced synthetic candidate returns `ADMIT_TO_PIPELINE`
  with an empty `missing` list.
- **H70-02** removing each requirement one at a time returns that requirement's
  typed verdict (`WAIT_LICENSE`, `WAIT_RESOURCE`, `REJECT_CONTRACT`, or
  `WAIT_CAPABILITY`) and reports exactly that requirement id as missing.
- **H70-03** the four first-wave candidate cards produce typed `WAIT_*` verdicts
  with explicit missing evidence; none is faked into `ADMIT_TO_PIPELINE`.
- **H70-04** a candidate carrying every requirement except `license_closure`
  returns `WAIT_LICENSE`, proving the license-unknown policy independently.

The gate exits non-zero on any failure.

## Relationship to P0 (WP-C23) and execution

P0 (WP-C23) admits a *built pack*; P1 decides whether to *build* one. The P1
`license_closure` requirement is satisfied by the receipt the P0
`LICENSE_CLEARED` stage issues, so P1 and P0 share one license policy rather
than two. A candidate that reaches `ADMIT_TO_PIPELINE` at P1 is cleared to
enter the P0 pipeline; a candidate held at any `WAIT_*` or `REJECT_CONTRACT` is
not. The actual-compute adapter referenced by `actual_compute_adapter` is the
same object the P0 `ACTUAL_COMPUTE_PROBED` stage later proves, so the two
layers share one notion of "a real adapter exists".
