# Handover report

Written 15/10/2026 from a read-only inspection of the repository in a cloud session. No application code, settings or data were changed. Where something could not be confirmed, the report says so.

---

## 1. Git state

`git status` on branch `claude/zealous-hopper-pmtzau` (before this report was added):

    On branch claude/zealous-hopper-pmtzau
    nothing to commit, working tree clean

`git log --oneline -15`:

    6baf407 Merge pull request #13 from Raafay/claude/sharp-keller-d89e2x
    25fa0e4 Stage 13: screens, STATUS, README; fix the remove-person page's blocked message
    6278008 Stage 13: guides (DEPLOY, RUNBOOK, BACKUPS, SUBPROCESSORS, STAFF-GUIDE, GO-LIVE) with a test that GO-LIVE carries every checklist line; reset_two_factor console command; secret key fallbacks
    0f3d0f8 Stage 13: security review write-up
    8c443d4 Stage 13: Settings, System page for the owner (version, backup note, jobs, email, Companies House and Xero, pause switch); demo data for retention and backups
    1d6f220 Stage 13: retention report and monthly job (lists, never deletes); subject access export as a ZIP; owner removes a person for good only when no retention period runs
    e39ac0b Stage 13: delivery reports from the email provider through a secret-checked webhook; bounces and spam complaints on the Queued page and to the approver
    f4d9a7f Stage 13: production image: build-only settings, uv from PyPI, release script, gunicorn config, Procfile, health check; add boto3 for the bucket and SES; fix a vendored source-map reference that broke collectstatic
    041e4f7 Stage 13: production settings refuse to start without what they need; private bucket, email provider, JSON logs, optional scrubbed Sentry, /healthz, live header check
    e5de4ee Stage 13: review fixes: text messages follow edit rules, retry re-checks, safe redirect, password before Xero connect and failures download, request size cap, files never cached, tax columns hidden in import, reveal client checked, portal code tries counted atomically
    3c37f11 Stage 13: portal never shows a colleague's draft details or sensitive uploads
    aee0716 Stage 13: fees kept from roles without the right (timeline, PDF, compose, queued messages, proposals, letters, sort); pipeline totals for finance.owner
    7ea382c Stage 13: take tokens out of every log line; JSON log lines on request
    6703f9c Stage 13: visitor address from the trusted proxy for lockout, rate limits and the log; limit wrong two-factor codes per person
    60a01c6 Stage 13: users.manage cannot be used to gain more access than the holder has; password asked again before inviting

Is everything committed and pushed?

- Yes for this checkout. `HEAD`, `origin/main` and `origin/claude/zealous-hopper-pmtzau` are all `6baf4075b859b195464472710f43a35b4928eae5`. Nothing is uncommitted.
- The local `main` ref in this container is stale (`cb85f60`) because it was not updated after the clone; `origin/main` on GitHub is current. This does not matter.
- No open pull requests on `Raafay/practice-manager`. All 13 stage pull requests (#1 to #13) are merged.
- CI (`.github/workflows/ci.yml`) on the latest `main` commit `6baf407` passed: run 27, https://github.com/Raafay/practice-manager/actions/runs/38585880965.

Branches not merged into `main`:

| Branch | Commits not in main | What it is |
|---|---|---|
| `origin/claude/sleepy-tesla-qwr8j6` | 1 (`9a0f414`, 14/10/2026) | "Demo loads on a Mac without Pango: stand-in PDF in development only". Adds `apps/core/pdf.py` and `apps/core/tests/test_pdf.py`, changes `apps/clients/demo.py`, `apps/comms/letters.py`, `README.md`, `docs/STATUS.md`. With DEBUG on, a one-page placeholder PDF is used when WeasyPrint's system libraries are missing; with DEBUG off it still raises. No pull request is open for it. Decide whether to open one and merge it. |

All other remote branches (`claude/adoring-galileo-6edwvg`, `awesome-hamilton-andry0`, `compassionate-darwin-kfwpn7`, `eloquent-clarke-aezclt`, `hopeful-gates-4pfqis`, `nifty-knuth-isuax1`, `peaceful-cerf-16u8mo`, `pensive-einstein-v7xugt`, `sharp-keller-d89e2x`, `sharp-knuth-96f9y3`, `stoic-cray-rqe1nl`, `trusting-feynman-fm97v2`) are 0 commits ahead of `main`, so they are fully merged and can be deleted.

Ignored files that exist in this environment (`git status --ignored`):

- `.venv/` only (the Python environment uv made). It holds no secrets and can be recreated with `uv sync`.
- There is no `.env`, no `media/`, no `media_test/` at the time of checking, no `*.sqlite3` and no `staticfiles/`. `static/css/tailwind.css` (built CSS) has not been built here.
- Nothing that matters lives only in this container. The local PostgreSQL database `pm_dev` is empty (no migrations applied, see section 7).

`.gitignore` excludes: `.env`, `.env.*` (but keeps `.env.example`), `/media/`, `/media_test/`, `/staticfiles/`, `*.sqlite3`, `/static/css/tailwind.css`, `/.django_tailwind_cli/`, `CLAUDE.local.md`, `.claude/settings.local.json`. On any machine where the app has been run, these are the files to keep safe or delete: `.env` (secrets), `media/` (uploaded files, including demo identity documents), `*.sqlite3` (local databases).

---

## 2. Build status

Stage table copied from `docs/STATUS.md`:

| Stage | State | Merged on |
|---|---|---|
| 0 Project pack | Done | 12/10/2026 |
| 1 Foundation | Done | 13/10/2026 |
| 2 Clients and contacts | Done | 13/10/2026 |
| 3 Companies House and jobs | Built, in review | |
| 4 Services and deadlines | Done | 13/10/2026 |
| 5 Tasks, part one | Built, in review | |
| 6 Communications | Built, in review | |
| 7 Onboarding and AML | Built, in review | |
| 8 Tasks, part two | Built, in review | |
| 9 Prospects and proposals | Built, in review | |
| 10 Portal and requests | Built, in review | |
| 11 Time, fees, Xero and forecast | Built, in review | |
| 12 Import and reports | Built, in review | |
| 13 Hardening and deployment | Built, in review | |

The table is out of date. Git shows every stage merged into `main`:

| Stage | Pull request | Merged |
|---|---|---|
| 3 | #3 | 13/10/2026 |
| 5 | #5 | 13/10/2026 |
| 6 | #6 | 14/10/2026 |
| 7 | #7 | 14/10/2026 |
| 8 | #8 | 14/10/2026 |
| 9 | #9 | 14/10/2026 |
| 10 | #10 | 14/10/2026 |
| 11 | #11 | 14/10/2026 |
| 12 | #12 | 14/10/2026 |
| 13 | #13 | 14/10/2026 |

What is still missing for the stages not marked Done (from the "Known gaps" list in `docs/STATUS.md`):

- 3: Companies House and the gov.uk bank holiday refresh were tested against samples only (both are reachable from this session today, see section 6).
- 5: Unticking a filing step does not reopen its deadline; the project filter has no box in the panel (added in 8).
- 6: SMS has no provider (button hidden); only console and in-memory email backends were tested live.
- 7: Risk questions, score bands and letter wording are starter text the owner must approve; 30-day HMRC postal code expiry needs confirming.
- 8: Project templates cannot be edited in Settings; drag and drop never checked in a live browser.
- 9: Drag and drop never checked in a live browser; Prospects list has no CSV export.
- 10: No email-in or WhatsApp-in; portal items are not withdrawn when a records task is cancelled.
- 11: Live Xero connection never tested (Xero not reachable from cloud sessions).
- 12: No real BrightManager export has been seen; the column-heading guesses are unproven.
- 13: The Docker image was never built with the WeasyPrint system libraries step (Docker Hub and the Debian mirror were blocked); live SES, bucket, Companies House and Xero untested; no host chosen; go-live checklist unticked.

Full test suite (`uv run pytest`, PostgreSQL 16, run 15/10/2026 in this session):

- Exit code 0. 1,584 tests collected.
- Passed: 1,583. Failed: 0. Skipped: 0. Errors: 0.
- Expected failure (strict xfail): 1, `apps/services/tests/test_rules.py::test_sa_second_payment_on_account_for_2026_27_as_the_spec_labels_it`. This is deliberate: spec 03 labels 31/07/2027 as the 2026/27 second payment on account, but it is the 2025/26 one; the code follows HMRC and the spec case is flagged in `docs/STATUS.md` for the owner.
- Warnings: Django 6 deprecation warning for `forms.URLField` default scheme (known, listed under Stage 2 gaps).

Lint: `uv run ruff check .` "All checks passed!"; `uv run ruff format --check .` "476 files already formatted". `uv run python manage.py makemigrations --check --dry-run`: "No changes detected".

---

## 3. Stack as actually built

| Item | As built |
|---|---|
| Python | 3.12 (`.python-version` = `3.12`; this environment runs 3.12.3; image `python:3.12-slim-bookworm`) |
| Django | 5.2.18 (`django>=5.2,<5.3` in `pyproject.toml`) |
| Database in development | PostgreSQL 16 (16.15 here), `postgres://pm:pm@localhost:5432/pm_dev`, driver `psycopg[binary]` 3.3. SQLite also works for a quick look (`DATABASE_URL=sqlite:///local.sqlite3`); CI smoke-tests migrate and seed on SQLite. |
| Database in production | Assumed managed PostgreSQL 16 in a UK or EEA region, through `DATABASE_URL` (parsed by `dj-database-url`, `conn_max_age=60`). |
| Cache | Development: `LocMemCache`. Production: `DatabaseCache` in table `cache_table` (made by `createcachetable` in `scripts/release.sh`). |
| Static files | `whitenoise` middleware with `CompressedManifestStaticFilesStorage` in production; `collectstatic` runs during `docker build` into `staticfiles/`. JavaScript libraries vendored in `static/vendor/` (htmx 2.0.11, Alpine CSP 3.17.4, SortableJS 1.15.7, Trix 2.1.19, Heroicons 2.2.0). No CDN. |
| Uploaded files | Development and tests: local disk, `FileSystemStorage` at `MEDIA_ROOT` (default `media/`, tests `media_test/`). Production: an S3-compatible private bucket via `django-storages[s3]` (`storages.backends.s3.S3Storage`) and `boto3`, `default_acl="private"`, signed URLs valid 60 seconds, `ServerSideEncryption: AES256` unless `STORAGE_SSE=false`, `file_overwrite=False`. Files are streamed through permission-checked views; `MEDIA_URL` is not routed. `config/settings/prod.py` makes a bucket compulsory; local disk is not an option in production. |
| PDFs | WeasyPrint 70.0, from HTML templates. System packages needed (installed in the `Dockerfile`): `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 libjpeg62-turbo shared-mime-info fonts-dejavu-core`. On a Mac, Homebrew `pango` is needed (or the unmerged stand-in branch, section 1). |
| CSS | Tailwind through `django-tailwind-cli` 4.8 (standalone Tailwind CLI 4.1.3 binary, no Node). Source `assets/css/source.css`, output `static/css/tailwind.css`. Commands: `uv run python manage.py tailwind build` (`make css`), `uv run python manage.py tailwind runserver` (`make dev`). Built in the image, then the binary is removed. |
| App server | gunicorn (`gunicorn.conf.py`): binds `0.0.0.0:$PORT` (default 8000), `WEB_CONCURRENCY` workers (default 3), `WEB_TIMEOUT` (default 60 s), `max_requests=1000` with jitter 100, access log off, `forwarded_allow_ips="*"`. |
| Other libraries | django-allauth[mfa] 65.19, django-axes 8.3, django-htmx 1.29, django-anymail 15.2, nh3 0.3, cryptography 50, segno (QR codes), sentry-sdk 2 (optional). Dev only: pytest, pytest-django, factory-boy, playwright, ruff. |

Deployment files that exist:

- `Dockerfile`: `python:3.12-slim-bookworm`; installs the WeasyPrint libraries listed above and `apt-get upgrade`; installs `uv==0.11.*` from PyPI; `uv sync --frozen --no-dev` into `/opt/venv`; builds CSS and runs `collectstatic` with `DJANGO_SETTINGS_MODULE=config.settings.build` (no secrets, no database); deletes the Tailwind binary; runs as non-root user `app` (uid 1000); `EXPOSE 8000`; `HEALTHCHECK` fetches `/healthz/` every 30 s; default command `gunicorn config.wsgi:application -c gunicorn.conf.py`; default settings `config.settings.prod`.
- `.dockerignore`: excludes `.git`, `.venv`, `.env*` (keeps `.env.example`), media, staticfiles, built CSS, `docs/screens`, caches.
- `Procfile`:

      release: sh scripts/release.sh
      web: gunicorn config.wsgi:application -c gunicorn.conf.py
      worker: python manage.py worker

- `scripts/release.sh`: `migrate --noinput`, `createcachetable`, `check --deploy --fail-level ERROR`.
- `docker-compose.yml`: for local trial only, with development settings (DEBUG on, HTTP, bypass code `000000`). Services `db` (postgres:16, user/password/db `pm`/`pm`/`pm_dev`, volume `pgdata`), `web` (runs `migrate`, `seed_demo`, `runserver 0.0.0.0:8000`, port 8000), `worker` (`manage.py worker`, passes `COMPANIES_HOUSE_API_KEY`).
- `.github/workflows/ci.yml`: on push to `main` and on pull requests: PostgreSQL 16 service, `uv sync --frozen`, ruff check and format, `pytest`, `makemigrations --check`, and a SQLite smoke test (`migrate` then `seed_demo`).
- No host-specific config (no `fly.toml`, `render.yaml`, `app.yaml`, Kubernetes or Terraform). `docs/DEPLOY.md` is written for a generic container host.

---

## 4. Scheduled and background work

There is one background process: `python manage.py worker` (`apps/jobs/management/commands/worker.py`). It loops forever, wakes at the start of each minute and calls `apps.jobs.services.run_due()`, which runs each registered job whose last schedule slot has not yet run. Each run is recorded in the database (`apps/jobs/models.py`), with a lock so a slot never runs twice. `python manage.py worker --once` checks once and stops. `python manage.py run_job <name>` runs one job by hand. The owner can also press "Run now" on the Jobs page, which asks the worker to run it.

There is no cron file, no systemd unit and no Celery or Redis. The worker is wired up in the `Procfile` (`worker`) and `docker-compose.yml` (`worker` service), but **nothing is running anywhere today**: no host exists, and no worker process is running in this environment. Exactly one worker copy must run in production (`docs/DEPLOY.md` step 9). Settings, System shows "Worker running" when it is alive.

Every registered job (times are Europe/London):

| Job name | What it does | Schedule | Code |
|---|---|---|---|
| `send_messages` | Sends approved queued emails (the message queue) | Every 5 minutes | `apps.comms.jobs.send_messages` |
| `owner_summary` | Owner summary email, when due by its own setting | Every 60 minutes (checks) | `apps.finance.jobs.owner_summary` |
| `ch_sync` | Companies House refresh of every linked company | Daily 02:00 | `apps.companieshouse.jobs.nightly_sync` |
| `xero_sync` | Xero contacts, invoices and payments sync (read only) | Daily 02:30 | `apps.finance.jobs.xero_sync` |
| `deadlines` | Deadline generation for every client service | Daily 03:00 | `apps.services.jobs.nightly_deadlines` |
| `tasks_catch_up` | Makes any tasks missing for deadlines | Daily 03:30 | `apps.tasks.jobs.tasks_catch_up` |
| `repeating_tasks` | Creates the current period of repeating tasks | Daily 03:45 | `apps.tasks.jobs.repeating_tasks` |
| `import_fetch` | Fetches Companies House data for imported companies | Daily 04:30 | `apps.imports.jobs.import_fetch` |
| `reminders` | Drafts client reminders into the queue from reminder schedules | Daily 06:00 | `apps.comms.jobs.reminders` |
| `aml_reviews` | AML review due dates and identity document expiry | Daily 06:30 | `apps.aml.jobs.aml_reviews` |
| `onboarding_daily` | HMRC authorisation expiry and engagement letter reviews | Daily 06:45 | `apps.onboarding.jobs.onboarding_daily` |
| `pipeline_daily` | Quiet prospects and expired proposals | Daily 06:50 | `apps.pipeline.jobs.pipeline_daily` |
| `task_notices` | Deadline notices to staff (bell) | Daily 07:00 | `apps.tasks.jobs.task_notices` |
| `daily_task_email` | Daily task email to staff (sent directly, not queued) | Daily 08:00 | `apps.tasks.jobs.daily_task_email` |
| `bank_holidays` | Refreshes UK bank holidays from gov.uk | Monthly, day 1, 03:30 | `apps.core.jobs.refresh_bank_holidays` |
| `retention_report` | Lists records past their retention dates (never deletes) | Monthly, day 2, 04:00 | `apps.clients.jobs.retention_report` |

Deadline generation also runs straight away when a client's services or inputs change (signals in `apps/services`), and after a services import. All jobs except `bank_holidays` notify the owner on failure.

---

## 5. Configuration

Settings modules: `config/settings/base.py` (shared), `dev.py` (reads `.env`, DEBUG on), `test.py`, `prod.py` (production), `build.py` (image build only). `manage.py` defaults to `config.settings.dev`; `config/wsgi.py` and the Docker image default to `config.settings.prod`. Helpers in `config/settings/env.py`; booleans accept `1`, `true`, `yes`, `on`.

In this environment **none** of the variables below is set in the shell, and there is no `.env` file. The session start script exports `DATABASE_URL=postgres://pm:pm@localhost:5432/pm_dev` for its own run only. Development falls back to the defaults shown.

### Read by the settings

| Variable | Purpose | Required in production | Default (base/dev) | Set here |
|---|---|---|---|---|
| `DJANGO_SETTINGS_MODULE` | Which settings file | Set by image (`config.settings.prod`) | `config.settings.dev` via `manage.py` | No |
| `SECRET_KEY` | Django signing key; prod refuses `django-insecure*` or under 40 characters | Yes | dev: `django-insecure-development-only` | No |
| `SECRET_KEY_FALLBACKS` | Old secret key during rotation (prod only) | No | empty | No |
| `DATABASE_URL` | PostgreSQL address | Yes | `postgres://pm:pm@localhost:5432/pm_dev` | No (session script only) |
| `ALLOWED_HOSTS` | Comma list of host names | Yes | dev: `localhost,127.0.0.1,[::1]` | No |
| `CSRF_TRUSTED_ORIGINS` | Comma list with `https://` | Yes | empty | No |
| `SITE_URL` | Public address used in email links; prod requires `https://` | Yes | `http://localhost:8000` | No |
| `FIELD_ENCRYPTION_KEYS` | Fernet keys for encrypted fields, newest first | Yes | dev: derived from `SECRET_KEY`; tests: fresh key per run | No |
| `DEFAULT_FROM_EMAIL` | Sending address (also `SERVER_EMAIL`) | Yes | `Practice Manager <no-reply@example.com>` | No |
| `EMAIL_PROVIDER` | `ses`, `postmark` or `brevo` (prod only) | Yes | base: `console` (hard-coded) | No |
| `EMAIL_WEBHOOK_SECRET` | `name:password` for delivery-report webhook `/email/events/` | Yes (prod checks for a colon) | empty | No |
| `EMAIL_ACCESS_KEY`, `EMAIL_SECRET_KEY` | Amazon SES IAM keys | Yes if `ses` | none | No |
| `EMAIL_REGION` | SES region | No | `eu-west-2` | No |
| `EMAIL_CONFIGURATION_SET` | SES configuration set for delivery events | No (needed for bounce reports) | none | No |
| `EMAIL_API_KEY` | Postmark server token or Brevo API key | Yes if `postmark` or `brevo` | none | No |
| `EMAIL_BACKEND` | Django email backend outside prod | No | console backend | No |
| `STORAGE_BUCKET` | Private bucket name | Yes | none | No |
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | Bucket keys | Yes | none | No |
| `STORAGE_ENDPOINT` | Endpoint for non-AWS buckets | No | AWS | No |
| `STORAGE_REGION` | Bucket region | No | `eu-west-2` | No |
| `STORAGE_SSE` | Send the server-side encryption header | No | `true` | No |
| `MEDIA_ROOT` | Local upload folder (non-prod) | No | `<repo>/media` | No |
| `COMPANIES_HOUSE_API_KEY` | Companies House REST key | No (System page shows "No key") | empty | No (the session proxy injects one, see section 6) |
| `COMPANIES_HOUSE_TRANSPORT` | `live` or `fake` (saved samples) | No | `live` (tests force `fake`) | No |
| `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET` | Xero app credentials | No | empty | No |
| `XERO_TRANSPORT` | `live` or `fake` | No | `live` (tests force `fake`) | No |
| `SMS_BACKEND` | Dotted path of an SMS class; empty means texts off; prod refuses the console class | No | empty | No |
| `TRUSTED_PROXY_COUNT` | Proxies in front of the app, to find the visitor's address | Usually 1 | `0` | No |
| `TRUSTED_CLIENT_IP_HEADER` | Host's own client-IP header instead of the count | Host-dependent | empty | No |
| `APP_VERSION` | Release name shown on Settings, System and in Sentry | No | `development` | No |
| `LOG_FORMAT` | `json` for JSON lines (prod forces JSON) | No | plain | No |
| `LOG_LEVEL` | Root log level | No | `INFO` | No |
| `SENTRY_DSN` | Optional error reports (scrubbed) | No | empty (off) | No |
| `SENTRY_ENVIRONMENT` | Sentry environment name | No | `production` | No |
| `ALLOW_DEMO_DATA` | Lets `seed_demo` run without DEBUG; prod refuses it | Must not be set | `false` | No |
| `MFA_TOTP_INSECURE_BYPASS_CODE` | Dev code that passes two-factor; prod refuses it | Must not be set | dev: `000000` | No |
| `DEBUG` | Only checked by prod, which refuses it if true | Must not be set | dev forces True | No |

### Read outside the settings

| Variable | Where | Default |
|---|---|---|
| `PORT` | `gunicorn.conf.py`, Docker `HEALTHCHECK` | `8000` |
| `WEB_CONCURRENCY` | `gunicorn.conf.py` | `3` |
| `WEB_TIMEOUT` | `gunicorn.conf.py` | `60` |
| any name you choose | `create_owner --password-from-env NAME` reads the password from it | none |

### Security settings, and how production sets them

| Setting | Production value (`config/settings/prod.py`) |
|---|---|
| `DEBUG` | `False`; startup fails if `DEBUG` env is truthy |
| `ALLOWED_HOSTS` | From `ALLOWED_HOSTS` env, required |
| `SECRET_KEY` | From env, required, not `django-insecure*`, at least 40 characters |
| `CSRF_TRUSTED_ORIGINS` | From env, required |
| `SECURE_SSL_REDIRECT` | `True`, except `^healthz/$` |
| `SECURE_PROXY_SSL_HEADER` | `("HTTP_X_FORWARDED_PROTO", "https")` |
| `SECURE_HSTS_SECONDS` | 31,536,000 (one year), `INCLUDE_SUBDOMAINS=True`, preload off on purpose (`security.W021` silenced) |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | `True` |
| `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_HTTPONLY` | `True` |
| `SESSION_COOKIE_SAMESITE`, `CSRF_COOKIE_SAMESITE` | `Lax` |
| `ACCOUNT_DEFAULT_HTTP_PROTOCOL` | `https` |
| Other headers (base, all environments) | strict CSP (`script-src 'self'`, `style-src 'self' 'unsafe-inline'`, `frame-ancestors 'none'`), `Referrer-Policy: same-origin`, `nosniff`, `X-Frame-Options: DENY` |

These are proved by `apps/core/tests/test_headers_live.py`, and can be checked against a live site with `python manage.py check_headers https://<domain>`.

---

## 6. External services

Reachability from this cloud session, tested 15/10/2026 with one request each: Companies House API returned HTTP 200 (the session proxy injects a key); gov.uk `bank-holidays.json` returned HTTP 200; `api.xero.com` could not be reached. CLAUDE.md says cloud sessions cannot reach Companies House or gov.uk; that is no longer true for this session, but the app's live paths were not exercised here.

| Service | State | Credentials | Where to get them | What does not work today |
|---|---|---|---|---|
| Companies House | Fully coded: `apps/companieshouse/api.py` (search, profile, officers, PSCs, filings, rate pacing), import, nightly `ch_sync`, `ch_check` command; fake transport in `apps/companieshouse/fake.py` | `COMPANIES_HOUSE_API_KEY` (REST key, live service) | Free, developer.company-information.service.gov.uk | No key is configured for the app. Without one, lookups fail ("No key"). Never run against the live API by the app itself in a deployed setting. |
| Xero | Fully coded, read-only sync plus "create contact" (`apps/finance/xero.py`, `sync.py`, fake in `xero_fake.py`), OAuth with tokens in encrypted fields | `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`; redirect `{SITE_URL}/integrations/xero/callback`; scopes `offline_access accounting.contacts accounting.invoices.read accounting.payments.read` | developer.xero.com, My Apps (steps in `docs/XERO_SETUP.md`) | Never connected to real Xero. Needs a deployed HTTPS site (or localhost) and a sync run. Disconnect only forgets tokens; the app must also be removed in Xero. Check Xero's current scope rules for apps created after 2 March 2026. |
| Email sending | Fully coded via django-anymail: `ses` (default, eu-west-2), `postmark`, `brevo`; message queue and approval; delivery webhook `/email/events/` (bounces, complaints, delivered) | SES: `EMAIL_ACCESS_KEY`, `EMAIL_SECRET_KEY`, `EMAIL_CONFIGURATION_SET`; others: `EMAIL_API_KEY`; all: `EMAIL_WEBHOOK_SECRET`, `DEFAULT_FROM_EMAIL` | AWS console (SES in London, IAM user limited to `ses:SendRawEmail`, SNS topic); or Postmark / Brevo accounts | Never sent through a real provider; only console and in-memory backends tested. SES production access must be requested. DNS (DKIM, SPF, DMARC) not set up. SNS signatures are not verified (shared secret only, accepted). |
| File bucket | Coded via django-storages S3 | `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, optional `STORAGE_ENDPOINT`, `STORAGE_REGION` | AWS S3, DigitalOcean Spaces, Cloudflare R2 (EU), etc. | Never run against a real bucket. Lifecycle rule (30 days of old versions) not set. |
| SMS | Interface only (`apps/comms/sms.py`): `ConsoleSmsBackend` (dev), `MemorySmsBackend` (tests). No provider class | A provider class plus its keys, then `SMS_BACKEND` | Not chosen | Texts cannot be sent. Button and text schedules are hidden. |
| Identity checks (electronic AML) | Interface only (`apps/aml/providers.py`, `get_provider()` returns `None`) | Depends on provider | Not chosen | No electronic checks. Identity checks are recorded by hand with an uploaded copy. |
| HMRC | Absent (no API). HMRC authorisations are tracked by hand in `apps/onboarding`, codes in encrypted fields | n/a | n/a | No agent authorisation API. |
| gov.uk bank holidays | Coded, monthly `bank_holidays` job; bundled list as fallback | None | n/a | Tested against a sample file only. |
| Sentry | Optional, coded with scrubbing (`apps/core/sentry.py`) | `SENTRY_DSN` | sentry.io, EU region | Not configured. |
| Virus scanning | Absent | n/a | n/a | Uploaded files are not scanned (accepted gap, needs owner sign-off). |
| Email in, WhatsApp, Slack, Teams, AI | Absent | n/a | n/a | Not in scope for this version. |

---

## 7. Data

**Demo data.** `make seed` runs `uv run python manage.py seed_demo` (`apps/core/management/commands/seed_demo.py`). It runs only when `DEBUG` is on or `ALLOW_DEMO_DATA=true`; production settings refuse to start with `ALLOW_DEMO_DATA` set, so it cannot run on a live site. It is safe to run twice. It loads practice "Hale & Castell Accountants (demo)", made-up staff (password `demo-password-2026`, dev two-factor code `000000`), clients, contacts, documents, Companies House snapshots, services, deadlines, tasks, messages, AML, onboarding, pipeline, three portal users, finance and import history. `docker compose up` also runs it.

**Removing demo data.** There is no command to remove it. The clean way is never to load it into the production database: start production from a fresh, empty database, which only gets the reference data made by migrations. On a database that has demo data, the only clean option is to drop and recreate the database and run `migrate` again (for example `dropdb pm_dev && createdb pm_dev && uv run python manage.py migrate`), and delete the `media/` folder (or the bucket contents). Deleting demo records by hand is not supported and would leave activity log lines.

**Migrations.** 41 migration files across the project apps (81 in the full plan with Django's own). `makemigrations --check --dry-run`: "No changes detected", so no migration is missing from the code. In this environment's `pm_dev` database **no migrations are applied** (`showmigrations --plan` shows all 81 as `[ ]`); the database is empty. They were not applied because this task was read-only. CI applies them on every run. Migrations that load reference data (not demo data): `accounts/0002_seed_roles`, `aml/0002_seed`, `comms/0002_seed_templates_and_schedules`, `finance/0002_seed_chase_templates`, `onboarding/0002_seed`, `pipeline/0002_seed`, `services/0002_seed_catalogue`, `tasks/0002_seed`, `tasks/0004_seed_project_templates`, `portal/0002_portal_wording`.

**First real owner on a fresh database** (production image, from the host's console):

    sh scripts/release.sh
    # which runs: python manage.py migrate --noinput
    #             python manage.py createcachetable
    #             python manage.py check --deploy --fail-level ERROR
    python manage.py create_owner --email owner@yourpractice.co.uk --name "Owner Name"
    # asks for the password twice (at least 12 characters), or:
    python manage.py create_owner --email owner@yourpractice.co.uk --name "Owner Name" --password-from-env OWNER_PASSWORD

Two-factor: there is no command to set it up. The owner signs in at `https://<domain>/login/` and is forced to add an authenticator app (TOTP) before any page opens, then saves the recovery codes. If a phone is lost: `python manage.py reset_two_factor --email <address>` (see `docs/RUNBOOK.md`).

Practice settings: there is no seeding command. The single `PracticeSettings` row (pk 1) is created automatically the first time it is read, with defaults (name "Our practice", accent `#2f5d8a`, VAT rate 20.00, not VAT registered, idle timeout 60 minutes, maximum session 12 hours, trust-this-browser on, retention 6 years, AML retention 5 years, sending paused off). The owner fills it in on screen: Settings, Practice details (name, address, phone, email, logo, VAT, sending address) and Settings, Security (session times, retention years). `AmlSettings` is created by migration. Reminder schedules are seeded off.

**Importing BrightManager data.** Built in Stage 12: Settings, Import (`/settings/import/`), owner only (`data.import`), password asked again. Input: CSV files, up to 5 MB and 5,000 rows each, UTF-8 (with or without BOM) or Windows-1252, delimiter `,` `;` tab or `|` detected. Three kinds, imported in this order: clients, contacts, services with fees. Steps: upload, match columns on screen (saved as a named mapping), check, import in one transaction, download failed rows, undo, Companies House fetch. Dates dd/mm/yyyy or yyyy-mm-dd; money may include £ and commas; common spellings of types, statuses and frequencies are recognised. The migration helper at `/settings/import/clear-deadlines/` clears deadlines already dealt with. No real BrightManager export has been tried, so the column matching is unproven.

---

## 8. Hardening

Compared with `docs/stages/stage-13.md` and `docs/specs/12-deploy-and-operations.md`:

| Item | State | Notes |
|---|---|---|
| Security review, 14 checks, `docs/SECURITY-REVIEW.md` | Done | 19 findings (2 high, rest medium or low), all fixed with tests; accepted gaps listed |
| URL walk test | Done | `apps/core/tests/test_url_walk.py`, six user kinds |
| `prod.py` refuses to start without required values or with unsafe ones | Done | Tested |
| Private bucket via django-storages | Done in code | Never run against a real bucket |
| whitenoise | Done | |
| `/healthz` | Done | `HealthCheckMiddleware`, checks the database |
| Structured logging | Done | JSON to stdout, tokens redacted (`apps/core/logs.py`) |
| Optional Sentry with scrubbing | Done in code | Not configured |
| Dockerfile (non-root, CSS, collectstatic, release) | Partly done | Written; the full image with WeasyPrint libraries has never been built (blocked mirrors). Docker is installed here but the build was not run (read-only task) |
| Procfile `web` and `worker` | Done | |
| Email provider, webhook, bounce handling | Done in code | Never live; SNS signature not verified (accepted) |
| Retention report job and page | Done | Lists only |
| Subject access export and purge | Done | |
| Guides (DEPLOY, RUNBOOK, BACKUPS, SUBPROCESSORS, STAFF-GUIDE, GO-LIVE) | Done | Host-specific steps still generic |
| Settings, System page | Done | |
| README | Done | |
| Dependency audit | Done on 14/10/2026 | `pip-audit` clean; repeat monthly |
| Go-live checklist ticked | Not done | Every box empty |
| Backups | Not done (depends on host) | Documented in `docs/BACKUPS.md`; no database or bucket exists; no restore test recorded |
| Logging retention at host | Not done | Host not chosen; DEPLOY asks for 30 days or less |
| Error reporting | Partly done | Sentry optional and off; the owner is notified in-app when a job fails |
| Rate limiting | Done | Sign-in (axes: 5 failures lock account plus address for 15 min; allauth 30 failed logins a minute per address), two-factor codes (5 per person per 15 min, 20 a day), portal codes, request links, action links. Cache-based counters not fully atomic (accepted). Correct only once `TRUSTED_PROXY_COUNT` or `TRUSTED_CLIENT_IP_HEADER` is set for the host |
| Session timeout | Done | Staff: idle 60 minutes and maximum 12 hours by default (Settings, Security), cookie never over 12 hours. Portal: idle 30 minutes, maximum 8 hours. Password asked again after 5 minutes for sensitive actions |
| File upload limits | Done | Request body 100 MB and 10 files (`RequestSizeLimitMiddleware`), staff documents 25 MB each, public request form 3 files of 10 MB, portal uploads up to 10 files, import CSV 5 MB; type checked by extension and first bytes; served as attachments, `private, no-store` |
| Virus scanning | Not done | Accepted gap, needs written owner acceptance |
| HSTS preload | Not done on purpose | |
| Password reset pages styled | Not done | allauth's plain layout |
| Second-person portal break-in test | Not done | Go-live line |
| Host chosen, domain, TLS, DNS | Not done | |

---

## 9. Domain and email

No real domain, email address or DNS record is in the code, settings or docs. Only placeholders appear:

- `example.com` addresses: default sender `Practice Manager <no-reply@example.com>` (`config/settings/base.py`, `.env.example`), demo practice `office@example.com`, demo staff and contacts (`morgan.hale@example.com`, `priya.castell@example.com` and others).
- `yourpractice.co.uk` in `docs/DEPLOY.md` and `docs/RUNBOOK.md`: `pm.yourpractice.co.uk`, `mail.yourpractice.co.uk`, `office@yourpractice.co.uk`, `you@yourpractice.co.uk`, `owner@yourpractice.co.uk`.
- `pm.example.co.uk` in `config/settings/base.py` comments and `docs/XERO_SETUP.md`.

Still to set up:

- **Domain for the app**, for example `pm.<practice domain>`: a CNAME to the host, a TLS certificate from the host, then `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `SITE_URL` set to it.
- **Client email (sent by the app)**: verify the practice domain at the provider (SES eu-west-2): three DKIM CNAMEs, a custom MAIL FROM subdomain with its MX and SPF `TXT` (`v=spf1 include:amazonses.com ~all`), a DMARC `TXT` at `_dmarc` (start `p=none`). Request SES production access. Create SNS topic `pm-email-events`, HTTPS subscription `https://NAME:PASSWORD@<domain>/email/events/`, SES configuration set `pm-events`. Set `DEFAULT_FROM_EMAIL` and the practice "sending address" and Reply-To in Settings. If the practice already sends mail from its domain (Microsoft 365, Google Workspace), its existing SPF record must be merged, not replaced.
- **Staff email**: the app sends staff invitations, password resets, notices and the daily email through the same provider and sender. Staff mailboxes themselves stay with the practice's existing email service; nothing in the app hosts mailboxes. Each staff account's email must be a real mailbox.
- **Client request link**: the public request form is `/r/<token>/` on the same domain (no separate domain). It works once `SITE_URL` is the live https address, since links and QR codes are built from it. The portal is `/portal/login/` on the same domain; portal codes are emailed directly, so email must work first.
- **Xero redirect**: `https://<domain>/integrations/xero/callback` registered in the Xero app.

---

## 10. Sizing

These are estimates, not measurements; no load test has been run.

Expected load for five staff and up to 300 clients: under 10 concurrent users, a few thousand page views a day at most, a few hundred client emails a month, a few dozen portal sign-ins a day at peaks (January self assessment, accounts deadlines). Background jobs are small: the nightly Companies House sync for up to 300 companies (paced to the API limit of 600 requests per 5 minutes) takes a few minutes; deadline generation is seconds. The heaviest single work is WeasyPrint PDF generation (letters, proposals, client summary), which can use 100 to 300 MB of memory for a few seconds.

Recommended for running everything on one machine (web, worker, PostgreSQL 16):

- 2 vCPU, 4 GB RAM (2 GB is possible with `WEB_CONCURRENCY=2` but tight with PDFs and PostgreSQL together).
- 40 GB SSD for the system, image, database and logs, plus the file storage below.
- Note: `config/settings/prod.py` requires an S3-compatible bucket and does not allow local disk for uploads. On one machine, either use an external bucket (recommended, it gives versioning and encryption) or run an S3-compatible server such as MinIO alongside, which adds about 0.5 GB RAM and needs its own backups. Off-machine database backups are still needed.

Storage growth per year from documents (assumption: about 20 to 40 files per client a year, averaging 0.5 to 1 MB, covering identity copies, records, signed letters and generated PDFs): roughly 3 to 12 GB a year for 300 clients, plus bucket versions of deleted files for 30 days. The database grows slowly, probably under 1 GB a year, mostly the activity log and message history. Records are never deleted automatically, so growth is cumulative over the 6-year retention period: plan for 20 to 75 GB of files by year six.

---

## 11. The ten most important gaps before live client data

1. No host, database, bucket or domain exists; nothing is deployed, so nothing in `docs/GO-LIVE.md` can be ticked yet.
2. The production Docker image has never been built with the WeasyPrint libraries or run end to end with real S3 and a real email provider; build and smoke-test it on a normal machine first.
3. Backups and a recorded restore test do not exist, and the encryption keys have not been generated or stored off-host.
4. Email has never been sent through a real provider; domain DNS (SPF, DKIM, DMARC), SES production access and the delivery webhook are all outstanding, and reminders and the portal depend on them.
5. The deadline rules (including the flagged `sa_payment` case and three "confirm" rules) and the AML risk questions and score bands have not been signed off by the practice owner.
6. Engagement letter, terms, privacy notice, proposal and clearance letter still carry starter wording, not the practice's own.
7. No independent person has tried to break into another client's data through the portal and request link.
8. The BrightManager import has never been run against a real export, and the one-month side-by-side run and 60-day deadline comparison have not started.
9. Companies House and Xero have never been connected live from the app; no API key or Xero app is registered.
10. Uploaded files are not virus scanned and the owner has not accepted this in writing; `docs/STATUS.md`'s stage table is also stale and the `claude/sleepy-tesla-qwr8j6` fix is unmerged.
