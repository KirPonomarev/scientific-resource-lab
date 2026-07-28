# Resource policy and admission semantics (WP-D30, M1)

This document describes the `ResourcePolicy/v1` that governs local scientific
execution in the M1 runner, its two envelopes (default and exception), the
`WAIT_REMOTE_EXECUTOR` overflow action, the free-disk preflight floor, and the
WIP=1 concurrency rule. It is the companion to the machine-readable policy at
`policies/resource-policy-m1.json`, the Python model under
`src/srl/execution/`, and the acceptance gate at `scripts/checks/wp30-gate.py`.

> Everything here is an **admission** contract. A green admission means a step
> fit the resource envelope; it never means a scientific claim is *supported*.
> See `GOVERNANCE.md` for the evidence rules.

## Scope

WP-D30 introduces the resource policy and the pure admission decision that the
runner (WP-D31) will call before launching a step locally. It does not launch
anything itself; it only decides whether a step *may* run locally, must run via
the exception envelope, or must park for a remote executor.

| Concern                       | Artifact                              | Python module                  |
|-------------------------------|---------------------------------------|--------------------------------|
| Resource policy document      | `policies/resource-policy-m1.json`    | `srl.execution.policy`         |
| Resource estimate (per step)  | `ResourceEstimate` dataclass          | `srl.execution.estimate`       |
| Free-disk preflight           | `PreflightReceipt/v1`                 | `srl.execution.platform_probe` |
| Acceptance gate               | `GateReceipt/v1` (WP-D30)             | `scripts/checks/wp30-gate.py`  |

The `srl.execution` package is **standard library only** — it has no dependency
on the scientific contracts layer (and its `jsonschema` runtime dependency) — so
it runs in any environment, including a minimal CI runner.

## The default envelope

The default envelope is the strict set of caps a step must fit to run locally
without any special opt-in. The shipped M1 policy pins these exact integers:

| Field                      | Value            | Meaning                                  |
|----------------------------|------------------|------------------------------------------|
| `cpu_cores`                | `1`              | One CPU core.                            |
| `rss_bytes`                | `1610612736`     | 1.5 GiB resident memory.                 |
| `wall_seconds`             | `300`            | 5 minutes wall-clock.                    |
| `scratch_bytes`            | `4294967296`     | 4 GiB scratch / working set.             |
| `required_free_disk_bytes` | `21474836480`    | 20 GiB free-disk floor (preflight).      |
| `concurrency`              | `1`              | WIP=1: at most one step in flight.       |

The safety consts are pinned: `canonical_writes=0` (a resource policy never
writes) and `grants_authority=false` (admitting a job never grants authority).

## The exception envelope

The exception envelope is a strictly-bounded widening of the default envelope.
It exists for steps that legitimately need a little more (a longer wall budget,
one more core) and is **opt-in**: the caller must pass `use_exception=True` to
`admit` to use it. The shipped M1 exception is:

| Field           | Exception value | Default value | Absolute cap |
|-----------------|-----------------|---------------|--------------|
| `cpu_cores`     | `2`             | `1`           | `<= 2`       |
| `rss_bytes`     | `2147483648`    | `1610612736`  | `<= 2 GiB`   |
| `wall_seconds`  | `900`           | `300`         | `<= 900`     |
| `scratch_bytes` | `4294967296`    | `4294967296`  | `<= default` |

The exception is bounded by absolute caps. Any exception value beyond them is
**rejected at load** with `PolicyError` (`fail_reason='CONTRACT_INVALID'`), so a
policy file cannot silently raise the ceiling:

- `cpu_cores` may not exceed `2`;
- `rss_bytes` may not exceed `2 GiB`;
- `wall_seconds` may not exceed `900`;
- `scratch_bytes` may not exceed the default scratch (the exception **never**
  widens scratch beyond the default).

## `WAIT_REMOTE_EXECUTOR` semantics

A larger job is **never** run locally. When an estimate does not fit either
envelope (or fits only the exception envelope but the caller did not opt in),
`admit` returns `WAIT_REMOTE_EXECUTOR`: the step parks. The runner does not
downgrade the estimate, does not clip it to the caps, and does not run it under
a smaller envelope. It waits for a remote executor (WP-D31 wires the plumbing).

The full admission matrix (`admit(estimate, policy, use_exception=...)`):

| Estimate                         | `use_exception=False` | `use_exception=True`   |
|----------------------------------|-----------------------|------------------------|
| within default                   | `ADMITTED_DEFAULT`    | `ADMITTED_DEFAULT`     |
| over default, within exception   | `WAIT_REMOTE_EXECUTOR`| `ADMITTED_EXCEPTION`   |
| over exception                   | `WAIT_REMOTE_EXECUTOR`| `WAIT_REMOTE_EXECUTOR` |

There is no fourth "silently downgraded" state. This is the load-bearing
property of the admission contract: a step never runs under an envelope it did
not explicitly fit.

## Free-disk floor

Before a step is admitted locally, the runner confirms the host can honour the
policy's free-disk floor via `preflight`. The preflight reads the free bytes
through an injectable provider and raises `ResourceLimitError`
(`fail_reason='RESOURCE_LIMIT'`) when the observed free bytes are strictly less
than `required_free_disk_bytes`. The boundary is inclusive: exactly at the floor
passes.

The provider is injectable (`PreflightProvider` protocol) so preflight is
hermetic in tests: a `StaticPreflightProvider(free_disk_bytes=...)` makes the
measurement a pure function of a chosen value, with no filesystem access. The
default `DiskProbe` reads `shutil.disk_usage` on the real volume.

## WIP=1 concurrency rule

The M1 policy fixes `concurrency=1`: at most one step is in flight locally at a
time. The runner (WP-D31) will enforce this by holding a single admission slot:
a second `admit` that returns `ADMITTED_DEFAULT` or `ADMITTED_EXCEPTION` while a
step is already running parks the new step as `WAIT_REMOTE_EXECUTOR` until the
in-flight step completes and the slot frees. This keeps the local runner
single-threaded and the resource accounting simple; widening WIP is a future
policy change, not a runner behaviour.

## Acceptance gate

The four WP-D30 checks (`scripts/checks/wp30-gate.py`) pin the contract above:

- **D30-01** default caps exact — the six pinned integers load verbatim.
- **D30-02** exception envelope bounded — every over-cap exception value is
  rejected at load (`CONTRACT_INVALID`).
- **D30-03** over-exception estimate parks — no silent downgrade in the
  admission matrix.
- **D30-04** low-disk preflight → `RESOURCE_LIMIT` — the typed fail reason for a
  hard resource limit.

The gate emits a single canonical `GateReceipt/v1` JSON line and exits non-zero
on any `FAIL`.
