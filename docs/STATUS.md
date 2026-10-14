# Status

Keep this file under 150 lines. When it grows, shorten older stages to two lines each.

## Where things stand

Next stage to build: 10 (Portal and requests).

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
- WeasyPrint produced a PDF (a HarfBuzz warning can be ignored). Chromium for Playwright is under `/opt/pw-browsers`.
- `manage.py tailwind build` downloaded the Tailwind binary (about 145 MB, a few seconds) into `.django_tailwind_cli/` and built the CSS. That folder is in `.gitignore`.
- django-allauth has the settings this project needs: `MFA_TRUST_ENABLED`, `MFA_TRUST_COOKIE_AGE`, `MFA_RECOVERY_CODES_SHOW_ONCE`, `MFA_TOTP_INSECURE_BYPASS_CODE` (development only) and `ACCOUNT_LOGIN_BY_CODE_ENABLED` (for the portal).

## Stage 1: foundation (built 13/10/2026)

Django 5.2 project, settings by environment, staff sign-in with compulsory two-factor, users, roles and rights, teams, invitations, activity log and notifications, encrypted fields, strict CSP, layout and `/styleguide/`. Vendored htmx 2.0.11, Alpine CSP 3.17.4, SortableJS 1.15.7, Trix 2.1.19, Heroicons 2.2.0; Tailwind CLI 4.1.3.

See `docs/screens/stage-01/`. `create_owner`, `seed_demo`, `dev_login`, `rotate_encryption_keys` commands.

## Stage 2: clients and contacts (built 13/10/2026)

Clients, contacts, links, notes, documents (private storage, permission-checked, sensitive access logged), saved views, CSV export, search, status moves, archive and delete for good with retention dates, tags and custom fields. NI numbers, UTRs and Companies House codes are encrypted and shown masked.

See `docs/screens/stage-02/` if present.

## Stage 3: Companies House and jobs (built 13/10/2026)

`apps/jobs` (registry, run log, lock, worker, owner-only Jobs page) and `apps/companieshouse` (API client over urllib, fake transport for tests, add from Companies House, nightly sync with snapshots, contact matching). Shapes checked live against the real API.

See `docs/screens/stage-03/`. 499 tests at the time.

## Stage 4: services and deadlines (built 13/10/2026)

- `apps/services`: Service (18 seeded by migration), ClientService, FeeChange, Deadline. Settings, Services (add, edit, reorder, switch off). Services panel on the Info tab (switches that ask first, fee boxes, totals; fees need `fees.view`). VAT, payroll and MTD settings are written to the client record; regular work and renewals keep theirs on the client service.
- All 17 rules in `apps/services/rules/`, pure functions with table tests from spec 03 section 6. Pay-date helpers are in `apps/core/dates.py`.
- `generate_for_client` is safe to run twice. It runs nightly at 03:00 (job `deadlines`), after a client's details or status change, and at the end of a Companies House sync. Companies House dates update in place and a filing marks the deadline done and creates the next.
- Mark done, not required, reopen, change date (reason, original kept). Client Deadlines tab, Reports, Deadlines (filters, CSV with `data.export`), list columns (next deadline, monthly fee) and filters (service, overdue). 18 services, demo clients get fees and deadlines. Screens in `docs/screens/stage-04/`. No new dependency.

## Stage 5: tasks, part one (built 13/10/2026)

- `apps/tasks`: Task, TaskStatus, TaskCategory, TaskTemplate and steps, TaskStep, TaskComment, TaskStar, TaskDocument. Statuses, 21 categories and the 16 templates are seeded by migration. Project, section and repeating-task links are plain nullable numbers for Stage 8.
- Deadlines make tasks through signals from `apps/services/deadlines.py` (services never imports tasks). Due dates follow the deadline. Ticking the filing step marks the deadline done ("Marked filed by {name}"). A deadline done elsewhere shows a banner offering to complete its tasks. Job `tasks_catch_up` runs at 03:30.
- Tasks page: table with in-place owner, status, target date and next step; chips, filter panel, grouping with Add task rows, sort, bulk actions, Load more, state in the address. Saved views reuse the client `SavedView` model (new `is_default` field, one per user per list). Drawer at `/tasks/<id>/`, New task (top bar, `n`), My work as the home page, client Tasks tab. Settings: Task statuses, Task categories, a Tasks button per service for templates and steps.
- Rich text cleaned with nh3 (`apps/core/html.py`); Trix loads on every page and refuses files. No new dependency. Screens in `docs/screens/stage-05/`.

## Stage 6: communications (built 13/10/2026)

- `apps/comms`: MessageTemplate, QueuedMessage, ReminderSchedule. Merge-field renderer (`merge.py`) swaps only the listed names; no Django template engine. Unknown fields and link fields with no page yet (`LINK_BUILDERS` is empty until Stages 7, 9, 10) block approval. `cs01_data` reads the Companies House snapshot; `outstanding_invoices` is empty until Stage 11.
- Queued page (filters, bulk approve, nav count, pause switch with banner on every page), message editor (Approve and send, Save, Cancel, Try again). Approve needs `comms.approve` (`comms.approve_fees` for the fees group). Nothing is approved without an address, subject, filled fields and a current client.
- Jobs: `send_messages` every 5 minutes (claims each message with one UPDATE, does nothing while paused), `reminders` daily at 06:00. From is the sending address with the approver's name; Reply-To is the approver; Bcc to the practice address when the new practice setting is on. Failures notify the approver. `record_delivery()` is ready for the Stage 13 webhook.
- Eight reminder schedules and starter templates seeded (off, hold for approval). Settings: Message templates (Trix, click-to-insert fields, preview for a chosen client), Reminders (on/off, timing, repeats, template, owner-only automatic).
- Client page: Send email (compose window), Log an email, Create a letter (WeasyPrint PDF on the letterhead, saved to Documents). Client list: Email these clients. SMS interface and console/memory backends; hidden until `SMS_BACKEND` is set.
- Screens in `docs/screens/stage-06/`. No new dependency. 893 tests in all.

## Stage 7: onboarding and AML (built 14/10/2026)

- `apps/onboarding`: checklist (template in Settings, created when status becomes onboarding or a proposal is accepted via `on_proposal_accepted`), go-live gate and `make_live` with owner override and logged reason, engagement letters (parts in Settings, edit, queue, public signing page, signed PDF with signature page, review task), HMRC authorisations, professional clearance, Overview panels. Shared `ActionLink` (hashed token) is in `apps/core`.
- `apps/aml`: identity checks (sensitive uploads, `IdentityProvider` interface with none behind it), 17 seeded risk questions, scoring, approval rules, Companies House snapshot PDF on approval, review prompts, AML state and header badge, register with CSV, practice records (officer, training, policy documents), daily job `aml_reviews`.
- Status form can no longer move onboarding to active; use Make live. 991 tests. Screens in `docs/screens/stage-07/`. No new dependency. New setting `SITE_URL` (links in emails).

## Stage 8: tasks, part two (built 14/10/2026)

- Tasks page has a Table / Board / Calendar switch (`layout=` in the address, so saved views remember it). Board: columns by status, owner, category, client (section inside a project); SortableJS drags saved by `fetch`, card put back on failure; float `position` with gaps, one row updated; Done column shows 14 days. Calendar: server-built month and week, target date or deadline date, fixed deadline markers, side list of undated tasks, `+` on a day opens New task. `static/js/keys.js` holds `g t`, `g c`, `g o`, `?`.
- Projects (list, page with table by section or board, progress, hours against budget, four seeded templates), repeating tasks (list, form from New menu and client tab, job `repeating_tasks` 03:45), Workload page, Overview as home page (my work, deadlines for my clients, waiting on me, panels).
- Notices: assigned, mentioned, comment on a followed task, step ticked by someone else, deadline within 7 days while To do (job `task_notices` 07:00, once per task). Daily email job `daily_task_email` 08:00 on working days; three profile switches. Notification gained `kind` and `key`; User gained `email_overdue`, `email_today`, `email_week`.
- Task now has real links `project`, `section`, `repeating_task`. Screens in `docs/screens/stage-08/`. No new dependency (Sortable now loads on every page).

## Stage 9: prospects and proposals (built 14/10/2026)

- `apps/pipeline`: PipelineStage (8 seeded), ProspectDetails, Meeting, Proposal, PipelineSettings. Prospects page (board with drag, list, filters, header figures), new prospect form, Sales and Meetings panels on the Info tab, quiet rule with daily job `pipeline_daily` (06:50, also expires proposals), quiet panel on Overview, `g p` shortcut.
- Proposals: made from proposed services, versions (older ones withdrawn), three fee switches, compose page, sent through the queue (approved at once if the sender may approve), public page behind the Stage 7 action link (view, accept, question, decline), PDFs to Documents, `on_proposal_accepted` calls Stage 7's onboarding hook. Settings: Pipeline stages, Proposal wording and rules. Engagement tab lists proposals.
- Merge field `proposal_summary` added. Screens in `docs/screens/stage-09/`. No new dependency.

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

- 2: Branch is `claude/sharp-knuth-96f9y3` (the session's required branch), not `stage-02-clients`.
- 2: New clients default to `active`. Prospects and onboarding come from Stages 7 and 9.
- 2: Notes are plain text, shown with line breaks (no rich text, so nothing to clean). Pinned notes show on the Info tab.
- 2: Status moves: prospect to onboarding or lost; onboarding to active, paused or former; active and paused to each other or former; former to active; lost to prospect.
- 2: Delete for good is blocked only by the retention dates. A live client with no dates is not blocked, so owner-only and the typed name are the guard.
- 2: Sensitive documents need `documents.sensitive`; only sensitive views and downloads are logged, plain ones are not.
- 2: Filing dates are read-only once a company number is set, so until Stage 3 they can only be set by the demo seed.
- 2: Contact changes are logged once on each linked client's timeline.

- 3: Branch is `claude/nifty-knuth-isuax1` (the session's required branch), not `stage-03-companies-house`.
- 3: A Companies House personal code is 11 letters or digits; Stage 2 had allowed six (that is the company authentication code). Fixed in the contact form.
- 3: The sync never renames a client unless its name still equals the old registered name. New clients take the registered name as given.
- 3: The sync also adds newly appointed people as contacts. A person who left before the company was added is listed on the tab but not made a contact.
- 3: "Run now" and "Run sync now" ask the worker; only "Sync now" on one client runs straight away. Jobs runs need `system.view` (owner); Integrations needs `integrations.manage`.
- 3: Calls go out without an Authorization header when `COMPANIES_HOUSE_API_KEY` is empty, so a network proxy that adds the key (as in cloud sessions) still works. The page then shows "No key".

- 4: Periods due more than 60 days ago are not created (so a service started years ago gets no history). Spec only gave the start-date rule.
- 4: Open calculated deadlines are re-calculated when inputs change (for example a new pay day); ones changed by hand are left alone.
- 4: Reminder-only rules (ct_payment, paye_payment, sa_payment, p11d Class 1A) and tax-year rules with no horizon are created 60 days ahead (CORRECTIONS 10). "Created N days ahead" for payroll, CIS and regular work is counted before the due date; VAT and MTD before the period end.
- 4: Going live (status Active) turns proposed services active, starting today. Paused clients keep active services but get nothing new.
- 4: Reports live in `apps/services` with a small Reports index; Stage 12 can add to it. Two icons missing from the set were replaced by `calendar` and `rectangle-stack`.

- 6: Branch is `claude/trusting-feynman-fm97v2` (the session's required branch), not `stage-06-communications`. No pull request opened: the session rules say only on request.
- 6: Build item 12 (move the daily email and invitations onto the sending path) is left out, as CORRECTIONS 4 says. Sign-in emails stay direct (CORRECTIONS 17).
- 6: "Repeats N times" means N more messages after the first. A date missed by more than 3 days is skipped, not sent late. One message per client goes to the main contact and contacts marked "receives reminders".
- 6: "Stops when" is any step flagged "stops reminders" and ticked on a task linked to the deadline, or on the task itself. A done or not-required deadline stops its reminders.
- 6: A schedule's template send mode is set from the Reminders page; only the owner can set automatic. An automatic message that has a blocking problem still waits for a person.
- 6: The starter wording asks clients to reply with records attached, because upload and portal pages arrive in Stage 10. Switch to `{{ upload_link }}` then.
- 6: Message bodies are cleaned with nh3, which drops inline styles, so link buttons arrive as plain links. Sensitive documents cannot be attached to an email.
- 6: Hand-written messages to a former or lost client show a warning and cannot be approved. Compose fills deadline fields from the client's nearest open deadline and warns if there is none.
- 6: `setup_fee` merges the client's one-off fees (no separate setup fee exists yet). The signature is the existing `email_signature` on the user profile.
- 6: Log an email adds a note of kind "email" (clients migration 0004).

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

## Known gaps

Things a stage left unfinished or found broken, with the stage number. Remove a line when it is fixed.

- 1: The Docker image was not built in the cloud session: Docker Hub refused the base image pull (429). Build with `docker build -t practice-manager .` or `docker compose up`.
- 1: Lockout, rate limits and the audit log use `REMOTE_ADDR`. Behind the production proxy, Stage 13 must take the client address from the trusted proxy header.
- 1: Date filter boxes use the browser's own date picker, which shows the browser's date order (dd/mm/yyyy on a UK computer).
- 2: Portal share switch on documents and portal access on contacts are stored but do nothing until Stage 10.
- 2: No quick switches on the Contacts tab; flags are edited in the Edit drawer.
- 2: Django 6 deprecation warning for URL form fields (assume https) shows in tests.
- 3: gov.uk is blocked in cloud sessions, so the bank holiday refresh was tested against a sample in the published shape only.
- 4: Spec 03 section 6 lists "sa_payment, second payment on account for 2026/27: 31/07/2027". 31 July 2027 is the second payment for 2025/26. Kept as a strict expected failure; the rule follows HMRC (31 July after the tax year).
- 4: Rules marked "(Confirm ...)" for the practice owner: long-period CT600 return date (rule 2), P11D and payrolling from 2027/28 (rule 9), auto-enrolment re-declaration day (rule 16).
- 4: The rule choice for a service can be edited in Settings, Services; there is no check that a rule suits the service.

- 5: A fourth target rule, "working days before the due date", exists for Payroll (2 working days before pay date); the spec names three kinds.
- 5: "Fixed day before the due date" means the latest such day strictly before the due date, moved back to a working day.
- 5: Manager default owner falls back to partner, then an owner. Documents attach only to tasks that have a client, as plain form posts.
- 5: The project filter works from the address (`project=`) but has no box in the panel until Stage 8. "Week due" groups by deadline, else target date.
- 5: Unticking a filing step does not reopen the deadline. My work sections use the target date, else the deadline; "waiting" status takes precedence.
- 5: Mention notices use the existing bell; the other notification triggers are Stage 8. Core's placeholder Overview page was removed; the home page is My work.
- 6: Delivery reports (delivered, bounced) have a function but no webhook until Stage 13. No provider is chosen, so only the console and in-memory backends are tested.
- 6: Text messages have no provider; the Send SMS button and text templates are hidden until `SMS_BACKEND` names one.
- 6: Letters use the practice logo and address only. The clearance letter wording is Stage 7's.

- 7: The practice owner must read the risk questions and score bands before they are relied on. Letter wording is starter text. The 30-day postal code expiry needs confirming with the practice.
- 7: Portal form for client details (Stage 10) not built: staff tick "Client details form completed". `SITE_URL` must be set in production (Stage 13).

- 8: Project templates cannot be edited in Settings. The calendar's deadline markers follow the client (and fixed client) only, not the other filters. Drag and drop was checked through the endpoints and page markup, not in a live browser.
- 9: Drag and drop was checked through the endpoints and markup, not in a live browser. The Prospects list has no CSV export.
