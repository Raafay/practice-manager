# Status

Keep this file under 150 lines. When it grows, shorten older stages to two lines each.

## Where things stand

Next stage to build: 2 (Clients and contacts), once Stage 1 is merged.

| Stage | State | Merged on |
|---|---|---|
| 0 Project pack | Done | 12/10/2026 |
| 1 Foundation | Built, in review | |
| 2 Clients and contacts | Not started | |
| 3 Companies House and jobs | Not started | |
| 4 Services and deadlines | Not started | |
| 5 Tasks, part one | Not started | |
| 6 Communications | Not started | |
| 7 Onboarding and AML | Not started | |
| 8 Tasks, part two | Not started | |
| 9 Prospects and proposals | Not started | |
| 10 Portal and requests | Not started | |
| 11 Time, fees, Xero and forecast | Not started | |
| 12 Import and reports | Not started | |
| 13 Hardening and deployment | Not started | |

## Stage 0: project pack (done)

Written outside Claude Code. Contains CLAUDE.md, the plan, thirteen stage briefs, the specs, and a session start script. No application code yet.

Checked in a cloud session on 12/10/2026:

- `scripts/session_start.sh` starts PostgreSQL 16, creates role `pm` and database `pm_dev`, and is safe to run twice. It takes about three seconds.
- These installed together with uv on Python 3.12: Django 5.2.18, psycopg 3.3, django-allauth 65.19 (with the mfa extra), django-axes 8.3, django-htmx 1.29, django-anymail 15.2, django-storages 1.14, django-tailwind-cli 4.8, WeasyPrint 70, nh3 0.3, cryptography 50, whitenoise 6.12, gunicorn 26, pytest 9.1, pytest-django 4.14, factory-boy 3.3, ruff 0.17.
- Migrations for allauth and its two-factor app ran on PostgreSQL. A test wrote to the database.
- WeasyPrint produced a PDF. It prints a HarfBuzz warning that can be ignored.
- `manage.py tailwind build` downloaded the Tailwind binary (about 145 MB, a few seconds) into `.django_tailwind_cli/` and built the CSS. That folder is in `.gitignore`.
- django-allauth has the settings this project needs: `MFA_TRUST_ENABLED`, `MFA_TRUST_COOKIE_AGE`, `MFA_RECOVERY_CODES_SHOW_ONCE`, `MFA_TOTP_INSECURE_BYPASS_CODE` (development only) and `ACCOUNT_LOGIN_BY_CODE_ENABLED` (for the portal).
- Chromium for Playwright is present under `/opt/pw-browsers`.

## Stage 1: foundation (built 13/10/2026)

- Django 5.2 project on Python 3.12 (uv). Settings `base`, `dev`, `test`, `prod` from the environment. `.env` is read in dev only, so no extra dependency. Apps: `core`, `accounts`, `events`.
- Staff sign-in with allauth: email and password, compulsory authenticator app (middleware sends anyone without one to set-up), recovery codes shown once, "trust this browser" 30 days (owner switch in Settings, Sign-in and sessions), axes lockout (5 per account and address, 15 min), idle and absolute session limits, password re-entry before role, rights, two-factor reset and security changes.
- `User` (email, `kind` staff or portal), `Role` with right names (three seeded by migration), single grants, `user.can()`, `StaffRequiredMixin`, `CapabilityRequiredMixin`, `|can` filter, teams, invitations (hashed token, one use, 72 h), last-owner guard on the model. Pages: Users, user detail, Teams, Roles, Profile, Practice details, Sign-in and sessions, Audit log, Notifications (bell). `create_owner`, `seed_demo`, `dev_login`, `rotate_encryption_keys`.
- `ActivityEvent` (never edited or deleted) with `events.record()` and request middleware. `Notification` and `events.notify()` (CORRECTIONS 1).
- Core: `dates.py` and bundled bank holidays, `EncryptedTextField` (MultiFernet) and `mask()`, public_id and timestamp mixins, pagination, money, cache rate limiter, strict CSP middleware, admin at `/control/` (owner only, Django's password-only login redirects to allauth), 403/404/500 pages.
- Layout and `/styleguide/` with every component from spec 00 section 5. Vendored with `npm pack` on 13/10/2026: htmx.org 2.0.11, @alpinejs/csp 3.17.4, sortablejs 1.15.7, trix 2.1.19; Heroicons 2.2.0 SVGs in `apps/core/icons/`. Tailwind CLI 4.1.3 via django-tailwind-cli.
- Dockerfile, docker-compose (web and db), `.github/workflows/ci.yml` (ruff, pytest on PostgreSQL, SQLite smoke). 318 tests. Screens in `docs/screens/stage-01/`.

## Assumptions

Add one line each time a stage makes a choice that the specs and `docs/DECISIONS.md` did not cover. Give the stage number.

- 1: Work pushed to the session's required branch `claude/keen-planck-yz97j4`, not `stage-01-foundation`; the cloud session could push only there.
- 1: Two-factor "done" means the user has an authenticator app; allauth finishes sign-in only after the code. `dev_login` adds one and does not count as a recent password.
- 1: Practice details need `settings.manage`. Sign-in and session settings (trust this browser, idle minutes, maximum hours) sit on the same row and need `users.manage`.
- 1: allauth registers its trust page only if the setting is on at start-up, so `config/urls.py` always registers it and `MFA_TRUST_ENABLED` reads the practice setting at run time.
- 1: Password re-entry guards the change (the POST), not opening the page. allauth replays the POST after the password.
- 1: A portal user on a staff page gets 403. `user.can()` raises on an unknown right name, so a typo never passes silently.
- 1: An invitation creates the account only when accepted. Deactivated users are refused on their next request; no hand-over prompt yet (CORRECTIONS 2).
- 1: `seed_demo` runs only with DEBUG or `ALLOW_DEMO_DATA=true`. Demo password `demo-password-2026`, dev two-factor code `000000`.
- 1: Notifications live in the `events` app. The bell links to a list page; the triggers come in Stage 8.

## Known gaps

Things a stage left unfinished or found broken, with the stage number. Remove a line when it is fixed.

- 1: The Docker image was not built in the cloud session: Docker Hub refused the base image pull (429). Build with `docker build -t practice-manager .` or `docker compose up`.
- 1: Lockout, rate limits and the audit log use `REMOTE_ADDR`. Behind the production proxy, Stage 13 must take the client address from the trusted proxy header.
- 1: Date filter boxes use the browser's own date picker, which shows the browser's date order (dd/mm/yyyy on a UK computer).
