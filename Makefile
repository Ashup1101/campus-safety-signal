.PHONY: install lint format typecheck test audit check

install:
	uv sync --locked
	uv run pre-commit install --install-hooks

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

# Audit the locked set (dev tools included); uv venvs ship without pip, so skip it.
audit:
	uv export --locked --no-emit-project --format requirements-txt \
		| uv run pip-audit --require-hashes --disable-pip -r /dev/stdin

check: lint typecheck test audit
