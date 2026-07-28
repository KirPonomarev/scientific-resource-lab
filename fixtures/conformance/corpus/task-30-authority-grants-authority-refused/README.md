# task-30: Packet claiming grants_authority refused

Category: `bridge-authority` — Expected outcome: `REJECT_AUTHORITY`

Pins the authority invariant: a packet whose `grants_authority` field is literally `true` is refused — `grants_authority` is pinned `false` across every schema, so any packet asserting authority is rejected at admission.
