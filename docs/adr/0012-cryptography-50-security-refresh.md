# ADR-0012: refresh cryptography to 50.0.0

Status: proposed for governance admission

## Context

SRL reuses `cryptography` for Ed25519 detached signatures in the bounded spool
and native-keyring adapters. The admitted lock selected 49.0.0. The mandatory
dependency audit later mapped `PYSEC-2026-3552` to CVE-2026-69247 and rejected
that lock; upstream fixes the affected range in 50.0.0.

SRL does not import the affected PKCS#7 decryption APIs. That reduces evidenced
direct exposure but does not make a vulnerable dependency closure admissible.
The dependency remains the maintained upstream implementation rather than a
new local cryptographic implementation.

## Decision

Reuse `cryptography` with a minimum version of 50.0.0 and lock exactly 50.0.0.
The lock refresh is restricted to this package. The selected release preserves
the Python requirement, direct dependency closure, and
`Apache-2.0 OR BSD-3-Clause` license used by the previous release. Existing
Ed25519 APIs remain covered by the A04 transport gate and hostile spool tests.

The authority-negative decision receipt is
`docs/verification/cryptography-50-reuse-decision-receipt-v1.json`. Its lock
and generated SBOM hashes are verified by a focused test.

## Sources

- Upstream changelog: <https://cryptography.io/en/latest/changelog/#v50-0-0>
- PyPI release metadata: <https://pypi.org/project/cryptography/50.0.0/>
- Advisory: <https://github.com/advisories/GHSA-g6cj-pr64-35w5>

## Consequences

- The dependency-audit gate no longer admits the affected 44.x-49.x range.
- No contract, wire format, key, epoch, native runtime, or authority changes.
- The package does not rotate or install keys and does not activate a bridge.
- A revert reintroduces a known vulnerable closure and must therefore restore
  a fail-closed dependency-audit/merge block until a fixed replacement exists.
