# Adversarial Runner Suite (WP-D34)

This document is the authoritative reference for the adversarial test oracle
that turns the bounded runner (`srl.execution.runner`) into a security test
harness. It is referenced by the `security` and `execution` workflows and by
`scripts/checks/wp34-gate.py`.

The harness lives in `src/srl/execution/adversarial.py`. It runs each adversarial
case against the **real** runner and materializer — never mocks at the harness
level — and asserts the single load-bearing invariant:

> A policy, resource-limit, or output-schema violation NEVER produces a valid
> run receipt.

## Case taxonomy

The suite covers 14 adversarial kinds, enumerated in
`AdversarialKind`. Each kind is backed by a JSON case descriptor under
`fixtures/conformance/adversarial/`:

| Kind | Fixture | Expected | What it proves |
|---|---|---|---|
| `command_injection` | `command-injection.json` | `rejected` | A shell-metacharacter adapter id is rejected at the static registry before any process is created. No shell is ever invoked. |
| `path_injection` | `path-injection.json` | `rejected` | A path-traversal string as an adapter id is an unknown registry key; rejected before spawn. |
| `archive_traversal` | `archive-traversal.json` | `rejected` | An archive/path-traversal hybrid id is rejected at the registry; no archive is opened. |
| `symlink_device` | `symlink-device.json` | `rejected` | A device path (`/dev/null`) as an adapter id is rejected; the registry is not a path resolver. |
| `memory_bomb` | `memory-bomb.json` | `resource_limit` | `bomb.v1` allocates until killed (`RLIMIT_AS` on Linux, wall watchdog on macOS). Bounded; no receipt. |
| `fork_bomb` | `fork-bomb.json` | `resource_limit` | `forker.v1` forks until `RLIMIT_NPROC=256` stops it with `EAGAIN`. Fan-out bounded; no orphan. |
| `output_bomb` | `output-bomb.json` | `resource_limit` | `chatter.v1` exceeds the 1 MiB per-stream output cap; the child is killed; no receipt. |
| `timeout` | `timeout.json` | `timeout` | `sleeper.v1` past the wall cap is killed by the process-group watchdog; no receipt; no orphan. |
| `network_canary` | `network-canary.json` | `no_receipt` | `netcanary.v1` attempts a TCP connect to `192.0.2.1` (TEST-NET-1). **Observational** — see below. |
| `credential_canary` | `credential-canary.json` | `no_receipt` | A parent-only env var never reaches the child (`build_child_env` excludes it). |
| `wrong_platform` | `wrong-platform.json` | `rejected` | A platform-mismatched adapter id is not a registry key; rejected before spawn. |
| `corrupted_input` | `corrupted-input.json` | `resource_limit` | A wrong-typed input (`text` as int) is rejected by the child's schema validator; exit 2; no receipt. |
| `schema_invalid_output` | `schema-invalid-output.json` | `no_receipt` | Marker case asserting the receipt-last invariant on a normal run; cross-references the WP-D32 sealer-level no-receipt path. |
| `partial_receipt` | `partial-receipt.json` | `no_receipt` | A run killed mid-flight leaves no `receipt-*.json` in scratch (receipt is written only after output validation on a clean exit). |

The four expected outcomes (`ExpectedOutcome`):

- **`rejected`** — the case is refused *before* any process runs (registry or
  materialization rejects it; `receipt_written` must be `False`).
- **`resource_limit`** — a hard cap fired (memory/cpu/files/forks/output), or the
  bomb's handler caught the cap and exited cleanly. The run is bounded; no
  receipt on a non-completed outcome.
- **`timeout`** — the wall watchdog killed the child; no receipt.
- **`no_receipt`** — the run completed or failed but the point of the case is the
  receipt-last invariant itself (no receipt on a violation; a receipt is
  legitimate only on a clean completion).

## The receipt-last oracle

For every case, `run_case` asserts two things:

1. The observed runner status matches the case's declared expectation
   (platform-tolerant: a memory bomb may be `resource_limit` on Linux and
   `timeout` on macOS; a fork bomb may be caught-and-exit-cleanly where
   `RLIMIT_NPROC` is very strict).
2. **The receipt-last invariant**: if the observed status is not `completed`,
   then `receipt_written` is `False` AND the scratch directory contains zero
   `receipt-*.json` files. A violation that produced a receipt fails the case
   outright.

This is the property the whole suite exists to defend. A green D34-01 means no
adversarial input — injection, bomb, timeout, or corruption — can trick the
runner into writing a receipt that claims a successful run.

## Observational network canary

The `network_canary` case is **observational**, not a blocking assertion. The
`netcanary.v1` test adapter attempts a TCP `connect` to `192.0.2.1` — an address
in RFC 5737 TEST-NET-1 reserved documentation space that must never correspond to
a real host — and records the attempt and its outcome in the child output.

The gate asserts:

- the connect attempt was **recorded** (`attempted=True`, `target` contains
  `192.0.2.1`), and
- the run completed (the child booted and returned a result).

The gate does **not** assert that the sandbox blocked the connect. Network
denial on macOS CI is not guaranteed (there is no network namespace isolation in
the GitHub Actions macOS runner). On Linux CI the connect to a non-routable
address times out or is refused; on a network-permissive host it would also time
out (TEST-NET-1 is not routable on the public Internet). The observational
posture means the case is hermetic and meaningful regardless of the host network
posture.

## Orphan-free guarantee

The 50-run conformance floor (`conformance_sequence`) is the orphan-free
guarantee. It runs 50 sequential executions — golden `echo.v1` runs interleaved
with the 14 adversarial cases — and after the last run performs a final
process-group sweep (`orphan_sweep`).

Two layers of orphan detection:

1. **Per-run** (`srl.execution.sandbox.verify_no_orphan`): after every watchdog
   kill, the runner walks the live process table for any process whose
   process-group id still matches the killed leader. A survivor is a
   `POLICY_VIOLATION` hard stop.
2. **Sequence-final** (`orphan_sweep`): after all 50 runs, a name-based sweep
   walks `/proc/<pid>/cmdline` on Linux and `/bin/ps` on macOS, flagging any
   process whose command line mentions `srl.execution.child`. This is the
   **setsid-evasion detector**: a grandchild that escaped its group via
   `os.setsid` (and thus survived a `killpg(leader_pid)`) is caught here.

The `setsiddler.v1` test adapter exists to exercise the detector: it forks a
grandchild that calls `setsid` and lingers briefly. The D34-03 check runs it and
then sweeps — the sweep must run without error and find no survivor (the handler
reaps its own grandchild before returning, so a clean run leaves nothing; the
point is that the detector *could* find one).

A green D34-02 means: across 50 mixed executions, no process survived its run,
and the receipt-last invariant held throughout.

## The 50-run conformance floor

The floor is fixed at 50 (`CONFORMANCE_FLOOR`). The schedule interleaves golden
`echo.v1` runs (even slots) with the adversarial cases (odd slots, cycled). This
mix exercises both the happy path (a clean run writes a receipt) and every
adversarial vector (a violation writes none) in one sequential pass, under real
resource pressure (the sequence holds no long-lived state, but each run spawns a
real child, so a leak — a file descriptor, a zombie, a scratch dir — accumulates
and surfaces within the 50 runs).

The sequence is the longest test in the suite (~35–50s on a warm machine). The
gate runtime ceiling is 120s; CI budgets `timeout-minutes: 15`.

## Platform limits

The suite is conservative everywhere and strict on Linux (CI).

**`RLIMIT_AS` (memory).** On macOS arm64 the kernel refuses to lower the hard
address-space limit, so `RLIMIT_AS` is best-effort there: a memory bomb is
bounded by the wall watchdog and the output cap instead of `SIGSEGV`. On Linux
(CI) `RLIMIT_AS` is enforced and kills an over-budget child directly. The
`memory_bomb` case accepts `resource_limit`, `timeout`, or `failed` on any
platform.

**`RLIMIT_NPROC` (forks).** Fixed at 256. On macOS this is so strict relative to
the Python runtime's own thread count that `os.fork()` hits `EAGAIN` immediately
(`forked=0`); on Linux the child forks up to ~256 times before the cap. Either
way the fan-out is bounded by construction and no orphan survives.

**Network denial.** Not guaranteed on macOS (see the observational canary above).

**Orphan sweep.** On Linux `/proc/<pid>/cmdline` is authoritative. On macOS
`/bin/ps` reports the command truncated and may not show a short-lived
grandchild that already exited; the sweep is best-effort there, and the per-run
`verify_no_orphan` is the authoritative check. The `comm` column on macOS is the
interpreter path, not the module args, so the name-based sweep only flags
processes whose `comm` literally contains the marker (rare) — the per-run group
check carries the weight on macOS.

**Child CWD.** The runner sets the child's working directory to the scratch dir
on all platforms (a WP-D34 hardening fix). The `cwdprobe.v1` adapter returns
`os.getcwd()` so the D34-03 check can assert the child did not inherit the
parent repo root.

## CI wiring

The suite is wired into two workflows:

- **`execution.yml`** — `adversarial-runner-gate (WP-D34)`: runs the full
  `wp34-gate.py` (all three checks) plus `pytest tests/security`.
- **`security.yml`** — three focused jobs:
  - `archive-adversarial`: the WP-C22 pack-extraction gate plus the D34-01
    archive-traversal case.
  - `command-injection`: the D34-01 adversarial-kinds gate plus the D31-01
    registry-first injection gate.
  - `path-boundary`: the D34-03 cwd/orphan-sweep hardening check.

All jobs run on `ubuntu-24.04` (where `RLIMIT_AS` is enforced), use the pinned
action SHAs, and request `permissions: contents: read` only.
