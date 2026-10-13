# Corrections

Read this at the start of every stage. It was written after an independent review of the pack and after the stages were reordered so that compliance comes first. Where it disagrees with a spec or a stage file, this file wins. Bare stage numbers in spec tables may still show the old order. The order in `docs/PLAN.md` is the true one.

## Stage order changes

1. Stage 1 also builds the Notification model, a `notify(user, message, link)` function and a simple bell list. Stage 8 adds the triggers, the email switches and the daily email, sent through the Stage 6 sending path.
2. Stage 1 leaves the client link off ActivityEvent. Stage 2 adds it, keeping the event and a client name label if the client is deleted. Stage 1 deactivates users only. Stages 2 and 5 add the hand-over prompt for clients and tasks.
3. Stage 5 builds the Overview page as the staff home (the My work sections plus deadlines in the next 14 days). Later stages add their panels to it. Stage 6 adds "messages waiting for approval".
4. Stage 6 does not move invitations or a daily email. It adds "Log an email" only. "Log a call" exists from Stage 2.
5. Stage 7 builds the action links described in `01-security-and-users.md` section 5, and the Engagement tab. It creates the onboarding checklist when a client's status becomes `onboarding`. It does not build retention dates.
6. Stage 9 reuses the action links, adds proposals to the Engagement tab, and on acceptance calls the Stage 7 onboarding function and ticks "Proposal accepted".
7. Stage 8 reuses the `n` and `/` keys already bound.

## Rules

8. Deadlines are unique on client service, rule and period key. The period key is the period end as yyyy-mm-dd, or the due date for rules with two dates in one period.
9. Create any period whose due date is on or after the service start date, not only periods ending after it. In the VAT generation test, with today 12/10/2026 and a start of 01/10/2026, the quarter ended 30/09/2026 is created and the one ended 30/06/2026 is not.
10. Reminder-only rules and tax-year rules with no stated horizon are created 60 days before their due date. Tax-year rules are labelled "Tax year 2026/27". Other rules without a label use "Due dd/mm/yyyy".
11. Dates that come from Companies House cannot be changed by hand.
12. A pay day the month does not have means the last day of the month. Weekly, fortnightly and four-weekly pay dates on a non-working day move to the working day before. `add_working_days` accepts a negative number. Annual accounting VAT needs a "VAT year end month" field on the client.
13. If you believe an expected value in a spec is wrong, mark that test as a strict expected failure with the reason, and list it under Known gaps. Do not leave the suite red.
14. Stage 1 reads section 5 of the deadlines spec and the `add_months` and working days tables in section 6.

## Access

15. Practice-wide money figures, the forecast, targets, hourly return and weighted pipeline value need `finance.owner`. One client's own fees, invoices and balance need `fees.view`.
16. Extra rights: `comms.pause`, `clients.status`, `time.edit_all` (owner and manager), `system.view` and `retention.manage` (owner). Everyone sees the unassigned task count. The AML register export needs `data.export`.
17. Sign-in emails (invitations, password resets, portal codes) go straight to the person and are not queued.
18. Retention is built in Stage 2: two settings and two dates on the client, `retain_until` (6 years) and `aml_retain_until` (5 years). Deleting for good is blocked while either runs.
19. A client has at most one main contact, with a warning when there is none. With no manager, notices and default task ownership go to the partner, then the owner.
20. A proposal link lasts until the proposal's valid-until date. Proposals also store the browser and a document fingerprint. Request-link tokens are stored readable, since staff must copy them.

## Smaller points

21. One-off fees are shown separately and never converted to a monthly figure. The go-live gate also needs services and start dates confirmed.
22. Forecast sums use whole pence. Round each service's monthly figure before adding. Clients needed is the gap divided by the average fee, rounded up. Proposals needed is clients needed times decided, divided by won, rounded up. Hide that line if nothing was won. A setup fee counts in the expected start month.
23. A reminder schedule holds a list of offsets and a working-days switch. "20 April" is 15 days after the tax year ends. "The 17th" is 5 days before the PAYE due date.
24. A link merge field whose page is not built yet shows a labelled placeholder and blocks sending.
25. The Content-Security-Policy allows inline styles (`style-src 'self' 'unsafe-inline'`). Scripts stay strict. Stored colours are checked as `#rrggbb`.
26. Vendor the JavaScript with `npm pack htmx.org @alpinejs/csp sortablejs trix`, copy the built files to `static/vendor/`, and record versions in STATUS.md.
27. Production uses the database cache, so the release command runs `createcachetable`.
28. Stage 13: start Docker with `service docker start`. If it will not run, give the user the exact build commands. Unless the prompt names another, document Amazon SES in London as the email provider. The agent cannot change its own model.
29. Use the postcode ZZ1 1ZZ in sample data. Up to six screenshots per stage.
