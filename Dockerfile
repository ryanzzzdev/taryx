FROM python:3.14-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock manage.py ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=taryx.config.settings \
    PYTHONUNBUFFERED=1

EXPOSE 8000
