# 05 Prospects and proposals

Read by Stage 9.

BrightManager marks a client as a prospect and onboards it. It has no sales side. This part adds one: where each enquiry stands, what it is worth, what to do next, and what was won or lost.

How the practice sells today: enquiries come by word of mouth or from existing clients. There is a face-to-face meeting. Then either more meetings, or an email with a proposal and the steps to join.

## 1. Data

A prospect is a Client with status `prospect`. Sales details sit in a one-to-one ProspectDetails row:

- stage (see below), owner (staff user)
- source (word of mouth, client referral, accountant referral, website, other), referred by (a client, or free text)
- enquiry date, expected start month
- expected monthly fee by hand (used only until services are ticked)
- next action (text) and next action date
- last activity at (kept up to date by the app)
- one-off setup fee
- won on, lost on, lost reason (price, went elsewhere, no reply, not a fit, timing, other) and a note

PipelineStage: name, order, chance of winning (percent), is open, is won, is lost, colour. Seed: Enquiry 10, Meeting booked 20, Meeting held 35, Follow-up 45, Proposal sent 60, Won 100, Lost 0, On hold 5. Edited in Settings.

Meeting: client, date and time, type (face to face, phone, video), place, staff present, people from the client, notes, outcome, follow-up. Saving a follow-up creates a task of kind `sales` for the owner.

Services wanted are ClientService rows in state `proposed`, each with a proposed fee, using the same Services panel as a live client. The expected monthly fee is their total, or the hand-entered figure if none are ticked.

## 2. Prospects page

Two views of the same list, with the same filters (owner, stage, source, quiet only).

Board: one column per open stage, then Won and Lost showing the last 30 days.

- A card shows: name, main contact, expected monthly fee (with `fees.view`), next action and its date (red when passed), days in this stage, owner circle, and a "quiet" marker.
- Dragging a card changes its stage. Dropping on Lost asks for the reason. Dropping on Won asks to confirm and starts onboarding.
- Each column header shows a count and, with `fees.view`, the total monthly value.

List: one row per prospect with the same facts, sortable.

Header figures, with `fees.view`: open pipeline value per month, weighted value (each fee times its stage's chance), proposals waiting for an answer, win rate over 12 months, average days from enquiry to won.

New prospect form, kept short: name, type, main contact (name, email, phone), source, referred by, services wanted, expected fee, next action and date, notes. Only the name and one way to reach the contact are required. "Add from Companies House" is offered for companies.

## 3. Gone quiet

A prospect is quiet when it is in an open stage other than On hold, and either its next action date has passed or nothing has happened for 14 days (a setting).

Activity that resets the clock: a meeting logged, an email sent, a note added, a proposal sent or viewed, a stage change, a sales task completed.

Quiet prospects show on the owner's Overview and are counted in the forecast feedback (Stage 11).

## 4. Proposal

Proposal: client, version, state (draft, sent, viewed, accepted, declined, expired, withdrawn), lines (a frozen copy of each service: name, description, fee, frequency), monthly total, setup fee, show fee breakdown, show fees including VAT, show VAT wording, valid until (30 days by default), opening text, sent at, sent to, viewed at, decided at, decided by (typed name), decision IP address, decline reason, PDF.

Creating a proposal from a prospect copies the proposed services and fees. Changing the services afterwards makes a new version. Older versions are kept and marked withdrawn.

Fee display:

- Fees are stored without VAT.
- "Show fee breakdown" lists a fee beside each service. Off, it shows the list of services and one monthly charge.
- "Show fees including VAT" multiplies by one plus the VAT rate from practice settings (20% by default) and only applies if the practice is VAT registered.
- "Show VAT wording" adds "+VAT" after amounts shown without VAT.

Sending:

- "Send proposal" opens a compose window with the proposal template filled in: recipient (the main contact), copy to the practice address, subject, the three switches above, an editable message, attachments, signature.
- The message lists the services, the charge, any setup fee, and the steps to become a client, with a button linking to the proposal page.
- Sending creates a QueuedMessage already approved by the sender (see `07-communications.md`) and sets the proposal to sent and the stage to Proposal sent.

Proposal page, reached by an action link (see `01-security-and-users.md` section 5):

- Practice name and logo, greeting, services with descriptions, fees as chosen, setup fee, valid-until date, and "What happens next".
- Accept: type full name, tick "I accept this proposal", submit.
- Ask a question: a text box that creates a request for the owner of the prospect.
- Decline: an optional reason.
- The first open sets viewed at. After a decision the page shows the outcome and nothing else can be done.

On accept:

- The proposal is accepted and a PDF copy with the acceptance details is saved to Documents.
- The stage becomes Won and the client status becomes `onboarding`.
- The proposed services stay `proposed` until the client is made live.
- The owner and the manager are notified. Stage 7 hooks in here to create the onboarding checklist and send the engagement letter.

On decline or expiry: the state changes and the owner is notified. The prospect stays where it is until staff move it to Lost.

## 5. Starter wording

Seed one proposal email template and the "What happens next" text, written fresh. Mark both clearly as starter text for the practice to replace. Do not copy BrightManager's wording.

## 6. Tests

- Weighted pipeline value for a small set of prospects.
- Quiet rule: each condition on its own, and On hold excluded.
- Proposal totals with each combination of the three switches, including a quarterly fee.
- The action link: works once for the decision, expired link refused, wrong token refused, and no other client's data reachable.
- Accepting moves stage and status and leaves services proposed.
