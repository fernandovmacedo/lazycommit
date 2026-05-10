.PHONY: help build clean test ci lint typecheck test-py311 test-py314

## Show available make targets.
help:
	@awk 'BEGIN { print "Available targets:" } \
		/^## / { help = substr($$0, 4); next } \
		/^[a-zA-Z0-9_.-]+:/ { \
			target = $$1; \
			sub(/:.*/, "", target); \
			if (help != "") { \
				printf "  %-10s %s\n", target, help; \
				help = ""; \
			} \
		}' $(MAKEFILE_LIST)

## Build the package artifacts.
build:
	uv build

## Remove local build and test artifacts.
clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .venv build dist *.egg-info

## Run the same checks as the CI workflow before pushing.
test: ci

## Aggregate local CI checks.
ci: lint typecheck test-py311 test-py314

## Run Ruff against the package and tests.
lint:
	uv run ruff check lazycommit/ tests/

## Run strict mypy over the package.
typecheck:
	uv run mypy lazycommit/

## Run the test suite on the oldest supported Python in CI.
test-py311:
	uv run --python 3.11 pytest tests/ -v

## Run the test suite on the newest Python in CI.
test-py314:
	uv run --python 3.14 pytest tests/ -v
