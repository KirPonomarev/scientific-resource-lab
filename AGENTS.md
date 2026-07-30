# SRL Agent Operating Agreement

Scientific Resource Lab agents work from repository evidence, not chat memory.
Before non-trivial mutation, read `GOVERNANCE.md`, `CONTRIBUTING.md` and the
active plan under `docs/plans/`.

## Current V3.7 Mission State

V3.7 A00-A22 software lanes are completed in the public repository evidence,
but the mission is not `DONE` and `v2.0.0` is not released. The current V3.7
terminal receipt is
`docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json`, which is
`BLOCKED_EXTERNAL_AUTHORITY`.

The historical `docs/verification/mission-closeout-receipt.json` belongs to
the V3.6/v1.0.1 foundation release. Do not use it as the active V3.7 closeout.

## Allowed Local Actions

- Use separate `codex/*` branches or worktrees for code, test and
  documentation changes.
- Run bounded local tests, gates, receipt validation, documentation checks and
  reproducible build checks.
- Regenerate committed public receipts only through the repository gate scripts
  that bind them to current public evidence.
- Park protected external work as exact WAIT states and operator action packets.

## Forbidden Without Native Authority

- Do not claim `DONE`, publish or retag `v2.0.0`, or convert
  `BLOCKED_EXTERNAL_AUTHORITY` into success.
- Do not install secrets, bind production signing keys, mutate T7 protected
  state, deploy, restart services, start live trading actions, or run
  target-specific security actions.
- Do not treat fixture-only, adapter-only or cached evidence as a real ACTIVE
  capability.
- Do not run unbounded research jobs on macOS as a substitute for the declared
  durable execution target.

## Bootstrap

For V3.7 work, verify:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
make gate-v37-plan
```

Then run the narrow gate for the affected lane before broader verification.
