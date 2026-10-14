# The app as one image. The same image runs both processes:
#   web:     gunicorn config.wsgi:application -c gunicorn.conf.py   (the default command)
#   worker:  python manage.py worker
#   release: sh scripts/release.sh   (once per deploy: migrations, cache table, checks)
# Production settings by default (config/settings/prod.py). See docs/DEPLOY.md.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

# System libraries WeasyPrint needs for PDFs, and a basic font.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        libffi8 libjpeg62-turbo shared-mime-info fonts-dejavu-core \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# uv installs the locked dependencies. Taken from PyPI, so the build needs only
# Docker Hub (for the base image) and PyPI.
RUN pip install --no-cache-dir "uv==0.11.*"

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Build the CSS and collect static files with build-only settings: no secrets and
# no database are needed. The Tailwind binary is removed afterwards.
RUN DJANGO_SETTINGS_MODULE=config.settings.build \
    sh -c "python manage.py tailwind build && python manage.py collectstatic --noinput" \
    && rm -rf .django_tailwind_cli

# Run as a user without root rights. The code is read-only to it.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz/', timeout=4)"
CMD ["gunicorn", "config.wsgi:application", "-c", "gunicorn.conf.py"]
