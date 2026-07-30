# Scientific Resource Lab

Reproducible, bounded and evidence-first scientific computation fabric for
autonomous research agents.

Scientific Resource Lab (SRL) provides:

- typed scientific contracts over canonical JSON (schema set `schemas/v1`);
- an immutable content-addressed artifact store with verified ingest;
- reviewed, hash-locked capability packs with safe materialization;
- a bounded fixed-entrypoint local runner with hard resource limits;
- a deterministic claim router and planner with explicit `WAIT_CAPABILITY`;
- a JSON-first CLI, a read-only MCP interface and a static evidence portal;
- a disclosure-sanitized `LabExportPacket/v1` proposal-only bridge.

## Scientific honesty

SRL never collapses distinct evidence axes:

```text
READY != COMPUTED
COMPUTED != VALIDATED
SAT/UNSAT != empirical truth
algorithm agreement != independent replication
formal proof != empirical validation
exportable != admitted
```

Exit code zero from any SRL command means the operation completed and a
receipt exists. It never means a scientific claim is supported.

## Status

Early development. See `CHANGELOG.md` and `docs/architecture/` for the
current state, and `GOVERNANCE.md` for how changes are admitted.

V3.7 A00-A22 public software evidence is present, but the V3.7 mission is
currently blocked on protected external authority and `v2.0.0` has not been
published. The active V3.7 closeout truth is
`docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json`; the older
`docs/verification/mission-closeout-receipt.json` is the historical
V3.6/v1.0.1 predecessor release receipt.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
