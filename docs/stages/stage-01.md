# Stage 1: Foundation

Goal: a running Django project where staff can sign in with two-factor, the owner can manage users, everything is logged, and the page layout and components exist for later stages to reuse.

Read first: `docs/specs/00-product.md`, `docs/specs/01-security-and-users.md`.

## Build

1. Project skeleton.
   - `uv init`, Python 3.12. Add: `django>=5.2,<5.3`, `psycopg[binary]`, `django-allauth[mfa]`, `django-axes`, `django-htmx`, `django-anymail`, `django-storages`, `django-tailwind-cli`, `whitenoise`, `dj-database-url`, `nh3`, `cryptography`, `weasyprint`, `gunicorn`. Dev: `pytest`, `pytest-django`, `factory-boy`, `ruff`, `playwright`.
   - `config/settings/` with `base.py`, `dev.py`, `test.py`, `prod.py`. Settings come from the environment, with `.env` read in development. The dev default database is `postgres://pm:pm@localhost:5432/pm_dev`. If `DATABASE_URL` starts with `sqlite`, that works too, for a quick look on a laptop.
   - `apps/` package with `core`, `accounts`, `events`.
   - `Makefile` with the commands in CLAUDE.md. `.env.example`. ruff and pytest settings in `pyproject.toml` (`addopts = "-q --tb=short --no-header"`).
   - UK settings: `en-gb`, `Europe/London`, dates as dd/mm/yyyy.

2. Layout and components.
   - Tailwind through django-tailwind-cli. Built CSS is not committed. Add its path to `.gitignore`.
   - Vendor HTMX, the Alpine CSP build, SortableJS and Trix into `static/vendor/`. Set `htmx.config.allowEval` to false.
   - Base template: top bar with the nav (only Overview and Settings for now), search box (inactive until Stage 2), New menu (empty), bell (inactive), user menu.
   - The components listed in `00-product.md` section 5, each as a template include or tag, all shown on `/styleguide/` (staff only).
   - Heroicons through a small template tag. Toasts for success and error messages. A drawer and a modal that load their content with HTMX.

3. Accounts.
   - Custom `User` with email sign-in and the fields in `01-security-and-users.md` section 1.
   - Roles and rights as in section 2: `Role` with a set of right names, three seeded roles, per-user extra rights, `user.can()`, the mixins and the template tag.
   - `Team`, and users in teams.
   - Sign-in, sign-out and password reset with django-allauth. Two-factor compulsory for staff, recovery codes, trust this browser, lockout with django-axes, session lengths, password re-entry for sensitive actions. All as in section 3.
   - Invitations by the owner.
   - Settings, Users: list, invite, change role, grant a single right, reset two-factor, deactivate and reactivate. Settings, Teams. Settings, Roles: tick boxes for Manager and Staff.
   - A profile page for each user: name, initials, colour, job title, weekly hours, password, two-factor.
   - `manage.py create_owner` to make the first owner from the command line.

4. Activity log.
   - `ActivityEvent`, `events.record()`, the middleware, and the audit log page, as in section 9.
   - Record sign-in, failed sign-in, sign-out and every user and role change now.

5. Core helpers, each with tests.
   - `apps/core/dates.py`: `add_months`, working-day functions, tax-year functions, and the bundled bank holidays. The exact behaviour and the dates are in `docs/specs/03-services-and-deadlines.md` section 5. Read only that section.
   - `EncryptedTextField` with key rotation, and a masked display helper.
   - A `public_id` mixin (random UUID), a timestamps mixin, pagination, money formatting.
   - Rate limiting helper on the Django cache.

6. Security baseline.
   - The production settings in section 11, and a test that loads `prod.py` with a fake environment and checks them.
   - Django admin at `/control/`, owner only.
   - Custom 403, 404 and 500 pages.

7. Practice settings: a single-row model and a Settings page for practice name, address, phone, email, logo, accent colour, VAT registered, VAT rate. Later stages add to it.

8. Demo data: `manage.py seed_demo` creates one owner, one manager, three staff and two teams with made-up names, and prints their sign-in details. Safe to run twice. In dev settings only, set `MFA_TOTP_INSECURE_BYPASS_CODE` so seeded users can sign in without a phone, and print the code. Add `manage.py dev_login <email>`, which works only when DEBUG is on, creates a signed-in session for that user with two-factor marked as done, and prints the session id. `scripts/screenshots.py` takes it as `--session`, so screenshots of signed-in pages need no typing.

9. Overview page: a welcome and the user's name for now.

10. Delivery.
    - `Dockerfile` (with the system libraries WeasyPrint needs) and `docker-compose.yml` with `web` and `db`.
    - `.github/workflows/ci.yml`: ruff, then pytest against a PostgreSQL service, then `migrate` and `seed_demo` on SQLite as a smoke test. If the push is refused because of the workflow file, save it as `docs/ci.yml.example` instead and say so in the pull request.
    - Update `README.md` section "Looking at the app on your Mac" if the commands differ from what is written there.

## Checks

- `make lint` and `make test` pass.
- Tests exist for: sign-in without two-factor is sent to set-up and can reach nothing else; lockout after five failures; invitation link works once and expires; each seeded role has the rights in the table; `user.can` with a per-user grant; deactivated user cannot sign in; the last owner cannot be removed or demoted; audit log is owner only; events are written for sign-in and role change; encrypted field stores ciphertext and survives key rotation; every date helper against the cases in the spec; production settings test.
- `uv run python manage.py makemigrations --check --dry-run` reports nothing.
- With `DATABASE_URL=sqlite:///smoke.sqlite3`: `migrate` and `seed_demo` run clean.
- Screenshots in `docs/screens/stage-01/`: sign-in, styleguide, users page, audit log.

## Not in this stage

Clients, tasks, anything about deadlines, the portal. Portal sign-in is Stage 10, but the `kind` field on `User` and the rule that a portal user cannot reach staff pages belong here, with a test.
