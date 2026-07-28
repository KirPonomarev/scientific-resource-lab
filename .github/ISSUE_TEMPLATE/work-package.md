---
name: Work package
about: Define a unit of work (a work package) for the implementation plan
title: "[WP-XX] <short summary>"
labels: []
assignees: []
---

<!--
  Scientific Resource Lab work-package issue.
  Use this template for each work package from the implementation plan.
  Fill every field; the acceptance gate is what reviewers check at merge time.
-->

## WP_ID

<!-- The work-package identifier, for example WP-A01. -->

## EPIC_ID

<!-- The epic or milestone this work package belongs to, for example v0.1.0
     or SRL_AUTONOMOUS_IMPLEMENTATION_PLAN_v1.0. -->

## Summary

<!-- One or two sentences describing what this work package delivers. -->

## OWNED_PATHS

<!-- The repository paths this work package is authorized to change, one per
     line. A work package must not touch paths outside this list. -->

```text

```

## EXPECTED_CHECKS

<!-- The acceptance checks (under scripts/checks/**) that must pass for this
     work package, one per line, plus any manual commands. -->

```text

```

## Acceptance gate

Describe the conditions that must hold for this work package to be considered
done. The pull request linked to this issue must demonstrate all of them in
its Evidence section.

- [ ] All OWNED_PATHS changes are within the declared set.
- [ ] All EXPECTED_CHECKS pass and their output is attached as evidence.
- [ ] Required PR body sections are present and complete.
- [ ] No protected governance path is modified, OR a governance-change
      workflow is attached (old verifier on new diff, new verifier,
      independent review receipt, no self-validation).
- [ ] Public repository boundary respected: no secrets, real datasets,
      operator identity, topology, canonical receipts, or absolute local
      paths.

## Definition of done

<!-- What concrete, observable state proves this work package is finished.
     Prefer a receipt, a hash, or a command output over a narrative. -->

## Dependencies

<!-- WP identifiers this depends on, and WP identifiers that depend on this,
     or "None." -->

## Notes

<!-- Anything else a reviewer or future contributor needs to know. -->
