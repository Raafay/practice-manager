#!/bin/bash
# Runs at the start of every Claude Code session (see .claude/settings.json).
# On your own machine it does nothing. In a cloud session it starts PostgreSQL,
# makes sure the development database exists and installs dependencies.
# It must never stop a session from starting, so it always exits 0.

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0
LOG=/tmp/session_start.log

{
  echo "== $(date -u +%FT%TZ) session_start"

  service postgresql start
  for _ in $(seq 1 30); do
    pg_isready -q && break
    sleep 0.5
  done

  # Throwaway dev role and database. Superuser so the test runner can create its own database.
  su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='pm'\"" | grep -q 1 \
    || su postgres -c "psql -c \"CREATE ROLE pm LOGIN SUPERUSER PASSWORD 'pm'\""
  su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='pm_dev'\"" | grep -q 1 \
    || su postgres -c "createdb -O pm pm_dev"

  if [ -f pyproject.toml ]; then
    uv sync --frozen || uv sync
  fi
} >"$LOG" 2>&1

if pg_isready -q; then
  echo "PostgreSQL is running. DATABASE_URL=postgres://pm:pm@localhost:5432/pm_dev (setup log: $LOG)"
else
  echo "PostgreSQL did not start. Read $LOG, then run: service postgresql start"
fi
exit 0
