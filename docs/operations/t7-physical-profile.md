# T7 Physical Profile

S24 performed a read-only physical capability preflight for the `T7` mount label
and prepared a binding request. The 2026-07-30 protected activation lane also
attempted a non-destructive native bind against the encrypted `T7-Secure`
operator target. No formatting, restore, sync, active database placement,
hardware purchase or cloud purchase were performed.

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
- T7-Secure native attempt: `PARTIAL_NATIVE_EVIDENCE`
- Science Compute Node: `WAIT_COMPUTE_NODE`

Native attempt evidence:

- SRF namespace created on the encrypted external target.
- Nonsecret CAS probe object roundtrip passed.
- Corrupted restore-test copy was rejected.
- Project data dependency on the internal Mac disk was not observed for the SRF
  namespace.
- Remaining blockers: repo-native authority receipt, target ownership enabled,
  unplug WAIT observation, and replug resume observation.

Artifacts:

- `docs/target-binding/t7-physical-binding-request.json`
- `docs/target-binding/t7-readonly-preflight.json`
- `docs/target-binding/t7-native-binding-operator-action.json`
- `docs/verification/srf-v3-7-a02-t7-binding-wait-receipt.json`
- `docs/verification/srf-v3-7-a02-t7-native-activation-attempt-receipt.json`

V3.7 A02 gate:

- Command: `uv run python scripts/checks/srf-v37-a02-gate.py`
- Current terminal state: `WAIT_T7_BINDING`
- Physical T7 writes by the gate: `0`
- Protected action hash: `d1cfaa6d-710ee48b-a6dcf5b0-e7ef31f6-08464e80-8a65a75b-754ed8e7-8a8fae41`

The gate proves the public, non-destructive storage side of A02 and blocks false
`ACTIVE` / `DONE` closure. It does not grant target authority. A physical
`T7BindingReceipt/v1` may become `ACTIVE` only after repo-native target-scoped
authority exists and the native bind records ownership-enabled target identity,
namespace creation, quota enforcement, a nonsecret object write/read/hashcheck,
corruption rejection, unplug wait, replug resume, and proof that project data
does not depend on internal Mac storage.
