# Science Compute Node

S18 defines the SRF-side routing contract for heavy PDE/HPC, Sage and budgeted
oracle capabilities. It does not purchase, start, deploy to, restart or mutate
any external node.

Current local capability posture:

- PETSc, FEniCSx, pyMOR, scikit-fem and Dedalus: `WAIT_COMPUTE_NODE`
- Modulus and neural-operator workloads: `WAIT_COMPUTE_NODE`
- SageMath: `WAIT_COMPUTE_NODE`
- Wolfram adapter: `WAIT_AUTHORITY` until explicit credential and budget receipt

Remote jobs must provide a profile id, required capability, image digest,
architecture, input digest and positive checkpoint interval. Routing accepts a
job only when a compatible node manifest is online, has the requested
capability, matches the architecture, includes the image and has not revoked
that image. Budgeted or paid jobs require a budget receipt before routing.

The shipped signature helper is a deterministic `test-hmac-sha256` fixture used
for conformance tests. A production executor must bind native keys and return a
native intake receipt before any real remote execution.

Rollback is local and reversible: remove the routing config and package, and no
remote state exists to clean up because S18 performs no launch or spend.
