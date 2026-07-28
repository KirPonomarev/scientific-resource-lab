# Storage abstraction + T7 identity conformance vectors (WP-C20)

This directory holds the conformance vectors for the SRL content-addressed
storage abstraction and T7 volume identity guard (`srl.cas`). The vectors are
synthetic and hermetic: no vector touches a real disk, and every volume UUID is
a fake (the canonical RFC 4122 variant/version bits are set so the shape parses,
but no value corresponds to a real operator volume).

Mount-info vectors cover the three observable mount states:

- `mount_info-mounted-expected.json` — the expected volume is mounted at the
  expected point; the identity guard verifies and the store proceeds. The
  `volume_uuid` is the fake `00000000-0000-4000-8000-000000000001`.
- `mount_info-mounted-foreign.json` — a different volume is mounted at the
  expected point; the store fails closed with `WRONG_T7_VOLUME` (hard stop) and
  never falls back. The `volume_uuid` is a distinct fake.
- `mount_info-absent.json` — no volume is mounted at the expected point; the
  provider raises `T7UnavailableError` and the store waits (`WAIT_STORAGE`).

The `mount_point` fields in the mount-info documents are pre-redacted to
digest-prefix tokens (`redacted:...`); the fixtures themselves never carry a raw
`/Volumes/` or `/Users/` path. Tests and the gate inject a fake provider that
reads these documents, so no subprocess is spawned.

Blob and descriptor vectors cover the local store and the fallback policy:

- `tiny-fixture-blob.txt` — a `<1 KiB` public fixture blob accepted by the local
  store round-trip and by the local fallback (it is under the 1 MiB
  single-object limit and is object class `fixture`, the only non-T7-bound
  class).
- `oversized-descriptor.json` — a descriptor (NOT real bytes) with a declared
  size of `1572864` bytes (> 1 MiB) that the local fallback must refuse with
  `WAIT_STORAGE`. The oversized payload is never materialized on disk; the
  descriptor exists only to exercise the single-object limit refusal.

The check script `scripts/checks/wp20-gate.py` consumes these vectors to drive
the four WP-C20 checks (wrong volume, unplugged T7, no raw paths in the public
API, fallback accept/refuse) and emits a `GateReceipt/v1` receipt. See
`docs/architecture/storage.md` for the storage planes, the identity guard, the
`WAIT_STORAGE` semantics, the capacity table, and the privacy redaction.
