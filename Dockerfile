FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies and uv.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

COPY . .

RUN uv sync --group extras

CMD ["uv", "run", "python", "run.py"]
