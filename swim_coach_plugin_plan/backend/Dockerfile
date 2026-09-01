FROM ghcr.io/astral-sh/uv:0.11.29 AS uv

FROM python:3.12.13-alpine3.23 AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apk upgrade --no-cache && adduser -D -u 10001 swim-coach

WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY --chown=swim-coach:swim-coach backend/src ./backend/src
RUN uv sync --frozen --no-dev --no-cache
COPY --chown=swim-coach:swim-coach backend/alembic.ini ./backend/alembic.ini
COPY --chown=swim-coach:swim-coach backend/alembic ./backend/alembic

USER swim-coach
EXPOSE 8000

CMD ["uvicorn", "swim_coach.bootstrap.api:app", "--host", "0.0.0.0", "--port", "8000"]
