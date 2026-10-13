# Stage 4: Services and deadlines

Goal: each client has its services and fees, and the app knows every date that falls due for every client, with where each date came from.

Read first: `docs/specs/03-services-and-deadlines.md`. This is the part of the app where a mistake costs the practice money, so the test tables in section 6 are not optional.

## Build

1. `apps/services` models: `Service`, `ClientService`, `FeeChange`, `Deadline`. Seed the catalogue from section 1.

2. Settings, Services: list, add, edit, reorder, switch off.

3. The Services panel on the client Info tab, as in section 2: switches, fee boxes, frequency, total, the small settings forms for VAT, Payroll, Bookkeeping, Management Accounts and renewals. Fees respect `fees.view`. Every fee change writes a `FeeChange` row and an event.

4. Date helpers still missing from `apps/core/dates.py`: `ct_payment_due`, `vat_due`, pay-date functions. With the tests from section 6.

5. The rules in `apps/services/rules/`, one module per rule or small family, each a plain function with no database access, registered by name. All seventeen in section 4.

6. The deadline job: for one client or all, work out the periods each active service should have and create what is missing. Follow section 3 for start dates, look-ahead, and what happens when a client is paused or leaves. Register it to run nightly and call it when a client's dates or services change and at the end of a Companies House sync.

7. The Companies House rules update the open deadline in place and mark it done when the filing shows, as in rules 1 and 4.

8. Deadline actions: mark done, mark not required, reopen, change date with a reason. Each writes an event.

9. The client Deadlines tab and the Reports, Deadlines page, as in section 7. Add Reports to the nav.

10. The client list gets the "next deadline" column, the monthly fee column, the service filter and the overdue filter.

11. Demo data: give the made-up clients realistic sets of services, fees, VAT and payroll settings, so the Deadlines report shows a spread of dates, some due soon and a few overdue.

## Checks

- `make lint` and `make test` pass.
- Every table in section 6 exists as a parametrised test with the expected values exactly as written. If a case fails and you believe the spec is wrong, leave the test failing, explain in `docs/STATUS.md` under Known gaps, and say so at the top of the pull request.
- Tests exist for: monthly equivalents and rounding; fee changes logged; fees hidden without the right; the job is safe to run twice; start-date rule; switching a service off; a paused client gets nothing new; Companies House change updates in place; filing detected marks done and creates the next; manual date change keeps the original and needs a reason; the report filters.
- Screenshots in `docs/screens/stage-04/`: the Services panel, a client's Deadlines tab, the Deadlines report.
- In the pull request, list the rules marked "(Confirm ...)" in the spec so the user can put them to the practice owner.

## Not in this stage

Tasks. Reminders to clients. The target dates in `docs/DECISIONS.md` belong to tasks in Stage 5.
