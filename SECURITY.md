# Security Policy

Scientific Resource Lab (SRL) is a reproducible, bounded and evidence-first
scientific computation fabric. Security, integrity and confidentiality of
research artifacts are part of the product, not an afterthought. This policy
describes how to report vulnerabilities responsibly and what the project
considers in scope.

## Supported versions

SRL is in early development toward a first stable `v1.0.0`. Only the release
lines listed below receive security updates. Anything not listed is out of
scope for backports.

| Version | Supported          | Notes                                                       |
|---------|--------------------|-------------------------------------------------------------|
| `main`  | Yes (development)  | Receives the fix first; becomes the basis for the next tag. |
| `1.0.x` | Yes (once released)| Latest patch line of the first stable release.              |
| `< 1.0` | Best effort        | Pre-release lines; fix lands on `main`, no backport promise.|

Pre-release versions (`0.x`) may ship breaking changes and must not be relied
upon for security-sensitive production workloads until `v1.0.0`.

## Reporting a vulnerability

**Do not open a public GitHub issue for a security vulnerability.**

Private vulnerability reporting is enabled on this repository. To report a
security issue:

1. Use GitHub's **Report a vulnerability** feature on the
   [Security](https://github.com/KirPonomarev/scientific-resource-lab/security/advisories/new)
   tab. This opens a private advisory visible only to repository maintainers.
2. Include a clear description of the issue, the affected component
   (contracts, CAS, runner, pack, portal, bridge, CLI, MCP), the steps to
   reproduce, and the observed versus expected behavior.
3. If known, include the SRL version or commit SHA, the platform, the Python
   version, and the relevant receipt identifiers.

A maintainer will acknowledge the report, usually within 5 business days, and
will coordinate a fix and disclosure timeline with you. Please do not disclose
the issue publicly until a fix has been released and you have been notified.

The project follows coordinated disclosure. Reporters are credited in the
release notes and in the published security advisory unless they ask to remain
anonymous.

## What to report

Please report vulnerabilities that affect SRL itself. Examples:

- Bypass of the bounded runner's fixed-entrypoint model or hard resource
  limits (CPU, wall-clock, memory, disk, process count).
- Path traversal, symlink escape, or arbitrary write outside the declared
  content-addressed store or pack materialization root.
- Hash-locked capability packs being accepted with mismatched content, or
  content-addressed ingest returning a digest for non-verified bytes.
- Improper handling of untrusted JSON or schema inputs that leads to code
  execution, denial of service, or receipt forgery.
- Failure of the disclosure sanitizer in the `LabExportPacket/v1` bridge that
  leaks private identifiers, real datasets, operator identity, or topology.
- Cross-platform handling of receipts, archives or manifests that breaks the
  evidence chain or produces a misleading receipt.

## What is not in scope

- Vulnerabilities in dependencies that are already tracked upstream. Report
  them to the upstream maintainer; we pick up the fix through normal updates.
- Theoretical timing or side-channel attacks against non-cryptographic paths.
- Findings from automated scanners without a reproducible impact statement.
- Issues in forks, mirrors or copies of this repository hosted elsewhere.
- Reports that require breaking the public repository's stated boundary (see
  the `public_repo_excludes` list in the execution context) to demonstrate.

If you are unsure whether something is in scope, send a private report anyway;
we will triage and respond.

## Hardening commitments

SRL treats the following as non-negotiable and any change weakening them is a
governance change subject to the dedicated `governance-change` workflow:

- Receipts must reflect observed reality. Exit code zero means an operation
  completed and a receipt exists; it never means a scientific claim is
  supported.
- Evidence axes are never collapsed (see `README.md`). Exportable is not
  admitted; computed is not validated.
- The public repository never contains private hypotheses, real datasets,
  provider outputs, private object hashes, operator identity, topology,
  credentials, or absolute local paths.

## Prohibition of secrets and private data in issues and pull requests

Issues, pull requests, comments, commit messages, and all other public
contributions must not contain secrets, credentials, API tokens, private keys,
real datasets, private identifiers, operator identity, absolute local paths,
or any other data that falls under the public repository boundary.

If you realize you have pushed a secret or private data:

1. Do **not** open a public issue describing it.
2. Rotate the affected credential immediately with the issuing provider.
3. Send a private vulnerability report describing the exposure window so the
   history can be addressed.

Pull request authors should run `detect-private-key` and
`check-added-large-files` (configured in `.pre-commit-config.yaml`) locally
before pushing. Large files and apparent key material are rejected by the
hooks and will block merge.
