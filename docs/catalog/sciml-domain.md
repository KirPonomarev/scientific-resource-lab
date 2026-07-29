# SciML And Domain Packs

S17 defines reproducible profile cards for Julia/Python SciML and
domain-science engines. The local execution evidence for this transition found
no Julia executable and no importable S17 Python domain runtimes, so every
named profile is held in `WAIT_CAPABILITY`.

WAIT_CAPABILITY profiles:

- `julia.sciml`, `julia.modelingtoolkit`, `julia.datadrivendiffeq`
- `python.diffrax`, `python.qutip`, `python.cadabra`, `python.astropy`
- `python.cantera`, `python.pybamm`, `python.quimb`, `python.cotengra`

The admission bundle records `shared_mutable_global_depots=0`, requires
unit bindings, solver family/name and positive absolute or relative tolerance,
and keeps all receipts authority-negative. Cross-language fixture receipts are
tolerance-only evidence; they reject bitwise identity claims across different
runtimes or solver families.
