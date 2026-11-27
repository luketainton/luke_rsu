FROM ghcr.io/astral-sh/uv:0.13.10 AS uv
FROM python:3.15-slim
ARG APP_VERSION=v0.0.0-dev
ENV APP_VERSION=${APP_VERSION} PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY config ./config
COPY ledger ./ledger
COPY templates ./templates
COPY manage.py ./
RUN DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" uv run python manage.py collectstatic --noinput
RUN useradd --system --uid 10001 --no-create-home app
ENV PATH="/app/.venv/bin:${PATH}"
USER app
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=3).close()" || exit 1
EXPOSE 8000
CMD ["/bin/sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
