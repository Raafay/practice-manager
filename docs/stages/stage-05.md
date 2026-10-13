# Stage 5: Tasks, part one

Goal: every deadline produces its tasks, and staff can see, filter, edit and complete all work in one table, including work that has nothing to do with a deadline.

Read first: `docs/specs/04-tasks.md` sections 1 to 6, `docs/reference/bright-observed.md` section 4.

## Build

1. `apps/tasks` models: `Task`, `TaskStatus`, `TaskCategory`, `TaskTemplate`, `TaskTemplateStep`, `TaskStep`, `TaskComment`, `TaskStar`. Seed statuses, categories and the templates in section 3. Leave the project and repeating-task links as nullable fields for Stage 8.

2. Task creation from deadlines: one task per active template when a deadline is created, names from the patterns, target dates from the template rule moved to a working day, owner from the template's default. Hook it to the deadline job and register it as a job of its own for catching up. Safe to run twice.

3. The links between deadlines and tasks in section 3: due date follows the deadline, the filing step marks the deadline done, a deadline marked done elsewhere offers to complete its tasks.

4. The Tasks page in table view, as in section 4: columns, alert icon, latest action, editing in place, sorting, grouping with "Add task" rows, quick chips, filter panel, bulk actions, "Load more", and the view state in the address. Add Tasks to the nav.

5. Saved views, with one default per user.

6. The task drawer, as in section 5, including comments with mentions and attached documents.

7. New task from the top bar and the `n` key. My work as the staff home page. The client Tasks tab. A "New task" button on the client header.

8. Settings: Task statuses, Task categories, and a templates page under each service to edit its templates and steps.

9. Events for every task change. Keep the timeline readable: one event per save, with a sentence such as "Sara moved VAT Return Period End 30/09/2026 to In review".

10. Demo data: run the deadline and task jobs for the made-up clients, then add 25 advisory tasks across the seeded categories, some unassigned, some overdue, some with steps ticked and comments.

## Checks

- `make lint` and `make test` pass.
- Tests exist for: one task per deadline and template, and none on a second run; name patterns; target date rules, including "31 October before the due date" and the working-day move; default owner rule; due date follows the deadline; filing step marks the deadline done; each quick chip and each filter; grouping; sort with empty deadlines last; bulk actions; saved views private and shared; in-place edits write events; mentions add followers; a status in use cannot be deleted; every address refuses signed-out users.
- The table stays quick with 2,000 tasks: add a test that the list view runs a bounded number of queries (no query per row).
- Screenshots in `docs/screens/stage-05/`: the table grouped by client, the table with the Fractional chip on, the task drawer, My work.

## Not in this stage

Board, calendar, projects, repeating tasks, workload, notifications and the Overview page. Those are Stage 8. Timers are Stage 11.
