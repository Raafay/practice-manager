# Stage 8: Tasks, part two

Goal: the same tasks can be worked as a board and a calendar, advisory work can be run as projects and repeating tasks, and people are told when something needs them.

Read first: `docs/specs/04-tasks.md` sections 7 to 12. Skim sections 1 and 4 only if you need a field or filter name.

## Build

1. A view switch on the Tasks page: Table, Board, Calendar. All three share the chips, the filter panel and saved views. A saved view remembers which of the three it was.

2. Board view, as in section 7. Use SortableJS. Save moves with HTMX. Put the card back if the save fails. Keep `position` stable with gaps so a move updates one row.

3. Calendar view, as in section 8. Build the month and week grids on the server. No calendar library.

4. Projects, as in section 9: models, the projects list, the project page with table and board, templates, and the four seeded templates with realistic task lists.

5. Repeating tasks, as in section 10: model, a form reachable from New and from the client Tasks tab, and the job.

6. Workload page, as in section 11.

7. Notifications, as in section 12: model, the bell, the triggers, per-user email switches on the profile page, and the daily email job. Use the console email backend.

8. The Overview page, replacing My work as the home page.

9. Keyboard: `n` new task, `/` search, `g t` tasks, `g c` clients, `?` shows the list. Keep this in one small script.

10. Demo data: two projects from templates at different points of progress, three repeating tasks, and enough spread of owners and dates for the board, calendar and workload to look lived in.

## Checks

- `make lint` and `make test` pass.
- Tests exist for: a board move changes the right field for each column type and writes one event; reordering within a column; the Done column's 14-day window; a calendar move changes the target date and never the due date; deadline markers cannot be moved; a project made from a template has the right tasks and dates; the repeating job creates the next task once per period and stops after the end date; workload numbers for a small set; each notification trigger, and no notice to yourself for your own action; the daily email content and the off switch.
- Screenshots in `docs/screens/stage-08/`: board by status, board by owner, calendar month, a project page, workload, Overview.

## Not in this stage

Timers and hours logged (Stage 11). Requests in the Overview (Stage 10). Sending real email (Stage 6).
