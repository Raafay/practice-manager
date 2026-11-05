# Stage 18: Custom domains and a security review of the multi-practice set-up

Goal: a firm can use its own address, and an independent review confirms no data can cross between practices.

## Build

1. Custom domain per practice (`portal.firm.co.uk`): the firm adds a DNS record, the platform checks it and the host issues a certificate. Links in emails and PDFs use the primary domain.
2. Security review in the style of Stage 13, aimed only at crossing between practices: middleware, sessions, cookies, cache, files, jobs, emails, public links, the platform admin and support access. Fix everything found, with tests.

## Checks

- Every finding fixed with a test, or accepted in `docs/SECURITY-REVIEW.md` with a reason.
