# Many practices on one installation

Written 04/11/2026 after the 23/10/2026 meeting. This replaces DECISIONS 1 ("one installation
has one practice") once the owner of the product and the revenue split are agreed in writing
with Mati. Build it in stages 14 to 18 (`docs/stages/`). Do not start before that agreement.

## The choice: one PostgreSQL schema per practice

Each practice gets its own schema (a separate set of every table) in one database, chosen by
the web address it is reached on (`fpas.example.com`). Built with `django-tenants` 4.0.1,
which supports Django 5.2.

Why this and not a `practice` column on every table:

| | Schema per practice (chosen) | `practice_id` on every table | A copy per firm |
|---|---|---|---|
| Can one firm see another's data? | Only through a bug in one small piece of middleware | Any one query missing a filter leaks | No |
| Work to build | About 15 files change | About 80 tables and 200 files of queries | None, but every firm is its own deployment |
| Backup, export, delete one firm | `pg_dump -n`, `DROP SCHEMA` | Hand-written per table | Per deployment |
| Upgrades | One deploy, migrations run per schema | One deploy | One per firm |
| Comfortable size | Hundreds of firms | Thousands | Tens |

Tried on 04/11/2026 in a throwaway copy (not kept): with `django-tenants` added and no other
code changed, two practices were created (about 9 seconds each, all 25 apps migrated),
`seed_demo` filled one, the other stayed empty, pages served on each practice's address, a
signed-in session from one practice was sent to sign in on the other's address, and an
unknown address got 404.

The meeting notes ask for "a practice record that every table is tied to". This meets the
intent (no data can leak between firms) more safely than a column would.

## What lives where

- **Platform (public schema):** `apps.tenancy` (Practice, Domain, plan and billing state,
  usage), platform admin users, Stripe webhooks, sign-up pages. Nothing about any firm's clients.
- **Each practice's schema:** everything else, unchanged: users, roles and teams, clients,
  tasks, messages, AML, documents, Xero connection, Creditsafe login, finance, the activity log,
  sessions, sign-in lockouts.

Users belong to one practice. Someone who works for two firms has two accounts. Platform staff
(you) sign in on the platform address only and never see a firm's data unless the firm grants
support access, which is logged in that firm's activity log.

## Things that must change (the list the build stages work through)

1. **Settings:** split `INSTALLED_APPS` into `SHARED_APPS` and `TENANT_APPS`, the
   `django_tenants.postgresql_backend` engine, the tenant router, `TenantMainMiddleware` first.
2. **Addresses:** `SITE_URL` is used in 11 places to build links in emails and jobs. Replace
   it with the current practice's primary domain (`apps/core/siteurl.py`). `ALLOWED_HOSTS` and
   `CSRF_TRUSTED_ORIGINS` come from the Domain table (a wildcard subdomain plus custom domains).
3. **Background work:** the `worker` command runs each due job once per practice, inside that
   practice's schema. A failure in one practice never stops the others. Each run is logged in
   the practice's own job log.
4. **Files:** uploads go under a folder per practice (`<schema>/...`) in the bucket, still
   encrypted. A file path from one practice must never open in another: the storage refuses a
   path outside the current practice's folder.
5. **Cache:** the cache key includes the schema name (`KEY_FUNCTION`), so rate limits and
   cached figures never cross over.
6. **Email:** each practice sends from its own address (Practice settings already holds the
   sending address, footer and logo). The email provider account stays the platform's;
   each firm verifies its sending domain once.
7. **Integrations per practice:** Xero is already stored per practice (it is a table).
   Creditsafe moves from environment variables into the practice's encrypted settings. Companies
   House stays one platform key (public data). The Claude API stays one platform key, and each
   question is already recorded per practice for billing.
8. **Encryption keys:** one platform key set to start. A key per practice is a later option.
9. **Theme:** already done (`apps/core/theme.py`); each practice's Practice settings give its
   colours, logo, name, email footer and PDF letterhead.
10. **Tests:** a fixture that creates two practices; every existing test runs inside the first.
    New tests: each address on another practice's domain is refused, files and cache cannot
    cross, a job runs in every practice, sign-up creates an empty practice.

## Billing (Stripe)

Stripe Checkout to subscribe, the Stripe customer portal to change card or cancel, and signed
webhooks to keep the practice's plan state. Price per user (active staff accounts, counted
nightly and sent to Stripe as the quantity) unless agreed otherwise. A practice whose payment
fails gets 14 days of warnings, then read-only access, never deletion. New dependency `stripe`.

## Leaving and deleting

- Export: a ZIP of every table as CSV plus every file, for the practice owner, logged.
- Deletion: on request, after export, marked for deletion with a 30-day hold, then
  `DROP SCHEMA` and the practice's file folder removed. Backups age out on their normal cycle.

## Paperwork before the first other firm (not code)

Written agreement with Mati on ownership and revenue. A data processing agreement and terms
of service (the platform becomes a data processor for each firm's client data). ICO
registration. Update `docs/SUBPROCESSORS.md` into a public page.

## Moving FPAS across

FPAS's existing data moves into its own schema in one step: create the Practice for FPAS with
`schema_name="fpas"`, then move the current tables from `public` into it with
`ALTER TABLE ... SET SCHEMA` inside one transaction, after a full backup. Stage 14 writes and
tests this command against a copy of the demo data first.
