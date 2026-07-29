# Environment factory and supply-chain gate

V3.7 A03 introduces a deterministic environment profile factory for scientific
resource packs. The factory is intentionally a control-plane contract: it builds
portable profile manifests from lock, SBOM, dependency DAG, license and
revocation evidence. It does not install toolchains, mutate global depots,
execute scientific probes, or grant authority.

## Profile kinds

The factory currently supports four isolated profile kinds:

- `python_uv` for uv/Python environments.
- `native_binary` for native tool profiles.
- `julia_depot` for Julia depot profiles.
- `lean_prover` for Lean/prover profiles.

Each profile receives isolated mutable roots under `work/envs/<profile_id>`,
`work/caches/<profile_id>`, `work/scratch/<profile_id>` and
`work/spool/<profile_id>`. Absolute paths, home-directory expansion, default
Julia depots, `.venv`, `site-packages`, traversal and platform drive syntax are
rejected before manifest construction.

## Scheduling status

`EnvironmentProfile/v1` status is a scheduling decision for the profile
factory, not a claim that the scientific capability has passed later acceptance.

- `ACTIVE`: lock, SBOM, license policy, isolated roots and dependency DAG are
  complete enough for the scheduler to consider the profile.
- `WAIT_LICENSE`: an unknown or incompatible dependency license prevents
  scheduling.
- `REVOKED`: a revoked dependency in the transitive DAG prevents scheduling.
- `INVALID`: reserved for structurally invalid profile records; invalid specs
  are rejected by contract errors before receipt construction.

The A03 gate proves deterministic rebuilds across all four profile kinds and
negative controls for global mutable depot, transitive dependency revocation and
unknown-license false ACTIVE claims.

## Evidence

Primary code:

- `src/srl/packs/environment.py`
- `tests/packs/test_environment.py`
- `scripts/checks/srf-v37-a03-gate.py`

Committed receipt:

- `docs/verification/srf-v3-7-a03-env-factory-receipt.json`

Required command:

```bash
uv run python scripts/checks/srf-v37-a03-gate.py
```
