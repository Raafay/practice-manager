# 07 Communications

Read by Stage 6.

BrightManager chases clients automatically by email and text and holds messages in a "Queued" list that staff edit and approve. This part does the same, with one firm rule: nothing reaches a client unless a person approved it or the owner has switched that template to automatic.

## 1. Templates

MessageTemplate: key (a fixed name for system templates), name, channel (email, text message, letter), subject, body (rich text for email and letters, plain text for texts), group (records request, reminder, deadline, proposal, onboarding, fees, general), send mode (`hold` for approval, or `auto`), active, system (cannot be deleted).

Edited in Settings with the Trix editor and a list of merge fields to click in. A preview renders the template for a sample client.

Body HTML is cleaned with nh3 when saved. A plain-text version is made for every email.

## 2. Merge fields

Written as `{{ client.name }}`. Rendered by a small renderer in `apps/comms` that only swaps known names from a fixed list. Do not run user-written templates through the Django template engine.

An unknown field shows as a highlighted warning in the preview and blocks sending.

| Field | Gives |
|---|---|
| practice.name, practice.phone, practice.email, practice.address | From practice settings |
| user.name, user.first_name, user.job_title, user.signature | The sender or approver |
| client.name, client.trading_name, client.ref, client.company_number, client.year_end | The client |
| contact.first_name, contact.last_name, contact.full_name | The person it goes to |
| deadline.label, deadline.due_date, deadline.period_end | The deadline that triggered the message |
| task.title, task.target_date | The related task |
| services_list | The client's services as a list |
| monthly_fee, setup_fee | Money, formatted as pounds |
| proposal_link, sign_link, portal_link, upload_link, request_link | Buttons with the right link |
| cs01_data | A block listing what Companies House holds, for the client to confirm |
| outstanding_invoices | A block of overdue invoices (Stage 11) |
| today | Today's date |

The `cs01_data` block, built from the last Companies House sync: registered office address, SIC codes, each current officer with role and appointment date, each person with significant control with the nature of control, and the statement date. It ends with a line asking the client to confirm shareholders and share capital, because the Companies House feed does not list shareholders.

## 3. The queue

QueuedMessage: channel, template, client, contact, to, cc, bcc, subject, HTML body, text body, attachments (documents), state (draft, needs approval, approved, sending, sent, failed, cancelled), created by (a user or the system), reason (a sentence saying what triggered it), related task and deadline, approved by, approved at, send after, sent at, provider message id, error, delivery state (delivered, bounced, complained), duplicate key (unique).

The Queued page:

- Messages needing approval first, then failed, then recent sent.
- Filters by template, client, manager and state. The nav shows a count of those needing approval.
- Opening a message shows: send from, to, subject and the body in an editor. Buttons: Approve and send, Save, Cancel message.
- Tick several and approve them together.
- A message with no address is flagged "No email address" and cannot be approved.
- A switch at the top, "Pause all automatic sending", for the owner and managers. While it is on, a banner shows on every staff page and nothing leaves, approved or not.

Sending:

- A job picks up approved messages whose "send after" time has passed, one at a time, and marks each sent or failed.
- From: the practice's sending address with the staff member's name. Reply-To: that staff member's email. Bcc: the practice address if the setting is on.
- Email goes through Django's email system with django-anymail. Development and tests use the console and in-memory backends. The provider is chosen in Stage 13 by setting `EMAIL_PROVIDER`.
- Every sent or failed message writes a timeline event on the client. A failure notifies whoever approved it.
- Delivery reports from the provider (delivered, bounced) update the message. The webhook is wired up in Stage 13.

Never send to a client whose status is former or lost, or who has "do not send automatic messages" on. Hand-written messages to such a client show a warning first.

## 4. Reminder schedules

ReminderSchedule: template, the deadline rule or task template it belongs to, trigger (days before the deadline, days before the target date, days after the period ends, when a named step is ticked), offset in days, repeat every so many days, maximum repeats, stops when a step flagged "stops reminders" is ticked, recipients (the main contact and contacts marked "receives reminders"), active.

A job creates queued messages from schedules. The duplicate key, for example `schedule:12:task:345:repeat:2`, makes it safe to run twice.

Seed these schedules, all inactive, with fresh starter wording:

| Schedule | When | Repeats | Stops when |
|---|---|---|---|
| Accounts records request | 7 days after the year end | every 21 days, 4 times | Records received |
| Confirmation statement details | 28 days before the statement date | every 7 days, 3 times | Client confirmed |
| VAT records request | 5 days after the period ends | every 5 days, 3 times | Records received |
| Self assessment records request | 20 April | every 30 days, 6 times | Records received |
| Payroll changes request | 5 working days before pay day | none | Changes received |
| Corporation tax payment reminder | 30 days and 7 days before the payment date | none | |
| Self assessment payment reminder | 14 days before 31 January and 31 July | none | |
| PAYE payment reminder | the 17th of each month | none | |

The owner switches a schedule on in Settings and chooses whether its template holds for approval or sends automatically.

## 5. Writing to one client

"Send email" on the client page opens a compose window: to (pick from the client's contacts), cc, bcc, template (optional), subject, body, attachments (from Documents or a new upload), signature (mine, or none).

- "Send now" creates a QueuedMessage that is already approved.
- "Save to queue" leaves it needing approval.

Each staff user has one signature, edited on their profile.

"Log an email" and "Log a call" on the timeline record contact that happened outside the app: date, who, summary.

## 6. Writing to many clients

From a filtered client list: "Email these clients", choose a template, see how many will receive it and who will be skipped and why. It creates one queued message per client, all needing approval.

## 7. Text messages

Build a small `SmsBackend` interface with `send(to, text)` and a console backend. Templates and schedules can use the text channel. The "Send SMS" button and text schedules are hidden unless a provider is configured. No provider is included in the first version.

## 8. Letters

A letter template renders to PDF with WeasyPrint on the practice letterhead (logo, name, address from settings) and is saved to Documents. Used for clearance letters in Stage 7.

## 9. Not in the first version

Emails received from clients are not filed automatically. Staff log them by hand.

## 10. Tests

- The renderer: every listed field, an unknown field blocks sending, and no template tags are executed.
- The queue: states, approval rights, bulk approve, the pause switch stops sending.
- Schedules: created once, repeated on time, stopped by the step, skipped for former clients and for "do not send".
- Nothing is sent in tests except to the in-memory outbox.
- HTML is cleaned: a script tag in a template body does not survive.
