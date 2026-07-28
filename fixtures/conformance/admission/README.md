# Admission pipeline conformance fixtures (WP-C23)

WP-C23 does not require static fixtures. The admission state machine is exercised
with synthetic evidence dicts in the unit tests (`tests/packs/test_admission.py`)
and in the acceptance gate (`scripts/checks/wp23-gate.py`).

The gate builds packs using the deterministic `srl.packs.builder.build_pack`
helper where a file tree is needed, but those trees are generated at runtime in
a temporary directory and never committed to this directory.

If future WP-C23 checks need persistent fixtures (e.g., reference receipt chains,
sample pack specs, or pre-computed manifests), they should be placed here as
JSON files and referenced from the gate by relative path.
