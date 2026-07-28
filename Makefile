# Scientific Resource Lab developer Makefile.
# Portable: no absolute paths or usernames. Uses uv for everything.
# Targets run via `uv run` so contributors only need uv installed.

.PHONY: bootstrap lint format typecheck test build verify repro-check gate-wp03 gate-wp10 gate-wp11 gate-wp12 gate-wp13 clean help

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

verify: lint typecheck test build ## Run lint, typecheck, tests, and build.

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

clean: ## Remove build artifacts and caches.
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache
