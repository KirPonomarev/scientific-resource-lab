# Pack manifest and safe materialization (WP-C22)

Scientific resource packs are content-addressed bundles of code, data, and
provenance that the SRL autonomous fabric moves from upstream source control to
a sandboxed execution environment. WP-C22 defines the pack manifest contract,
the safe extraction rules, the platform matching policy, and the materialization
bridge that copies a verified pack into a mutable staging area before any
execution step runs.

## Manifest model (`ResourcePackManifest/v1`)

The manifest is the control-plane identity of a pack. It is canonical JSON
(sorted keys, compact separators, UTF-8, trailing newline) and is validated by
`srl.packs.manifest.build_manifest`.

```json
{
  "schema_version": "ResourcePackManifest/v1",
  "pack_id": "srl.pack.example",
  "name": "Example Pack",
  "version": "1.0.0",
  "capability_profiles": ["algebra_exact"],
  "platforms": [
    {"os": "linux", "arch": "x86_64", "abi": null},
    {"os": "macos", "arch": "arm64", "abi": null}
  ],
  "source": {
    "url": null,
    "commit": null,
    "source_sha256": "sha256:..."
  },
  "lock_sha256": "sha256:...",
  "tree_sha256": "sha256:...",
  "license": {
    "spdx": "MIT",
    "texts_sha256": ["sha256:..."]
  },
  "sbom_sha256": null,
  "entrypoints": [
    {"entrypoint_id": "runtime", "kind": "python_module", "ref": "run.py"},
    {"entrypoint_id": "compute", "kind": "python_module", "ref": "compute.py"}
  ],
  "probes": {
    "runtime_probe": "runtime",
    "actual_compute_probe": "compute"
  },
  "created_utc": "2026-07-28T00:00:00Z",
  "canonical_writes": 0,
  "grants_authority": false
}
```

Field semantics:

- `capability_profiles` — a subset of the 15 B14 capability profile names.
  Only known profiles are accepted; unknown names raise `CONTRACT_INVALID`.
- `platforms` — a non-empty list of supported execution platforms. Each entry has
  `os` in `{linux, macos}`, `arch` in `{x86_64, arm64}`, and an optional `abi`
  string. The current platform must match at least one entry; otherwise the
  pack raises `PLATFORM_UNSUPPORTED`.
- `source` — provenance of the upstream source. `url` and `commit` are nullable;
  `source_sha256` is a content digest of the source archive.
- `lock_sha256` — digest of the dependency lock file, if any.
- `tree_sha256` — deterministic digest of the extracted pack tree (see below).
- `license` — an SPDX identifier plus content-addressed license texts. The
  license is enforced against an allowlist and an incompatible prefix list.
- `sbom_sha256` — optional digest of the software bill of materials.
- `entrypoints` / `probes` — declared entrypoints and the two probe ids that
  the execution bridge calls. Probe ids must be declared entrypoints.
- `canonical_writes` — must be `0`; packs are immutable inputs.
- `grants_authority` — must be `false`; packs do not grant autonomous authority.

## License policy

The pack license is a hard gate because an incompatible upstream license could
contaminate the public repository or published artifacts.

- **Allowlist**: `MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `Apache-2.0`, `ISC`,
  `PSF-2.0`, `Python-2.0`, `MPL-2.0`, `CC0-1.0`.
- **Incompatible prefixes**: `GPL-`, `LGPL-`, `AGPL-`, `SSPL-`, `BUSL-`.
  Matching an SPDX identifier against these prefixes raises
  `LICENSE_INCOMPATIBLE`.
- Any other SPDX identifier raises `LICENSE_UNKNOWN`.

Both failures are terminal contract errors.

## Deterministic tree hash

`tree_sha256` is computed by `srl.packs.manifest.compute_tree_sha256` over a
directory:

1. Walk the directory recursively.
2. For each regular file, compute the SHA-256 of its content.
3. Sort the relative paths alphabetically.
4. Build a canonical JSON object mapping each sorted path to its
   `sha256:<hex>` digest.
5. Compute the SHA-256 of the canonical JSON bytes.

The result is `sha256:<hex>` and is stable across platforms and extraction order.

## Safe extraction rules

`srl.packs.extract.extract_pack` unpacks a `.tar` / `.tar.gz` / `.tar.bz2` /
`.tar.xz` / `.zip` archive into a destination directory while rejecting any
content that could escape the destination or escalate privileges:

- absolute paths or `..` segments;
- archive members that resolve outside the destination after extraction;
- symbolic links, hard links, FIFOs, devices, sockets, or any non-regular,
  non-directory member;
- setuid / setgid bits;
- executable bits on files that are not declared entrypoints.

Only regular files and directories are accepted. On-disk permissions are
normalized to `0o755` for directories, `0o644` for regular files, and `0o755`
for declared entrypoints. This makes the materialized tree independent of the
archive mode bits and safe for later execution.

## Platform matching

`srl.packs.platform.current_platform` returns the normalized current platform as
`{"os": "linux"|"macos", "arch": "x86_64"|"arm64"}`. A manifest is accepted for
execution only if at least one of its `platforms` entries matches the current OS
and architecture. On mismatch the runtime raises `PLATFORM_UNSUPPORTED`.

## Materialization bridge

Materialization is the transition from the immutable pack store to a mutable
staging area:

1. `materialize(manifest, pack_root, staging)` first checks that `pack_root`
   is not inside an immutable store root. An immutable store is marked by a
   `.srl_immutable` flag file. If the flag is found, the function raises
   `PACK_INTEGRITY_FAILURE` with the note "mutable T7 execution forbidden".
2. It computes the tree hash of `pack_root` and compares it to
   `manifest.tree_sha256`. A mismatch raises `PACK_INTEGRITY_FAILURE`.
3. It copies the pack tree to `staging` with deterministic permissions.
4. It recomputes the tree hash of the staged copy and compares it again to the
   manifest. A post-copy mismatch raises `PACK_INTEGRITY_FAILURE`.
5. On success it emits a `MaterializationReceipt/v1` recording the from/to tree
   hashes, the staging path, and a UTC timestamp.

WP-C23 builds the state machine that orchestrates extraction, materialization,
probe execution, and cleanup on top of this bridge.

## Failure reasons

WP-C22 uses the following fail reasons from `automation/fail-reasons.json`:

- `PACK_INTEGRITY_FAILURE` — unsafe archive content, tree hash mismatch, or
  immutable-store execution attempt.
- `LICENSE_UNKNOWN` — license not in the allowlist.
- `LICENSE_INCOMPATIBLE` — license matches a copyleft/source-available prefix.
- `PLATFORM_UNSUPPORTED` — current platform not in the manifest platform list.
- `CONTRACT_INVALID` — any structural manifest violation.

## Acceptance gate

`scripts/checks/wp22-gate.py` runs six checks on runtime-generated fixtures:

- C22-01: traversal, symlink, hardlink, device, and setuid archives are rejected.
- C22-02: non-entrypoint files with executable bits are rejected.
- C22-03: a manifest without a matching platform raises `PLATFORM_UNSUPPORTED`.
- C22-04: GPL licenses raise `LICENSE_INCOMPATIBLE`; unknown licenses raise
  `LICENSE_UNKNOWN`.
- C22-05: a post-copy tree hash mismatch raises `PACK_INTEGRITY_FAILURE`.
- C22-06: execution from an immutable store root is refused.

The gate emits a `GateReceipt/v1` and exits non-zero on any failure.
