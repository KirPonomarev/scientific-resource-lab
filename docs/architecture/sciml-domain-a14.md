# A14 SciML And Domain Activation

A14 turns the old S17 profile cards into an executable activation lane. The
stage uses a dedicated product surface in `srl.products.sciml_domain`, a gate at
`scripts/checks/srf-v37-a14-gate.py`, and the committed stage receipt
`docs/verification/srf-v3-7-a14-sciml-domain-receipt.json`.

The design separates three boundaries:

- Julia provisioning is explicit and isolated. The prepare step creates a stage
  Julia project and depot under the caller-provided cache paths, then records
  the `Project.toml` and `Manifest.toml` SHA-256 digests. The gate fails closed
  if the project has not been prepared.
- Python domain engines are optional. The `sciml-domain` extra contains
  `diffrax`, `qutip`, `astropy`, `cantera`, `quimb` and `cotengra`; default
  installs and unrelated gates do not import them.
- The truth ledger is an offline projection. It reads the committed A14 stage
  receipt and validates pack ids, replacement ids, unit/tolerance/solver
  provenance and no-authority fields. It does not import Julia, JAX, Cantera or
  any other domain runtime.

The Julia and Python ODE tasks solve the same bounded exponential-decay model,
but their receipt is tolerance-only. Cross-language bitwise identity is
forbidden because the runtimes and solver implementations differ.

PyBaMM is not admitted into the v2 default or A14 optional closure. The A14
battery representative task is a native bounded RC discharge model with units,
trace digest and deterministic diagnostics. PyBaMM remains a formally replaced
catalog item until a separate license, weight and runtime review admits it.
