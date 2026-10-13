# 08 Client portal and requests

Read by Stage 10.

Two different things for two different groups:

- The portal is for a client's main contacts. They sign in to sign, upload, confirm and look things up.
- The request link is for a client's staff. They never sign in. They fill in a short form and the request lands in an inbox at the practice.

Sign-in rules, action links and rate limits are in `01-security-and-users.md` sections 4 to 6. Follow them exactly. This is the part of the app that faces the internet without a staff login in front of it.

## 1. Giving a contact portal access

On the client Contacts tab, "Invite to portal" for a contact with an email address. It creates a portal user, switches on portal access for that link, and queues an invitation email with the portal address.

The client header shows the portal state: not invited, invited, active (has signed in).

Staff can withdraw access. A contact linked to several clients sees a switcher.

## 2. Portal pages

Kept simple and built for a phone first. The practice's logo, name and accent colour come from settings.

Home

- "Things to do": open items, each with a button. See section 3.
- Recent documents shared with them.
- Upcoming deadlines for their business: label and date only, nothing internal.

Documents

- Documents the practice has shared with them, and what they have uploaded.
- Upload: choose a category, add a note, pick files. Each file becomes a Document with source `portal`. The manager is notified.

Requests

- Their past requests with state, and "New request".

Details

- What the practice holds: business details and people, read-only.
- "Tell us about a change" opens a request. Clients never edit records directly.

## 3. Things to do

PortalItem: client, contact (empty means any portal user of the client), kind, title, description, linked object, state (open, done, cancelled), due date, completed at, completed by.

Kinds:

- `sign_letter`: sign an engagement letter. Uses the signing page from Stage 7.
- `accept_proposal`: view a proposal. Uses the page from Stage 9.
- `upload_records`: upload what was asked for. Has a "That is everything" button, which ticks the task step flagged "stops reminders" and notifies the task owner.
- `confirm_details`: the confirmation statement check. See section 4.
- `client_details`: the onboarding form. See section 5.
- `approve_document`: read a document and approve it, for accounts or a tax return. Uses the same signing mechanism: tick box, typed name, record kept. The approval is saved as a PDF page attached to the document and ticks the matching task step.

Items are created by staff from a task or a client page, or by the app when a reminder is queued. A reminder email carries a link to its item.

## 4. Confirmation statement check

Replaces "reply to this email with no change".

The form shows what Companies House holds, one section at a time: registered office, directors and secretary, people with significant control, business activity (SIC codes), shareholders and share capital, registered email address. For each section the client chooses "No change" or "There is a change" and describes it.

On submit: the answers are saved, a PDF copy goes to Documents, the task step "Client confirmed" is ticked, and the task owner is notified. Any "change" answer is highlighted.

## 5. Client details form

The onboarding form. Sections depend on client type: the business (trading name, address, start date, what it does), people (names, dates of birth, home addresses, for those who must be identified), tax references, accounting software in use, the previous accountant (for the clearance letter), and confirmation of the services agreed.

- The client can save and come back.
- Fields the practice already holds are shown filled in.
- On submit, staff get a review screen showing each answer beside the current record, with "Apply" per field. Nothing overwrites the record without a staff click.
- Applying everything, or dismissing the rest, ticks the onboarding item "Client details form completed".

## 6. Requests

Request: client (may be empty), contact (may be empty), sender name, sender email, sender phone, channel (form, portal, email, WhatsApp, phone, in person), subject, body, attachments, urgency (normal, urgent), state (new, in progress, answered, closed, spam), received at, logged by, linked task, closing note.

The request link

- Each client has one, at `/r/<token>/`. The client Requests tab shows it with a copy button and a QR code, and "Replace link". Staff can post it in the client's WhatsApp group.
- The page shows the practice name and logo and "Send a request to {practice} about {client name}".
- Fields: your name, your email, phone (optional), what do you need help with, how urgent, up to three files of 10 MB each.
- A hidden field traps simple bots. Rate limits apply.
- After sending: a thank-you page with a reference number. An acknowledgement email is optional and off by default.

Logging by hand

- "Log a request" is in the New menu on every page. Fields: channel, client, who asked, the text (paste from WhatsApp), a screenshot or file.
- "Log and create task" does both in one step, because that is the usual case.

The Requests page

- New requests first, with client, sender, subject, channel and age. The nav shows a count of new ones.
- Opening one offers: convert to a task, link to an existing task, reply by email, close with a note, mark as spam.
- Converting fills in the task: title from the subject, description from the body, kind `request`, a category the staff member picks, owner, and a target date three working days ahead. Attachments carry over as documents. The request becomes "in progress" and is closed when the task is done.
- A request with no client asks the staff member to choose one or leave it as general.

The client Requests tab lists that client's requests.

Overview gets a "New requests" panel.

## 7. What a portal user must never see

Fees, time logged, internal notes, task comments, risk assessments, other contacts' personal details, staff-only documents, or anything from another client.

## 8. Tests

- Sign-in by code: right code, wrong code, expired code, same response for unknown emails.
- For every portal page and every portal object address: a user of another client gets 404.
- A staff account cannot use the portal, and a portal account cannot reach any staff address.
- The request form: creates a request, enforces file rules, the bot trap works, the rate limit works, an old token stops working after "Replace link".
- "That is everything" ticks the right step once.
- The details form never changes a record until staff apply it.
