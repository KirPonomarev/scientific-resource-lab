# Public exporter — LabExportPacket/v1 (WP-I80)

WP-I80 defines the **export direction** of the public boundary: turning a set of
internal scientific objects into a sanitized, disclosure-safe
`LabExportPacket/v1` that may be released across the public repository boundary.
A packet is the only sanctioned shape for moving summary evidence out of the
private lab and into the public record.

The framework is implemented in three places:

- `src/srl/bridge/exporter.py` — the `LabExportPacket/v1` producer:
  `build_packet(objects, policy)` and the `DisclosurePolicy` / `ExportObject`
  types.
- `src/srl/bridge/sanitizer.py` — the refuse-not-strip disclosure sanitizer.
- `src/srl/contracts/schemas/v1/lab-export-packet.json` — the JSON Schema
  2020-12 document (registered in `srl.contracts.schema`).

Plus the acceptance gate (`scripts/checks/wp80-gate.py`), the conformance
fixtures (`fixtures/conformance/bridge/`), and the hermetic tests
(`tests/bridge/`).

## The disclosure boundary

A packet is a **read-only, review-only view** of summary evidence. The four
safety consts are pinned by both the schema and the exporter:

| Field | Const | Meaning |
| --- | --- | --- |
| `review_only` | `true` | A packet is for human review, never an instruction to an automated consumer. |
| `canonical_effect` | `"none"` | Authoring a packet mints, mutates, or retires zero canonical objects. |
| `grants_authority` | `false` | A packet never authorizes an action, integration, or promotion. |
| `canonical_writes` | `0` | The packet performs zero canonical writes; it is a view, not a transaction. |

Tampering any const fails schema validation (defense in depth), exercised by
the I80-05 gate check.

## What never crosses the boundary

The sanitizer (`srl.bridge.sanitizer`) refuses — it does **not** strip — a
summary that contains any of these classes. A refused object never becomes a
packet; the caller must honestly re-summarize it (describe the science, not the
environment) before it can be exported.

| Forbidden class | Why it is refused |
| --- | --- |
| `local_path` | Absolute local paths (`/Users/`, `/home/`, `/Volumes/`) disclose the private filesystem layout. |
| `unix_path` / `windows_path` | Any absolute path discloses the environment, not the science. |
| `argv_flag` / `argv_short_flag` / `shell_command` | Command-line markers indicate a command was pasted, not a summary written. |
| `env_assignment` / `env_reference` | Environment-variable shapes leak private configuration. |
| `credential_pattern` | Concrete credential shapes (GitHub PATs, `sk-` keys, AWS IDs, Slack tokens, JWTs, PEM headers) must never cross. |
| `raw_dataset_marker` | Words indicating raw private data (`raw_dataset`, `patient_data`, `phi`, `pii`). |
| `t7_uuidv7` | The RFC 9562 UUIDv7 shape used for T7 volume identities. |
| `vps_topology_marker` | Deployment-topology identifiers (`vps_host`, `instance_id`, `availability_zone`). |
| `private_key_marker` | Pulse / Snapshot / OperatorContext-shaped private keys (`organism_pulse`, `unified_snapshot`, `operator_context`) — the same sensitive-key set the public-boundary scanner flags. |
| `promotion_flag` | Live / trading / promotion words (`live_mode`, `live_trading`, `trading_enabled`) — a packet can never promote status. |

### Why refuse, not strip

A quiet rewrite (e.g. replacing `/Users/alice/secret` with `<redacted>`) would
let a private value leak through in a subtly-different form on the next
revision, and would hide the fact that a disclosure was *attempted* with private
data in it. Refusing forces the exporter's caller to describe the *science* —
"the solver converged quadratically" — not the *environment* — "the binary at
`/Users/alice/secret`". This mirrors the public-boundary scanner
(`scripts/checks/public_boundary.py`), which already rejects these classes in
tracked files; the sanitizer is the producer-side counterpart so a refused
summary can never become a tracked-file violation in the first place.

The only mutation the sanitizer performs is **whitespace-only normalization**
(collapse runs, strip ends). It never edits the *content* of a summary.

## Disclosure policy and digest replacement

A private object's identity digest is **not automatically publishable**. The
`disclosure_policy.private_identities` field selects how private identities are
handled:

- **`digest_replaced`** (default): each raw private object digest and each
  provenance ref is replaced with a **packet-local digest**:
  `sha256(packet_seed_hex + private_digest_hex)`. The raw private digest never
  appears in the packet.
- **`omitted`**: the object is still summarized (it gets a packet-local digest
  so it is identifiable within the packet) but its `provenance_refs` list is
  emptied — no provenance crosses the boundary.

### The packet-local seed

The `packet_seed` is the content-addressed id of the objects' **public content**
only (`object_type` + normalized `sanitized_summary`) plus the disclosure
policy. It does **not** depend on any raw private digest, so:

- it is free of self-reference (no fixed point);
- two packets with identical public content yield an identical seed;
- the same private digest in two packets with *different* public content yields
  *different* replacements (the seed differs);
- the raw private digest is never recoverable from the replacement.

The replacement is deterministic: `replacement_digest_for(packet, objects,
policy, private_digest)` recomputes the expected replacement from the packet's
public content plus the raw digest, so a gate or test can assert the raw digest
is absent (I80-03) and the replacement matches.

## The 1 MiB canonical-encoded cap

The canonical encoded packet (UTF-8, sorted keys, compact separators, one
trailing newline) must be at most `PACKET_MAX_BYTES` (1 MiB = 1 048 576 bytes).
An oversize packet is a typed `OversizePacketError` (fail reason
`BRIDGE_CONTRACT_MISMATCH`). The exporter performs **no truncation**, because
truncating would silently corrupt the content-addressed identity and the
disclosure. The caller must reduce the object set or shorten summaries and
rebuild (I80-04).

## Honesty: exportable is not admitted

A packet discloses that summary evidence *exists*; it does **not** admit a
scientific claim and does **not** authorize an integration. This mirrors the
evidence-model orthogonality in `srl.semantic.evidence`: "exportable is not
admitted". The `grants_authority=false` const is the structural enforcement; a
packet is a disclosure of summaries, never a promotion of standing.

A packet is also **not** raw private data. Every object carries only a coarse
`object_type` (from a small disclosure-safe vocabulary), a short
`sanitized_summary`, and (under `digest_replaced`) packet-local digests — never
paths, commands, credentials, or the raw private object payloads.

## Acceptance gate

`scripts/checks/wp80-gate.py` runs five checks and emits a `GateReceipt/v1`:

- **I80-01** each valid fixture case builds, validates against the schema, and
  is under the 1 MiB cap.
- **I80-02** every adversarial input class is rejected typed
  (`BRIDGE_CONTRACT_MISMATCH` for a forbidden class, `CONTRACT_INVALID` for a
  structural failure). The literal forbidden strings are reconstructed at
  runtime from the fixture's safe placeholder pieces, so the fixture file itself
  is scanner-clean.
- **I80-03** under `digest_replaced` the raw private digests are absent and the
  replacement is deterministic; under `omitted` the provenance list is empty.
- **I80-04** an oversize packet is rejected with `OversizePacketError`; no
  truncation.
- **I80-05** the four safety consts are pinned and enforced; tampering any
  const fails schema validation.

The gate exits non-zero on any failure.

## Scanner-clean fixtures

The adversarial fixture (`fixtures/conformance/bridge/adversarial.inputs.v1.json`)
is the key design artifact: it exercises *every* forbidden class through the
sanitizer, yet the file itself is scanner-clean under
`scripts/checks/public_boundary.py` even when tracked. It achieves this by
storing only **character-level placeholder tokens** (`{S}` = slash, `{H}` =
hyphen, etc.) plus **opaque credential labels** (`{GH}`, `{SK}`, `{AK}`, `{PEM}`)
whose literal expansions live in the gate/test Python source, split across
concatenation so no contiguous forbidden literal appears in any tracked file.
The literal forbidden strings exist only in memory, at runtime, after
substitution.
