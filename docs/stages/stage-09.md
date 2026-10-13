# Stage 9: Prospects and proposals

Goal: the practice can see every enquiry, what it is worth and what happens next, send a proposal, and have it accepted online.

Read first: `docs/specs/05-prospects-and-proposals.md`, `docs/specs/01-security-and-users.md` section 5 (links that work without signing in), `docs/reference/bright-observed.md` section 3.

## Build

1. `apps/pipeline` models: `PipelineStage`, `ProspectDetails`, `Meeting`, `Proposal`. Seed the stages. Settings, Pipeline stages.

2. Action links, in `apps/core`: the token model and helpers described in the security spec, with expiry, cancel, single-use action and rate limiting. Stage 7 and Stage 10 reuse this, so keep it general.

3. The Prospects page: board and list, cards, drag between stages, the Lost and Won prompts, column totals, header figures, filters. Add Prospects to the nav.

4. The new prospect form, with "Add from Companies House" for companies.

5. On a prospect's client page: a Sales panel at the top of the Info tab (stage, owner, source, referred by, expected start, next action and date, setup fee), the Services panel working in `proposed` state, and a Meetings list with "Log a meeting". A follow-up creates a sales task.

6. The quiet rule and its job, the "quiet" marker, and a panel on the owner's Overview.

7. Proposals: create from the proposed services, versions, the three display switches, the compose window, sending through the queue, and state changes. A proposals list on a new client tab, Engagement.

8. The proposal page behind an action link: view, accept, ask a question, decline, as in section 4. "Ask a question" stores a note on the timeline and notifies the owner of the prospect. Stage 10 turns these into requests.

9. On accept: the PDF copy to Documents, stage to Won, status to `onboarding`, notifications. Leave a clear function, `on_proposal_accepted(client)`, for Stage 7 to extend.

10. Starter wording for the proposal email and "What happens next", marked as starter text.

11. Demo data: twelve prospects spread across the stages, some quiet, some with meetings, three proposals in different states, two won and three lost in the last year with reasons.

## Checks

- `make lint` and `make test` pass.
- Every test in section 6 of the spec exists.
- Also: fees on cards and totals are absent for a user without `fees.view`; dragging to Lost without a reason is refused; a new version withdraws the old one; the proposal page shows nothing about any other client and works without signing in; a cancelled or expired link shows a plain message.
- Screenshots in `docs/screens/stage-09/`: the pipeline board, a prospect's Info tab, the compose window, the proposal page on a phone-width screen.

## Not in this stage

The onboarding checklist and engagement letter (Stage 7). The forecast (Stage 11).
