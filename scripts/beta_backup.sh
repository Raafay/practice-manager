#!/bin/sh
# Copy the beta database and uploaded files into BACKUP_DIR, keeping the newest 30
# of each. Run nightly (docs/BETA.md). Time Machine then copies BACKUP_DIR off the laptop.
set -eu
cd "$(dirname "$0")/.."
setting() { sed -n "s/^$1=//p" .env.beta | tail -n 1; }

DATABASE_URL=$(setting DATABASE_URL)
MEDIA_ROOT=$(setting MEDIA_ROOT)
BACKUP_DIR=$(setting BACKUP_DIR)
: "${DATABASE_URL:?DATABASE_URL missing from .env.beta}"
: "${MEDIA_ROOT:?MEDIA_ROOT missing from .env.beta}"
: "${BACKUP_DIR:?BACKUP_DIR missing from .env.beta}"

umask 077
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y-%m-%d_%H%M)
pg_dump --format=custom --file="$BACKUP_DIR/db_$STAMP.dump" "$DATABASE_URL"
tar -czf "$BACKUP_DIR/files_$STAMP.tar.gz" -C "$MEDIA_ROOT" .

for kind in db files; do
    ls -1t "$BACKUP_DIR"/"$kind"_* 2>/dev/null | tail -n +31 | while read -r old; do rm -f "$old"; done
done
echo "Backup written to $BACKUP_DIR ($STAMP)."
