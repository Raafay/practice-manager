# Status

Keep this file under 150 lines. When it grows, shorten older stages to two lines each.

## Where things stand

Next: choose a host, deploy (`docs/DEPLOY.md`) and work through `docs/GO-LIVE.md`. All thirteen stages are built.

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

## Assumptions

Add one line each time a stage makes a choice that the specs and `docs/DECISIONS.md` did not cover. Give the stage number.
- 1: Work pushed to the session's required branch `claude/keen-planck-yz97j4`, not `stage-01-foundation`; the cloud session could push only there. Two-factor "done" means the user has an authenticator app; allauth finishes sign-in only after the code. `dev_login` adds one and does not count as a recent password. Practice details need `settings.manage`. Sign-in and session settings (trust this browser, idle minutes, maximum hours) sit on the same row and need `users.manage`.
- 1: allauth registers its trust page only if the setting is on at start-up, so `config/urls.py` always registers it and `MFA_TRUST_ENABLED` reads the practice setting at run time. Password re-entry guards the change (the POST), not opening the page. allauth replays the POST after the password. A portal user on a staff page gets 403. `user.can()` raises on an unknown right name, so a typo never passes silently.
- 1: An invitation creates the account only when accepted. Deactivated users are refused on their next request; no hand-over prompt yet (CORRECTIONS 2). `seed_demo` runs only with DEBUG or `ALLOW_DEMO_DATA=true`. Demo password `demo-password-2026`, dev two-factor code `000000`. Notifications live in the `events` app. The bell links to a list page; the triggers come in Stage 8.
- 2: Branch is `claude/sharp-knuth-96f9y3` (the session's required branch), not `stage-02-clients`. New clients default to `active`. Prospects and onboarding come from Stages 7 and 9. Notes are plain text, shown with line breaks (no rich text, so nothing to clean). Pinned notes show on the Info tab.
- 2: Status moves: prospect to onboarding or lost; onboarding to active, paused or former; active and paused to each other or former; former to active; lost to prospect. Delete for good is blocked only by the retention dates. A live client with no dates is not blocked, so owner-only and the typed name are the guard. Sensitive documents need `documents.sensitive`; only sensitive views and downloads are logged, plain ones are not.
- 2: Filing dates are read-only once a company number is set, so until Stage 3 they can only be set by the demo seed. Contact changes are logged once on each linked client's timeline.
- 3: Branch is `claude/nifty-knuth-isuax1` (the session's required branch), not `stage-03-companies-house`. A Companies House personal code is 11 letters or digits; Stage 2 had allowed six (that is the company authentication code). Fixed in the contact form. The sync never renames a client unless its name still equals the old registered name. New clients take the registered name as given.
- 3: The sync also adds newly appointed people as contacts. A person who left before the company was added is listed on the tab but not made a contact. "Run now" and "Run sync now" ask the worker; only "Sync now" on one client runs straight away. Jobs runs need `system.view` (owner); Integrations needs `integrations.manage`. Calls go out without an Authorization header when `COMPANIES_HOUSE_API_KEY` is empty, so a network proxy that adds the key (as in cloud sessions) still works. The page then shows "No key".
- 4: Periods due more than 60 days ago are not created (so a service started years ago gets no history). Spec only gave the start-date rule. Open calculated deadlines are re-calculated when inputs change (for example a new pay day); ones changed by hand are left alone. Reminder-only rules (ct_payment, paye_payment, sa_payment, p11d Class 1A) and tax-year rules with no horizon are created 60 days ahead (CORRECTIONS 10). "Created N days ahead" for payroll, CIS and regular work is counted before the due date; VAT and MTD before the period end.
- 4: Going live (status Active) turns proposed services active, starting today. Paused clients keep active services but get nothing new. Reports live in `apps/services` with a small Reports index; Stage 12 can add to it. Two icons missing from the set were replaced by `calendar` and `rectangle-stack`.
- 6: Branch `claude/trusting-feynman-fm97v2`. Item 12 left out (CORRECTIONS 4); sign-in emails go direct (CORRECTIONS 17). "Repeats N times" means N more after the first; a date missed by over 3 days is skipped. One message per client to the main contact and "receives reminders" contacts.
- 6: "Stops when": a ticked "stops reminders" step on a linked task, or a done/not-required deadline. Only the owner sets a template to automatic; a blocked automatic message waits. nh3 drops inline styles, so link buttons arrive as plain links; sensitive documents are never attached.
- 6: Hand-written messages to former or lost clients cannot be approved. Compose fills deadline fields from the nearest open deadline. `setup_fee` merges one-off fees. Log an email adds a note of kind "email".
- 7: Branch is `claude/hopeful-gates-4pfqis` (the session's required branch). No pull request opened: the session rules say only on request.
- 7: The register export needs `data.export` (CORRECTIONS 16), not "owner only" as the stage file says; the owner and managers hold it.
- 7: Make live needs `clients.status`; going live with items open also needs `onboarding.override` and a reason.
- 7: A signing link lasts 14 days. The engagement and signed-copy emails wait in Queued (hold), so nothing reaches a client unapproved. Engagement review date is 12 months after signing.
- 7: "Verified" identity needs a method, a document type and an uploaded copy. A live client with no assessment and no checklist shows "Needs review (imported)".
- 7: Higher-risk services that prompt a review are chosen on the AML bands page. HMRC row expires automatically once its link or code date passes while still waiting.
- 7: Added h2 and h3 to the allowed rich-text tags (letters use them). Demo data adds 3 contacts and some notifications; two earlier demo-count tests were loosened.
- 8: Branch is `claude/peaceful-cerf-16u8mo` (the session's required branch). No pull request opened.
- 8: The board ignores "Show done" and always shows done work from the last 14 days. Dragging on the calendar works only while it shows target dates; in deadline mode cards are fixed. Dropping a task on the side list clears its target date.
- 8: A board move to another client is refused for tasks that come from a deadline. A plain reorder writes no activity event.
- 8: Workload counts open tasks by target date, else deadline, in the next 14 days (overdue work is in its own column, not in the hours). Overdue and this-week links use the same filters as the counts; "next week" is a hidden chip.
- 8: The three email switches are overdue, due today and due this week. The daily email is sent straight to staff (not queued; it is not a client message) and leaves out tasks waiting on the client. Overview "my clients" means manager or partner. The system never notifies on generated tasks.
- 8: A repeating task makes only the current period; periods missed while nothing ran are skipped. Its target date is the period start plus "days to finish"; no hard due date.
- 8: Project templates have no editor in Settings yet.
- 9: Source and referrer stay on the client (Internal panel), not copied to ProspectDetails. Moving a card to Won or Lost needs no `clients.status` right.
- 9: Weighted pipeline value needs `finance.owner` (CORRECTIONS 15); open value and column totals need `fees.view`. Quiet prospects on Overview: your own, or all for `finance.owner`.
- 9: VAT switches apply only if the practice is VAT registered; "inc. VAT" is added to amounts shown with VAT. A quarterly or annual fee shows as its own frequency with breakdown on; the monthly charge is the rounded monthly total. One-offs and the setup fee are shown apart.
- 9: A proposal link lasts to the end of the valid-until day. Wrong, expired and cancelled links all give the same plain 404 page. Won cards cannot be dragged back. Accepting does not draft the engagement letter; staff prepare it on the Engagement tab. Link buttons in the email arrive as plain links (nh3).
- 9: Board drops other than Lost and Won reload the page so column totals stay right.
- 11: Hourly return uses today's agreed monthly fee times the months in the window (not Xero invoices). The window is N calendar months ending with this one.
- 11: Check fee compares a client's whole month of invoiced net with the agreed fee (two invoices add up). Not invoiced counts any non-void invoice dated this month, once the set day (10) has passed.
- 11: Contracted for past months uses today's records, so clients who have since left are missing. Ended services count up to their end date. A setup fee counts only for onboarding clients, in their expected start month.
- 11: "Ending by month" counts services that end before the last day of that month. Proposed services of an onboarding client with no expected start start 60 days from today (setting).
- 11: Time boxes holding several entries are read-only on the timesheet; edit them from the client Time tab. Time cannot be logged for a future day.
- 11: Send to Xero, matching and the Xero buttons need `finance.owner`. The owner summary email is internal, not queued. One task-table query budget test raised from 30 to 32 for the timer lookup.
- 12: Rows a person must fix are left out, never guessed. A client's type is needed for a new client. An import never changes an existing client's status, reference or company number, nor the year end of a client synced with Companies House.
- 12: A UTR goes into the client's UTR field whatever the client type. The uploaded file is stored encrypted until imported, then cleared; failed rows are kept encrypted with tax references replaced by "(left out)".
- 12: A service with no start date starts on the client's "client since" date, else today. Imported services of prospect or onboarding clients are proposed. Deadlines are generated straight after a services import.
- 12: Undo counts a record as changed if it was saved after the import, or (for a client) if anyone worked on it since, or it has hand-made or completed tasks. Companies House fetch and generated deadlines and tasks do not count. People Companies House added go with the client if nothing else links to them.
- 12: The migration helper lists all open deadlines overdue or due within 30 days (not only imported clients), and can also complete their open tasks (ticked by default).
- 12: A practice-wide monthly total on the Services report needs `finance.owner`; each row's fee needs `fees.view`. Request "first action" is the first set client, convert, link, answer, close or spam. Time report defaults to this month and the two before.

- 13: Branch is `claude/sharp-keller-d89e2x` (the session's required branch). No host was named, so DEPLOY.md is for a generic container host. Email defaults to Amazon SES in London (CORRECTIONS 28).
- 13: The bucket and email keys are required in production; Companies House and Xero keys are optional (the System page shows "No key"). HSTS preload left off. Request bodies capped at 100 MB, 10 files.
- 13: Proposals and engagement letters need `fees.view` (they show fees). Open pipeline value and column totals now need `finance.owner` (CORRECTIONS 15), replacing the Stage 9 choice.
- 13: A person may be removed only when every client that holds anything about them is former or lost and past both dates. The removal event keeps no name. Retention "people" are those no live or in-date client keeps.
- 13: Delivery reports keep delivered, bounced and complained only; opens and clicks are not tracked.
- After 13: With DEBUG on and WeasyPrint's system libraries missing (a Mac without Pango), PDFs are a one-page stand-in so `seed_demo` and the site still run; a live site still stops with the error (`apps/core/pdf.py`).

## Known gaps

Things a stage left unfinished or found broken, with the stage number. Remove a line when it is fixed.

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

### Stage 10 assumptions and gaps
- Portal sign-in is our own small code flow, not allauth's login by code, because that would also apply to staff at `/login/`. Sign-in and invitation emails go straight out (CORRECTIONS 17), not through the queue.
- The details form never shows another person's date of birth, address, tax references or saved draft answers to a portal user; staff see everything on the review screen.
- Items made by `upload_link`/`confirm_link` are created when the email is rendered, once per task. A recipient with no portal access cannot open them until invited. Rendering a preview also creates the item.
- Request attachments stay as private `RequestFile`s until converted or linked, then become Documents. Requests closed by a done task become "closed". A reply to a request is queued and marks it "answered".
- Demo data has three portal users (Copperleaf, Harbour Bakes, Wren and Finch) so every item kind is open. The portal code appears in the runserver console.
- Known gaps: no email-in or WhatsApp-in (not in stage); portal items are not auto-withdrawn when a records task is cancelled.
- 12: No real BrightManager export has been seen; the headings suggested are guesses and the owner checks the matching on screen. Live Companies House fetch was tested against the fake only.
- 11: Live Xero connection untested (cloud cannot reach Xero); built and tested against the samples. Disconnect only forgets the tokens; remove the app in Xero too.
- 13: Password reset pages use allauth's plain layout. Virus scanning, SNS signature checks and fully atomic rate-limit counters are accepted gaps (`docs/SECURITY-REVIEW.md`).
