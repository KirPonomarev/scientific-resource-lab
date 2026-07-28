# Lane management (WP-GOV-LANES)

This document is the architecture reference for machine-enforced lane
management under `AutonomyPolicy/v2`. The machine-checkable contracts live in
`src/srl/autonomy/lanes.py` and `automation/lanes.json`; this document is the
prose that explains *why* the lane ledger is shaped the way it is.

Under `AutonomyPolicy/v1` the repository ran at most **four** implementation
lanes, fixed. `AutonomyPolicy/v2` (governance-change GOV-0001,
operator-authorized) admits **four to six** lanes: the policy's
`max_parallel_implementation_lanes` is the bound, currently `6`. Concurrency
without coordination would let two lanes clobber the same file, so every lane
must claim its work through the lane ledger before it mutates anything. The
ledger is the single source of truth for *which lanes are active, what each one
owns, and whether its lease is live*.

Everything here is an *admission* contract. A green acquire means the lane
satisfied the lane-ledger contract; it never means a scientific claim is
supported (see `GOVERNANCE.md` for the evidence rules).

## The active-lane ledger

The ledger is `automation/lanes.json`, a canonical `ActiveLaneLedger/v1`
document:

```json
{"lanes":[],"schema_version":"ActiveLaneLedger/v1"}
```

Each lane entry carries its full identity:

| Field                   | Meaning                                                              |
|-------------------------|----------------------------------------------------------------------|
| `lane_id`               | Stable identifier for the lane (e.g. `gov-lane-ledger`).             |
| `wp_id`                 | The work-package identifier the lane is implementing.                |
| `executor`              | One of `glm-5.2`, `kimi-for-coding`, `orchestrator`.                 |
| `worktree_fingerprint`  | SHA-256 hex of the absolute worktree path. The raw path is **never** persisted (the public boundary holds). |
| `branch`                | The git branch the lane is working on.                               |
| `base_sha`              | The commit SHA the lane branched from.                               |
| `owned_paths`           | Repo-relative paths the lane may mutate. Disjointness is enforced.   |
| `lease`                 | `{acquired_utc, heartbeat_utc, ttl_seconds}` (default TTL 900s).     |
| `status`                | One of `active`, `parked`, `completed`, `stopped`.                   |

The ledger is persisted canonically (sorted keys, compact separators,
ASCII-only, single trailing newline) and atomically (tmp + `fsync` +
`os.replace` + directory `fsync`, mirroring the CAS engine discipline). Two
writers over the same set produce byte-identical files. Lanes are serialized
sorted by `lane_id`, so the file is byte-stable for equal content.

## Why the policy is the only cap source

The lane cap is read from `automation/policy.json` via
`srl.autonomy.lanes.policy_lane_cap` — the **same symbol**
`acquire_lane` uses to enforce the bound. The ledger module never hardcodes a
lane number. This is deliberate: it makes the policy file the single source of
the bound, so moving the cap is a governance change (a policy edit under review),
not a code change that could silently slip through.

The governance gate (`scripts/checks/gov-lanes-gate.py`, check GOV-01) proves
the cap has one value across all three places that name it:

1. the policy key `max_parallel_implementation_lanes` (currently `6`);
2. the `max_lanes` const in `automation/state.schema.json` (currently `6`);
3. the bound `acquire_lane` actually enforces.

GOV-01 *derives* the cap from the policy and compares it to the schema const;
it never hardcodes a number. If the policy said `6` but the gate enforced
another number, GOV-01 would FAIL. A unit test pins the same property:
`test_state_schema_max_lanes_matches_policy_cap`.

## Acquire-time invariants

`acquire_lane` enforces three invariants, in order, before a lane starts:

1. **Cap.** The number of currently-active lanes must be below the policy cap.
   A lane past the cap is rejected with fail reason `CONTRACT_INVALID`.
2. **Disjoint ownership.** Every owned path must be disjoint from every active
   lane's owned paths — no equal, no prefix-of (candidate nests under an
   existing owned path), no prefixed-by (candidate encloses an existing owned
   path). A collision raises `PathOwnershipError` naming the conflicting lane,
   with fail reason `CONTRACT_INVALID`. Sibling paths do not collide.
3. **Worktree uniqueness.** The worktree fingerprint must not match an active
   lane's fingerprint. One worktree, one lane. The raw absolute path is never
   persisted.

The disjointness predicate treats owned paths as directory trees: `src/srl/foo/`
and `src/srl/foo/bar.py` collide (containment), but `src/srl/foo/` and
`src/srl/foob/` do not (siblings, not a prefix). This matches the
`scopes.check_write` containment model: if two lanes' owned paths overlapped,
a write in the overlap would be authorized by both scopes and neither lane
could reason about the other's mutation.

## Lease, heartbeat, and expiry

Each active lane holds a **lease**: an acquired-at timestamp, a heartbeat
timestamp, and a TTL (default 900s / 15 minutes). A lane keeps its lease alive
by calling `heartbeat` before the TTL elapses; a lane that stops heartbeating is
treated as an orphaned process.

`expire_leases(ledger, now)` transitions every active lane whose
`heartbeat_utc + ttl_seconds` is in the past to status `stopped`. The fail
reason is `ORPHAN_PROCESS_DETECTED` (documented in
`automation/fail-reasons.json`, class `ci`, `hard_stop=true`, `retriable=false`):
a lane that stops heartbeating is not retried, it is stopped for human
attention. Stopping a lane releases its cap slot and its ownership claim, so a
fresh disjoint lane may acquire the freed slot.

## Release

`release_lane(ledger, lane_id, status)` transitions a lane to `parked` or
`completed`. Release is **idempotent**: releasing an already-released lane into
the same status is a no-op. A parked or completed lane releases its ownership
claim (its owned paths become acquirable by a new lane) and its cap slot.
`active` is not an admissible release status — use `heartbeat` to keep a lane
active.

## Crash safety

The ledger write is atomic and matches the CAS engine's durability contract:

- the temp file is created in the same directory as the target (so the rename
  is atomic on the same filesystem);
- the temp is `fsync`ed before the rename;
- the rename is `os.replace` (atomic publish);
- the containing directory is `fsync`ed after the rename (best-effort: a
  filesystem that refuses directory `fsync` still got the atomic rename);
- on any failure the temp is removed and the original file is left intact.

A crash mid-write leaves the previously-persisted ledger byte-intact (old
state, never partial). The governance gate (GOV-05) proves this by injecting a
failure at `os.replace` and asserting the old bytes are unchanged and no temp
remains.

## State schema extension

`automation/state.schema.json` (`AutomationStateSchema/v1`) was extended
**additively** with two optional fields:

- `active_lanes` — an array of lane entries mirroring the ledger shape, bounded
  by `maxItems: 6`;
- `max_lanes` — an integer const (`6`) that MUST equal the policy cap.

Both fields are optional: an `AutomationState` document without them still
validates (the `required` array is unchanged). The gate (GOV-01) and a unit
test pin that `max_lanes` equals the policy cap, so the three sources of the
bound cannot drift.

## Governance gate

`scripts/checks/gov-lanes-gate.py` runs five checks and emits a
`GateReceipt/v1`; it exits nonzero on any FAIL. It is wired into CI as the
`gov-lanes-gate` job in `.github/workflows/ci.yml`.

| Check  | What it proves                                                         |
|--------|------------------------------------------------------------------------|
| GOV-01 | policy cap == schema `max_lanes`; the gate derives the cap (no hardcode). |
| GOV-02 | `acquire_lane` admits the cap number of lanes and rejects one more.    |
| GOV-03 | exact / prefix-of / prefixed-by ownership collisions are all rejected. |
| GOV-04 | a lane past its TTL is stopped; a heartbeating lane survives.          |
| GOV-05 | a mid-write failure leaves the old ledger byte-intact; no temp remains.|

Because this work package touches protected governance paths (`automation/`,
`ci.yml`), it follows the governance-change workflow in `GOVERNANCE.md`: the
old verifier (the full unit suite plus `wp03-gate`) must pass against the new
diff before the PR opens. Those run in CI, not in this gate.
