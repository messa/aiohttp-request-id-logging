default: check

check: lint typecheck test

test:
	uv run pytest --log-level=DEBUG --tb=short -v tests $(pytest_args)

lint:
	uv run ruff check .
	uv run ruff format --check .

lint-fix:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run ty check
	uv run mypy

.PHONY: default check test lint lint-fix typecheck
