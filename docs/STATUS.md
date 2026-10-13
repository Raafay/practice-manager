# Status

Keep this file under 150 lines. When it grows, shorten older stages to two lines each.

## Where things stand

Next stage to build: 1 (Foundation).

| Stage | State | Merged on |
|---|---|---|
| 0 Project pack | Done | 12/10/2026 |
| 1 Foundation | Not started | |
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

## Assumptions

Add one line each time a stage makes a choice that the specs and `docs/DECISIONS.md` did not cover. Give the stage number.

None yet.

## Known gaps

Things a stage left unfinished or found broken, with the stage number. Remove a line when it is fixed.

None yet.
