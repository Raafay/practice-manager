release: sh scripts/release.sh
web: gunicorn config.wsgi:application -c gunicorn.conf.py
worker: python manage.py worker
