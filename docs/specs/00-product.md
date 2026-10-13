# 00 Product overview

Read by Stage 1. Later stages do not need it.

## 1. Who uses it

- Staff of the practice. Five people to begin with, no limit on accounts. They sign in to the main app.
- The owner. A staff member with every right, including users, settings, and the finance pages nobody else sees.
- Client main contacts. They sign in to a separate, simpler area called the portal to sign, upload and confirm things.
- Client staff. They never sign in. They send requests through a link.

## 2. Words used in this project

- Client: a business or person the practice acts for. Has a type (limited company, sole trader and so on) and a status.
- Prospect: a client record whose status is "prospect". It has not signed yet.
- Contact: a person. One person can be linked to several clients with different roles.
- Service: something the practice sells, such as Accounts or Payroll. A client takes a set of services, each with a fee.
- Deadline: a date something is due for one client and one period, such as accounts for the year to 31/03/2026.
- Task: a piece of work with an owner. It may come from a deadline, a request, a project, or be added by hand.
- Fractional work: advisory work where the practice acts as a part-time finance director for a client. Operations problems, internal controls, training the client's junior staff. In the data this is the "advisory" kind of task.
- Request: something a client asked for. It sits in an inbox until a staff member turns it into a task.
- Project: a group of tasks for one piece of advisory work.
- Queue: messages waiting to be approved or sent.
- Portal: the client-facing area.
- AML: anti-money-laundering. The checks an accountancy practice must do on each client before acting and at intervals after.
- LoE: letter of engagement. The contract between the practice and the client.

## 3. Navigation

Top bar, left to right: Overview, Tasks, Clients, Prospects, Requests, Queued, Time, Reports, Settings. On the right: search box, New (task, client, prospect, request, time entry), timer, notifications bell, user menu. The owner also sees Finance.

A nav item appears in the stage that builds it. Do not show dead links.

| Item | What it opens | Stage |
|---|---|---|
| Overview | My work today, deadlines this week, things waiting on me. Extra owner panels later. | 1 (placeholder), 6 |
| Tasks | The task pool in table, board or calendar view. Also Projects and Workload. | 5, 6 |
| Clients | The client list. A client opens to a page with tabs. | 2 |
| Prospects | The sales pipeline. | 8 |
| Requests | Inbox of client requests. Badge shows new ones. | 10 |
| Queued | Messages waiting for approval. Badge shows how many. | 7 |
| Time | My timesheet and timers. | 11 |
| Reports | Deadlines, AML register, time, pipeline, exports. | 4 onward |
| Finance | Fees, Xero, targets and forecast. Owner only. | 11 |
| Settings | Practice details, users, services, templates, statuses, stages, integrations. | 1 onward |

## 4. Principles

1. Everything about a client is on that client's page.
2. One pool of tasks. Compliance work and fractional work sit side by side and filter apart with one click.
3. The app drafts and people approve. Nothing reaches a client by surprise.
4. Dates are shown with where they came from: "From Companies House" or "Calculated: 12 months after the period ends".
5. Every action leaves a record of who did it and when.
6. Sensible defaults everywhere, all of them editable in Settings by the owner or a manager.
7. Fast to use all day: dense lists, inline editing, keyboard shortcuts, no page reload for small changes.

## 5. Look and feel

- Structure follows BrightManager so staff feel at home: top navigation, a record header with action buttons, a strip of tabs, an Info tab with folding panels on the left and a services panel with switches and fee boxes on the right.
- The design is our own. Neutral greys, one accent colour that the practice can set, green for done or on, amber for due soon, red for overdue.
- System fonts. No web fonts.
- Icons from Heroicons (MIT licence), inline SVG through a template tag.
- Light theme only in the first version.
- Works on a laptop screen first. Usable on a phone for looking things up, logging a request and ticking a task. The portal must work well on a phone.

Stage 1 builds a `/styleguide/` page with every component: buttons, badges, tabs, folding panels, tables, forms, switches, drawers, modals, toasts, empty states, avatars with initials.

## 6. Not in the first version

See the list at the end of `docs/PLAN.md`.
