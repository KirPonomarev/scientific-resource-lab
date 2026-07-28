# Capability catalog snapshot (WP-C24)

WP-C24 defines the deterministic, content-addressed capability catalog: the
immutable identity view of the 15 science-lab capabilities, a snapshot whose
identity is a pure function of its entries, a small local cache that stays
queryable when the artifact store is absent, and a verifier that proves a record
still matches its identity. It is the control-plane layer above WP-B14 (the
in-repo capability catalog the router consults) and alongside WP-C22/C23 (pack
manifest and admission): a registry entry records *what a capability is* and, if
a pack has been admitted, *which pack proves it* — never where it can run today.

The catalog is implemented in four modules:

- `srl.catalog.registry` — `CapabilityRegistrySeed/v1` and the immutable
  `CapabilityRegistryEntry` identity records.
- `srl.catalog.snapshot` — the `ScientificCatalogSnapshot/v1` content-addressed
  snapshot with its Merkle root.
- `srl.catalog.local_cache` — the `<1 MiB` store-agnostic local JSON cache.
- `srl.catalog.verify` — `verify_snapshot`, the recompute-and-compare verifier.

## Identity vs dynamic

The catalog's central invariant is the split between **identity** (immutable,
content-addressed) and **dynamic** state (mutable, never part of identity).

| Concern              | Identity (immutable)                         | Dynamic (separate)                       |
| -------------------- | -------------------------------------------- | ---------------------------------------- |
| What it is           | profile, adapter, provenance, admission stage | location / availability, build timestamp |
| Where it lives       | `CapabilityRegistryEntry`, snapshot entries  | `location_state_ref`, `created_utc`      |
| Changes identity?    | yes                                          | **no**                                   |
| Stored on the entry? | yes                                          | no                                       |

A `ScientificCatalogSnapshot`'s identity (`snapshot_id`) is computed over the
identity body only:

```python
identity_body = {
    "schema_version": "ScientificCatalogSnapshot/v1",
    "entries": [e.to_dict() for e in sorted_entries],
    "merkle_root": merkle_root,
    "canonical_writes": 0,
    "grants_authority": False,
}
snapshot_id = object_id(identity_body)
```

Two consequences are load-bearing:

1. **Order-independence.** Entries are sorted by `capability_id` before hashing,
   so two agents that build a snapshot over the same entries in different orders
   produce byte-identical canonical bytes, an equal `merkle_root`, and an equal
   `snapshot_id`. Identity is a pure function of the entry *set*.
2. **Location-immunity.** `created_utc` and `location_state_ref` are excluded
   from the identity body. Changing a capability's location/availability alters
   `location_state_ref` (the dynamic digest over the separate location map) but
   never `snapshot_id`, `merkle_root`, or the entry bytes.

### Merkle root

`merkle_root` is the binary Merkle root over the ordered canonical per-entry
digests. Each leaf is `sha256(canonical_dumps(entry.to_dict()))`. Adjacent leaves
are paired, concatenated, and hashed; a level with an odd node count duplicates
the final node. The root of an empty entry set is `sha256(b"")`. Because the
entry order is fixed (sorted by `capability_id`), the root is deterministic and
contributes to the snapshot identity.

## Honesty: presence never implies readiness

The shipped registry seed is derived from the B14 `catalog_data.json` and the
honest C22/C23 metadata model: **every** seed entry carries
`admission_stage="not_admitted"`, `pack_manifest_digest=null`,
`license_spdx="NOASSERTION"`, and null provenance. No real pack has been admitted
through the WP-C23 pipeline, so no entry claims one.

This honesty extends to the dynamic layer. A capability *appearing* in the
registry is a statement of identity ("this capability exists and is served by
this profile"), not of availability. Readiness is a dynamic location property
reported separately, and the honest default is `{"state": "unknown"}`:

- A registry entry with `admission_stage="not_admitted"` is not ready to run,
  full stop — even if an `adapter_id` is named.
- The local cache's listing API, when the content-addressed artifact store is
  absent, reports `{"state": "unknown"}` for every capability. The cache must
  never claim availability it cannot prove.
- A future WP that admits a real pack flips the registry entry's
  `admission_stage` (changing the snapshot identity) and may record a non-unknown
  location; until then, every applicable capability waits honestly.

This mirrors the B14 router contract: absence of an available adapter is an
honest `WAIT_CAPABILITY`, never a silent fallback to a local substitute.

## The local cache

`SnapshotCache` is the on-disk landing pad for the latest snapshot and its
dynamic location state. It is deliberately tiny (the cache file is hard-capped
at 1 MiB; the 15-entry seed cache is ~5 KiB) and **store-agnostic**:

- `write(snapshot, locations)` rebuilds the snapshot from its entries together
  with the full location map (defaulting unrecorded capabilities to `unknown`)
  so the persisted record is internally consistent, then writes it atomically
  (temp-file + rename).
- `read()` returns `None` when no cache file exists (the store may simply be
  unavailable); callers fall back to the `unknown` location state.
- `list_capabilities(store_present=False)` and `inspect(...)` work with the store
  absent, surfacing identity fields and an honest `{"state": "unknown"}`.

A cache whose snapshot fails identity verification on read is a typed
`LocalCacheError` (`CONTRACT_INVALID`): a tampered or divergent cache is never
trusted silently.

## Verification

`verify_snapshot(snapshot, locations=None)` recomputes the snapshot identity
from the snapshot's own entry list and compares each field to the recorded value:

- the fixed record tail (`schema_version`, `canonical_writes`, `grants_authority`);
- the entry ordering (entries must be sorted by `capability_id`);
- `merkle_root` (recomputed from the canonical per-entry digests);
- `snapshot_id` (recomputed from the identity body);
- `location_state_ref` (recomputed from the location map, defaulting to the
  `unknown` map when `locations` is `None`).

Any divergence raises `SnapshotMismatchError` with fail reason `CONTRACT_INVALID`
and records the `field`, the `recorded` value, and the `recomputed` value. A
snapshot that fails to verify must never be trusted; the caller routes the
failure through the fail-reason machinery as a hard, non-retriable contract
failure. This is the read-side counterpart to `build_snapshot`: the builder
derives identity deterministically, the verifier proves a record still matches.

## Gate (WP-C24-01..04)

`scripts/checks/wp24-gate.py` emits a `GateReceipt/v1` over four checks and
exits nonzero on any FAIL:

- **C24-01** — shuffled entries produce identical canonical bytes, `merkle_root`,
  and `snapshot_id`.
- **C24-02** — a location mutation changes `location_state_ref` only;
  `snapshot_id`, `merkle_root`, and the entry set are unchanged.
- **C24-03** — the cache lists and inspects capabilities with the store absent,
  every capability reporting `{"state": "unknown"}`.
- **C24-04** — a tampered entry field is detected via a `merkle_root` mismatch
  (`SnapshotMismatchError`, `CONTRACT_INVALID`).
