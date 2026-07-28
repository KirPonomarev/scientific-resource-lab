# CI Security Hardening Threat Model

This document captures the threat model and hardening posture for the public
continuous-integration (CI) pipelines of the Scientific Resource Lab (SRL).
It is authoritative for WP-A04 and is referenced by the ``security``,
``public-boundary`` and ``docs`` workflows.

## Scope

The hardening applies to every GitHub Actions workflow that runs on:

- pull requests to this public repository,
- direct pushes to the ``main`` branch,
- merge-group entries enqueued by the ``main-protection-v1`` ruleset.

## Threats

### Untrusted pull request data

Anyone can open a pull request from a fork. A malicious PR can contain:

- modified workflow files,
- build scripts,
- Markdown documentation,
- synthetic fixtures,
- or any other tracked file.

**Mitigation:**

- Every workflow declares `permissions: contents: read`.
- No workflow writes to the repository, releases artifacts, or touches secrets.
- All custom checks are pure Python scripts from the repository; they receive no
  secrets, perform no network calls, and mutate no state.
- Workflows that need the locked dependency set run `uv sync --locked` and
  execute checks inside the uv-managed virtual environment.

### Action supply-chain compromise

Third-party actions can be compromised, re-tagged, or removed. A workflow that
references a mutable tag (`v1`) can silently receive a different payload on
every run.

**Mitigation:**

- Every action reference is pinned to a full SHA-256 commit digest.
- The human-readable version is kept in a trailing comment.
- Updating an action is a deliberate change: resolve the new tag to its commit
  SHA, update the workflow, and review the diff.

### Read-only token misuse

GitHub provides a temporary `GITHUB_TOKEN` for every workflow. If granted write
permissions, a compromised job could push commits, create releases, or modify
repository settings.

**Mitigation:**

- All WP-A04 workflows request `permissions: contents: read` only.
- `persist-credentials: false` is passed to `actions/checkout` so the checkout
  step does not retain the token longer than necessary.
- No workflow writes packages, publishes docs, or posts comments.

### Secret leakage

CI logs and build artifacts are public. A workflow that echoes environment
variables, prints credentials, or materializes secret files can leak them.

**Mitigation:**

- No repository secrets are defined for read-only CI jobs.
- The secret-scan job scans every tracked file for credential shapes, private
  keys, and high-entropy hex strings.
- The public-boundary job scans for absolute local paths, credential patterns,
  oversized files, binary extensions, UUIDv7 identifiers, and sensitive JSON
  keys (`organism_pulse`, `unified_snapshot`, `operator_context`).
- Both scanners use only stdlib and never make network calls.

### Malicious dependency insertion

A pull request could add a dependency with a copyleft, proprietary, or unknown
license, or a dependency with a known vulnerability.

**Mitigation:**

- `uv.lock` is the single source of truth for the dependency tree.
- The license-inventory job fails if any dependency is outside the allowlist
  (MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0, Unicode-3.0,
  MPL-2.0, Python-2.0) or is unknown.
- The dependency-audit job exports the locked tree to a requirements file and
  runs `pip-audit` to detect known vulnerabilities.

## Fork-PR posture

Forks are explicitly supported. A fork PR receives the same read-only
permissions and runs the same checks as a branch PR. Because no secrets are
required and no write permissions are granted, fork PRs are safe to run without
maintainer approval. The ruleset's required-status-checks policy still applies,
so every PR must pass the hardened gates before merge.

## Rationale for SHA pinning

SHA pinning is the only workflow supply-chain control that survives tag
rewriting, account takeovers, and accidental breaking changes. The project
records the resolved SHA and the corresponding version comment in each workflow
file. When an action must be updated, the new SHA is verified through the GitHub
API or the action's release notes and committed as a normal change, which itself
passes the same CI gates.

## Out of scope

This model intentionally does not cover:

- release workflows (WP-F52),
- demo build and deployment (WP-F52),
- branch protection or ruleset changes (governance workflow),
- repository-level secret management (there are no read-only CI secrets).

These are handled by separate work packages and require the governance-change
process defined in `GOVERNANCE.md`.
