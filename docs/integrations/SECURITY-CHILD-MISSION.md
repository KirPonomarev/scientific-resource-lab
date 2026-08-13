# Security Child Mission

A20 records the native Security child mission packet for the inactive bridge.
At the recorded V3.7 A20 evidence generation, native Security health reported
RED and the native closeout was absent, so activation was parked. This is
historical bound evidence, not current Security runtime truth.

Artifacts:

- `docs/child-missions/security/security-bridge-child-request.json`
- `docs/child-missions/security/security-bridge-wait-receipt.json`
- `docs/child-missions/security/security-native-bootstrap-evidence.json`

Historical read-only native evidence at the recorded V3.7 generation:

- Security HEAD: `c5e8349b05b601c3d2976da7bad58bf756600185`
- Worktree status: detached HEAD, clean
- Native bootstrap command:
  `python3 tools/superbrain_health.py --json`
- Native bootstrap result: non-zero, `status=DEGRADED`,
  `organism_status=RED`
- Next native gate: `review_knowledge_batch`
- Root reason:
  `forbidden_checkout_data_entry:crypto_kb.db`
- Safety evidence: `no_live_authority=true`,
  `private_material_on_vps=0`, `safety_status=GREEN`
- Wait state: `WAIT_SECURITY_HEALTH:ORGANISM_RED`

The request is proposal-only and asks for native validation/merge of inactive
bridge code only. Parent direct Security writes, target actions, scanner
control, exploit execution, and activation remain forbidden.

Current Security state requires an exact current native bootstrap receipt. If
it is unavailable, report `NOT_CHARACTERIZED`; never promote the recorded A20
observation to current runtime truth.
