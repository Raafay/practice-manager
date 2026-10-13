# Stage 13: Hardening and deployment

Goal: the app is checked for weaknesses, set up to run in production, and comes with plain guides and a go-live checklist. After this stage, and only after the checklist is ticked, real client data can go in.

Read first: `docs/specs/12-deploy-and-operations.md`, `docs/specs/01-security-and-users.md`, `docs/specs/10-integrations.md` sections 4 to 6.

Before starting, the person running the build should say which host they have chosen. If the prompt does not name one, do every item that does not depend on the host, write `docs/DEPLOY.md` for a generic container host, and list what is left.

Use a stronger model for item 1 if one is available. A fresh pair of eyes matters more here than speed.

## Build

1. The security review in section 1 of the spec. Write `docs/SECURITY-REVIEW.md` with each of the fourteen checks, what was found and what was done. Fix findings, most serious first. Add a test for each fix.

2. The URL walk test: every address in the project against an expected result for signed-out, portal, staff, manager and owner users. A new address without an entry fails the test.

3. Production settings, section 3: `prod.py` refusing to start without what it needs, the private bucket through django-storages, whitenoise, `/healthz`, logging, optional Sentry with scrubbing.

4. The Dockerfile finished for production: non-root user, the CSS built in the image, `collectstatic`, a release command that runs migrations. A `Procfile` or the host's equivalent with `web` and `worker`.

5. Email for real: the provider chosen by `EMAIL_PROVIDER`, the delivery webhook with its signature checked, and bounce handling on the Queued page.

6. The retention report job and its page for the owner. It lists and never deletes.

7. The subject access export for a contact, and the owner's purge action with its checks.

8. The guides in section 4: `DEPLOY.md`, `RUNBOOK.md`, `BACKUPS.md`, `SUBPROCESSORS.md`, `STAFF-GUIDE.md`, `GO-LIVE.md`. Plain English. Exact commands where a command is needed.

9. A Settings, System page for the owner: version, last backup note (typed by hand), job health, email health, Companies House and Xero state, and the pause switch.

10. Update `README.md` so it describes the finished app and points to the guides.

## Checks

- `make lint` and `make test` pass, including the URL walk and the production settings tests in section 7 of the spec.
- `docker build` succeeds and the container starts against a fresh database, runs migrations, and serves `/healthz`.
- The dependency audit is clean or each remaining item is explained in `SECURITY-REVIEW.md`.
- `docs/GO-LIVE.md` contains every line of section 5 of the spec as a tick box.
- In the pull request, list plainly: what the user must do by hand (accounts, DNS, keys), what the practice owner must sign off, and any finding that was not fixed.

## Not in this stage

Loading real client data. That happens after the checklist, by the owner, using the import from Stage 12.
