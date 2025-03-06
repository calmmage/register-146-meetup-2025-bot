# Register 146 Meetup 2025 Bot

## Build & Test Commands
- Install: `poetry install`
- Run: `poetry run python run.py`
- Docker: `docker-compose up --build`
- Tests: `poetry run pytest`
- Single test: `poetry run pytest tests/path_to_test.py::test_name`
- Coverage: `poetry run pytest --cov=app`

## Code Style Guidelines
- **Formatting**: Black (line length 100)
- **Linting**: Flake8 (ignores E203, W503)
- **Imports**: isort, organized: stdlib → third-party → local
- **Types**: Use type annotations everywhere
- **Naming**: Classes=PascalCase, functions/variables=snake_case, constants=UPPER_SNAKE_CASE
- **Documentation**: Google-style docstrings
- **Error handling**: Use try/except with loguru logging

## Project Structure
- `app/`: Main application code (bot.py, router.py, routers/)
- `tests/`: Test files
- Environment variables via `.env` file and pydantic_settings