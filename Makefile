.PHONY: run run-debug

run:
	uv run python run.py

run-debug:
	uv run python run.py --debug
