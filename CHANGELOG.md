# Changelog

All notable changes to Scientific Resource Lab are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Commit subjects on `main` follow [Conventional Commits](https://www.conventionalcommits.org/).

A green entry means a change was admitted; it never means a scientific claim
is supported. See `README.md` and `GOVERNANCE.md` for the evidence rules.

## [Unreleased]

### Added

- Repository governance baseline under `AutonomyPolicy/v1`: policy immutability
  for an active mission, protected governance paths, and a dedicated
  governance-change workflow requiring the old verifier on the new diff, a new
  verifier, and an independent review receipt, with no self-validation.
- `SECURITY.md` with private vulnerability reporting, a supported versions
  policy, scoped reporting guidance, and an explicit prohibition on secrets or
  private data in issues and pull requests.
- `CONTRIBUTING.md` establishing the pull-request-only workflow, the
  conventional commit type set (`feat`, `fix`, `refactor`, `test`, `docs`,
  `build`, `ci`, `chore`, `perf`, `security`), and the required pull request
  body sections.
- `CODE_OF_CONDUCT.md` based on the Contributor Covenant v2.1.
- `CITATION.cff` (CFF 1.2.0) for software citation.
- `NOTICE` for the Apache-2.0 attribution.
- `.github/pull_request_template.md` embedding the required pull request body
  sections.
- `.github/ISSUE_TEMPLATE/work-package.md` and
  `.github/ISSUE_TEMPLATE/governance-change.md` for structured issue intake.
- `.editorconfig`, `.gitattributes`, and `.pre-commit-config.yaml` for shared
  formatting and hygiene hooks (trailing whitespace, end-of-file fixer, JSON
  and YAML validation, large-file and private-key detection, `ruff`).
- Repository labels and milestones aligned to the implementation plan
  (`v0.1.0` through `v1.0.0`).
- Python package skeleton `srlab` (v0.1.0) with a `src/srl` layout, a typed
  surface (`py.typed`), a canonical-JSON helper (`srl.canonical`), and a
  JSON-first CLI dispatcher (`srl.cli`) implementing `srlab doctor`,
  `srlab version`, and a canonical `ErrorReport/v1` for unknown commands.
- `pyproject.toml` selecting `hatchling` as the build backend (see
  `docs/adr/0001-build-backend.md`), with `ruff`, `mypy` (strict for `srl`),
  and `pytest` configured, and a uv-native `dev` dependency group.
- `Makefile` with `bootstrap`, `lint`, `format`, `typecheck`, `test`, `build`,
  `verify`, and `repro-check` targets (portable; no absolute paths).
- `scripts/build/reproducible-check.py` (standard library only) that builds the
  wheel twice under a fixed `SOURCE_DATE_EPOCH`, normalizes both archives, and
  emits a `ReproducibleWheelManifest/v1` with a `content_manifest_sha256`.
- `.github/workflows/ci.yml` (`name: ci`) running lint, typecheck, a
  3.11/3.12/3.13 unit matrix, and a `ubuntu-24.04`/`macos-15` package job that
  runs the reproducible-wheel check; actions pinned to full commit SHAs.
- Unit tests for the CLI dispatcher and version identity, and Hypothesis
  property tests for canonical-JSON stability and round-tripping.
- `docs/adr/0001-build-backend.md` recording the `hatchling` decision.
- `.python-version` pinning the project baseline to `3.12`.
- Committed `uv.lock` and tracked the WP-A01 closeout receipt
  (`automation/receipts/wp-closeout-a01.json`).

### Changed

- README now references `CHANGELOG.md`, `GOVERNANCE.md`, and `NOTICE`.

### Security

- Documented the public repository boundary and the prohibition on committing
  secrets, real datasets, operator identity, and absolute local paths.

## [0.1.0] - Unreleased

The first milestone target (`v0.1.0`) covers the repository, contracts, the
Scientific IR, and conformance. It is tracked as a GitHub milestone and is
released from this `Unreleased` section once the acceptance checks pass.
