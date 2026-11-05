# Stage 15: Platform admin and practice settings per practice

Goal: you can see and manage every practice from a platform page that shows no client data, and each practice holds its own integration logins.

Read first: `docs/MULTITENANT.md`.

## Build

1. Platform sign-in on the platform address only, with two-factor, separate from practice users. Pages: practices (name, domains, status, users, clients count, storage used, last sign-in, plan), one practice (change status, add a domain, see usage and API spend), and a log of every platform action.
2. Support access: a practice owner can grant platform staff access for up to 24 hours from their Settings; each grant and each page seen is logged in that practice's activity log. Without a grant, platform staff cannot open any practice page.
3. Creditsafe username, password and portfolio move from environment variables into the practice's settings (encrypted, masked, revealing is logged). Companies House and Claude API keys stay platform-wide; Claude API use is shown per practice on the platform page.
4. Read-only mode: a practice with status read-only can sign in and export but every POST is refused with a plain message.

## Checks

- Platform pages refuse practice users; practice pages refuse platform users without a live grant.
- No platform page shows a client, contact or document.
- Each practice's Creditsafe login is used only for that practice.
