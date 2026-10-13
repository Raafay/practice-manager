# 12 Hardening, deployment and running the app

Read by Stage 13.

Stage 13 is different from the others. Part of it is checking and fixing, part is configuration, and part is writing plain guides for the two people who will run and use the app. The hosting company is chosen by the person running the build before the stage starts. If none has been chosen, do everything that does not depend on the host and say what is left.

## 1. Security review

Do this first, as a fresh pass over the whole codebase. Write findings to `docs/SECURITY-REVIEW.md`, then fix them, most serious first.

Check each of these and record the result:

1. Every staff address refuses signed-out users and portal users. Walk the URL list in a test, so a new address cannot be missed.
2. Every portal and public address refuses another client's objects. Lookups use `public_id`.
3. Every address that needs a right checks it. Finance figures are absent from pages for people without the right.
4. File handling: types, size, private storage, attachment downloads, sensitive access logged.
5. Tokens: hashed at rest, expire, single use where promised, constant-time comparison.
6. Sign-in: lockout, two-factor enforced for staff, session lengths, password re-entry on sensitive actions.
7. Forms have CSRF protection. Rich text is cleaned. No user text is marked safe in templates.
8. Queries are built by the ORM. Any raw SQL uses parameters.
9. Headers and cookies as listed in `01-security-and-users.md` section 11, proved by a test against production settings.
10. Secrets: none in the repo or its history. Encrypted fields are used wherever section 8 of that spec says.
11. Rate limits on sign-in, portal codes, request links and action links.
12. Dependencies: run `uv run pip-audit` or the nearest equivalent and deal with anything serious.
13. Logs and error pages leak no personal data.
14. CSV exports are safe against spreadsheet formulas.

## 2. What the app needs from a host

- Runs a container built from the repo's Dockerfile, with two processes: `web` (gunicorn) and `worker` (`manage.py worker`).
- PostgreSQL 16, managed, with automatic daily backups kept at least 14 days and the option to restore to a point in time.
- A private file bucket that speaks the S3 protocol, with encryption at rest and versioning.
- A UK or EEA region for all three.
- HTTPS on a custom domain with certificates renewed automatically.
- Secrets set as environment variables.
- A way to run a one-off command (migrations, creating the first owner).

Hosts that fit this shape and are worth comparing at the time: Render (Frankfurt), Fly.io (London), DigitalOcean App Platform (London), Railway (Amsterdam), and AWS in the London region for anyone comfortable with it. Regions and prices change, so check them on the day. Do not pick for the user.

## 3. Production settings

`config/settings/prod.py` reads everything from the environment and refuses to start if something required is missing.

| Variable | Purpose |
|---|---|
| SECRET_KEY | Django secret |
| DATABASE_URL | PostgreSQL address |
| ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS | The site's domain |
| FIELD_ENCRYPTION_KEYS | Keys for encrypted fields, newest first |
| STORAGE_BUCKET, STORAGE_ENDPOINT, STORAGE_REGION, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY | The private file bucket |
| EMAIL_PROVIDER and its key, DEFAULT_FROM_EMAIL | Sending email |
| COMPANIES_HOUSE_API_KEY | Companies House |
| XERO_CLIENT_ID, XERO_CLIENT_SECRET | Xero |
| SITE_URL | The public address, used in links |
| SENTRY_DSN | Optional error reporting, with personal data scrubbing on |

Also: static files served by whitenoise, migrations run on each release before the new version takes traffic, a `/healthz` address that checks the database, and structured logs to standard output.

## 4. Guides to write

All in plain English, for people who are not developers.

`docs/DEPLOY.md`: step by step for the chosen host. Create the database, the bucket and the app. Set each variable. First release. Create the first owner with `manage.py create_owner`. Point the domain at it. Add the email DNS records. Connect Companies House and Xero. A short section on releasing an update and rolling one back.

`docs/RUNBOOK.md`: what to do when something goes wrong.

- The site is down.
- A job keeps failing.
- Emails are not arriving.
- Someone is locked out, or lost their phone.
- A staff member leaves.
- A suspected data breach: who to tell and by when. A personal data breach that is likely to put people at risk must be reported to the Information Commissioner's Office within 72 hours of becoming aware of it.
- Restoring from a backup, with the exact commands.
- Rotating the encryption keys and the secret key.

`docs/BACKUPS.md`: what is backed up and how often, where it is kept, and a restore test to carry out on the first day and every three months after: restore last night's backup into a spare database, start the app against it, and check that a known client is there. Record each test in a table in the same file.

`docs/SUBPROCESSORS.md`: every outside company that stores or sees client data, what it holds, and where.

`docs/STAFF-GUIDE.md`: two pages for the practice's staff. Signing in, finding a client, the three task views, logging a request, approving queued messages, onboarding a client.

`docs/GO-LIVE.md`: the checklist in section 5, as tick boxes.

## 5. Go-live checklist

No real client data goes in until every line is ticked.

Security

- The security review is done and every serious finding is fixed.
- A second person, or a separate review session that did not write the code, has tried to reach another client's data through the portal and the request link and failed.
- Two-factor is on for every staff account. The development bypass code is not set.
- HTTPS works, and the header test passes against the live site.
- Known gap accepted in writing by the owner: uploaded files are not virus scanned.

Data

- Backups are running. A restore test has been done and recorded.
- The file bucket is private. A direct link to a file without signing in fails.
- Encryption keys are stored somewhere safe outside the host as well.
- The retention settings are set.

Compliance, signed off by the practice owner

- The deadline rules table in `03-services-and-deadlines.md` has been read and agreed.
- The risk questions, score bands and review intervals in `06-onboarding-and-aml.md` have been read and agreed.
- The engagement letter, terms, privacy notice, proposal and clearance letter carry the practice's own wording.
- The practice's privacy notice mentions the portal and the companies in `SUBPROCESSORS.md`.
- The practice's registration with the Information Commissioner's Office is current.

Operations

- Email sending is set up with SPF, DKIM and DMARC, and a test message arrives in an inbox, not in spam.
- The Companies House key works: `ch_check` returns dates for a known company.
- Xero is connected and a sync has run.
- The worker is running and last night's jobs show as done.
- Every reminder schedule is still off. The owner switches them on one at a time after go-live.
- The staff have read the staff guide and signed in.

Moving across

- Run both systems side by side for at least one full month before cancelling BrightManager.
- Import clients, contacts and services from the BrightManager export. Use the migration helper to clear deadlines already dealt with.
- Compare the next 60 days of deadlines in both systems, client by client. Any difference is looked into before relying on the new one.

## 6. Ongoing care

- Apply security updates monthly: `uv lock --upgrade`, run the tests, release.
- Read the job page and the failed messages weekly.
- Repeat the restore test every three months.
- Review who has an account every three months.

## 7. Tests added in this stage

- A walk of every URL for signed-out, portal, staff, manager and owner users against an expected table.
- Production settings: headers, cookies, DEBUG off, the app refusing to start without required variables or with the development bypass set.
- `/healthz`.
- The retention report lists the right records and deletes nothing.
