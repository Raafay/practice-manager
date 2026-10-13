# 04 Tasks

Stage 5 reads sections 1 to 6. Stage 8 reads sections 7 to 12.

The task list is the main reason this app exists. BrightManager shows only compliance tasks in one flat list. Here every kind of work sits in one pool that can be viewed as a table, a board or a calendar, in the spirit of Monday.com and Microsoft Planner.

## 1. Task

Fields:

- title, description (rich text, cleaned)
- client (empty for internal work), related contact (the person at the client it concerns, optional)
- kind: `compliance`, `advisory`, `request`, `onboarding`, `sales`, `internal`
- category (see section 2), service (optional), deadline (optional link), template (optional)
- status (see section 2), cancelled at
- owner (a staff user, or empty for unassigned), reviewer (optional), team (optional), followers
- priority: low, normal, high, urgent
- due date: a hard date, statutory or promised to the client. Target date: when the practice plans to finish. Start date (optional).
- period label, estimate in minutes
- project and section (Stage 8), repeating task it came from (Stage 8)
- position (for ordering on the board)
- source: `generated`, `manual`, `request`, `repeating`, `project_template`
- created by, completed at, completed by

Related tables: TaskStep, TaskComment, TaskStar (a user's starred tasks), and documents attached through the Document model.

"Fractional" in the interface means kind `advisory`.

## 2. Statuses and categories

TaskStatus: name, colour, order, is done, is waiting, is default. Seed: To do (default), In progress, Waiting on client (waiting), In review, Done (done). Cancelling is separate from status and hides the task.

TaskCategory: name, kind it belongs to, colour, order, active. Seed:

- compliance: Accounts, Corporation tax, VAT, Payroll, Self assessment, Company secretarial, Bookkeeping, AML
- advisory: Operations, Internal controls, Training and coaching, Insurance, Finance systems, Reporting and budgets, Cash flow and funding, HR and payroll queries, Supplier and contract queries, Other
- internal: Practice admin
- sales and onboarding: Sales, Onboarding

Both lists are edited in Settings with `settings.manage`. A status or category in use cannot be deleted, only switched off or merged into another.

## 3. Templates, steps and creation from deadlines

TaskTemplate: service, the deadline rule that triggers it, name pattern, category, default owner (client manager, client partner, a named user, or unassigned), target date rule, estimate, steps in order, active.

The target date rule is one of three kinds: a number of days before the due date, a number of days before the corporation tax payment date for the same period, or a fixed day of the year before the due date, such as 31 October.

A step has a name and two optional flags: "stops reminders" and "is the filing step".

When a deadline is created, one task is created for each active template with that service and rule. Unique on deadline and template, so the job is safe to run twice. Target dates move back to a working day.

- If the deadline's due date changes, the task's due date follows and the change is logged.
- Ticking the filing step marks the deadline done, with evidence "Marked filed by {name}".
- When a deadline is marked done from elsewhere, for example by the Companies House sync, its open tasks get a banner offering to complete them.

Seed these templates. The name patterns match what staff know from BrightManager.

| Service | Rule | Name pattern | Target | Steps (filing step marked F, stops reminders marked S) |
|---|---|---|---|---|
| Accounts | ch_accounts | Accounts Preparation Year End {period_end} | 60 days before due | Records requested, Records received (S), Accounts drafted, Sent to client for approval, Approved by client |
| Accounts | ch_accounts | Companies House Submission Year End {period_end} | 30 days before due | Filed at Companies House (F) |
| CT600 Return | ct600 | CT600 Submission Year End {period_end} | 14 days before the payment date | Computation prepared, Sent for approval, Approved, Filed with HMRC (F), Client told the amount and payment date |
| Confirmation Statement | confirmation_statement | Confirmation Statement Period End {period_end} | 7 days before due | Details sent to client, Client confirmed (S), Filed at Companies House (F) |
| VAT Returns | vat_return | VAT Return Period End {period_end} | 7 days before due | Records requested, Records received (S), Return prepared, Approved by client, Filed (F) |
| Payroll | payroll_run | PAYE {period_label} | 2 working days before pay date | Changes received (S), Payroll run, Payslips sent, Submission filed (F) |
| Payroll | payroll_year_end | Payroll Year End {period_label} | 14 days before due | Final submission filed, P60s issued (F) |
| Bookkeeping | periodic | Accounts Bookkeeping Period End {period_end} | on the due date | Records received (S), Posted, Bank reconciled (F) |
| Management Accounts | periodic | Management Accounts Period End {period_end} | on the due date | Prepared, Reviewed, Sent to client (F) |
| CIS | cis_return | CIS Return Month End {period_end} | 3 days before due | Details received (S), Return filed (F), Statements sent |
| P11D | p11d | P11D {period_label} | 14 days before due | Benefits details received (S), Forms prepared, Filed (F) |
| Self Assessment | self_assessment | Self Assessment {period_label} | 31 October before the due date | Records requested, Records received (S), Return prepared, Sent for approval, Approved, Filed (F), Client told the amount and payment dates |
| MTD for Income Tax | mtd_itsa_quarterly | MTD Quarterly Update {period_label} | 7 days before due | Records received (S), Update submitted (F) |
| MTD for Income Tax | mtd_itsa_final | MTD Final Declaration {period_label} | 31 October before the due date | Return prepared, Approved, Filed (F) |
| Partnership Return | partnership_return | Partnership Return {period_label} | 31 October before the due date | Records received (S), Return prepared, Approved, Filed (F) |
| Auto-Enrolment | auto_enrolment_redeclaration | Auto-Enrolment Re-declaration due {due_date} | 30 days before due | Staff assessed, Re-declaration submitted (F) |

Dates in names print as dd/mm/yyyy. Settings has a page per service to edit its templates and steps.

## 4. Table view

The default view of Tasks. One row per task.

Columns: tick box, star, alert icon, task name, client, category, owner (initials in a coloured circle), latest action, status (a coloured pill), target date, deadline (a badge: red if overdue, amber within 14 days, grey otherwise), and row buttons for comment and complete. Stage 11 adds a timer button.

- The alert icon shows when the target date has passed or the deadline is within 7 days and the task is not done.
- Latest action shows the last step ticked, or "No action yet". It is a drop-down of the task's steps, so the next step can be ticked from the list.
- Owner, status and target date are edited in place. Changes save at once without a page reload.
- Default sort: deadline, soonest first, tasks with no deadline last. Any column sorts.
- Group by: none, client, owner, status, category, service, or week due. Groups fold. Each group ends with an "Add task" row that takes its values from the group.
- Quick chips above the table: All, Compliance, Fractional, Requests, Mine, Unassigned, Overdue, This week. Done tasks are hidden unless "Show done" is on.
- Filter panel: owner, client, manager of the client, team, kind, category, service, status, priority, project, starred, date range on target or deadline, text.
- Bulk actions on ticked rows: change owner, change status, change target date, complete, cancel.
- Show 50 rows per group and 200 in all, with "Load more".
- The whole view state lives in the address, so a view can be bookmarked, saved and shared.

SavedView: owner or shared, name, page, the query string, is default. Each user can set one default view for Tasks.

## 5. Task detail

Opens as a drawer from the right over the list, with its own address so a link to a task works.

Shows: title (click to edit), client link, status, owner, reviewer, dates, priority, kind and category, period, description, steps with tick boxes, comments, attached documents, followers, history from the activity log. Stage 11 adds time logged.

Comments are plain text. `@name` notifies that person and adds them as a follower. Status and owner changes appear in the same stream as small system lines.

## 6. Adding tasks, My work, and the client tab

- New task from the top bar or the `n` key: title, client (type to search, optional), kind and category, owner (me by default), target date, due date, description. Opened from a client page, the client is filled in.
- My work is the staff home page until Stage 8 builds the Overview: my tasks in sections Overdue, Today, This week, Later, Waiting on client. Managers and the owner also see a count of unassigned tasks.
- The client Tasks tab is the same table, fixed to that client.

## 7. Board view

The same tasks as cards in columns.

- Columns by status, in order. A switch changes columns to owner, category or client. Dragging a card to another column changes that field. Dragging within a column reorders.
- A card shows: title, client, owner circle, deadline badge, a stripe in the category colour, and step progress such as 2/5.
- Each column shows its count. Columns fold. The Done column shows the last 14 days only.
- The same chips and filters as the table. Clicking a card opens the drawer.
- A failed save puts the card back and shows a message.

## 8. Calendar view

- Month and week layouts.
- Tasks sit on their target date. A switch shows them on their deadline date instead.
- Statutory deadlines also appear as fixed markers that cannot be dragged.
- Dragging a task to another day changes its target date only.
- Clicking a day opens New task with that date.
- A side list holds tasks with no target date.
- Same chips and filters.

## 9. Projects

For advisory work with several steps.

Project: client (optional), name, description, owner, state (planned, active, on hold, done), start, end, budget hours, sections in order. A task belongs to at most one project and one section.

- The project page shows its tasks as a table grouped by section, or as a board, with a progress bar.
- ProjectTemplate: name, sections, and a list of tasks with category, estimate and a day offset from the project start. "New project from template" creates the tasks.
- Seed four templates with sensible task lists: Finance function health check, New starter finance training (12 weeks), Internal controls review, Insurance renewal review.
- Projects are listed under Tasks, Projects.

## 10. Repeating tasks

For regular advisory work that has no statutory deadline.

RepeatingTask: client, title, category, owner, frequency (weekly, fortnightly, monthly, quarterly, annual), first date, days until due, ends on, active. A nightly job creates the next task when its period starts. Examples: a weekly finance catch-up, a monthly board pack.

## 11. Workload

A page under Tasks. One row per staff member, plus Unassigned:

- open tasks, overdue, due this week, due next week
- estimated hours in the next 14 days against capacity (weekly hours times two), as a bar that turns amber over 85% and red over 100%

Clicking a number opens the table filtered to it.

## 12. Notifications and the Overview page

Notification: user, verb, message, link, read at. A bell in the top bar shows the unread count and a list.

Notify a user when: a task is assigned to them, they are mentioned, someone comments on a task they follow, someone else ticks a step on a task they own, a deadline is within 7 days and its task is still in To do.

A daily email at 08:00 on working days lists overdue, due today and due this week. Each user can switch each kind of email off. In-app notices stay on. Email goes through the console backend until Stage 6.

The Overview page replaces My work as the home page: the My work sections, deadlines in the next 14 days for my clients, a "waiting on me" list (reviews and mentions), and placeholders that later stages fill (requests, queued messages, onboarding in progress, AML reviews due).
