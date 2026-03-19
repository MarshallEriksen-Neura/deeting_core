FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY app /app/app
COPY main.py /app/main.py
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
COPY pyproject.toml /app/pyproject.toml
COPY uv.lock /app/uv.lock
COPY scripts/docker-entrypoint.sh /app/docker-entrypoint.sh

RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p logs security \
    && uv sync --frozen --no-dev --no-install-project

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["api"]
