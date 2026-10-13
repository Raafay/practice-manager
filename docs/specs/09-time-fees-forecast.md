# 09 Time, fees, Xero figures and the forecast

Read by Stage 11, with the Xero section of `10-integrations.md`.

The owner sets an income target and wants the app to say how far off it is and what would close the gap. Everything on the Finance pages needs `finance.owner`. Check it in the view, in the template and in any export.

## 1. Time

TimeEntry: user, client (empty for internal time), task (optional), service (optional), date, minutes, note, billable (yes by default), started at and ended at when it came from a timer.

- One running timer per user, shown in the top bar with the task or client and a stop button. Starting a second timer stops the first.
- A timer starts from a task row, the task drawer, or "Log time" on a client page. Stopping it saves an entry.
- The Time page is a weekly timesheet: rows for client and task, columns for the days, quick typing in hours and minutes, daily and weekly totals against the user's weekly hours.
- Users edit their own entries. Managers and the owner edit anyone's.
- The client Time tab lists entries with totals by month, by service and by person.
- The task drawer shows time logged against the estimate.
- Workload (Stage 8) now also shows hours logged this week.

## 2. Fees

A client's monthly fee is the total monthly equivalent of its `active` services (see `03-services-and-deadlines.md` section 2).

Finance, Fees page:

- Total monthly recurring fees now, with a split by service, by manager and by client type.
- Changes this month and last month, from FeeChange rows: new, increased, reduced, ended.
- Every live client with its monthly fee, sortable.

Hourly return, same page: for each client, fees over the last 3 or 12 months divided by hours logged in the same months. Lowest first. Clients below the target hourly rate (a setting) are flagged. Clients with no time logged are listed apart.

## 3. Xero

How the connection and sync work is in `10-integrations.md`. What the app does with the data:

- Matching screen: Xero contacts beside app clients, with suggested matches by name. The owner confirms each. "Send to Xero" on a client creates the contact there and links it.
- Client "Fees and invoices" tab: agreed fees by service, then that client's invoices from Xero (number, date, due date, net, VAT, total, amount due, state), with totals invoiced in the last 12 months, outstanding and overdue. Invoices need `fees.view`.
- Not invoiced: live clients with a monthly fee and no invoice dated in the current month, once the 10th has passed (a setting).
- Check fee: invoices in the current month whose net total differs from the agreed monthly fee by more than £1.
- Overdue: unpaid invoices past their due date, grouped by client, with days overdue.

Chasing overdue fees: "Draft chase emails" creates one queued message per client using a template chosen by the oldest invoice's age (7 days, 14 days, 30 days or more), with the `outstanding_invoices` block. These always wait for approval and need `comms.approve_fees`. Seed the three templates with fresh starter wording.

"Invoiced" in a month means the net amount of sales invoices dated in that month whose state is authorised or paid, less credit notes dated in that month.

## 4. Targets

Target: month, amount. The amount is the monthly recurring income the owner wants in that month.

Finance, Targets page: twelve months at a time. Quick fill: a yearly figure spread evenly, or a start and end figure with a straight line between.

## 5. Forecast

Finance, Forecast page. A table and a chart for the next 12 months, plus the last 6 months of actuals.

For each month:

- Contracted: the total monthly equivalent of services that count in that month, for clients that are live, paused or in onboarding. A service counts in a month if it starts on or before the last day of the month and has not ended before the last day of the month. A `proposed` service of a client in onboarding counts from the client's expected start month. No part-month sums.
- Weighted pipeline: for each open prospect, expected monthly fee times the chance for its stage, counted from its expected start month onward. A prospect with no expected start month is assumed to start 60 days from today (a setting).
- Forecast: contracted plus weighted pipeline.
- Gap: target minus forecast. Positive means short.
- One-off income (setup fees and one-off services) is shown on its own line and is not part of the forecast.
- For past months: invoiced, from Xero, beside what was contracted.

Figures used in the feedback:

- Average new-client fee: the mean monthly fee of clients made live in the last 12 months. If there are none, the mean across all live fee-paying clients. If there are none, hide the lines that use it.
- Win rate: prospects won, divided by won plus lost, among those decided in the last 12 months. Hide the lines that use it if fewer than 5 were decided.

Feedback, written by rules in plain English. Show each line that applies, in this order, for the month the owner picks (next month by default):

1. "You are £X a month short of your target for {month}." or "You are £X a month ahead of your target for {month}."
2. "At your average new-client fee of £A a month, that is N more clients." N is the gap divided by A, rounded up.
3. "At your win rate of W%, that means about P more proposals." P is N divided by the win rate, rounded up.
4. "£V a month of proposals are waiting for an answer. K of them have had no contact for 14 days or more."
5. "£E a month is due to end by {month} from clients leaving or reducing."
6. "N clients return less than £R an hour." (only with time data)
7. "The team logged H hours last month against C hours available." At 90% or more, add: "You are close to full. More work may need more people or higher fees."

## 6. Worked example for the tests

Today is 12/10/2026. Target for November 2026 and December 2026: £3,000 each.

Live clients:

| Client | Service and fee | Monthly equivalent | Note |
|---|---|---|---|
| A | Accounts, £300 monthly | 300.00 | made live 01/03/2026 |
| B | Payroll, £450 monthly | 450.00 | made live 15/06/2026, service ends 30/11/2026 |
| C | Accounts, £1,200 quarterly | 400.00 | live since 2023 |
| D | Self Assessment, £2,400 annual | 200.00 | live since 2022 |

Client E is in onboarding with proposed services of £350 a month, expected start November 2026, and a £150 setup fee.

Open prospects:

| Prospect | Expected fee | Stage and chance | Expected start |
|---|---|---|---|
| F | 500 | Proposal sent, 60% | November 2026 |
| G | 250 | Meeting held, 35% | December 2026 |
| H | 400 | On hold, 5% | none given, so 60 days from today, which is December 2026 |

In the last 12 months 6 prospects were won and 4 lost.

Expected results:

| Figure | November 2026 | December 2026 |
|---|---|---|
| Contracted | 1,700.00 | 1,250.00 |
| Weighted pipeline | 300.00 | 407.50 |
| Forecast | 2,000.00 | 1,657.50 |
| Gap | 1,000.00 | 1,342.50 |
| One-off income | 150.00 | 0.00 |
| Average new-client fee | 375.00 | 375.00 |
| More clients needed | 3 | 4 |
| Win rate | 60% | 60% |
| More proposals needed | 5 | 7 |

Contracted today is 1,350.00. Proposals waiting for an answer: £500 a month.

## 7. Owner summary

A page under Finance and an email, sent Fridays at 15:00 by default (day and time are settings). Written by rules. Sections:

- Deadlines: overdue, and due in the next 14 days, by service.
- Work: tasks completed this week, tasks overdue, by person.
- Requests: received this week, still open, oldest open.
- Sales: new enquiries, stage moves, proposals sent, won and lost, quiet prospects.
- Compliance: onboarding in progress, AML reviews due in 30 days, identity documents expiring, HMRC authorisations expiring.
- Money: recurring fees now, change in the week, invoiced this month against contracted, overdue fees, and the first three feedback lines from the forecast.
- People: hours logged against capacity, by person.

The Overview page gets owner-only panels for the same headline numbers.

## 8. Tests

- The worked example above, every figure.
- Monthly equivalents and rounding.
- A service starting mid-month counts for that month. A service ending mid-month does not.
- "Invoiced" excludes draft, voided and deleted invoices and subtracts credit notes.
- Not invoiced and check fee lists.
- Every Finance address returns 403 for a manager and for staff, and no finance figure appears in pages they can open.
- One running timer per user.
