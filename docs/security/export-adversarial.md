# Export Adversarial Corpus (WP-I81)

This document is the authoritative reference for the adversarial corpus that
turns the public `LabExportPacket/v1` exporter (`srl.bridge.exporter`) and the
refuse-not-strip sanitizer (`srl.bridge.sanitizer`) into a security test
harness. It is referenced by the `bridge` workflow's `export-corpus-gate`
job and by `scripts/checks/wp81-corpus.py`.

The corpus lives under `fixtures/conformance/bridge/corpus/`:

- `valid.v1.json` — twelve synthetic, disclosure-safe build cases.
- `adversarial.v1.json` — forty-plus malformed/adversarial build cases.

The gate drives every case through the **real, merged exporter** — never mocks
at the corpus level — and asserts the single load-bearing invariant:

> A forbidden disclosure NEVER produces a valid export packet.

## How the corpus is driven

The gate (`scripts/checks/wp81-corpus.py`) emits a single canonical
`CorpusReceipt/v1` JSON line and exits non-zero on any failure. Four checks:

| Check | Asserts |
|---|---|
| **I81-01** valid corpus | Every valid case builds through `build_packet`, schema-validates against `LabExportPacket`, has a content-addressed `packet_id`, and is at most 1 MiB when canonically encoded. At least 12 cases. |
| **I81-02** adversarial corpus | Every adversarial case is rejected with the EXPECTED typed `fail_reason`. No case passes with the WRONG reason. At least 40 cases. |
| **I81-03** determinism | Two runs of the substantive checks produce byte-identical canonical bytes (no wall-clock, no random, no order-dependent fields). |
| **I81-04** counts | The valid corpus has ≥ 12 cases and the adversarial corpus has ≥ 40 cases. |

The pytest mirror (`tests/bridge/test_export_corpus.py`) re-implements the
minimal corpus driver inline so a change to the gate cannot silently weaken
what the test suite checks; it parametrizes per case so a regression names the
exact failing case.

## Forbidden-class taxonomy

The adversarial corpus covers every class the sanitizer refuses. Each class
maps to a stable detector name reported by `SanitizerRefusalError.forbidden_class`
and to an `expected_fail_reason`. Two typed reasons apply:

- `BRIDGE_CONTRACT_MISMATCH` — a forbidden summary class, an oversize packet,
  or a recursive-payload smuggling hit. A deterministic boundary violation.
- `CONTRACT_INVALID` — a structural/schema/object-construction failure (bad
  object type, tampered const, wrong type, stale hash, unknown schema version,
  unknown license field).

| Class | Detector | Reason | What it proves |
|---|---|---|---|
| `local_path` | `_LOCAL_PATH_RE` | `BRIDGE_CONTRACT_MISMATCH` | An absolute local path (`/Users/`, `/home/`, `/Volumes/`) in a summary is refused. |
| `unix_path` | `_UNIX_ABS_PATH_RE` | `BRIDGE_CONTRACT_MISMATCH` | ANY structural unix path (`/app/secret/file`, `/opt/data/f`, `/var/log/x.log`) is refused. The detector is structural, not list-based — an unlisted directory root does not bypass it. |
| `windows_path` | `_WINDOWS_PATH_RE` | `BRIDGE_CONTRACT_MISMATCH` | A Windows drive path (`C:\...`, `D:/...`) is refused. |
| `argv_flag` / `argv_short_flag` | `_ARGV_FLAG_RE` / `_ARGV_SHORT_FLAG_RE` | `BRIDGE_CONTRACT_MISMATCH` | A leading-dash command flag (`--secret`, `-x8`) reads like a pasted command line, not a summary. |
| `shell_command` | `_SHELL_COMMAND_RE` | `BRIDGE_CONTRACT_MISMATCH` | A known shell invocation (`sudo`, `bash`, `curl`, ...) as the first token is refused. |
| `env_assignment` | `_ENV_ASSIGN_RE` | `BRIDGE_CONTRACT_MISMATCH` | A `KEY=value` assignment is refused, CASE-INSENSITIVELY (`API_KEY=` and `api_key=` alike). |
| `env_reference` | `_ENV_REF_RE` | `BRIDGE_CONTRACT_MISMATCH` | A `$VAR` / `${VAR}` shell reference is refused, case-insensitively. |
| `credential_keyword` | `_CREDENTIAL_KEYWORD_RE` | `BRIDGE_CONTRACT_MISMATCH` | A credential field bound by `=` or `:` (`secret=hunter2`, `token: abc`) discloses a secret shape even when the value is not a recognized concrete pattern. |
| `credential_pattern` | `_CREDENTIALS_COMPILED` | `BRIDGE_CONTRACT_MISMATCH` | A concrete credential shape (GitHub PAT, `sk-`, AWS access key ID, PEM private-key header) is refused. |
| `raw_dataset_marker` | `_RAW_DATASET_RE` | `BRIDGE_CONTRACT_MISMATCH` | A word indicating raw private data (`raw_dataset`, `private_data`, `patient_record`, ...) is refused. |
| `t7_uuidv7` | `_UUIDV7_RE` | `BRIDGE_CONTRACT_MISMATCH` | A T7 / RFC 9562 UUIDv7 identifier is refused. |
| `vps_topology_marker` | `_VPS_TOPOLOGY_RE` | `BRIDGE_CONTRACT_MISMATCH` | A deployment-topology word (`vps_host`, `availability_zone`, `region_tag`, ...) is refused. |
| `private_key_marker` | `_PRIVATE_KEY_RE` | `BRIDGE_CONTRACT_MISMATCH` | A Pulse / Snapshot / OperatorContext-shaped private key (`organism_pulse`, `unified_snapshot`, `operator_context`) is refused. |
| `promotion_flag` | `_PROMO_FLAG_RE` | `BRIDGE_CONTRACT_MISMATCH` | A live/trading/promotion flag (`live_mode`, `trading_enabled`, `promotion_granted`, ...) is refused. A packet can never promote status. |
| `nested_smuggling` | `scan_payload` (recursive) | `BRIDGE_CONTRACT_MISMATCH` | A forbidden value hidden in ANY nested non-exempt string field of the packet payload is refused. Closes the smuggling vector where a forbidden value outside `sanitized_summary` would reach a built packet. |
| `oversize_packet` | `OversizePacketError` | `BRIDGE_CONTRACT_MISMATCH` | A packet whose canonical encoded bytes exceed 1 MiB is refused; the exporter performs NO truncation. |
| `unicode_evasion` | (ASCII detectors) | `BRIDGE_CONTRACT_MISMATCH` | A unicode-evasion ATTEMPT (fullwidth slash, zero-width space) co-occurring with an ASCII forbidden substring is refused. See the rationale below. |
| `self_referential_hash` | (guard + schema) | `CONTRACT_INVALID` | A self-referential fixed point is not constructible through the public API; a structurally-invalid digest is rejected. |
| `stale_hash` | (schema) | `CONTRACT_INVALID` | A stale / non-content-addressed object digest is rejected by schema validation (defense in depth). |
| `unknown_schema_version` | (schema) | `CONTRACT_INVALID` | A packet whose `schema_version` is not `LabExportPacket/v1` fails validation. |
| `unknown_license` | (schema) | `CONTRACT_INVALID` | `LabExportPacket/v1` forbids additional properties; a smuggled `license` field is rejected. The packet carries no license field by design. |
| `unknown_object_type` | (`ExportObject`) | `CONTRACT_INVALID` | An `object_type` outside the disclosure-safe enum vocabulary is rejected at construction. |
| `wrong_type` | (`normalize_summary` / `ExportObject`) | `CONTRACT_INVALID` | A non-string `sanitized_summary` or a non-sha256 `object_digest` is a structural contract violation. |
| `grants_authority_tamper` | (schema) | `CONTRACT_INVALID` | A tampered safety const (`grants_authority`, `canonical_writes`) fails validation. A packet never grants authority. |

## Scanner-clean fixtures

Both corpus files are **scanner-clean** under `scripts/checks/public_boundary.py`
even when tracked. The adversarial fixture stores only CHARACTER-LEVEL placeholder
tokens (`{S}` for slash, `{H}` for hyphen, `{U}` for underscore, `{E}` for equals,
`{B}` for backslash, `{FW}` for the fullwidth slash U+FF0F, `{ZW}` for the
zero-width space U+200B) plus OPAQUE CREDENTIAL LABELS (`{GH}`, `{SK}`, `{AK}`,
`{PEM}`). The gate owns the credential-label expansion in Python source, SPLIT
across string concatenation so no contiguous forbidden literal appears in the
tracked `.py` file either. The literal forbidden string is reconstructed at
runtime by direct substitution, then fed to `build_packet`. **No literal
secrets** are present — every credential is a placeholder pattern, never a live
value.

## Unicode-evasion rationale

The sanitizer does **not** Unicode-normalize summaries before running the
forbidden-class detectors. This is a deliberate, considered choice, not an
oversight:

- **Refuse-not-strip forbids a quiet Unicode rewrite.** Normalizing a summary
  (e.g. NFKC-folding a fullwidth slash `／` U+FF0F to an ASCII `/`) would be a
  silent mutation of the disclosure text. The sanitizer's contract is that the
  only mutation it performs is whitespace collapsing (`normalize_summary`); it
  never edits content. A Unicode fold would be a content edit and would violate
  that contract. A refused summary must be honestly re-summarized by the caller.

- **The consequence is an accepted detection gap for pure-Unicode evasion.** A
  summary containing ONLY fullwidth slashes (`／app／secret／file`) or ONLY
  zero-width spaces BETWEEN path segments (replacing the ASCII slash) is NOT
  refused, because no ASCII forbidden substring is present. This is documented
  here as a known limitation rather than patched with a quiet normalization.

- **The corpus exercises the CAUGHT attempts.** The two `unicode_evasion`
  cases carry the Unicode character AND a co-occurring ASCII forbidden
  substring, so an ASCII detector fires and the attempt IS refused:
  - `adv-037` — a fullwidth slash interspersed with an ASCII structural path
    (`/etc/foo`); the ASCII `unix_path` detector fires.
  - `adv-038` — a zero-width space injected INSIDE a path segment
    (`/app/sec<ZW>ret/file`); the slashes and segment bodies stay contiguous,
    so the ASCII `unix_path` detector fires.

  These cases document that the caught attempts are caught only because of the
  ASCII co-occurrence, NOT because the sanitizer Unicode-normalizes.

- **Mitigation responsibility.** The honest fix for the pure-Unicode gap is at
  the producer: a summary that needs a path-like glyph should be re-summarized
  to describe the science (not the environment). A future hardening that adds
  Unicode-aware detection must do so as an explicit, refuse-not-strip rule
  (refuse the summary, do not fold it), and must extend both the producer-side
  sanitizer and the `public_boundary` scanner together.

## Refuse-not-strip reminder

A summary (or, recursively, any non-exempt string field of the packet payload)
that contains a forbidden class is **REFUSED** at build time with a typed
`BRIDGE_CONTRACT_MISMATCH` error. The sanitizer never silently strips, masks,
truncates, or rewrites a forbidden substring. A quiet rewrite would let a
private value leak through in a subtly-different form on the next revision, and
would hide the fact that a disclosure was attempted with private data in it.
Refusing forces the exporter's caller to honestly re-summarize the object — to
describe the *science*, not the *environment* — before the summary can cross
the boundary.

The recursive payload scan (`scan_payload`) extends this to EVERY string field
of the assembled packet (defense in depth), so a forbidden value cannot hide in
any field other than `sanitized_summary`. Structural fields (digests, the pinned
`schema_version`, timestamps, the closed `disclosure_policy` / `object_type`
vocabularies) are exempt because they are validated by the schema and the
exporter's constructors and carry no free-text risk.

## Honesty

A corpus PASS never means the exporter is "secure". It means the documented
refusal behavior is reproduced for this synthetic corpus. The corpus is
synthetic: synthetic digests, disclosure-safe summaries, placeholder
credential patterns. No real private data, no live secrets, no real paths.
