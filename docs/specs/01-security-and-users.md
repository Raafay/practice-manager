# 01 Users, access and security

Read by Stages 1 and 13. Other stages follow the rules in CLAUDE.md, which repeat the essentials.

## 1. Kinds of user

One `User` model with email as the sign-in name and a `kind`: `staff` or `portal`.

- Staff sign in at `/login/`. Portal users sign in at `/portal/login/`. A staff account can never use the portal sign-in and the other way round.
- Staff fields: name, initials (two letters, shown in avatars), colour, job title, role, teams, weekly hours (for workload), email signature, active flag.
- Portal users are created from a contact when staff invite them. They have no password.

## 2. Roles and what they may do

Three roles are seeded. The owner can change the ticks for Manager and Staff in Settings, and can grant a single right to a single user on top of their role. The Owner role always has every right, and one active owner must always exist.

| Right (code name) | Owner | Manager | Staff |
|---|---|---|---|
| See and edit clients, contacts, tasks, deadlines, requests | yes | yes | yes |
| See client fees (`fees.view`) | yes | yes | yes |
| Finance pages: forecast, targets, Xero totals, hourly rates (`finance.owner`) | yes | no | no |
| Approve AML risk assessments (`aml.approve`) | yes | no | no |
| View identity documents (`documents.sensitive`), each view logged | yes | yes | yes |
| Approve and send queued messages (`comms.approve`) | yes | yes | yes |
| Approve fee-chasing messages (`comms.approve_fees`) | yes | yes | no |
| Change settings: services, templates, statuses, stages (`settings.manage`) | yes | yes | no |
| Add users, change roles and teams (`users.manage`) | yes | no | no |
| Export lists to CSV (`data.export`) | yes | yes | no |
| Run imports (`data.import`) | yes | no | no |
| Archive a client (`clients.archive`) | yes | yes | no |
| Delete a client for good (`clients.delete`) | yes | no | no |
| Make a client live without full onboarding (`onboarding.override`) | yes | no | no |
| Connect Xero and other services (`integrations.manage`) | yes | no | no |
| View the audit log (`audit.view`) | yes | no | no |

In code: `user.can("fees.view")`, a `CapabilityRequiredMixin` for views and a template tag for fragments. A figure the user may not see must not be in the page source at all.

Teams are labels for grouping people and filtering work. They do not restrict what anyone sees.

## 3. Staff sign-in

- Email and password. Minimum 12 characters, Django's validators, no forced change on a timer.
- Two-factor is compulsory. A staff user without an authenticator app set up is sent to set one up and can reach nothing else. Recovery codes are shown once.
- "Trust this browser" for 30 days is on (`MFA_TRUST_ENABLED`, `MFA_TRUST_COOKIE_AGE`). The owner can turn it off.
- Five wrong passwords lock that account from that address for 15 minutes (django-axes). Each failure is logged.
- New staff are invited by the owner: name, email, role. The invite link works once and lasts 72 hours. The person sets a password, then two-factor.
- The owner can reset someone's two-factor and can deactivate an account. Deactivating asks who should take over that person's open tasks and clients.
- A session ends after 60 minutes idle and after 12 hours in any case. Both are settings.
- The password is asked for again before: viewing recovery codes, changing two-factor, exporting data, changing roles, connecting an integration.
- Development only: `MFA_TOTP_INSECURE_BYPASS_CODE` may be set in dev settings so a seeded user can sign in without a phone. Production settings must refuse to start if it is set or if DEBUG is on.

## 4. Portal sign-in

- The person enters their email. If it belongs to a portal user, a six-digit code is emailed (allauth login by code). It lasts 10 minutes and allows 5 tries. The page says the same thing whether or not the email is known.
- A portal session ends after 30 minutes idle and after 8 hours in any case.
- A portal user sees only the clients they are linked to with portal access. With more than one, they get a switcher.

## 5. Links that work without signing in

Action link. Lets one person do one thing: read and accept a proposal, sign an engagement letter, fill in one form.

- The token is 32 random bytes. Only its hash is stored. It is tied to one contact, one purpose and one object.
- It expires (14 days by default) and staff can cancel it.
- The page can be opened many times. The action can be done once.
- Signing asks for the full name typed out and a tick box. The app stores the name, time, IP address and browser.

Request link. One per client, for client staff to send a request.

- A long random token on the client record. Staff can replace it, which kills the old link.
- The form creates a request and shows nothing about the client except its name.

Both kinds are rate limited through the Django cache (database cache in production): 10 submissions an hour per address, 30 a day per token.

## 6. Access rules in code

- Staff views use `StaffRequiredMixin`: signed in, kind staff, active, two-factor done.
- Portal views use `PortalRequiredMixin`. Every query goes through a manager method such as `Document.objects.for_portal_user(user)`. Objects are looked up by `public_id`.
- Public views accept a token only, compared in constant time.
- The Django admin lives at `/control/`, is for the owner only, and is a last resort.
- New URL, new tests: signed-out, wrong role, wrong client.

## 7. Files

- Private storage. In development a media folder outside static files. In production a private bucket with encryption at rest and no public access.
- Stored under `documents/<random>/<random>.<ext>`. The original file name is kept in the database only.
- Allowed types: pdf, jpg, jpeg, png, heic, webp, doc, docx, xls, xlsx, csv, txt, eml, msg. Maximum 25 MB. Check the extension and the first bytes for PDFs and images.
- Downloads go through a view that checks permission, sets `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`. Staff can preview PDFs and images in the page.
- A document can be marked sensitive. Identity and proof-of-address documents are sensitive by default. Each view or download of a sensitive document is logged, and sensitive documents are left out of bulk exports.
- Deleting hides a document. Only the owner can remove it for good.
- There is no virus scanning in the first version. This is listed as a known gap in the go-live checklist.

## 8. Encrypted fields

`EncryptedTextField` in `apps/core`, using Fernet from the cryptography library with keys from `FIELD_ENCRYPTION_KEYS` (a comma-separated list, first one active, so keys can be rotated).

Used for: National Insurance numbers, UTRs, Companies House authentication codes, Companies House personal codes, HMRC authorisation codes, Xero tokens.

These fields cannot be searched. They are shown masked, for example `••••••12A`. A "Show" click reveals the value and records a `sensitive.revealed` event.

## 9. Activity log

One model, `ActivityEvent`, serves as both the audit trail and the client timeline.

Fields: actor (user, empty for the system or the public), actor label, verb, client (optional), target (generic link), summary (one plain sentence), data (JSON of changed fields, old and new, never the value of an encrypted field), IP address, browser, time.

Events are never edited or deleted by the app.

Record at least: sign-in, failed sign-in, sign-out, two-factor reset, user invited, role changed, user deactivated, client created, changed, status changed, archived, contact changes, document uploaded, viewed, downloaded, shared, deleted, deadline created, changed, done, overridden, task created, changed, completed, message queued, approved, sent, failed, proposal sent, viewed, accepted, declined, letter sent, signed, risk assessment submitted, approved, overridden, onboarding item done, client made live, override used, portal sign-in, portal upload, form submitted, request received, request converted, export run, import run, setting changed, integration connected, sensitive value revealed.

`events.record(actor, verb, summary, client=None, target=None, **data)` is the only way to write one. A middleware keeps the current user and address so model code can call it.

The audit log page (owner only) lists all events with filters by person, client, verb and date.

## 10. Data protection

- Retention: AML records are kept at least 5 years after the relationship ends. Other records 6 years. Both are settings.
- When a client becomes "former", store the end date and work out `retain_until`. A monthly report lists what has passed that date. The owner decides what to remove. Nothing is deleted automatically.
- The owner can export everything held about one contact as a ZIP of data and files, for a subject access request.
- Removing a person's data for good is an owner action, blocked while a retention period runs, and logged.
- Stage 13 writes `docs/SUBPROCESSORS.md` listing every outside service that holds or sees client data.

## 11. Production settings

Stage 13 checks each of these with a test or a command:

- DEBUG off. Secret key, database address and encryption keys from the environment.
- HTTPS only, HSTS for a year, secure and HttpOnly cookies, SameSite Lax.
- Content-Security-Policy: `default-src 'self'`, images from self, data and blob, no inline scripts, `frame-ancestors 'none'`. This is why the Alpine CSP build is used and `htmx.config.allowEval` is false.
- `Referrer-Policy: same-origin`, `X-Content-Type-Options: nosniff`.
- Logs contain no personal data and no secrets.
- Error pages show nothing internal.
