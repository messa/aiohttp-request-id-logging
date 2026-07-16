default: check lint

check:
	uv run pytest --log-level=DEBUG --tb=short -v tests $(pytest_args)

lint:
	uv run ruff check .
	uv run ruff format --check .

lint-fix:
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: default check lint lint-fix
