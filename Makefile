.PHONY: install lint format typecheck test audit check backup schedule unschedule

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

# Additive copy of local-only state to BACKUP_DIR from .env; nothing in the backup is deleted.
# Reads the one key instead of sourcing .env, so unquoted paths with spaces work.
backup:
	@dir="$$(sed -n 's/^BACKUP_DIR=//p' .env 2>/dev/null | tail -n 1 | tr -d "\"'")"; \
	case "$$dir" in "~"/*) dir="$$HOME/$${dir#\~/}" ;; esac; \
	test -n "$$dir" || { echo "set BACKUP_DIR=/path/to/backup in .env" >&2; exit 1; }; \
	mkdir -p "$$dir" && rsync -a data .notes "$$dir"/ && echo "copied data/ and .notes/ to $$dir"

# Daily LaunchAgent for `iu-crime-log run` (macOS).
schedule:
	uv run python scripts/launchd_job.py install

unschedule:
	uv run python scripts/launchd_job.py uninstall
