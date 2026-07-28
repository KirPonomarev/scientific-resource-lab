# Autonomous workflow

This document is the architecture reference for how autonomous work moves
through the Scientific Resource Lab repository under `AutonomyPolicy/v1`. It
covers the Git lifecycle state machine, work-package identity, the commit and
auto-merge policy, deterministic resume, and the retry policy. The
machine-checkable contracts live in `automation/` and `src/srl/autonomy/`;
this document is the prose that explains *why* they are shaped the way they
are.

Everything here is an *admission* contract. A green state in this machine
means a change satisfied the automation contract; it never means a scientific
claim is supported (see `GOVERNANCE.md` for the evidence rules).

## Git lifecycle state machine

An autonomous work package moves through a fixed sequence of Git states. The
only admitted transitions are the arrows below; any other transition is a
contract violation and must be reconciled or stopped.

```mermaid
stateDiagram-v2
    [*] --> DISCOVER
    DISCOVER --> CLAIM
    CLAIM --> BRANCH
    BRANCH --> IMPLEMENT
    IMPLEMENT --> LOCAL_VALIDATE
    LOCAL_VALIDATE --> REPAIR: checks fail (bounded)
    REPAIR --> LOCAL_VALIDATE
    LOCAL_VALIDATE --> COMMIT: checks pass
    COMMIT --> PUSH
    PUSH --> PR_OPEN
    PR_OPEN --> CI_WAIT
    CI_WAIT --> REPAIR: CI fails (bounded)
    CI_WAIT --> MERGE_READY: all checks pass
    MERGE_READY --> SQUASH_MERGE
    SQUASH_MERGE --> SYNC_MAIN
    SYNC_MAIN --> RECEIPT
    RECEIPT --> NEXT_WP
    NEXT_WP --> [*]

    CI_WAIT --> STOP: unresolvable failure
    MERGE_READY --> STOP: conditions unmet
    STOP --> [*]
```

Each state has one responsibility:

| State             | Responsibility                                                       |
|-------------------|----------------------------------------------------------------------|
| `DISCOVER`        | Read the plan, the policy, and the canonical runtime state.          |
| `CLAIM`           | Claim the work package; record its identity fields.                  |
| `BRANCH`          | Create a feature branch from the latest `main`.                      |
| `IMPLEMENT`       | Make the focused change within the declared write scope.             |
| `LOCAL_VALIDATE`  | Run `make verify` and the WP gate locally before any commit.         |
| `REPAIR`          | Apply a bounded fix cycle when a check fails.                        |
| `COMMIT`          | Create conventional commits once local checks pass.                  |
| `PUSH`            | Push the branch to the remote (`-u`).                                |
| `PR_OPEN`         | Open one pull request with the required body sections.               |
| `CI_WAIT`         | Wait for all required CI checks.                                     |
| `MERGE_READY`     | Verify the auto-merge conditions (below) all hold.                   |
| `SQUASH_MERGE`    | Squash-merge into `main`, preserving linear history.                 |
| `SYNC_MAIN`       | Sync local `main` to the merged commit.                              |
| `RECEIPT`         | Write the closeout receipt (provenance only; never a scientific claim). |
| `NEXT_WP`         | Advance to the next work package.                                    |

## Work-package identity

A work package (WP) is identified by five fields, recorded at `CLAIM`:

| Field            | Meaning                                                         |
|------------------|-----------------------------------------------------------------|
| `repository_id`  | Stable repository identity (`owner/repo`).                      |
| `mission_digest` | SHA-256 hex of the mission manifest under which the WP runs.    |
| `wp_id`          | The work-package identifier (e.g. `WP-A03`).                    |
| `base_sha`       | The `main` commit the WP branched from.                         |
| `policy_sha`     | SHA-256 hex of the canonical policy document in force.          |

These five fields are the input to the idempotency key (below). Together they
answer: *the same work, against the same base, under the same policy*. A
change to any field means the WP is no longer the same unit of work, and any
artifacts bound to the old key must be recomputed rather than reused.

The declared write scope (the set of paths a WP may mutate) is recorded at
`CLAIM` and enforced pre-write by `srl.autonomy.scopes.check_write`. A write
outside the owned set, or an absolute / `..`-traversal path, raises
`ScopeViolation` (typed fail reason `CONTRACT_INVALID`) before any file is
touched.

## Commit policy

- **Conventional commits only.** Every commit subject (and the squash-merge
  subject on `main`) follows Conventional Commits with the project's type
  set (`feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`,
  `perf`, `security`). See `CONTRIBUTING.md`.
- **No direct push to `main`.** The `main-protection-v1` ruleset blocks
  force-pushes and deletions, requires linear history, and requires a pull
  request. Merges are squash merges.
- **No secrets, no private data, no absolute local paths.** The public
  boundary holds: the repository contains code, schemas, synthetic fixtures
  and sanitized documentation only. The pre-commit leak guard
  (`srl.autonomy.leakguard`) scans staged diff content for absolute POSIX
  home paths (`/Users/<name>`, `/home/<name>`), `/Volumes/` paths, secret
  token shapes (`ghp_`, `gho_`, `github_pat_`, `sk-`, `AKIA…`, PEM private
  key headers) and long hex secrets, and refuses the commit with typed fail
  reason `PUBLIC_LEAK_DETECTED`.
- **Synthetic fixtures only.** Tests and gates that exercise the leak guard
  construct obviously-fake fixtures inline (e.g.
  `ghp_EXAMPLE000000000000000000000000000000`); real-looking credentials are
  never committed.

## Auto-merge conditions

A pull request is auto-mergeable at `MERGE_READY` only when **all ten** of the
following hold. The reconciler must verify each; any one missing routes back
to `REPAIR` or to a stop.

1. The PR originates from a branch owned by this mission (no external PR).
2. The base branch is `main` and has not drifted (the PR is rebased onto the
   latest `main`, or the merge is a clean fast-forward through squash).
3. All required CI checks pass (lint, typecheck, the unit matrix, the package
   job, and the WP-A03 autonomy-contracts gate).
4. No CI check is in a failing or indeterminate state.
5. The squash-merge would preserve linear history (no merge commits).
6. All review conversations are resolved (enforced by the ruleset).
7. The leak guard reports no findings on the final diff.
8. The change is within the declared write scope for the WP.
9. The policy in force is the immutable `AutonomyPolicy/v1` for this mission
   (`canonical_runtime_mutation` is `false`).
10. The merge method is squash (the policy's `merge_method`).

External pull requests are never auto-merged (`external_pr_auto_merge` is
`false` under v1).

## Post-merge steps

After `SQUASH_MERGE`:

1. **`SYNC_MAIN`** — fetch and fast-forward local `main` to the merged
   commit. The canonical HEAD must match the recorded `base_sha` lineage; a
   mismatch is `CANONICAL_HEAD_MISMATCH` (hard stop).
2. **`RECEIPT`** — write a `WorkPackageCloseoutReceipt/v1` recording the WP,
   the merge commit, the PR, the changed paths, and the evidence (local
   gates, CI run, reproducible manifest hash). The receipt is provenance
   only; it never asserts a scientific claim.
3. **`NEXT_WP`** — advance the automation state and claim the next WP.

## Idempotency key

The idempotency key is the SHA-256 of the canonical JSON encoding of the
ordered tuple:

```
(repository_id, mission_digest, wp_id, base_sha, policy_sha)
```

Implemented by `srl.autonomy.resume.idempotency_key`. The key anchors resume:
two runs with the same key are *the same work*, and prior artifacts bound to
that key may be reused rather than recomputed. A change to any of the five
fields invalidates the key and forces a rerun.

The canonical encoding uses a JSON **list** (not a dict) so the field order
is fixed and the key is independent of any dict insertion order. The
encoding is sorted-key, compact-separator, ASCII-only canonical JSON, so the
key is byte-stable across implementations.

## Deterministic resume

When a run is interrupted and resumed, `srl.autonomy.resume.reconcile`
answers one question deterministically: given the observed state, what is the
single correct next action? The answer must be identical for identical
inputs on any machine, so two resumes over the same serialized state produce
byte-identical decision JSON.

The resume table, in precedence order (first match wins):

| Observed state                                | Decision          | Permits merge |
|-----------------------------------------------|-------------------|---------------|
| external commit on the target branch          | `STOP_EXTERNAL`   | no            |
| working tree in unknown dirty state           | `STOP_DRIFT`      | no            |
| WP inputs changed since last recorded run     | `RERUN`           | no            |
| output hash matches (expected == computed)    | `NOOP_VERIFIED`   | no            |
| PR merged, checks failing                     | `STOP_DRIFT`      | no            |
| PR merged, checks passing                     | `RECONCILE_MERGED`| **yes**       |
| commit exists, checks failing                 | `UPDATE_PR`       | no            |
| commit exists, checks passing                 | `REUSE_COMMIT`    | no            |
| open PR exists (not merged)                   | `UPDATE_PR`       | no            |
| no recognized prior state (default)           | `RERUN`           | no            |

Two properties matter most:

- **Only `RECONCILE_MERGED` permits merge.** Every other decision describes
  work that is not yet merged, or a stop that forbids merge. A failing check
  can never reach a merge-permitting decision: the merged and commit rows
  split into a passing-check and failing-check variant, and the failing
  variants route to `STOP_DRIFT` or `UPDATE_PR` respectively.
- **Deterministic output.** `decision_to_json` serializes a decision to
  canonical JSON; two `reconcile` calls over the same observed state yield
  byte-identical JSON. This is the contract the WP-A03 gate (A03-05) checks.

## Retry policy

Retries are bounded and narrow. The agent may retry **at most 2 times**,
with backoff and jitter, **only** for these transient classes:

- explicit HTTP **429** (rate limit) — e.g. `GITHUB_RATE_LIMITED`;
- **5xx** server errors from the platform;
- a **network reset before any response** was received.

Retries are **never** permitted for:

- permission failures (`GITHUB_AUTH_UNAVAILABLE`, `RULESET_BLOCKED`);
- privacy failures (`PUBLIC_LEAK_DETECTED`);
- license failures (`LICENSE_UNKNOWN`, `LICENSE_INCOMPATIBLE`);
- policy or contract failures (`CONTRACT_INVALID`, `SCHEMA_BREAKING_CHANGE`);
- hash or integrity failures (`CAS_INTEGRITY_FAILURE`, `PACK_INTEGRITY_FAILURE`,
  `CANONICAL_HEAD_MISMATCH`, `CANONICAL_BOOTSTRAP_RED`);
- injection or security failures (`NETWORK_POLICY_VIOLATION`,
  `EXTERNAL_COMMIT_DETECTED`);
- resource failures (`RESOURCE_LIMIT`, `TIMEOUT`, `ORPHAN_PROCESS_DETECTED`);
- scientific failures (`ACTUAL_COMPUTE_FAILED`, `NONDETERMINISTIC_RESULT`);
- conflict / base-drift failures (`PR_CONFLICT`, `DEPENDENCY_LOCK_DRIFT`).

These are not transient and retrying would only burn budget against a
deterministic failure.

**Product CI failures** (`CI_PRODUCT_FAILURE`) follow a separate, tighter
loop: at most **3 bounded fix cycles**. If the check does not pass within 3
cycles, the WP is **parked** (`terminal_status: PARKED`) for human attention
rather than retried indefinitely. Infra-only CI failures (`CI_INFRA_FAILURE`)
are retryable under the 2-retry transient budget above.

The typed fail reasons, their classes, hard-stop flags, and retriable flags
are recorded in `automation/fail-reasons.json` (`FailReasonRegistry/v1`).
Only `GITHUB_RATE_LIMITED` and `CI_INFRA_FAILURE` are marked retriable; every
other reason is terminal within its loop.

## Lane ledger

Under `AutonomyPolicy/v2` the repository may run up to
`max_parallel_implementation_lanes` implementation lanes concurrently
(currently `6`). Concurrency is coordinated through a machine-enforced
**active-lane ledger** (`automation/lanes.json`, `ActiveLaneLedger/v1`):
every lane acquires an entry before it mutates anything, and `acquire_lane`
enforces the policy cap, owned-path disjointness, and worktree uniqueness. Each
lane holds a **lease** with a heartbeat and TTL (default 900s); a lane that
stops heartbeating past its TTL is stopped with fail reason
`ORPHAN_PROCESS_DETECTED`. The policy file is the single source of the lane cap;
the governance gate (`scripts/checks/gov-lanes-gate.py`) proves the cap agrees
across the policy, the state schema, and the enforcement. See
`docs/architecture/lane-management.md` for the full contract.
