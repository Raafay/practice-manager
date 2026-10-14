# Backups

## What is backed up, how often, and where

| What | Where it lives | Backup | Kept |
|---|---|---|---|
| The database: every client, contact, task, deadline, message, the activity log, encrypted tax references | Managed PostgreSQL at the host (UK or EEA region) | The host's automatic daily backup, plus point-in-time restore | At least 14 days (set this in the database's settings) |
| Uploaded files: documents, identity copies, signed letters, PDFs | The private bucket (UK or EEA region) | Versioning on the bucket keeps earlier versions of changed or deleted files | 30 days of old versions (lifecycle rule) |
| Encryption keys (`FIELD_ENCRYPTION_KEYS`) and the secret key | The host's environment settings | **A copy in the practice's password manager**, outside the host | Until replaced |
| The code | GitHub | Every commit is kept | Always |

Without the encryption keys, the National Insurance numbers, UTRs and codes in a backup cannot be read. Check the off-host copy each time you do a restore test.

The app never deletes records on its own. The retention report lists what has passed its date, and the owner decides.

## Restore test

Do this **on the first day**, before real client data goes in, and **every three months** after. It takes about 30 minutes. It proves the backups can actually be used.

1. **Restore last night's backup into a spare database.** Never restore over the live one.
   - With the host's point-in-time restore: choose "Restore" or "Fork" on the live database, pick last night, and create it as a new database, for example `pm_restore_test`.
   - Or take a dump and load it, as in `docs/RUNBOOK.md`, "Restoring from a backup".
2. **Start the app against it.** Use a second app or service at the host, or a laptop with Docker. Give it the same environment variables as live, but with:

   - `DATABASE_URL` set to the spare database
   - `ALLOWED_HOSTS` and `SITE_URL` set to its own address
   - `EMAIL_PROVIDER` left as live, but **do not run a worker**, so nothing is sent

   For a laptop:

       docker run --rm -p 8000:8000 --env-file restore-test.env practice-manager

   Then open `http://localhost:8000/healthz/`. It should say `ok`. Over plain HTTP on a laptop, the sign-in page redirects to https, so run step 3 from the console instead:

       docker run --rm --env-file restore-test.env practice-manager python manage.py shell -c "from apps.clients.models import Client; c = Client.objects.filter(name__icontains='KNOWN NAME').first(); print(c, c and c.updated_at)"

3. **Check that a known client is there.** Pick a client you know, open them (or use the command above), and check that last week's changes are present. Then reveal one National Insurance number or UTR. If it shows, the keys are right.
4. **Delete the spare database** and the test app.
5. **Record the test** in the table below. Also add a note on Settings, System, Backups.

## Restore test record

| Date | Done by | Backup restored (time) | Known client checked | Encrypted value readable | Result and notes |
|---|---|---|---|---|---|
| | | | | | |
