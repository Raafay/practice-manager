# Status

Keep this file under 150 lines. When it grows, shorten older stages to two lines each.

## Where things stand

Next: choose a host, deploy (`docs/DEPLOY.md`) and work through `docs/GO-LIVE.md`. Stages 1 to 13 are built; Stage 14 (several practices) is built and waits for the agreement with Mati.

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
| 14 One schema per practice | Built, in review (do not merge before the agreement) | |

## Stages 0 to 12 in short

Older stages are shortened to two lines each. Details are in git history and each stage's pull request.

- 0 Project pack: CLAUDE.md, plan, stage briefs, specs, session start script. Checked 12/10/2026: PostgreSQL 16, the dependency set, WeasyPrint and the Tailwind binary all work.
  Versions: Django 5.2.18, psycopg 3.3, allauth 65.19, axes 8.3, django-htmx 1.29, anymail 15.2, storages 1.14, tailwind-cli 4.8, WeasyPrint 70, nh3 0.3, cryptography 50.
- 1 Foundation: settings, staff sign-in with compulsory two-factor, roles and rights, teams, invitations, activity log, notifications, encrypted fields, strict CSP, `/styleguide/`.
  Vendored htmx 2.0.11, Alpine CSP 3.17.4, SortableJS 1.15.7, Trix 2.1.19, Heroicons 2.2.0; Tailwind CLI 4.1.3. Commands `create_owner`, `seed_demo`, `dev_login`, `rotate_encryption_keys`.
- 2 Clients and contacts: clients, contacts, links, notes, private documents, saved views, CSV export, search, status moves, archive and delete with retention dates, tags, custom fields.
  NI numbers, UTRs and Companies House codes are encrypted and masked.
- 3 Companies House and jobs: `apps/jobs` (registry, run log, lock, worker, Jobs page) and `apps/companieshouse` (API client, fake transport, add from Companies House, nightly sync, contact matching).
  Shapes checked live against the real API.
- 4 Services and deadlines: Service, ClientService, FeeChange, Deadline; all 17 rules in `apps/services/rules/` with table tests; `generate_for_client` runs nightly and on changes.
  Mark done, not required, reopen, change date; client Deadlines tab; Deadlines report.
- 5 Tasks, part one: tasks, statuses, categories, templates and steps; deadlines make tasks by signal; Tasks table, drawer, My work, saved views; rich text cleaned with nh3.
  Ticking the filing step marks the deadline done.
- 6 Communications: templates, merge fields, message queue with approval, reminder schedules, send job, letters as PDF, Log an email; SMS behind an interface, off.
  Nothing reaches a client unapproved; sending address and Reply-To rules in place.
- 7 Onboarding and AML: checklist and go-live gate, engagement letters signed on screen, HMRC authorisations, clearance; identity checks, risk questions, scoring, register, review job.
  Shared `ActionLink` in `apps/core`. New setting `SITE_URL`.
- 8 Tasks, part two: Board and Calendar views, projects, repeating tasks, Workload, Overview home page, notices and the daily email.
  Keyboard shortcuts in `static/js/keys.js`.
- 9 Prospects and proposals: pipeline stages, Prospects board and list, meetings, proposals with versions, public proposal page, acceptance starts onboarding.
  Merge field `proposal_summary`.
- 10 Portal and requests: portal sign-in by emailed code, portal pages and things to do, client details form, public request form and inbox. New dependency `segno` (QR codes).
  Every portal query starts from `for_portal_user`.
- 11 Time, fees, Xero and forecast: time entries and timer, timesheet; Finance pages for `finance.owner` (fees, invoices, targets, forecast, summary); Xero read-only sync.
  Setup steps in `docs/XERO_SETUP.md`. Screens for each stage in `docs/screens/stage-NN/`.
- 12 Import and reports: CSV import with column matching, check, undo and Companies House fetch; one Reports page with six new reports and safe CSV export; client summary PDF.
  Every CSV goes through `safe_cell` in `apps/core/csvexport.py`.

## Stage 13: hardening and deployment (built 14/10/2026)

- Security review in `docs/SECURITY-REVIEW.md`: three independent passes, 19 findings (no critical), all fixed with tests; accepted items listed there. `pip-audit` clean.
- URL walk (`apps/core/tests/test_url_walk.py`): every address, six kinds of user, real demo records, an expected table; a new address without a line fails.
- `config/settings/prod.py` refuses to start without what it needs or with anything unsafe; private S3 bucket (`STORAGE_*`), `EMAIL_PROVIDER` (ses, postmark, brevo), JSON logs with tokens redacted, optional scrubbed Sentry, `/healthz`, live check `manage.py check_headers`.
- Docker image: build-only settings, non-root, CSS and static built in, `scripts/release.sh` (migrate, cache table, deploy checks), `gunicorn.conf.py`, `Procfile`. Built and run here against a fresh database: migrations ran, `/healthz` ok, headers right, worker ran.
- Email delivery webhook `/email/events/` (anymail, shared secret); bounces and spam complaints on the Queued page and to the approver.
- Retention report (Settings) and monthly job, lists only; subject access ZIP and "Remove for good" on the contact page for the owner. Settings, System page. `reset_two_factor` command.
- Guides: DEPLOY (generic container host), RUNBOOK, BACKUPS, SUBPROCESSORS, STAFF-GUIDE, GO-LIVE. README rewritten. Screens in `docs/screens/stage-13/`. 1584 tests.
- New dependencies: `sentry-sdk` (optional error reports), `boto3` and `django-storages[s3]` (the bucket and SES never worked without them).

## Beta on one laptop (added 21/10/2026)

- `config/settings/beta.py`: as strict as prod (no debug, no two-factor bypass, no demo data, secure cookies, HSTS) but files on the laptop disk and email to the terminal only. Reads `.env.beta`; refuses to start if anything is missing or unsafe (`apps/core/tests/test_beta_settings.py`).
- `make beta-init DOMAIN=...` writes `.env.beta` with fresh keys once; `make beta` runs migrate, checks, gunicorn on 127.0.0.1:8000 and the worker; `make beta-backup` dumps the database and files. Guide: `docs/BETA.md` (Cloudflare Tunnel and Access in front).
- Tried here end to end with a scratch database: `/login/` and styles 200, wrong host 400, owner created, `seed_demo` refused, backup written.
- Assumption: the beta deliberately sends no email, so staff invitations are copied from the terminal and the portal is not used until go-live with an email provider.

## After the 23/10/2026 meeting (built 01/11/2026, branch `claude/awesome-thompson-idlpxq`)

- 1 Toggles: only Payroll, VAT Returns and Management Accounts open the set-up box; every other service switches on at once (today, monthly, default fee if one is set in Settings, else blank).
- Uploads encrypted at rest with the field keys (`apps/core/storage.py`); `manage.py encrypt_files` encrypts older plain files. Run it once on the beta laptop.
- 6/7 "Requests" renamed "Client requests". New information request (`apps/portal/inforequest.py`): asks one person only for details still empty (UTR, NI, CH codes, email, phone, address, date of birth) by a 28-day no-login link (email held in Queued) or a printed form; replies wait for staff to tick and apply; files land in Client requests; reminders at 7 and 14 days (job `info_reminders`). AML recording was already built in Stage 7.
- 3 Profit page and "Ask" (owner only): profit targets, monthly P&L (Xero report or typed in), gap to target, clients needed, what-if, forecast against actual, concentration warning at 25%. Ask uses the Claude API with tools over `apps/finance/planning.py`; it never does arithmetic and is read-only; usage metered per question. Needs `ANTHROPIC_API_KEY`. New dependency `anthropic` (the Claude API client).
- 2 Creditsafe (`apps/creditsafe`): Check credit on the Risk tab (needs `clients.status`, costs one report), rating badge in the client header, history, owner notice and Overview panel when a rating falls, daily alerts job re-checks only companies Creditsafe flags. Needs `CREDITSAFE_USERNAME`, `CREDITSAFE_PASSWORD`, `CREDITSAFE_PORTFOLIO_ID`. Prospects use the same button from their Risk tab.
- 04/11: margin targets (all three targets, as Mati asked); theme in one place (`apps/core/theme.py`: accent and top bar colours as CSS variables, contrast checked, email footer under every client email). Xero stays read-only; AML stays recorded by hand (DECISIONS 14).
- Multi-tenant designed, not built: `docs/MULTITENANT.md` (one PostgreSQL schema per practice, tried in a throwaway copy) and stage briefs 14 to 18. Start after the ownership agreement with Mati. Also not done: bills and repeating invoices from Xero.

## Stage 14: one schema per practice (built 05/11/2026, branch `claude/zealous-volta-50rlsl`, not to merge before the agreement with Mati is signed)

- New dependency `django-tenants` 4.0.1 (the design chosen in `docs/MULTITENANT.md`: one schema per practice, chosen by address). `apps/tenancy`: Practice (status active, read-only, closing) and Domain in `public`; everything else in each practice's schema. `PracticeMiddleware` gives an unknown or public address a plain 404; `/healthz/` answers on any address.
- Links from the practice's primary address (`apps/core/siteurl.py`); `SITE_URL` removed (prod and beta refuse it). Worker: each due job once per active practice, failures kept to that practice. Files under `<schema>/` (disk or bucket), names outside refused; cache keys start with the schema.
- `create_practice`, `move_into_schema` (backup under an hour old, counts compared, one transaction, then files); `--practice SCHEMA` on per-practice commands. `seed_demo`: `localhost` (full) and `second.localhost` (staff only).
- Tests: practices A (`testserver`) and B (`other.testserver`); the whole suite runs in A. New: URL walk on B, files, cache, jobs, commands, the move of the demo data with every page visited.
- Checked by hand: a database made and seeded by the pre-Stage 14 code, moved with the new code: 106 tables and 4,420 rows unchanged, 43 files moved, 349 pages visited as the owner with no errors.

## Assumptions

Add one line each time a stage makes a choice that the specs and `docs/DECISIONS.md` did not cover. Give the stage number. Stages 1 to 13 are in `docs/ASSUMPTIONS.md`.
- 14: Pushed to the session's required branch, not `stage-14-...`. ALLOWED_HOSTS stays an environment setting (a wildcard such as `.pm.example.co.uk` plus custom domains); the Domain table then decides the practice, so an allowed but unknown address still gets 404. Read-only and closing practices are served as normal and only skip jobs (behaviour for them comes with billing). Users and their sign-ins belong to one practice. The second demo practice has staff accounts only. A practice's extra domains are added from the shell until the platform pages exist. Query budget for the 2,000-task table raised from 32 to 35 (choosing the practice: two schema switches and the address lookup); `SET search_path` is sent only when the practice changes (`TENANT_LIMIT_SET_CALLS`). Bank holidays (national data) may be cached in memory from any practice's copy. Existing tests changed only where they wrote files at fixed disk paths, made a request without the database, or used threads (each thread must choose the practice).
- Meeting: work on the session branch, one pull request for all items. Costs in the profit figures are a 3-month average and treated as fixed, so each new client adds its whole fee to profit. Clients who are people are sent to the Claude API as a reference, not a name. The default fee from Settings still fills in on instant switch-on. A credit check needs `clients.status` (owner and managers) because each report is charged. Information request links use the existing one-use action links; each reminder sends a fresh link to the same request.

## Known gaps

Things a stage left unfinished or found broken, with the stage number. Remove a line when it is fixed.

- 14: The email delivery webhook is per practice address; with one provider account for every practice, delivery reports reach only the practice whose address is registered with the provider (others are ignored). A platform-level webhook belongs with stage 15. Xero needs one redirect address per practice registered on the Xero app. Moving files in a bucket is left to the provider's tools (the command prints what to run); on disk it is done.

- Meeting: Creditsafe and the Claude API were built against made-up samples and a fake client; neither was reachable from the cloud session. Check Creditsafe's field names (`apps/creditsafe/api.py`) against their documentation with the first real report. Xero needs Disconnect and Connect again for the new reports scope.
- 13: In the cloud session Docker Hub (429), ghcr.io and the Debian mirror were blocked; the image was built from a mirrored base through the proxy without the WeasyPrint system libraries step. Build once on a normal machine or the host before go-live: `docker build -t practice-manager .`. Live SES, bucket, Companies House and Xero untested from here.
- 1: Date filter boxes use the browser's own date picker, which shows the browser's date order (dd/mm/yyyy on a UK computer).
- 2: No quick switches on the Contacts tab; flags are edited in the Edit drawer. Django 6 deprecation warning for URL form fields (assume https) shows in tests.
- 3: gov.uk is blocked in cloud sessions, so the bank holiday refresh was tested against a sample in the published shape only.
- 4: Spec 03 section 6 lists "sa_payment, second payment on account for 2026/27: 31/07/2027". 31 July 2027 is the second payment for 2025/26. Kept as a strict expected failure; the rule follows HMRC (31 July after the tax year). Rules marked "(Confirm ...)" for the practice owner: long-period CT600 return date (rule 2), P11D and payrolling from 2027/28 (rule 9), auto-enrolment re-declaration day (rule 16).
- 4: The rule choice for a service can be edited in Settings, Services; there is no check that a rule suits the service.
- 5: A fourth target rule, "working days before the due date", exists for Payroll (2 working days before pay date); the spec names three kinds. "Fixed day before the due date" means the latest such day strictly before the due date, moved back to a working day.
- 5: Manager default owner falls back to partner, then an owner. Documents attach only to tasks that have a client, as plain form posts. The project filter works from the address (`project=`) but has no box in the panel until Stage 8. "Week due" groups by deadline, else target date.
- 5: Unticking a filing step does not reopen the deadline. My work sections use the target date, else the deadline; "waiting" status takes precedence. Mention notices use the existing bell; the other notification triggers are Stage 8. Core's placeholder Overview page was removed; the home page is My work.
- 6: Only the console and in-memory email backends are tested live; the providers are tested through anymail's webhook payloads. Text messages have no provider; the Send SMS button and text templates are hidden until `SMS_BACKEND` names one.
- 6: Letters use the practice logo and address only. The clearance letter wording is Stage 7's.
- 7: The practice owner must read the risk questions and score bands before they are relied on. Letter wording is starter text. The 30-day postal code expiry needs confirming with the practice.
- 8: Project templates cannot be edited in Settings. The calendar's deadline markers follow the client (and fixed client) only, not the other filters. Drag and drop was checked through the endpoints and page markup, not in a live browser.
- 9: Drag and drop was checked through the endpoints and markup, not in a live browser. The Prospects list has no CSV export.
- 10: No email-in or WhatsApp-in (not in stage); portal items are not auto-withdrawn when a records task is cancelled.
- 12: No real BrightManager export has been seen; the headings suggested are guesses and the owner checks the matching on screen. Live Companies House fetch was tested against the fake only.
- 11: Live Xero connection untested (cloud cannot reach Xero); built and tested against the samples. Disconnect only forgets the tokens; remove the app in Xero too.
- 13: Password reset pages use allauth's plain layout. Virus scanning, SNS signature checks and fully atomic rate-limit counters are accepted gaps (`docs/SECURITY-REVIEW.md`).
