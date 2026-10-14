#!/bin/sh
# The release step: runs once on each deploy, before the new version takes traffic.
# If any step fails the deploy stops and the old version keeps running.
set -eu
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py check --deploy --fail-level ERROR
echo "Release steps done."
