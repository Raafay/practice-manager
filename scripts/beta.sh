#!/bin/sh
# Run the beta: prepare the database and static files, then the website and the
# background worker. The website listens on 127.0.0.1 only, so it is reachable
# through the Cloudflare Tunnel and from this laptop, never from the local network.
# Stop with Ctrl+C. See docs/BETA.md.
set -eu
cd "$(dirname "$0")/.."
export DJANGO_SETTINGS_MODULE=config.settings.beta

uv run python manage.py migrate --noinput
uv run python manage.py createcachetable
uv run python manage.py tailwind build
uv run python manage.py collectstatic --noinput --verbosity 0
uv run python manage.py check --deploy --fail-level ERROR

uv run python manage.py worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null || true' EXIT INT TERM

echo "Beta running. Open it at the address in SITE_URL. Ctrl+C stops it."
uv run gunicorn config.wsgi:application -c gunicorn.conf.py --bind 127.0.0.1:8000
