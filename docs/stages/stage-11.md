# Stage 11: Time, fees, Xero and forecast

Goal: staff log time, the owner sees fees and what Xero says was invoiced and paid, sets a target, and gets a plain-English forecast of how far off it is.

Read first: `docs/specs/09-time-fees-forecast.md`, `docs/specs/10-integrations.md` section 3.

Cloud sessions cannot reach Xero. Build against sample responses under `apps/finance/tests/samples/`, written from the shapes in the spec: contacts, invoices in every state, a credit note, a second page of invoices, and a 429 response.

## Build

1. Time, section 1: `TimeEntry`, the timer in the top bar, start from a task row and the drawer, "Log time" on the client page, the weekly timesheet, the client Time tab, time in the task drawer, hours in Workload. Add Time to the nav.

2. Fees page and hourly return, section 2. Add Finance to the nav for users with `finance.owner` only.

3. Xero connection: the OAuth flow, tokens encrypted, refresh inside a lock, Settings, Integrations with connect, disconnect, last sync and "Sync now". One client class, and a fake for tests.

4. Xero sync job: contacts, sales invoices and credit notes, changed-since, paging, limits. Local `XeroContact`, `XeroInvoice`, `XeroCreditNote` and a sync log.

5. The matching screen, and "Send to Xero" on the client page.

6. The client "Fees and invoices" tab. The not-invoiced, check-fee and overdue lists under Finance. Section 3.

7. Chasing overdue fees: the three starter templates, the `outstanding_invoices` merge block, "Draft chase emails", and the approval right.

8. Targets page, section 4.

9. Forecast page, section 5: the monthly table, a simple chart drawn as inline SVG on the server (no chart library), actuals for past months, and the feedback lines. Put the sums in plain functions in `apps/finance/forecast.py`.

10. The owner summary, section 7: the page, the weekly email job, the day and time settings, and the owner-only Overview panels.

11. Demo data: time entries for the last three months, a made-up Xero data set loaded from the samples so every Finance page has figures without a connection, and targets for the next twelve months.

## Checks

- `make lint` and `make test` pass.
- The worked example in section 6 of the spec is a test, with every figure in the results table checked exactly.
- Every other test in section 8 exists.
- Also: token refresh rotates and survives two calls at once; a broken connection shows the last good sync and notifies the owner; matching suggestions; the chase drafts always need approval and need the right; the summary email goes only to owners.
- A test walks every Finance address as a manager and as staff and expects 403, and checks that no figure from the Finance pages appears in any page those users can open.
- Screenshots in `docs/screens/stage-11/`: the timesheet, the Fees page, a client's Fees and invoices tab, the Forecast page, the owner summary.
- In the pull request, tell the user the steps to register a Xero app and where the two keys go. The live connection can only be made once the site is deployed, or on a laptop with the redirect address set to localhost.

## Not in this stage

Creating invoices in Xero. Payment collection.
