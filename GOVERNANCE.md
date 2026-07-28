# Governance

Scientific Resource Lab (SRL) is governed by `AutonomyPolicy/v1`. This policy
is the authority for how change is admitted to the repository and how the
project's hardened guarantees are preserved over time. It is intentionally
written down, versioned, and resistant to silent drift.

The goal of governance here is not ceremony. It is to make sure that every
admitted change preserves the project's scientific honesty, its bounded
execution model, and its public repository boundary, and that the evidence for
that preservation is itself a receipt.

## AutonomyPolicy/v1

`AutonomyPolicy/v1` is the active governance policy for the repository. It
defines three invariants that every change must preserve:

1. **Receipts reflect reality.** A successful exit code and an existing
   receipt mean an operation completed. They never mean a scientific claim is
   supported.
2. **Evidence axes are never collapsed.** `READY != COMPUTED`,
   `COMPUTED != VALIDATED`, `SAT/UNSAT != empirical truth`,
   `algorithm agreement != independent replication`,
   `formal proof != empirical validation`, and `exportable != admitted`.
3. **The public boundary holds.** The repository contains code, schemas,
   synthetic fixtures and sanitized documentation only.

Any change that would weaken one of these invariants is a governance change
and must follow the governance-change workflow below. It cannot be admitted
through an ordinary pull request.

## Policy immutability

**Once a mission starts, the governing policy is immutable for the duration of
that mission.** The active `AutonomyPolicy/v1` and the ruleset
`main-protection-v1` cannot be edited, suspended, renamed, or weakened in
flight to unblock work.

If the policy must change, the change creates a **new version** of the policy
(for example `AutonomyPolicy/v2`) through the dedicated governance-change
workflow. The old policy remains the authority for all work started under it
until the new version is fully admitted and a clean transition receipt exists.

This rule exists precisely because the moments when a policy "gets in the way"
are the moments it matters most. The policy is allowed to refuse a change.

## Protected governance paths

The following paths are protected because they encode the policy, the
automation that enforces it, the schemas that define the contracts, and the
release and toolchain configuration. A change touching any of them is a
governance change:

- `.github/**` — automation, branch protection interactions, templates, and
  the ruleset-aligned workflows.
- `automation/**` — execution-context and mission receipts that establish
  provenance.
- `scripts/checks/**` — the acceptance and conformance checks that gate merge.
- `schemas/**` — the scientific and data contract schemas, including
  `schemas/v1`.
- `policies/**` — the persisted policy definitions and their version history.
- `pyproject.toml` — the project, toolchain and dependency manifest.
- `uv.lock` — the locked dependency set for reproducible builds.
- `AGENTS.md` — the agent operating agreement.
- release configuration — anything that controls how a release tag, changelog
  or artifact is produced.

Governance changes require the heavier review path described below. All other
changes follow the ordinary pull-request workflow in `CONTRIBUTING.md`.

## Ordinary change workflow

For any change that does not touch a protected governance path and does not
weaken an invariant:

1. Open an issue describing the change and its work-package identifier.
2. Open a pull request from a feature branch with the required body sections
   from `CONTRIBUTING.md`.
3. Pass the acceptance checks under `scripts/checks/**`.
4. Resolve all review threads.
5. Merge by squash merge into `main`, preserving linear history.

The `main-protection-v1` ruleset enforces the pull request requirement, linear
history, and conversation resolution mechanically. It does not by itself
guarantee the invariants hold; reviewers and the acceptance checks do that.

## Governance-change workflow

A change is a governance change if **any** of the following are true:

- it modifies a protected governance path;
- it modifies or replaces `AutonomyPolicy/v1` or `main-protection-v1`;
- it weakens, narrows, or redefines any of the three invariants;
- it changes what counts as evidence, what a receipt means, or what the public
   boundary excludes.

A governance change must be opened as a dedicated `governance-change` work
package and must satisfy all of the following before it can be merged:

1. **Old verifier on the new diff.** The verifier that was authoritative
   under the outgoing policy must run against the proposed new diff and either
   pass, or produce a documented, reviewed set of deviations. The old
   verifier is not discarded by proposing a new one.
2. **New verifier.** The proposed new policy ships with its own verifier, and
   that verifier runs against the proposed diff and passes.
3. **Independent review receipt.** An independent reviewer (not the author,
   not the same agent that authored the change) produces a review receipt that
   records what was checked, what passed, and any residual risk.
4. **No self-validation.** The agent or person that authored a policy change
   may not be the one that verifies it. Self-validation of policy changes is
   prohibited and is itself an invariant.

The governance-change issue template captures these requirements as
structured fields. A governance-change pull request missing any of them
cannot be merged, even if the ruleset would otherwise permit it.

## Versioning of policy

Policy versions are recorded as discrete, named artifacts (for example
`AutonomyPolicy/v1`, `AutonomyPolicy/v2`) and never edited in place once
admitted. The history of admitted policies is part of the evidence chain.
Superseding a policy does not delete it; it retires it with a transition
receipt that names the old version, the new version, and the delta.

## Roles

- **Contributor** — anyone who opens an issue or pull request following
  `CONTRIBUTING.md`.
- **Reviewer** — a contributor empowered to resolve threads and request
  changes, responsible for the invariants in this document.
- **Independent reviewer** — a reviewer who did not author a given governance
  change and is responsible for its review receipt.
- **Maintainer** — a contributor empowered to merge pull requests after the
  acceptance checks pass and all threads resolve, subject to this policy.

No role grants an exemption from the invariants or the public boundary.

## Relationship to the ruleset

`main-protection-v1` is the mechanical enforcement layer. It blocks
deletions, blocks force-pushes, requires linear history, and requires a pull
request with all conversations resolved. This document is the authority the
ruleset exists to protect. Where the two appear to conflict, this document
governs, and resolving the conflict is itself a governance change.
