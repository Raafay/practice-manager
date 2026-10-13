# Build plan

Thirteen stages. Each stage is one Claude Code session and ends in one pull request. Merge a stage before starting the next one, because each stage builds on the one before.

## How to run a stage

1. Start a new cloud session on this repository, on the main branch.
2. Choose Plan mode and paste the prompt below with the stage number filled in.
3. Read the short plan it proposes. Approve it, or correct it in one message.
4. When it finishes, open the pull request, follow its "How to check" steps, then merge.

The prompt:

    Build Stage N. Read docs/STATUS.md and docs/stages/stage-NN.md, then only the specs that stage lists. Propose a short plan first. Then build it, run the stage checks, update docs/STATUS.md, push the branch and open a pull request.

If a session stops before the stage is finished, start a new session on the stage branch and paste:

    Continue Stage N. Read docs/STATUS.md and docs/stages/stage-NN.md. Work out which build items are already done on this branch and finish the rest.

If a merged stage has a fault, start a session on main and paste:

    Fix this in the Stage N work: <what is wrong and where you saw it>. Add a test that would have caught it. Update docs/STATUS.md.

## Stages

| Stage | Name | What exists when it is done |
|---|---|---|
| 1 | Foundation | Sign-in with two-factor, roles, users and teams, activity log, page layout, styleguide, demo data |
| 2 | Clients and contacts | Client list, client page with tabs and panels, contacts, links, documents, notes, search |
| 3 | Companies House and jobs | Add a company by number, officers and owners pulled in, nightly sync, background jobs |
| 4 | Services and deadlines | Service list with fees per client, deadline rules, deadlines per client and across the practice |
| 5 | Tasks, part one | Tasks created from deadlines, table view, filters, saved views, Overview page, task detail |
| 6 | Communications | Templates with merge fields, the message queue, reminder schedules, sending email |
| 7 | Onboarding and AML | Checklist and go-live gate, engagement letters signed on screen, risk assessments, identity checks, HMRC tracker |
| 8 | Tasks, part two | Board, calendar, projects, repeating tasks, workload, notifications |
| 9 | Prospects and proposals | Pipeline board, meetings, proposals sent and accepted online |
| 10 | Portal and requests | Client portal, uploads, forms, the request link, requests inbox |
| 11 | Time, fees, Xero and forecast | Timers and timesheets, fees, Xero invoices, overdue fees, targets and forecast, owner summary |
| 12 | Import and reports | Import from a BrightManager export, reports and exports |
| 13 | Hardening and deployment | Security review, production settings, backups, deployment guide, go-live checklist |

Compliance comes first, as agreed with the practice: stages 1 to 7. Stages 7 and 8 do not depend on each other and can be swapped.

Stages 1 to 10 and 12 need nothing from outside. Stage 3 can be checked live once a free Companies House key exists. Stage 11 needs the owner to connect Xero once the site is deployed. Stage 13 needs a hosting account, the domain and an email-sending account.

No real client data goes in until the Stage 13 go-live checklist has passed.

## After the first version

These are left out on purpose and can each be a later stage:

- A paid identity-check service for AML, behind the interface built in Stage 7.
- A direct HMRC link for agent authorisation requests. HMRC has to approve the software first.
- Text messages through a provider, behind the interface built in Stage 6.
- Emails received from clients filed onto the timeline automatically.
- A direct WhatsApp Business link.
- Raising invoices from the app into Xero.
- A form builder for custom client forms.
- Alerts into Slack or Teams.
