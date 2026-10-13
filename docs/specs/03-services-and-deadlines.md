# 03 Services, fees and deadlines

Read by Stage 4. The rules here are correct to the best of our knowledge in October 2026. The practice owner must read section 4 before go-live, because the practice carries the risk if a date is wrong.

## 1. Service catalogue

A Service is something the practice sells. Fields: code, name, kind (compliance or advisory), which client types it applies to, default monthly fee (optional), description for proposals, engagement letter schedule text (used in Stage 7), order, active.

Seed this list. The names of the first eleven match what staff see in BrightManager today.

| Code | Name | Kind | Applies to | Deadline rules |
|---|---|---|---|---|
| accounts | Accounts | compliance | companies, LLPs | ch_accounts |
| ct600 | CT600 Return | compliance | companies | ct600, ct_payment |
| confirmation | Confirmation Statement | compliance | companies, LLPs | confirmation_statement |
| bookkeeping | Bookkeeping | compliance | all | periodic |
| vat | VAT Returns | compliance | all | vat_return |
| payroll | Payroll | compliance | all | payroll_run, paye_payment, payroll_year_end |
| auto_enrolment | Auto-Enrolment | compliance | all | auto_enrolment_redeclaration |
| management_accounts | Management Accounts | compliance | all | periodic |
| cis | CIS | compliance | all | cis_return |
| p11d | P11D | compliance | all | p11d |
| fee_protection | Fee Protection Service | compliance | all | periodic (annual renewal) |
| self_assessment | Self Assessment | compliance | individuals, sole traders | self_assessment, sa_payment |
| mtd_income_tax | MTD for Income Tax | compliance | individuals, sole traders | mtd_itsa_quarterly, mtd_itsa_final |
| partnership_return | Partnership Return | compliance | partnerships | partnership_return |
| registered_office | Registered Office | compliance | companies, LLPs | periodic (annual renewal) |
| fractional_fd | Fractional Finance Director | advisory | all | none, or periodic if the client has a regular meeting |
| training | Training and Coaching | advisory | all | none |
| operations_support | Operations and Controls Support | advisory | all | none |

Advisory services carry a fee like any other. Their work arrives as requests, projects and tasks added by hand (Stages 5, 6 and 10).

Settings has a Services page to add, edit, reorder and switch off services. Needs `settings.manage`.

## 2. Client services and fees

ClientService: client, service, state (`proposed`, `active`, `ended`), fee amount, fee frequency (`monthly`, `quarterly`, `annual`, `one_off`), starts on, ends on, settings (JSON for anything service-specific), notes. One open row per client and service.

Monthly equivalent, rounded half up to pence: monthly as given, quarterly divided by 3, annual divided by 12, one-off counts as nothing recurring and is shown separately.

Every change to a fee writes a FeeChange row: client service, old amount, new amount, old frequency, new frequency, effective on, changed by, reason. Stage 11 uses this history.

The Services panel on the client Info tab:

- One row for each active catalogue service that applies to the client type: a switch, a fee box, a frequency drop-down (monthly by default).
- The total monthly equivalent at the bottom. Fees show only to users with `fees.view`.
- Switching a service on for an active client sets state `active` and starts on today, which can be changed. For a prospect or a client in onboarding it sets state `proposed`.
- Switching off asks for an end date and sets state `ended`. Open deadlines for periods after that date become "not required".
- Services with their own settings open a small form when switched on: VAT (frequency, stagger), Payroll (frequency, pay day rule, first pay date), Bookkeeping and Management Accounts (frequency), renewals (renewal date). Where the client record already holds the value, use it.

## 3. How deadlines work

Deadline: client, client service, rule, period key, label, period start, period end, due date, original due date, source (`companies_house`, `calculated`, `manual`), source note, status (`open`, `done`, `not_required`), done on, done by, done note, evidence, override reason. Unique on client, rule and period key.

- Deadlines are created only for services the client takes, in state `active`. The exception is onboarding: when a client is made live, deadlines are created straight away.
- Shown state is worked out, not stored: overdue (open and past due), due soon (within 14 days), upcoming.
- The source note is shown beside every date, for example "From Companies House" or "Calculated: 7th of the second month after the period ends".
- Staff can mark a deadline done (date and note), mark it not required (reason), reopen it, or change its due date (reason needed, original date kept, shown as "changed by hand").
- A generation job runs every night and whenever a client's dates or services change. It is safe to run twice.
- Only periods ending on or after the service start date are created, so a new client does not get years of history. Rules 1 to 4 are the exception: the current open obligation is always created.
- When a client becomes paused or former, the job stops creating deadlines. Open ones stay until staff mark them.

Each rule is a plain function in `apps/services/rules/`. It takes the dates it needs and today's date, and returns periods. It does not touch the database, so it can be tested with a table of cases.

## 4. The rules

How far ahead a period is created is given for each rule as "created".

1. `ch_accounts` (Accounts). Applies to clients with a company number once Companies House data is present.
   - Period end is Companies House `next_made_up_to`. Period start is the day after `last_accounts.made_up_to`, or the incorporation date for a first period.
   - Due date is Companies House `next_due`, used exactly as given.
   - One open deadline per client. Created as soon as Companies House data arrives.
   - On each sync: if the due date changed, update it. If the period end changed with no filing (the year end was moved), update the open deadline in place and log it. If `last_accounts.made_up_to` is on or after the open period end, mark the deadline done with the evidence "Shown as filed at Companies House, seen dd/mm/yyyy" and create the next one.
   - Label: "Year end dd/mm/yyyy".

2. `ct600` (CT600 Return). Follows the accounts period from rule 1 and is created at the same time.
   - If the accounts period is 12 months or less, there is one corporation tax period, the same as the accounts period.
   - If it is longer, there are two: the first 12 months, and the rest.
   - The return is due 12 months after the end of the accounts period. For a long period, both returns are due on that same date. (Confirm the long-period case with the practice.)
   - Also create one for the previous accounts period if its due date is today or later. The accounts may be filed while the tax return is not.
   - Marked done by staff only. Label: "Period ended dd/mm/yyyy".

3. `ct_payment` (CT600 Return). One per corporation tax period. A reminder date with no task by default.
   - Due date follows HMRC's manual, CTM01800. If the period ends on the last day of a month, payment is due on the first day of the tenth month after. Otherwise it is due the day after the same day number in the ninth month after. If that month has no such day, it is due on the first day of the tenth month.
   - Companies that pay by instalments are out of scope. A client-service note field covers them.

4. `confirmation_statement` (Confirmation Statement).
   - Period end is Companies House `confirmation_statement.next_made_up_to`. Due date is `next_due`, which is 14 days later. If `next_due` is missing, add 14 days.
   - One open deadline. Marked done when `last_made_up_to` is on or after the period end.
   - Label: "Period end dd/mm/yyyy".

5. `vat_return` (VAT Returns). From the client's VAT settings.
   - Quarterly: quarters end on the last day of the months in the client's stagger. Monthly: every calendar month.
   - Due one month and seven days after the period ends. For a period ending on the last day of a month, that is the 7th of the second month after.
   - Annual accounting scheme: one period a year, due two months after it ends.
   - Created 30 days before the period ends. Label: "Quarter ended dd/mm/yyyy" or "Month ended dd/mm/yyyy".

6. `payroll_run` (Payroll). One per pay date.
   - Monthly: the pay day rule gives the date. If it is not a working day, use the working day before.
   - Weekly, fortnightly and four-weekly: step from the first pay date.
   - Due date is the pay date. Real Time Information must be sent on or before pay day.
   - Created 31 days ahead. Label for monthly: "October 2026". Otherwise "Pay date dd/mm/yyyy".

7. `paye_payment` (Payroll). A reminder date with no task by default.
   - The tax month runs from the 6th to the 5th. Payment is due on the 22nd of the month in which the tax month ends, when paid electronically.
   - If the 22nd is not a working day, also show "pay by" the working day before.
   - Small employers who pay quarterly (a client-service setting): due 22 July, 22 October, 22 January, 22 April.

8. `payroll_year_end` (Payroll). One per tax year, due 31 May, for giving P60s to employees. Label: "Tax year 2026/27".

9. `p11d` (P11D). One per tax year. Forms due 6 July after the tax year. A second reminder date of 22 July for Class 1A National Insurance.
   - Payrolling of benefits becomes compulsory in stages from 6 April 2027, which reduces P11D work from the 2027/28 tax year. Keep this as a service the practice switches on per client. (Confirm with the practice.)

10. `cis_return` (CIS). Monthly. The tax month ends on the 5th and the return is due on the 19th of the same month. Created 31 days ahead. Label: "Month ended 05/mm/yyyy".

11. `self_assessment` (Self Assessment). One per tax year. The tax year ends on 5 April. The online return is due 31 January after. Created on 6 April when the tax year has ended. Label: "Tax year 2025/26". Skipped for a tax year in which the client is in Making Tax Digital for Income Tax.

12. `sa_payment` (Self Assessment). Reminder dates with no task by default: 31 January, and 31 July if the client makes payments on account.

13. `mtd_itsa_quarterly` (MTD for Income Tax). Only for tax years from the client's start year.
    - Quarters end 5 July, 5 October, 5 January, 5 April. Updates are due 7 August, 7 November, 7 February, 7 May.
    - A client using calendar quarters has the same due dates. Only the label changes.
    - Created 30 days before the quarter ends. Label: "Q1 2026/27".
    - Who is in scope: qualifying income over £50,000 from 6 April 2026, over £30,000 from 6 April 2027, over £20,000 from 6 April 2028. The app does not decide this. Staff set the start year on the client.

14. `mtd_itsa_final` (MTD for Income Tax). One per tax year, due 31 January after the tax year. Replaces rule 11 for that year.

15. `partnership_return` (Partnership Return). One per tax year, due 31 January after the tax year.

16. `auto_enrolment_redeclaration` (Auto-Enrolment). Every three years.
    - Anchor: the last re-enrolment date if set, otherwise the duties start date. The anniversary is three years after the anchor.
    - The re-enrolment window runs from three months before the anniversary to three months after.
    - The re-declaration is due within five calendar months of the anniversary. Use the anniversary plus five months, less one day. (Confirm the exact day with the practice.)
    - Created 180 days before the due date.

17. `periodic` (Bookkeeping, Management Accounts, renewals, any regular advisory meeting). From the client-service settings: frequency (monthly, quarterly, annual), the month and day a period ends, and how many days after the period end it is due. Defaults: bookkeeping 14 days, management accounts 20 days, renewals 0. Created 31 days ahead. Label: "Period ended dd/mm/yyyy" or "Renewal dd/mm/yyyy".

## 5. Date helpers

In `apps/core/dates.py`, each with tests:

- `add_months(d, n)`: if `d` is the last day of its month, the answer is the last day of the target month. Otherwise the same day number, pulled back to the month's last day if needed.
- `ct_payment_due(period_end)`: the rule in section 4, rule 3.
- `vat_due(period_end)`: if `period_end` is a month end, the 7th of the second month after. Otherwise `add_months(period_end, 1)` plus 7 days.
- `tax_year_of(d)` and `tax_year_label(end)`: the tax year ends on 5 April. Label as "2025/26".
- `is_working_day(d)`, `previous_working_day(d)`, `add_working_days(d, n)`: Monday to Friday, less bank holidays.

Bank holidays for England and Wales, bundled in `apps/core/data/bank_holidays.json` (Stage 3 adds a job that refreshes them from gov.uk in production):

- 2026: 1 January, 3 April, 6 April, 4 May, 25 May, 31 August, 25 December, 28 December.
- 2027: 1 January, 26 March, 29 March, 3 May, 31 May, 30 August, 27 December, 28 December.
- 2028: 3 January, 14 April, 17 April, 1 May, 29 May, 28 August, 25 December, 26 December.

Statutory due dates are shown as they are, even on a weekend. Only planning dates (task target dates, pay dates, "pay by" hints) move to a working day.

## 6. Test cases

Turn each table into a parametrised test. Do not change an expected value to make a test pass.

Corporation tax payment (the first eight rows are HMRC's own examples):

| Period ends | Payment due |
|---|---|
| 31/03/1999 | 01/01/2000 |
| 01/07/1999 | 02/04/2000 |
| 28/02/2000 | 29/11/2000 |
| 29/02/2000 | 01/12/2000 |
| 28/05/2000 | 01/03/2001 |
| 29/05/2000 | 01/03/2001 |
| 30/05/2000 | 01/03/2001 |
| 31/05/2000 | 01/03/2001 |
| 31/03/2026 | 01/01/2027 |
| 28/02/2026 | 01/12/2026 |
| 30/06/2026 | 01/04/2027 |
| 30/09/2026 | 01/07/2027 |
| 15/08/2026 | 16/05/2027 |
| 29/02/2028 | 01/12/2028 |

CT600 return due (12 months after the accounts period ends):

| Accounts period ends | Return due |
|---|---|
| 31/03/2026 | 31/03/2027 |
| 28/02/2026 | 28/02/2027 |
| 30/06/2026 | 30/06/2027 |
| 29/02/2028 | 28/02/2029 |

Long accounts period: starts 01/01/2025, ends 31/03/2026 (15 months). Two tax periods: 01/01/2025 to 31/12/2025 and 01/01/2026 to 31/03/2026. Both returns due 31/03/2027. Payments due 01/10/2026 and 01/01/2027.

`add_months` with the month-end rule:

| Date | Months | Result |
|---|---|---|
| 31/03/2026 | 9 | 31/12/2026 |
| 28/02/2026 | 9 | 30/11/2026 |
| 30/04/2026 | 9 | 31/01/2027 |
| 30/09/2026 | 9 | 30/06/2027 |
| 31/05/2026 | 9 | 28/02/2027 |
| 15/08/2026 | 9 | 15/05/2027 |
| 29/02/2028 | 12 | 28/02/2029 |

VAT:

| Period ends | Due |
|---|---|
| 30/09/2026 | 07/11/2026 |
| 31/10/2026 | 07/12/2026 |
| 30/11/2026 | 07/01/2027 |
| 31/12/2026 | 07/02/2027 |
| 31/01/2027 | 07/03/2027 |
| 28/02/2027 | 07/04/2027 |

Companies House rules (use the dates given, do not calculate):

| Rule | Companies House says | Deadline |
|---|---|---|
| ch_accounts | next_made_up_to 31/03/2026, next_due 31/12/2026 | period end 31/03/2026, due 31/12/2026 |
| confirmation_statement | next_made_up_to 20/10/2026, next_due 03/11/2026 | period end 20/10/2026, due 03/11/2026 |
| confirmation_statement | next_made_up_to 19/10/2026, next_due missing | period end 19/10/2026, due 02/11/2026 |
| ch_accounts | open deadline for 31/03/2026, then last_accounts.made_up_to becomes 31/03/2026 and next_made_up_to 31/03/2027 | first deadline done, new one for 31/03/2027 |

Payroll and PAYE:

| Case | Result |
|---|---|
| Monthly pay on the 25th, October 2026 | 23/10/2026 (the 25th is a Sunday) |
| Monthly pay on the 25th, December 2026 | 24/12/2026 (the 25th is a bank holiday) |
| Monthly pay on the last working day, August 2026 | 28/08/2026 (the 31st is a bank holiday) |
| Monthly pay on the last working day, October 2026 | 30/10/2026 |
| Monthly pay on the last working day, December 2026 | 31/12/2026 |
| PAYE payment for the tax month ending 05/11/2026 | due 22/11/2026, pay by 20/11/2026 |
| CIS return for the tax month ending 05/11/2026 | due 19/11/2026 |

Tax-year rules:

| Rule | Case | Due |
|---|---|---|
| self_assessment | tax year 2025/26 | 31/01/2027 |
| sa_payment | second payment on account for 2026/27 | 31/07/2027 |
| mtd_itsa_quarterly | 2026/27 Q1, Q2, Q3, Q4 | 07/08/2026, 07/11/2026, 07/02/2027, 07/05/2027 |
| mtd_itsa_final | tax year 2026/27 | 31/01/2028 |
| p11d | tax year 2025/26 | 06/07/2026, Class 1A reminder 22/07/2026 |
| payroll_year_end | tax year 2026/27 | 31/05/2027 |

Auto-enrolment:

| Anchor | Anniversary | Window | Re-declaration due |
|---|---|---|---|
| 01/10/2023 | 01/10/2026 | 01/07/2026 to 01/01/2027 | 28/02/2027 |
| 01/07/2023 | 01/07/2026 | 01/04/2026 to 01/10/2026 | 30/11/2026 |
| 01/02/2024 | 01/02/2027 | 01/11/2026 to 01/05/2027 | 30/06/2027 |

Working days:

| Date | Previous working day on or before |
|---|---|
| 07/11/2026 (Saturday) | 06/11/2026 |
| 22/11/2026 (Sunday) | 20/11/2026 |
| 25/12/2026 (bank holiday) | 24/12/2026 |
| 31/08/2026 (bank holiday) | 28/08/2026 |
| 31/12/2026 (Thursday) | 31/12/2026 |

Generation:

- Running the job twice creates nothing new the second time.
- A client with no Accounts service gets no `ch_accounts` deadline even though Companies House dates are held.
- Switching a service off with an end date marks later open deadlines "not required".
- A service starting on 01/10/2026 with quarterly VAT on stagger 1 gets a first deadline for the quarter ending 31/12/2026, not for 30/09/2026.

## 7. Screens

- Settings, Services: the catalogue.
- Client, Info tab: the Services panel in section 2.
- Client, Deadlines tab: open deadlines by due date, then a folded list of past ones. Each row: label, service, due date with its source note, state badge, and the actions in section 3.
- Reports, Deadlines: every open deadline in the practice. Filters: due within 14, 30, 60 or 90 days, overdue, service, manager, client. Export to CSV with `data.export`.
- Client list: the "next deadline" column and the "has an overdue deadline" filter now work. The monthly fee column works.

## 8. Sources for the rules

- Corporation tax payment date: HMRC Company Taxation Manual, CTM01800.
- Making Tax Digital for Income Tax dates and thresholds: GOV.UK news release of July 2026 on the first quarterly update.
- Auto-enrolment: The Pensions Regulator, "Re-enrolment and re-declaration" guidance for business advisers.
- Filing dates for accounts and confirmation statements are taken from Companies House data, not calculated.
