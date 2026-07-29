# A12 Discovery And Dynamics Activation

A12 activates the discovery/dynamics surface through real bounded probes, not
through import-only admission or fixture declarations.

## Active Packs

The v2 A12 mandatory engines are:

- PySR for Julia-backed symbolic regression.
- PySINDy for sparse dynamics identification.
- PyDMD for dynamic mode decomposition.

Each engine must produce an `ACTIVE` pack receipt with backend versions,
candidate binding, dataset binding, null/surrogate evidence, bounded resource
envelope, `canonical_writes=0` and `grants_authority=false`.

## Runtime Boundary

PySR requires an explicit Julia executable. The gate accepts Julia from
`SRL_A12_JULIA_EXE` or `PATH`, probes `julia --version`, and exports the
JuliaCall environment for that smoke only. It must fail closed when Julia is
absent; it must not silently provision Julia into the repository.

PySR 1.5 resolves Julia packages through `juliapkg` at import time. CI therefore
keeps provisioning separate from probing: `srf-v37-a12-prepare-julia.py` resolves
the cacheable Julia depot and emits an authority-negative
`A12JuliaDepotPrepareReceipt/v1`, while `srf-v37-a12-gate.py` performs the real
PySR/PySINDy/PyDMD smoke and is the only source of A12 `ACTIVE` evidence.

## Ledger Boundary

`CapabilityTruthLedger/v1` projects A12 truth only from the committed
`StageCompletionReceipt/v1` at
`docs/verification/srf-v3-7-a12-discovery-dynamics-receipt.json`. Ledger
projection is offline and must not import PySR/PySINDy/PyDMD, spawn Julia, or
perform network/provisioning work.

## Scientific Authority

A12 receipts are candidate-only scientific evidence. They do not promote a law,
select a market action, authorize a canonical writer, or materialize a
prospective holdout. The legacy wishlist engines SR4MDL, Operon, gplearn,
AI-Feynman, pyKoopman and dysts are formally replaced for v2 A12 instead of
being reported as hidden successes.
