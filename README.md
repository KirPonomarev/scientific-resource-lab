# Scientific Resource Lab

Reproducible, bounded and evidence-first scientific computation fabric for
autonomous research agents.

Scientific Resource Lab (SRL) provides:

- typed scientific contracts over canonical JSON (schema set
  `src/srl/contracts/schemas/v1`);
- an immutable content-addressed artifact store with verified ingest;
- reviewed, hash-locked capability packs with safe materialization;
- a bounded fixed-entrypoint local runner with hard resource limits;
- a deterministic claim router and planner with explicit `WAIT_CAPABILITY`;
- a JSON-first CLI, a read-only MCP interface and a static evidence portal;
- a disclosure-sanitized `LabExportPacket/v1` proposal-only bridge.

## Role in the federation

SRL is the primary scientific cortex and formal
`SCIENTIFIC_REASONING_COMPUTE_FABRIC`; it is never a global writer.
Global A2 is forbidden. Read the
[`federated organism doctrine`](docs/architecture/federated-research-organism-doctrine-v1.md).
Before any cross-repository description or change, run
`make gate-federation-doctrine` and `srlab labctl federation-orient NONE`.
The orientation separates SRL V3.7 release truth from runtime truth: without
exact current native receipts, SRL, Market, Security, Dual and federation
runtime are all `NOT_CHARACTERIZED`. A declared scope grants no authority.

C3 is a proposal semantic kind, not a synonym for authority-negative. Results,
evidence, receipts and validation artifacts retain their semantic kind when
they cross a boundary; any requested effect derived from them is a separate C3
proposal admitted only by the target native domain.

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
