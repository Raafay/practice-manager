# Stage 14: One schema per practice

Goal: the app serves several practices from one installation, each in its own PostgreSQL schema chosen by web address, with FPAS's data moved into its own schema and nothing else changed for its staff.

Read first: `docs/MULTITENANT.md` (all of it). Do not start until the ownership and revenue agreement with Mati is in writing.

## Build

1. Add `django-tenants==4.0.1`. New app `apps/tenancy`: `Practice` (TenantMixin: name, status active/read-only/closing, created and updated) and `Domain`. Settings split into `SHARED_APPS` and `TENANT_APPS` as in the design; tenant backend, router, `TenantMainMiddleware` first. Unknown addresses get a plain 404.
2. `apps/core/siteurl.py` builds links from the current practice's primary domain; remove every use of `SITE_URL` (11 places). Jobs and emails get the domain from the practice they run for.
3. Worker: each due job runs once per active practice inside `schema_context`; one practice's failure is logged there and never stops the rest.
4. Files under `<schema>/` in the bucket, still through the encrypting storage, and the storage refuses a path outside the current practice's folder. Cache key function includes the schema.
5. `manage.py create_practice NAME SCHEMA DOMAIN OWNER_EMAIL` and `manage.py move_into_schema fpas`: moves today's tables from `public` into the new schema in one transaction after checking a backup was taken in the last hour.
6. Test set-up: a fixture with two practices; the whole existing suite runs inside the first. Update `seed_demo` to make two demo practices.
7. `docs/DEPLOY.md`, `docs/BETA.md`, `docs/BACKUPS.md`: wildcard DNS, per-practice backup and restore (`pg_dump -n`).

## Checks

- Every existing test passes inside a practice.
- For every address in the URL walk: signed in at practice A, the same request on practice B's address is sent to sign in or 404; never 200 with A's data.
- A file uploaded in A cannot be opened from B, even with its exact path. A rate limit hit in A does not count in B.
- A job runs in both practices; a failure in one is logged and the other still runs.
- `move_into_schema` on a copy of the demo data leaves every count the same and every page working.

## Not in this stage

Sign-up, billing, the platform admin, export and deletion (stages 15 to 17).
