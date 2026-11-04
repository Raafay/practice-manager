# Stage 17: Export, deletion and per-practice backups

Goal: each practice can take all its data away, ask for it to be deleted, and be restored on its own.

## Build

1. Full export for the practice owner: a ZIP of every table as CSV (through `safe_cell`) and every file, decrypted, built by a job and downloaded once from a link that lasts 24 hours. Logged.
2. Deletion request by the owner, typed practice name, 30-day hold during which it can be cancelled, then the schema is dropped and the file folder removed. The platform log keeps the practice name and dates only.
3. Backups: nightly per-practice `pg_dump -n` kept 30 days, alongside the whole-database backup. A restore command restores one practice into a new schema without touching the others.

## Checks

- An export of the demo practice opens and contains every client and file.
- After deletion the schema and files are gone and the other practice is unaffected.
- A one-practice restore brings back its data exactly.
