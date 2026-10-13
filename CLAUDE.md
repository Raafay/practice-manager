# Practice Manager (working title)

A private web app for one UK accountancy practice. It replaces BrightManager and adds what the practice found missing.

What it does:

- Clients and contacts, with company details and filing dates pulled from Companies House.
- Services per client, each with a monthly fee. Each service creates its own recurring deadlines and tasks.
- One pool of tasks for all work, compliance and fractional finance-director work alike, shown as a table, a board or a calendar.
- Prospects with a sales pipeline, proposals, engagement letters signed on screen, an onboarding checklist and AML (anti-money-laundering) checks.
- Client reminders by email, held in a queue for approval. A client portal. A request form for client staff.
- Time tracking, fees, Xero figures and an income forecast that only the owner sees.

It will hold identity documents and tax references of real people, and the practice relies on its dates. Two things must never be wrong: who can see what, and when a deadline falls.

## How to work in this repo

1. One stage per session. `docs/PLAN.md` is the index. `docs/stages/stage-NN.md` is your brief.
2. Start by reading `docs/STATUS.md`, `docs/CORRECTIONS.md` and your stage file. Where CORRECTIONS disagrees with a spec or stage file, CORRECTIONS wins. Then read only the spec files that stage lists. Do not read other specs for background.
3. Build only what your stage lists. Leave later stages alone, even where they look easy.
4. Do not stop to ask questions. Use the default in `docs/DECISIONS.md`. If the point is not covered, take the simplest option that fits the specs and log it under "Assumptions" in `docs/STATUS.md`. Stop only if carrying on would lose data or break a security rule below.
5. Commit and push after each numbered build item, so a later session can pick up where this one stopped.
6. To finish: every check in the stage file passes, `docs/STATUS.md` is updated, and the work is pushed on a branch named `stage-NN-short-name`. Open a pull request if you have a tool for it. Its description says what was built, what was assumed, and gives "How to check" steps a non-developer can follow in a browser.
7. Keep usage low. Find code with `rg` before opening files. While iterating, run one app's tests with `-x`. Run the full suite once before finishing. Pipe long output through `tail -n 40`. Do not re-read a file you have just written.

## Stack

- Python 3.12, Django 5.2 LTS, PostgreSQL 16. Dependencies with uv. Lint and format with ruff. Tests with pytest, pytest-django and factory_boy.
- Pages are rendered on the server with Django templates. HTMX for partial updates, Alpine.js (the CSP build) for small interactions, SortableJS for drag and drop, Trix for rich text. No React and no single-page app.
- Tailwind CSS through `django-tailwind-cli` (a standalone binary, so no Node is needed).
- JavaScript libraries are copied into `static/vendor/`. Nothing loads from a CDN.
- django-allauth for sign-in. Staff use email, password and an authenticator app. Portal users sign in with a code sent by email.
- django-axes (lockout), django-anymail (email providers), nh3 (HTML cleaning), WeasyPrint (PDFs), django-storages (private bucket in production), cryptography (encrypted fields).
- Background work is a small `jobs` app with a `worker` management command, added in Stage 3. No Celery and no Redis.
- This set was installed and smoke-tested together in a cloud session on 12 October 2026. Details are in `docs/STATUS.md`.

## Commands

The Makefile is created in Stage 1. Until then use the raw commands.

    make setup     # uv sync, migrate, build CSS
    make dev       # run the site with the CSS watcher
    make test      # full test suite
    make lint      # ruff check and ruff format --check
    make seed      # load made-up demo data, safe to run twice
    uv run pytest apps/tasks -x
    uv run python manage.py makemigrations --check --dry-run

In a cloud session `scripts/session_start.sh` runs by itself. It starts PostgreSQL, creates the dev database and installs dependencies. Database: `postgres://pm:pm@localhost:5432/pm_dev`. Chromium for Playwright is already installed (see `$PLAYWRIGHT_BROWSERS_PATH`). Never run `playwright install`.

Cloud sessions cannot reach Companies House, Xero or gov.uk. Build and test those parts against the sample responses described in `docs/specs/10-integrations.md`.

## Layout

    config/                 settings (base, dev, test, prod) and urls
    apps/core/              shared helpers: working days, dates, money, encrypted field, permission mixins, layout, styleguide
    apps/accounts/          users, roles, teams, invitations, two-factor rules
    apps/events/            activity log: audit trail and client timeline
    apps/clients/           clients, contacts, links, notes, documents, saved views      Stage 2
    apps/companieshouse/    API client, import, nightly sync                            Stage 3
    apps/jobs/              job registry, run log, worker command                       Stage 3
    apps/services/          service catalogue, client services and fees, deadline rules Stage 4
    apps/tasks/             tasks, projects, categories, the three views, workload      Stages 5 and 8
    apps/comms/             templates, merge fields, message queue, email and SMS       Stage 6
    apps/pipeline/          prospect stages, meetings, proposals                        Stage 9
    apps/onboarding/        checklist, engagement letters, signatures, HMRC tracker     Stage 7
    apps/aml/               risk assessments, identity checks, reviews                  Stage 7
    apps/portal/            client portal, public request form, requests inbox          Stage 10
    apps/timekeeping/       time entries and timers                                     Stage 11
    apps/finance/           fees, Xero, targets, forecast, owner summary                Stage 11
    apps/imports/           CSV import with column mapping                              Stage 12
    apps/reports/           exports and reports                                         Stage 12

Inside an app: `models.py`, `services.py` (business rules), `views.py`, `forms.py`, `urls.py`, `templates/<app>/`, `tests/`.

## Code conventions

- Business rules live in plain functions in `services.py` (deadline rules in `apps/services/rules/`), not in views or templates, so they can be tested without a web request.
- Views are thin. Every staff view uses `StaffRequiredMixin`. Use `CapabilityRequiredMixin` or `user.can("name")` for anything a role may not do.
- Every model has `created_at` and `updated_at`. Anything shown in the portal or a public link is looked up by a random `public_id`, never by its number.
- Money is `DecimalField(max_digits=10, decimal_places=2)`, in pounds, excluding VAT.
- UK English in the interface. Dates show as dd/mm/yyyy. Time zone Europe/London.
- Call `events.record(...)` for every create, change, delete, send, sign, approve, export, and every view or download of a sensitive file.
- HTMX views return a partial when `request.htmx` is set. Partial template names start with an underscore.
- Commit migrations. Never edit one that has been merged. Add a new one.
- No new dependency without a line in `docs/STATUS.md` saying why.

## Interface conventions

- Reuse the components on `/styleguide/`. When you add a component, add it to the styleguide.
- Dense, calm and readable: tables for lists, tabs on record pages, panels that fold, toggle switches, status badges.
- Our own look and our own wording. BrightManager is a guide to structure only. Never copy its text, logo, colours or screenshots.
- No inline scripts and no inline event handlers, so the Content-Security-Policy can stay strict.
- Every page works by keyboard with a visible focus ring. Colour is never the only signal.
- An empty list says what to do next.

## Security rules (never break these)

1. Deny by default. A view with no permission check is a bug.
2. Portal users and the public never reach staff views or another client's data. Every portal query is filtered by the signed-in contact's clients. Add a test for this with every portal or public view.
3. Uploaded files never get a public address. They are served through a view that checks permission. Each view or download of a sensitive file is logged.
4. Secrets come from environment variables. Never commit keys, tokens or `.env`.
5. National Insurance numbers, UTRs, Companies House codes, HMRC codes and API tokens use the encrypted field. Show them masked. Revealing one is logged.
6. No real personal data in the repo, tests, sample files, logs or prompts. Demo data is made up by `seed_demo`.
7. Nothing reaches a client unless a QueuedMessage exists and is approved, or its template is set to send automatically. Development and tests use the console and in-memory backends only.
8. Never weaken a security setting or remove a failing security test to make something pass.
9. Every form has CSRF protection. Rich text from users is cleaned with nh3 before it is stored or shown.
10. Finance figures for the owner (forecast, targets, Xero totals) are checked in the view, the template and the export.

## Testing

- Each stage file lists the tests that must exist.
- Deadline rules get table-driven tests from the cases in `docs/specs/03-services-and-deadlines.md`. Never change an expected date to make a test pass. Fix the code, or flag the case in `docs/STATUS.md`.
- For each new address: signed-out users are sent to sign in, the wrong role gets 403, and a portal user gets 404 for another client's object.
- Use factories. No test data that looks like a real NI number, UTR or company.
- Screens: for stages that add pages, save two to five screenshots to `docs/screens/stage-NN/` with `scripts/screenshots.py` and look at them once to check the layout.

## Definition of done

- The stage checks pass, `make lint` and `make test` are clean, and migrations are included.
- `seed_demo` covers the new features with made-up data.
- `docs/STATUS.md` has the stage summary, assumptions and known gaps, in under 15 lines.
- The branch is pushed and the pull request description has "How to check" steps.

## Compact instructions

When compacting, keep: the stage number and goal, files created or changed, decisions and assumptions made this session, failing tests with their errors, and what is left to do.
