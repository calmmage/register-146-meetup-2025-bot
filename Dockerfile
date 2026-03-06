FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies and uv.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

# Reuse dependency layers when app code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group extras

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "run.py"]
