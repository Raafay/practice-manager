# Stage 16: Sign-up and billing

Goal: a new firm signs up, gets an empty practice on its own address, pays through Stripe, and is moved to read-only (never deleted) if payment stops.

Read first: `docs/MULTITENANT.md` (Billing).

## Build

1. Public sign-up page on the platform address: firm name, chosen address (`firm.example.com`), owner name and email. Email confirmation, then the practice is created, the owner sets a password and two-factor. Rate limited; no free-text that reaches another practice.
2. Stripe (new dependency `stripe`): Checkout for the subscription, the customer portal for card and cancelling, signed webhooks (`checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`) updating the practice's plan state. Price per active staff user, counted nightly and sent as the quantity. Keys from environment variables; test mode in development, a fake in tests.
3. Trial of 30 days. Payment failed: banner for 14 days, then read-only. Cancelled: read-only at the end of the paid period.
4. Terms of service and the data processing agreement accepted at sign-up, with the version and time stored.

## Checks

- Sign-up to a working empty practice with the default service catalogue, templates and checklist.
- A forged webhook is refused; a repeated one changes nothing.
- A practice that stops paying can still sign in and export.
