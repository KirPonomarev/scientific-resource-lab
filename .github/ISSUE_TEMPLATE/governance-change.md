---
name: Governance change
about: Propose a change to AutonomyPolicy/v1, a protected governance path, or an invariant
title: "[governance-change] <short summary>"
labels: ["governance-change"]
assignees: []
---

<!--
  Scientific Resource Lab governance-change issue.
  Use this template ONLY for changes that touch a protected governance path,
  modify or replace AutonomyPolicy/v1 or main-protection-v1, weaken an
  invariant, change what a receipt means, or change the public boundary.

  See GOVERNANCE.md. Governance changes cannot be self-validated.

  Protected governance paths:
    .github/**, automation/**, scripts/checks/**, schemas/**, policies/**,
    pyproject.toml, uv.lock, AGENTS.md, release config.
-->

## Objective

<!-- The single governance goal of this change. -->

## Governance path or invariant affected

<!-- Name the protected path(s) or invariant(s) affected, and whether this
     creates a new policy version (for example AutonomyPolicy/v2). -->

## Old verifier on the new diff

<!-- The verifier authoritative under the outgoing policy must run against the
     proposed new diff and either pass or produce a reviewed set of
     deviations. Attach the run, the result, and any deviation analysis.
     The old verifier is not discarded by proposing a new one. -->

## New verifier

<!-- The proposed new policy ships with its own verifier. Attach it and its
     run against the proposed diff. -->

## Independent review receipt

<!-- An independent reviewer (not the author, not the authoring agent) must
     produce a review receipt recording what was checked, what passed, and
     any residual risk. Attach it here. -->

## No self-validation confirmation

<!-- Confirm that the author is not the verifier and not the independent
     reviewer for this change. -->

## Delta versus the current policy

<!-- Precise description of what changes from AutonomyPolicy/v1, including the
     transition receipt that names the old version, the new version, and the
     delta. -->

## Rollback

<!-- How this governance change is reverted safely if it misbehaves in
     practice, without breaking the evidence chain. -->

## Roll forward plan

<!-- The follow-up governance work this change unblocks, or "None." -->
