# SRF Recovery Runbook

SRF recovery is fixture-bounded unless a native target authority says
otherwise. The local operator Mac may run restore drills against disposable
directories, but it must not overwrite a live store, start a daemon, bind T7, or
claim Market health.

## Health Model

- `SRFPulse/v1` is SRF-local and authority-negative.
- A stale or cross-HEAD SRF pulse projects to `WAIT_SRF`.
- `FederationStatus/v1` aggregates cell projections read-only. It can report
  Market `RED` and SRF `WAIT_SRF` at the same time; it never rewrites native
  `OrganismPulse`, `OperatorContext`, or Security health.
- `canonical_writes` is always `0`, and `grants_authority` is always `false`.

## Restore Drill

`bounded_restore_drill` copies exact content-addressed artifacts from a source
fixture CAS into an empty restore target, then verifies every restored digest.

Safety rules:

- the target must be empty;
- the source store performs integrity verification on read;
- the target digest must match the source digest;
- duplicate artifact ids are restored once;
- no absolute target path is written into the public receipt.

Failures are terminal evidence, not authority. A corrupt source CAS raises the
CAS integrity error; a non-empty target raises a restore contract error. Live T7
restore, destructive overwrite, remote reboot, or production backup movement
remains `WAIT_AUTHORITY`.
