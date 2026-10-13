# Decisions and defaults

Part 1 is settled. Part 2 lists points only the practice owner can confirm. Each has a default, and the build uses the default until it is changed. Nothing in Part 2 blocks a stage.

## Part 1: settled

Product

1. The app is for one practice. One installation has one practice and one database. If it is ever sold, each firm gets its own copy.
2. Staff accounts are unlimited. The owner adds and removes people and sets what each role may do.
3. All staff see all clients and all tasks. Each task shows its owner. Targets, forecast and Xero totals are for the owner only.
4. A prospect is a client record with the status "prospect". Converting it changes the status. Nothing is copied.
5. There is one task table for all work. A task has a kind (compliance, advisory, request, onboarding, sales, internal) and a category the practice can edit. "Fractional" work is the advisory kind.
6. Deadlines are stored separately from tasks. A deadline is a date that exists whether or not anyone has planned the work. Tasks link to deadlines.
7. For anything registered at Companies House, Companies House dates are used as given. The app does not calculate its own version of those dates.
8. A client cannot be made live until the engagement letter is signed, the client details are in, identity is verified and the risk assessment is approved. The owner can override with a written reason, which is logged.
9. Fees are a fixed amount per service, usually monthly, stored without VAT. Quarterly, annual and one-off fees are allowed and converted to a monthly figure for totals.
10. The app writes summaries and feedback from rules. There are no AI features inside the app in the first version, so there is no running AI cost and no client data goes to an AI service.

Messages

11. Every message to a client goes through the queue. A template either waits for approval or sends by itself. Every seeded template and schedule starts switched off or waiting for approval.
12. Email only at launch. Text messages are built behind an interface and stay off until a provider is chosen.
13. Client staff do not sign in. They use a request link. Their requests land in an inbox and a team member turns each one into a task. WhatsApp and phone requests are logged by hand.

Compliance

14. AML checks are recorded by hand in the first version: who was checked, how, by whom and when, with the documents. A paid checking service can be plugged in later.
15. HMRC agent authorisations are tracked by hand: requested, code received, submitted, authorised.
16. Engagement letters and proposals are signed with a typed name. The app records who signed, when, from which address, and a fingerprint of the document.
17. Reports of suspicious activity are not kept in this app. The practice handles them outside it.
18. Records are never deleted automatically. The app lists what has passed its retention date and the owner decides.

Money

19. Invoices are raised in Xero. The app reads invoices and payments from Xero and can create a contact there. It does not create invoices in the first version.

Technology

20. Django 5.2 LTS, PostgreSQL 16, server-rendered pages with HTMX, Alpine.js and Tailwind. See CLAUDE.md.
21. PostgreSQL is used in cloud sessions, tests and production. SQLite is allowed only for a quick look on a laptop, so avoid features that only PostgreSQL has unless a spec asks for one.
22. Staff sign in with email, password and an authenticator app. Two-factor is compulsory for staff. Portal users sign in with a six-digit code sent by email.
23. UK English, Europe/London, dates as dd/mm/yyyy, pounds only, working days are Monday to Friday less England and Wales bank holidays.
24. Hosting is chosen in Stage 13. The app runs as a standard container with a managed PostgreSQL database and a private file bucket, in a UK or EEA region.
25. Demo data only until the Stage 13 go-live checklist has passed.
26. The layout follows BrightManager's structure so staff feel at home. The wording, colours and design are our own.

## Part 2: defaults to confirm with the practice owner

| # | Question | Default used |
|---|---|---|
| 1 | Which services does the practice sell, and what tasks does each create? | The seeded list in `specs/03-services-and-deadlines.md`. All of it can be edited in Settings. |
| 2 | Which columns should a task move through on the board? | To do, In progress, Waiting on client, In review, Done. |
| 3 | What categories should fractional work use? | Operations, Internal controls, Training and coaching, Insurance, Finance systems, Reporting and budgets, Cash flow and funding, HR and payroll queries, Supplier and contract queries, Other. |
| 4 | What are the sales stages and the chance of winning at each? | Enquiry 10%, Meeting booked 20%, Meeting held 35%, Follow-up 45%, Proposal sent 60%, Won 100%, Lost 0%, On hold 5%. |
| 5 | Can all staff see each client's fee? | Yes. It can be switched off per role. |
| 6 | Who approves AML risk assessments? | The owner, and anyone the owner grants that right to. |
| 7 | How often is a client's AML risk reviewed? | High risk every 12 months, medium every 24, low every 36. |
| 8 | How is identity checked? | One of: original seen in person, Post Office certified copy, copy certified by a professional, electronic check. The method is recorded for each person. |
| 9 | Who must be identified for a company? | The main contact, every director, and every owner with more than 25%. Staff can adjust the list with a reason. |
| 10 | Which reminders may send without a person approving them? | None. The owner switches each one to automatic when ready. |
| 11 | Which address do emails come from, and who gets replies? | From the practice's main address. Replies go to the staff member who sent or approved the message. A copy goes to the practice address. |
| 12 | Is the fee one figure per client or built up per service? | Per service, with a total. A single figure can be put on one service line. |
| 13 | When is a fee overdue, and who chases? | When the Xero due date has passed. Chase emails are drafted at 7, 14 and 30 days and always wait for approval by the owner or a manager. |
| 14 | Is the income target monthly or yearly? | A figure for each month. Entering a yearly figure spreads it evenly. |
| 15 | When should the owner summary arrive? | Fridays at 15:00, by email and as a page. |
| 16 | How long are records kept after a client leaves? | AML records 5 years. Everything else 6 years. Both are settings. |
| 17 | How far ahead of a deadline should work be planned to finish? | Accounts 60 days before filing is due. Confirmation statement 7 days. VAT 7 days. Self assessment by 31 October. Payroll 2 working days before pay day. Each is a setting on the task template. |
| 18 | Engagement letter, terms, proposal and clearance letter wording | Placeholder text marked for replacement. The practice supplies its own wording before go-live. |
| 19 | Does the practice want existing BrightManager history brought across, or only current clients and their services? | Current clients, contacts, services and fees only. |

The practice owner should also read the deadline rules table in `specs/03-services-and-deadlines.md` and the risk questions in `specs/06-onboarding-and-aml.md` before go-live. The practice stays responsible for both.
