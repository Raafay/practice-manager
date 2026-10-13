# Stage 10: Portal and requests

Goal: client main contacts can sign in to a simple portal to sign, upload and confirm. Client staff can send requests through a link. Every request lands in one inbox and becomes a task.

Read first: `docs/specs/08-portal-and-requests.md`, `docs/specs/01-security-and-users.md` sections 4 to 6.

These are the pages that face the internet without a staff sign-in in front of them. Write the access tests as you go, not at the end.

## Build

1. Portal sign-in by emailed code with django-allauth, at `/portal/login/`, with the rules in the security spec. Portal session lengths. `PortalRequiredMixin` and the `for_portal_user` manager methods on every model the portal reads.

2. Inviting a contact, withdrawing access, the portal state on the client header, and the client switcher. Section 1.

3. The portal layout: its own base template, phone first, with the practice's logo, name and accent colour.

4. Portal pages: Home, Documents with upload, Requests, Details. Section 2. The "share with portal" switch on staff-side documents now takes effect.

5. `PortalItem` and "Things to do". Section 3. Wire in the kinds that already have pages: signing an engagement letter and viewing a proposal. Build `upload_records` with "That is everything", and `approve_document` using the signing mechanism from Stage 7.

6. Creating portal items from the staff side: from a task ("Ask the client to upload", "Ask the client to approve this document") and automatically when a records-request reminder is queued, with the link in the email through the `upload_link` merge field.

7. The confirmation statement check form. Section 4. Add it to the confirmation statement task, and put its link in the seeded reminder template.

8. The client details form and the staff review screen. Section 5. Ticks the onboarding item.

9. Requests: the `Request` model, the public form at `/r/<token>/` with the bot trap and limits, the token with copy button, QR code and "Replace link" on a new client Requests tab. Section 6.

10. The Requests page, with convert, link, reply, close and spam. "Log a request" in the New menu with "Log and create task". Add Requests to the nav with its count. Add the Overview panel.

11. Turn "Ask a question" on the proposal page into a request.

12. Optional acknowledgement template, off by default.

13. Demo data: two portal users on different clients, open portal items of each kind, a completed confirmation form, and fifteen requests across channels and states, some converted to tasks.

## Checks

- `make lint` and `make test` pass.
- Every test in section 8 of the spec exists.
- A single test walks every portal and public address with a user from another client and expects 404 or a redirect, so a new address cannot be forgotten.
- A test asserts that none of the items in section 7 of the spec (fees, time, notes, comments, risk, other people's details) appears in any portal page for the demo client.
- Screenshots in `docs/screens/stage-10/`: portal home and upload at phone width, the confirmation form, the public request form, the Requests page, the convert-to-task window.

## Not in this stage

Receiving requests by email or straight from WhatsApp. A form builder.
