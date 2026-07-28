# Canonical JSON conformance vectors (WP-B10)

This directory holds the byte-exact conformance vectors for the SRL canonical
JSON contract (`srl.contracts.canonical`). Each positive vector is a pair of
files:

- `<name>.input.json` — the input value, deliberately written in a
  non-canonical form (typically a different key order) so the vector exercises
  the canonicalizer, not just a byte copy.
- `<name>.expected.json` — the exact canonical bytes the input must
  canonicalize to (sorted keys, compact separators, UTF-8, trailing newline).

Negative vectors live under `negative/`. Each is an `<name>.input.json` whose
value the canonicalizer or a contract validator must **reject**. The companion
`<name>.expected_error.json` names the contract reason the rejection must
carry.

## Coverage

Positive vectors (`v01`..`v12`) cover:

- `v01` key-order normalization (same object, three orderings -> same bytes),
- `v02` unicode NFC passthrough (non-ASCII survives as UTF-8, not `\uXXXX`),
- `v03` nested empty containers (`{}`, `[]`, nesting),
- `v04` decimal-string preservation (precision value carried as a string),
- `v05` integer byte counts (non-negative int),
- `v06` deeply nested sorted keys,
- `v07` array order preservation (sequences are *not* reordered),
- `v08` null / bool / int distinctness,
- `v09` unicode supplementary-plane code points,
- `v10` negative decimal string,
- `v11` empty object root,
- `v12` safe-range large integer.

Negative vectors (`negative/n01`..`negative/n08`) cover:

- `n01` `NaN`,
- `n02` `Infinity`,
- `n03` bool-as-int (a `True` where a byte count is expected),
- `n04` self-hash (object carries its own `object_id`),
- `n05` absolute path,
- `n06` traversal path (`..`),
- `n07` fractional timestamp,
- `n08` offset timestamp.

The check script `scripts/checks/canonical-vectors.py` loads every positive
vector, canonicalizes the input, and asserts byte-equality with the expected
file; and loads every negative vector, runs the named validator, and asserts a
typed rejection. Both print JSON receipts and exit non-zero on any mismatch.
