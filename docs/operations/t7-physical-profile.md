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
- `docs/target-binding/t7-native-binding-operator-action.json`
- `docs/verification/srf-v3-7-a02-t7-binding-wait-receipt.json`

V3.7 A02 gate:

- Command: `uv run python scripts/checks/srf-v37-a02-gate.py`
- Current terminal state: `WAIT_T7_BINDING`
- Physical T7 writes by the gate: `0`
- Protected action hash: `a3028eef-04e3f0f3-d0e8dac7-42237dc5-b2308119-0b18b687-5feadeba-798bc315`

The gate proves the public, non-destructive storage side of A02 and blocks false
`ACTIVE` / `DONE` closure. It does not grant target authority. A physical
`T7BindingReceipt/v1` may become `ACTIVE` only after target-scoped authority
exists and the native bind records namespace creation, quota enforcement, a
nonsecret object write/read/hashcheck, corruption rejection, unplug wait, replug
resume, and proof that project data does not depend on internal Mac storage.
