# Practice Manager (working title)

A private web app for one UK accountancy practice. It replaces BrightManager and adds what the practice found missing. This file is for the people who run and look after the app. Claude Code reads `CLAUDE.md` instead.

**No real client data goes in until every line of [`docs/GO-LIVE.md`](docs/GO-LIVE.md) is ticked.** Until then the app holds made-up demo data only.

## What the app does

- **Clients and contacts**, with company details and filing dates pulled from Companies House and kept in step each night. Tax references are encrypted and shown masked, and each reveal is logged.
- **Services and deadlines.** Each client service has a monthly fee and makes its own recurring deadlines (accounts, confirmation statements, VAT, payroll, self assessment and more), worked out on UK working days.
- **One pool of tasks** for compliance and advisory work, shown as a table, a board or a calendar, with templates, steps, projects, repeating tasks and a workload view.
- **Prospects and proposals:** a sales pipeline, proposals the client accepts on screen, engagement letters signed on screen, an onboarding checklist, AML identity checks and risk assessments, HMRC authorisations and professional clearance.
- **Client emails held in a queue for approval.** Nothing reaches a client until a person approves it, unless the owner sets a template to send by itself. Reminder schedules, letters as PDF, and delivery and bounce reports.
- **A client portal** (sign-in by emailed code) for documents, requests and things to do, plus a request form for client staff.
- **Time, fees and Xero:** a timesheet and timer, fee checks against Xero invoices, and targets and an income forecast that only the owner sees.
- **Import and reports:** CSV import from BrightManager with column matching and undo, and reports with CSV export.
- **For the owner:** the audit log, Settings > System (is everything working?), the retention report, subject access exports, and removing a person for good once the retention period has passed.

## Guides

| Guide | For | What it covers |
|---|---|---|
| [`docs/STAFF-GUIDE.md`](docs/STAFF-GUIDE.md) | Everyone at the practice | Signing in, finding a client, the task views, logging requests, approving messages, onboarding |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Whoever puts it online | Database, bucket, app, every setting, first owner, domain, email DNS, Companies House, Xero, releases and rollback |
| [`docs/GO-LIVE.md`](docs/GO-LIVE.md) | The owner | The checklist before real data goes in |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | The owner | When something goes wrong: site down, failing jobs, email, lockouts, leavers, data breach, restores, key rotation |
| [`docs/BACKUPS.md`](docs/BACKUPS.md) | The owner | What is backed up, and the restore test with its record |
| [`docs/SUBPROCESSORS.md`](docs/SUBPROCESSORS.md) | The owner, for the privacy notice | Every outside company that holds or sees client data |
| [`docs/SECURITY-REVIEW.md`](docs/SECURITY-REVIEW.md) | The owner | The security review, what was fixed, and what was accepted |
| [`docs/XERO_SETUP.md`](docs/XERO_SETUP.md) | Whoever connects Xero | Registering the Xero app |

## How it is built

Python 3.12, Django 5.2 LTS and PostgreSQL 16. Pages are rendered on the server, with HTMX and Alpine.js for small interactions and Tailwind for the look. Nothing loads from outside the site. Background jobs run in a `worker` process. It is shipped as one Docker image with two processes, `web` and `worker`. Details are in `CLAUDE.md`.

What is in this repository:

- `apps/`: the app, one folder per area.
- `config/`: settings for development, tests, production (`prod.py`) and the image build.
- `Dockerfile`, `Procfile`, `gunicorn.conf.py`, `scripts/release.sh`: what the host runs.
- `docs/`: the guides above, plus `PLAN.md`, `stages/`, `specs/`, `DECISIONS.md`, `CORRECTIONS.md` and `STATUS.md` from the build.

## Looking at the app on a laptop

    git pull
    make setup     # install, create the database tables, build the CSS
    make seed      # load made-up demo data (safe to run twice)
    make dev       # run the site

Then open `http://localhost:8000`. `make seed` prints the sign-in details for the made-up staff. The first time, you need uv installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and PostgreSQL 16 running. For a quick look without PostgreSQL, copy `.env.example` to `.env` and set `DATABASE_URL=sqlite:///local.sqlite3`.

Or with Docker: `docker compose up`. It uses the development settings, not production ones.

Checks before any release:

    make lint      # ruff
    make test      # the full test suite, including the walk of every address

## Accounts with other services

| Service | What it is for | Who sets it up |
|---|---|---|
| GitHub | Holds the code | You |
| A hosting company | Runs the site, its database and its file storage (UK or EEA) | You. See `docs/DEPLOY.md` |
| The practice's domain | The site's address, and proving emails come from the practice | Whoever controls the domain's DNS |
| Amazon SES (or Postmark or Brevo) | Sends client emails and sign-in codes | You. See `docs/DEPLOY.md` step 8 |
| Companies House developer account | A free key to read company details and filing dates | You, in about five minutes |
| Xero developer app | Lets the app read invoices and payments | You create the app; the owner connects it |
| Later, if wanted | A text message provider, a paid identity-check service, HMRC developer access | |

## Rules

- No real client data until the go-live checklist is ticked.
- Never paste real client names, emails, tax references or documents into a Claude Code session, an issue, or this repository.
- The practice owner reads and agrees the deadline rules (`docs/specs/03-services-and-deadlines.md`) and the AML risk questions (`docs/specs/06-onboarding-and-aml.md`) before go-live. The practice stays responsible for both.
- Keep BrightManager running alongside for at least one full month after go-live.

## Building further

The app was built in thirteen stages, one Claude Code session and one pull request each. The plan is in `docs/PLAN.md` and the progress in `docs/STATUS.md`. For later work, start a fresh session, point it at `CLAUDE.md` and describe the change. Keep one change per session and per pull request.
