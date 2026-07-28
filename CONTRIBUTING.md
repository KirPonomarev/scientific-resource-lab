# Contributing to Scientific Resource Lab

Thank you for considering a contribution to Scientific Resource Lab (SRL).
This project is a reproducible, bounded and evidence-first scientific
computation fabric, and it is governed by `AutonomyPolicy/v1` (see
`GOVERNANCE.md`). Contributions of any size are welcome, but they must
respect the project's discipline around contracts, evidence, and the public
repository boundary.

This document is the source of truth for *how* a contribution is made. What
may be admitted is defined by `GOVERNANCE.md`, and what is expected of a
scientifically honest result is defined by `README.md`.

## Ground rules

Before doing anything else, please read and accept these points:

- **Pull requests only.** No work lands on `main` by direct push. The
  `main-protection-v1` branch ruleset blocks force-pushes and deletions,
  requires linear history, and requires a pull request. Merges are squash
  merges.
- **Public boundary.** The public repository contains code, schemas, synthetic
  fixtures and sanitized documentation only. It must never contain private
  hypotheses, real datasets, provider outputs, private object hashes, operator
  identity, topology, canonical receipts, credentials, or absolute local
  paths. See `SECURITY.md` for the prohibition on secrets.
- **Evidence over enthusiasm.** A green check is a receipt that an operation
  completed, not that a claim is supported. Do not collapse evidence axes.
- **Be kind.** Participation is governed by `CODE_OF_CONDUCT.md`.

## Contribution workflow

1. **Find or open an issue.** Every non-trivial change should trace to an
   issue. Work-package issues follow the work-package template; governance
   changes follow the governance-change template.
2. **Create a branch.** Use a descriptive name, for example
   `codex/wp01-repo-governance`, `feat/cas-ingest-receipt`, or
   `fix/runner-cpu-limit`. Do not branch from a stale `main`; rebase onto the
   latest.
3. **Make focused commits.** Keep branches reviewable. Prefer several small
   commits over one large one.
4. **Run local checks** (see the Tests section below) before pushing.
5. **Open a pull request** using the pull request template and filling in
   every required section.
6. **Respond to review.** Resolve every review thread before merge. The
   ruleset requires all conversations to be resolved.

## Conventional commits

All commit messages **and** the squash-merge commit subject on `main` use
[Conventional Commits](https://www.conventionalcommits.org/) with the
following types:

| Type       | Use for                                                                 |
|------------|-------------------------------------------------------------------------|
| `feat`     | A new feature or capability for an end user or agent.                   |
| `fix`      | A bug fix.                                                              |
| `refactor` | A code change that neither adds a feature nor fixes a bug.             |
| `test`     | Adding or correcting tests.                                             |
| `docs`     | Documentation only changes.                                             |
| `build`    | Changes to build tooling, dependency manifests, or lock files.          |
| `ci`       | Changes to CI configuration and automation pipelines.                   |
| `chore`    | Maintenance that does not fall under the other types.                   |
| `perf`     | A change that improves performance without changing behavior.           |
| `security` | A change that hardens the project against a vulnerability or abuse.     |

Format:

```text
<type>(<optional scope>): <imperative summary in lowercase>

<optional body explaining why, what changed structurally, and any receipts>

<optional footer, e.g. Refs: WP-A01>
```

Examples:

```text
feat(cas): verify content digest before recording ingest receipt

fix(runner): enforce fixed entrypoint under subprocess replacement

docs(governance): add AutonomyPolicy/v1 admission criteria

chore(governance): repository governance and community baseline
```

A scope is optional but encouraged. Common scopes include `contracts`, `cas`,
`runner`, `pack`, `portal`, `bridge`, `cli`, `mcp`, `governance`, `ci`,
`docs`.

## Required pull request sections

Every pull request must include **all** of the following sections, in this
order, even if a section states "None." A pull request missing a required
section cannot be merged. The template at `.github/pull_request_template.md`
provides the scaffold.

1. **Objective** — the single goal of the change, stated as one or two
   sentences.
2. **Scope** — the concrete files, modules, contracts or paths touched, and
   the work-package identifier if applicable.
3. **Out of scope** — adjacent work that is deliberately not in this change.
4. **Contracts changed** — any scientific or data contract that changed,
   including schema versions and `LabExportPacket` fields, or "None."
5. **Security impact** — whether the change touches the runner boundary, the
   content-addressed store, pack materialization, the disclosure sanitizer,
   or any hardened path. If it does, state how the hardening is preserved.
6. **Resource impact** — effect on CPU, wall-clock, memory, disk, network, or
   runner limits, including for automated runs.
7. **License impact** — confirmation that all new content is Apache-2.0
   compatible, and any third-party content attribution added to `NOTICE`.
8. **Tests and exact commands** — the exact commands a reviewer can copy and
  paste to verify the change, and the expected output or receipt.
9. **Evidence** — receipts, hashes, command output or links that demonstrate
   the change works and that acceptance checks passed.
10. **Known limitations** — caveats, follow-ups, or behavior a reviewer must
    be aware of.
11. **Rollback** — how to revert the change safely, including any migration or
    cleanup that a revert requires.
12. **Follow-up WP** — the work-package identifiers that this change unblocks
    or that depend on it, or "None."

## Coding standards

- Python is the primary implementation language. Target the Python baseline
  declared in the project context (currently 3.12) and keep the CI matrix in
  mind (3.11, 3.12, 3.13).
- Code is formatted and linted with `ruff`. The configuration lives in
  `pyproject.toml`. Run `ruff check --fix` and `ruff format` before pushing.
- Dependencies are managed with `uv` and declared in `pyproject.toml`; the
  lock file is `uv.lock`. Adding a dependency is a `build` commit.
- Configuration files follow `.editorconfig`: UTF-8, LF line endings, a final
  newline, 4-space indentation for Python, 2-space for YAML and JSON.
- `.pre-commit-config.yaml` installs the shared hooks (trailing whitespace,
  end-of-file fixer, JSON/YAML validation, large-file and private-key
  detection, `ruff`). Install them with `pre-commit install`.

## Tests and receipts

Every feature or fix must include or update tests. A receipt must be
reproducible from the commands in the pull request. Prefer:

- Pure-Python unit tests for contract logic, the router, and the planner.
- Property-based tests for hashing, ingest and manifest verification.
- Integration tests for the runner under the bounded configuration.

Do not commit receipts that reference private identifiers or absolute local
paths. Receipts committed to the repository must use synthetic fixtures only.

## Licensing

By contributing, you agree that your contributions are licensed under the
Apache-2.0 license, as stated in `LICENSE` and `NOTICE`. Third-party content
must be compatible with Apache-2.0 and attributed in `NOTICE`.

## Need help?

- For governance and admission questions, read `GOVERNANCE.md`.
- For security concerns, follow `SECURITY.md`; do **not** use public issues.
- For behavior expectations, read `CODE_OF_CONDUCT.md`.
