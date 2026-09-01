FROM ghcr.io/astral-sh/uv:0.12.9 AS uv
FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY config ./config
COPY ledger ./ledger
COPY templates ./templates
COPY manage.py ./
RUN uv run python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["/bin/sh", "-c", "uv run python manage.py migrate --noinput && uv run gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
