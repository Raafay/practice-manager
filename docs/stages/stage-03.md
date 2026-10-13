# Stage 3: Companies House and background jobs

Goal: a company can be added by name or number with its people pulled in, its filing dates stay up to date every night, and the app has a way to run work in the background.

Read first: `docs/specs/10-integrations.md` sections 1 and 2, `docs/specs/02-clients.md` section 2 (company fields) and section 3 (contacts).

UPDATE (owner, 13/10/2026): the owner has stored a Companies House key as a network secret (type Basic, key as user name, empty password) for host `api.company-information.service.gov.uk`. Cloud sessions started after that CAN reach the live API. Do this first, before building:

1. Run one real lookup with the Basic-auth secret (for example `GET /company/00000006`, Companies House's own well-known test company, or any real public company) and look at the real response shape. If it fails with a network denial, a 401, or no secret in the environment, STOP and tell the user exactly which of those it was and what to change in the environment settings. Do not carry on with made-up data.
2. Build the client against the live API, and fix the spec's shapes wherever the live response differs. Never print or log the key.
3. Tests and CI still use saved samples (CI has no key). Save real responses as samples only after removing anything personal: replace real people's names, dates of birth and addresses with made-up ones. Real company names and numbers are public records, but keep samples to the small set below.
4. Seeded demo data stays made up.

The paragraph below is the older plan and still applies to the tests. Write them under `apps/companieshouse/tests/samples/` from the shapes in the spec, with made-up companies: an ordinary company, a new company with no accounts filed, one with a resigned director and a former owner, a dissolved company, and an LLP.

## Build

1. `apps/jobs`: the registry, `JobRun`, `manage.py worker`, `manage.py run_job`, the lock, the owner's Jobs page with "Run now", and a failure notice to the owner. As in section 2 of the spec.

2. `apps/companieshouse`: one client class with the five calls, sign-in, pacing under two requests a second, and handling of 401, 404, 429 and 5xx. A fake for tests that serves the samples.

3. "Add from Companies House": search, preview and confirm, as in the spec. Also "Fill in from Companies House" on an existing client that has a company number.

4. Creating and matching contacts from officers and owners. Parse "SURNAME, Forenames". Roles set on the link. Corporate officers and owners are listed on the tab but do not become contacts.

5. The nightly sync job and "Sync now", with change detection and timeline events, as in the spec. Store a snapshot of the last profile, officers, owners and filings as JSON on a `CompanySnapshot` row for each client.

6. The client Companies House tab.

7. The company fields on the client Info tab become read-only once a company number is set, with the "From Companies House" note and the last sync time.

8. Identity verification: the personal code and verified flag on the contact, shown on the Companies House tab beside each director. If the sample or live data carries verification fields, map them.

9. `manage.py ch_check <number>`.

10. Settings, Integrations: Companies House shows "Key present" or "No key", the last sync, and "Run sync now". The key itself is never shown.

11. The bank holiday refresh job. It must fail quietly.

12. Demo data: `seed_demo` attaches snapshots to its made-up companies so the tab has something to show without a key.

## Checks

- `make lint` and `make test` pass.
- Tests exist for: each call against the samples; 429 waits and retries; number padding; name parsing; adding a company creates the client, contacts and links once, and running it again creates nothing new; an existing contact is matched by officer id; the sync writes one event per change and none when nothing changed; a resigned officer is marked, not deleted; a non-active status notifies the manager; a job is not run twice at once; a failing job is recorded and tried again; the Jobs page is owner only.
- Screenshots in `docs/screens/stage-03/`: the search and preview, the Companies House tab, the Jobs page.
- A live check was run in this session against the real API and its result is in the pull request description (which fields were present or empty). The user should not need to run anything themselves.

## Not in this stage

Deadlines and tasks. The sync only stores dates here. Stage 4 turns them into deadlines.
