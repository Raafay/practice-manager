# Stage 6: Communications

Goal: staff can email clients from templates, automatic reminders are drafted into a queue, and nothing goes out without approval unless the owner has said it may.

Read first: `docs/specs/07-communications.md`.

## Build

1. `apps/comms` models: `MessageTemplate`, `QueuedMessage`, `ReminderSchedule`. A signature field on the user profile.

2. The merge-field renderer in section 2, with the full field list. The `cs01_data` block reads the Companies House snapshot from Stage 3. `outstanding_invoices` renders empty until Stage 11.

3. Settings, Templates: list, edit with Trix and click-to-insert merge fields, preview against a chosen client, send mode, active. HTML cleaned with nh3 on save.

4. The Queued page and message editor, as in section 3, with the nav count, bulk approve and the pause switch with its banner.

5. Sending: the job, the From, Reply-To and Bcc rules, the provider setting through django-anymail, console and in-memory backends for development and tests, timeline events, and failure notices. Add the practice settings this needs: sending address, copy-to address on or off.

6. Reminder schedules, as in section 4: the model, the job with duplicate keys, the "stops when" rule, the skip rules for former clients and "do not send". Seed the eight schedules, inactive, and a starter template for each with fresh wording.

7. Settings, Reminders: list of schedules with on and off, timing, repeats, and which template.

8. "Send email" on the client page, as in section 5. "Log an email" and "Log a call" on the timeline.

9. "Email these clients" from the client list, as in section 6.

10. Text messages, as in section 7: the interface, a console backend, the text channel on templates and schedules, and the hidden "Send SMS" button.

11. Letters, as in section 8: a letterhead template and PDF output to Documents.

12. Move the Stage 8 daily email and invitations onto this sending path.

13. Demo data: turn on two schedules in the demo data only, run the job, and leave a dozen messages in the queue in different states.

## Checks

- `make lint` and `make test` pass.
- Every test in section 10 of the spec exists.
- Also: approving needs the right; a message with no address cannot be approved; the pause switch holds approved messages; Reply-To is the approver; a failed send is recorded and can be retried; the bulk send shows who is skipped and why.
- No test sends anything outside the in-memory outbox.
- Screenshots in `docs/screens/stage-06/`: the Queued page, the message editor, a template with its preview, the compose window.

## Not in this stage

Choosing an email provider and DNS set-up (Stage 13). Receiving email. A text message provider.
