# T7 Physical Profile

S24 performs a read-only physical capability preflight for the `T7` mount label and
prepares a binding request. No storage writes, formatting, restore, sync,
database placement, hardware purchase or cloud purchase were performed.

Read-only observation:

- Volume label: `T7`
- Filesystem: APFS
- External physical disk observed: true
- Capacity: 931 GiB
- Available: 544 GiB
- Minimum free reserve: 100 GiB
- Reserve check: PASS

Current states:

- T7 binding: `WAIT_T7_BINDING`
- Science Compute Node: `WAIT_COMPUTE_NODE`

Artifacts:

- `docs/target-binding/t7-physical-binding-request.json`
- `docs/target-binding/t7-readonly-preflight.json`
