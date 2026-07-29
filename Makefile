# Scientific Resource Lab developer Makefile.
# Portable: no absolute paths or usernames. Uses uv for everything.
# Targets run via `uv run` so contributors only need uv installed.

.PHONY: bootstrap lint format typecheck test build verify repro-check gate-a01 gate-a02 gate-a03 gate-a04 gate-a05 gate-a06 gate-a07 gate-a08 gate-a09 gate-wp03 gate-wp10 gate-wp11 gate-wp12 gate-wp13 gate-wp14 gate-wp45 corpus router-determinism clean help

help: ## Show this help.
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make <target>\n\nTargets:\n"} \
	  /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

bootstrap: ## Install dependencies from the lockfile (uv sync --locked).
	uv sync --locked

lint: ## Lint and check formatting without writing (ruff).
	uv run ruff check .
	uv run ruff format --check .

format: ## Apply ruff formatting and auto-fixes in place.
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Type-check the srl package with mypy strict.
	uv run mypy

test: ## Run the test suite (pytest, quiet).
	uv run pytest

build: ## Clean dist/ and build sdist + wheel (uv build).
	rm -rf dist
	uv build

# Deterministic build proof: two clean wheel builds must be byte-for-byte
# equivalent after normalization. Prints a JSON manifest with the content hash.
repro-check: ## Run the reproducible-wheel check and print the manifest.
	uv run python scripts/build/reproducible-check.py


verify: ## Run lint, typecheck, tests, V3.7 gates, one A09 prepare, and build.
	uv run python scripts/ci/verify-v37.py

gate-a01: ## Run the V3.7 A01 truth-ledger acceptance gate.
	uv run python scripts/checks/srf-v37-a01-gate.py

gate-a02: ## Run the V3.7 A02 non-destructive T7 binding gate.
	uv run python scripts/checks/srf-v37-a02-gate.py

gate-a03: ## Run the V3.7 A03 environment factory gate.
	uv run python scripts/checks/srf-v37-a03-gate.py

gate-a04: ## Run the V3.7 A04 signing and transport gate.
	uv run python scripts/checks/srf-v37-a04-gate.py

gate-a05: ## Run the V3.7 A05 enforced sandbox gate.
	uv run python scripts/checks/srf-v37-a05-gate.py

gate-a06: ## Run the V3.7 A06 durable executor and scheduler gate.
	uv run python scripts/checks/srf-v37-a06-gate.py

gate-a07: ## Run the V3.7 A07 P0 Python core activation gate.
	uv run python scripts/checks/srf-v37-a07-gate.py

gate-a08: ## Run the V3.7 A08 native algebra and SMT activation gate.
	uv run python scripts/checks/srf-v37-a08-gate.py

gate-a09: ## Run the V3.7 A09 Lean/mathlib and corpus activation gate.
	uv run python scripts/checks/srf-v37-a09-gate.py

# WP-A03 autonomy-contracts gate. Runs the five acceptance checks and prints a
# GateReceipt/v1 JSON receipt; non-zero exit on any FAIL. Pure stdlib + the
# in-repo srl package, so it runs under `python3` without a prior install.
gate-wp03: ## Run the WP-A03 autonomy-contracts acceptance gate.
	uv run python scripts/checks/wp03-gate.py

# WP-B10 canonical JSON and identifiers gate. Runs the four acceptance checks
# (B10-01..B10-04) and prints a GateReceipt/v1 JSON receipt; non-zero exit on
# any FAIL. Uses the contracts layer (which depends on jsonschema), so it runs
# under `uv run python`.
gate-wp10: ## Run the WP-B10 canonical-JSON acceptance gate.
	uv run python scripts/checks/wp10-gate.py

# WP-B11 scientific object fabric gate. Runs the four acceptance checks
# (B11-01..B11-04) — restricted MathIR allowlist, fixture-scoped dimensional
# consistency, claim invariants at schema + python layer, schemas meta-valid +
# positive fixtures validate — and prints a GateReceipt/v1 JSON receipt;
# non-zero exit on any FAIL. Uses the contracts + semantic layer (which depend
# on jsonschema), so it runs under `uv run python`.
gate-wp11: ## Run the WP-B11 scientific-object-fabric acceptance gate.
	uv run python scripts/checks/wp11-gate.py

# WP-B12 transformation receipts + adapter semantic profiles gate. Runs the
# four acceptance checks (B12-01..B12-04) — a lossy step cannot claim LOSSLESS
# (schema + python), an introduced assumption is carried explicitly, a backend
# projection binds the adapter/pack hash with lineage chaining, and no raw
# sympify/sage_eval input route is exposed — and prints a GateReceipt/v1 JSON
# receipt; non-zero exit on any FAIL. Uses the contracts + semantic layer
# (which depend on jsonschema), so it runs under `uv run python`.
gate-wp12: ## Run the WP-B12 transformations acceptance gate.
	uv run python scripts/checks/wp12-gate.py

# WP-B13 evidence assessment + run receipt gate. Runs the four acceptance
# checks (B13-01..B13-04) — an import probe cannot yield COMPUTED (receipt +
# assessment levels), a SMT-style answer yields at most CHECKED without a
# verified certificate (formal_check=proven rejected without a certificate),
# a formal axis cannot update an empirical axis, and algorithmic reproduction
# differs from independent replication — and prints a GateReceipt/v1 JSON
# receipt; non-zero exit on any FAIL. Uses the contracts + semantic layer
# (which depend on jsonschema), so it runs under `uv run python`.
gate-wp13: ## Run the WP-B13 evidence-model acceptance gate.
	uv run python scripts/checks/wp13-gate.py

# WP-B14 router and planner gate. Runs the four acceptance checks
# (B14-01..B14-04) — determinism (same inputs -> byte-identical plan across 3
# rebuilds incl. shuffled input keys), decision coverage (all 15 profiles, no
# silent drops), no silent fallback (remote_required never runs local), and
# unknown capability -> WAIT_CAPABILITY (plus cyclic-dependency + resource
# overflow negatives) — and prints a GateReceipt/v1 JSON receipt; non-zero
# exit on any FAIL. Uses the contracts + planning layer (which depend on
# jsonschema), so it runs under `uv run python`.
gate-wp14: ## Run the WP-B14 router-planner acceptance gate.
	uv run python scripts/checks/wp14-gate.py

# Router/planner determinism proof: rebuild the golden plan twice and compare
# bytes. Fails closed the moment the planner's output becomes input-order-
# dependent (a regression that would break content-addressed identity). Prints
# a RouterDeterminismReceipt/v1 JSON receipt; non-zero exit on failure.
router-determinism: ## Run the router/planner determinism check.
	uv run python scripts/checks/router-determinism.py

# WP-E45 P0 integration gate. The Phase E capstone: runs the six acceptance
# checks (E45-01..E45-06) — runtime probes for all four P0 packs (units, smt,
# ripser, pyriemann), actual-compute probes against their goldens, >=5 distinct
# MEASURED real-compute runs per pack (wall/rss/expanded_bytes read off the
# process, never fabricated), catalog seal determinism, the synthetic
# end-to-end slice (claim -> plan -> run -> validate -> portal), and an
# overclaim scan (no formal_check=proven with authority=none) — and prints an
# IntegrationReceipt/v1 JSON receipt; non-zero exit on any FAIL or if the gate
# wall exceeds 300s. Uses the packs + planning + portal + semantic layers, so
# it runs under `uv run python`.
gate-wp45: ## Run the WP-E45 P0 integration acceptance gate.
	uv run python scripts/checks/wp45-gate.py

# WP-B15 public conformance corpus. Loads the thirty-task public corpus under
# fixtures/conformance/corpus/, runs each TaskSpec/v1 through the real
# science-lab pipeline (a pure evaluation against the router/planner + the
# contract validators), compares each task's expected outcome against the
# outcome the pipeline produced, and verifies the declared category coverage.
# Prints a CorpusReceipt/v1 JSON receipt (30 outcomes, zero mismatches on
# PASS); non-zero exit on any mismatch or coverage drift. Pure stdlib + the
# in-repo srl package, so it runs under `python3` without a prior install.
corpus: ## Run the WP-B15 public conformance corpus check.
	uv run python scripts/checks/wp15-corpus.py

clean: ## Remove build artifacts and caches.
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache
