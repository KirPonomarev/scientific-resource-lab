# SciML And Domain Packs

A14 activates the V3.7 SciML/domain catalog through bounded executable
workloads and hash-bound receipts. The catalog is not a claim of scientific
promotion; each result remains authority-negative and tolerance-scoped.

ACTIVE A14 workloads:

- `julia_sciml_ode`: Julia `SciMLBase`/`OrdinaryDiffEq` ODE solve in an isolated
  stage project.
- `python_diffrax_ode`: Python `diffrax` ODE solve of the same bounded model.
- `python_qutip_quantum`: QuTiP two-level Schrodinger evolution.
- `python_astropy_astronomy`: Astropy ICRS to Galactic coordinate transform.
- `python_cantera_combustion`: Cantera HP methane-air equilibrium.
- `native_battery_rc`: native bounded single-cell RC discharge model.
- `python_quimb_many_body`: quimb two-site Heisenberg exact diagonalization.
- `python_cotengra_tensor_network`: cotengra tensor contraction path search.

FORMALLY_REPLACED for v2:

- `julia_modelingtoolkit`, `julia_datadrivendiffeq`: represented for v2 by the
  real Julia SciML ODE workload and explicit cross-language tolerance receipt.
- `python_cadabra`: symbolic-physics coverage is outside the A14 executable
  domain-science target.
- `python_pybamm`: represented for v2 by the native bounded battery RC workload;
  the broader PyBaMM closure remains parked for separate license/weight review.

The Julia and Python ODE results are compared only under declared absolute and
relative tolerances. A14 receipts reject cross-runtime bitwise identity claims
and require unit bindings, solver provenance, backend versions, synthetic input
bindings, trace SHA-256 digests, bounded resource envelopes, `canonical_writes=0`
and `grants_authority=false`.
