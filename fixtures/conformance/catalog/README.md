# WP-C24 catalog conformance fixtures

This directory holds the conformance fixture surface for the capability catalog
(WP-C24). The catalog snapshot is **fully derived at runtime** from the packaged
seed registry (`src/srl/catalog/seed_entries.json`) and from in-memory synthetic
entries built by `srl.catalog.registry.build_entry`, so — unlike the WP-C22 pack
fixtures — there is no generated artifact tree to ship here.

What lives here
---------------

- This README, which documents why no generated fixtures are required and points
  at the runtime sources the gate and tests use.

Runtime fixture sources
-----------------------

- **Seed registry** (`src/srl/catalog/seed_entries.json`): the 15 honest
  `not_admitted` / `DISCOVERED`-stage seed entries derived from the B14
  `catalog_data.json`. Loaded via `srl.catalog.registry.load_registry_seed()`.
- **Synthetic entries** (`build_entry(...)`): the WP-C24 gate and the hermetic
  test suite construct admitted and tampered entries programmatically with
  `build_entry` so identity/merkle and tamper-detection assertions are exact and
  hermetic (no filesystem state, no network, no clock dependence beyond an
  explicit `created_utc`).

The C24-04 tamper case mutates a seed entry's field and confirms
`verify_snapshot` raises `SnapshotMismatchError` (`CONTRACT_INVALID`); the
mutation is performed in-process, so no tampered fixture file is committed.
