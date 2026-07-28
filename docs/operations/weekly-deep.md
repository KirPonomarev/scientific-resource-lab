# weekly-deep workflow

## Purpose

The `weekly-deep` workflow is a scheduled, read-only verification job that runs
every **Monday at 04:00 UTC** (and on demand via `workflow_dispatch`). It
exercises checks that are too slow or redundant for per-PR CI but still
valuable to run once a week:

* deterministic property-based tests on the contracts layer,
* a replay of the canonical conformance vectors plus a schema digest and policy
  load check,
* a clean-clone build proving the committed tree bootstraps standalone,
* a dependency vulnerability audit with `pip-audit`.

## Schedule and trigger

* Cron: `0 4 * * 1` (Monday 04:00 UTC).
* `workflow_dispatch` for manual/on-demand runs.

## Runner and permissions

* Runs on `ubuntu-24.04` (GitHub-hosted).
* `permissions: contents: read` only.
* No `pull_request_target` trigger.
* No `secrets` context is read, and no repository secrets are required.

## What it does

1. **`property-deep`** — installs dependencies with `uv sync --locked`, then
   runs `pytest tests/property tests/contracts -q` twice with fixed Hypothesis
   seeds (`--hypothesis-seed=0` and `--hypothesis-seed=1`).
   *Why two seeds?* The repository does not register a Hypothesis `deep`
   profile, so `HYPOTHESIS_PROFILE=deep` would fail. Running the same suites
   with two fixed seeds doubles example coverage while keeping failures
   reproducible for debugging.
2. **`deterministic-replay`** — runs `scripts/checks/weekly_replay.py`, which
   re-runs `scripts/checks/canonical-vectors.py`, verifies that
   `automation/policy.json` loads through `srl.autonomy.policy.load_policy`,
   and recomputes a MANIFEST-style sha256 digest over the v1 schema files under
   `src/srl/contracts/schemas/v1`.
3. **`clean-clone-build`** — exports the committed tree with `git archive HEAD`,
   extracts it into a temporary directory under `$RUNNER_TEMP`, and runs
   `uv sync --locked && uv build` there to prove the repo bootstraps without
   relying on the checkout's local state.
4. **`dependency-audit-weekly`** — exports `uv.lock` to a `requirements.txt`
   file with `--no-editable` so only the PyPI dependencies are listed, then
   runs `uvx pip-audit -r requirements.txt`. The job fails if any known
   vulnerability is reported.

## What it does NOT do

* **No deployment.** It does not publish packages, update GitHub Pages, or push
  to any registry.
* **No private data.** It does not read user data, credentials, or environment
  variables outside the repository tree.
* **No live API calls.** The replay script and the workflow steps do not
  contact external services or APIs.
* **No secrets.** The workflow does not use `secrets.*`, `GITHUB_TOKEN`, or any
  other repository secret.
* **No self-hosted runners.** It runs exclusively on GitHub-hosted runners, as
  required by the autonomy policy.
* **No merges.** Results are reported to the repository's Actions UI only; the
  workflow never opens, merges, or modifies pull requests.

## Non-secret guarantee

Because the workflow is schedule-triggered, it cannot be observed directly in a
pull request check list. The YAML file is validated by manual structural review
and by `actionlint` when available. The workflow uses only `contents: read`
permission and pinned action commit SHAs, so a compromise would be limited to
reading the repository contents that are already public.

## Related documents

* `.github/workflows/weekly-deep.yml` — the workflow definition.
* `scripts/checks/weekly_replay.py` — the replay script run by the
  `deterministic-replay` job.
* `docs/operations/resource-policy.md` — resource limits for repository jobs.
