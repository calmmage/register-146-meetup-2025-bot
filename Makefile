.PHONY: run run-debug check fix test

run:
	uv run python run.py

run-debug:
	uv run python run.py --debug

# Run all CI checks locally
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run vulture --min-confidence 80 --exclude .venv .
	uv run pyright
	uv run pytest tests/

# Auto-fix what can be fixed
fix:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest tests/ --cov=app --cov-report=term --cov-fail-under=50
