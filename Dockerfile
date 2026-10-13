# The web app as one container. Production settings by default (see config/settings/prod.py).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# System libraries WeasyPrint needs for PDFs, and a basic font.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        libffi8 libjpeg62-turbo shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Build the CSS and collect static files. These placeholders only let the
# settings load during the build; no database is touched and nothing is kept.
RUN SECRET_KEY=build-only-placeholder DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    FIELD_ENCRYPTION_KEYS=build-only-placeholder ALLOWED_HOSTS=localhost \
    sh -c "python manage.py tailwind build && python manage.py collectstatic --noinput" \
    && rm -rf .django_tailwind_cli

RUN useradd --create-home --uid 1000 app && mkdir -p /app/media && chown -R app /app/media
USER app

EXPOSE 8000
# Release step on each deploy: python manage.py migrate && python manage.py createcachetable
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
