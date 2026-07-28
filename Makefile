# Scientific Resource Lab developer Makefile.
# Portable: no absolute paths or usernames. Uses uv for everything.
# Targets run via `uv run` so contributors only need uv installed.

.PHONY: bootstrap lint format typecheck test build verify repro-check clean help

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

clean: ## Remove build artifacts and caches.
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache
