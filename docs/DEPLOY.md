# Putting the app online

This guide is for a **generic container host**, because no hosting company had been chosen when it was written. Any host that fits the list in "What you need" will work. Where a step depends on the host, the guide says what to look for in that host's settings.

Hosts that fit, worth comparing on the day (prices and regions change): Render (Frankfurt), Fly.io (London), DigitalOcean App Platform (London), Railway (Amsterdam), and AWS in London for anyone comfortable with it.

Allow an afternoon for the first time. Do the steps in order. **No real client data goes in until every line of `docs/GO-LIVE.md` is ticked.**

---

## 1. What you need

| Thing | What to choose | Notes |
|---|---|---|
| A container host | Runs a Docker image as two processes, `web` and `worker`, plus a "release" or "pre-deploy" command | Region: UK or EEA |
| PostgreSQL 16 | A managed database from the host or a separate company | Daily automatic backups kept at least 14 days, with point-in-time restore. UK or EEA |
| A private file bucket | Any S3-compatible storage: AWS S3, DigitalOcean Spaces, Cloudflare R2 (EU jurisdiction), and so on | Private (no public access), encryption at rest, versioning on. UK or EEA |
| Email sending | Amazon SES in London (`eu-west-2`) is the default. Postmark and Brevo also work | You need to be able to add DNS records for your domain |
| A domain name | For example `pm.yourpractice.co.uk` | You need access to its DNS settings |
| Companies House API key | Free, from developer.company-information.service.gov.uk | Optional at first. Needed for company lookups and the nightly sync |
| Xero app | See `docs/XERO_SETUP.md` | Optional at first |

---

## 2. Make the secrets

You need three random values. Make them on any computer that has Docker, from the repository folder:

    docker build -t practice-manager .
    docker run --rm practice-manager python -c "import secrets; print(secrets.token_urlsafe(50))"
    docker run --rm practice-manager python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    docker run --rm practice-manager python -c "import secrets; print('hooks:' + secrets.token_urlsafe(30))"

The three lines print, in order:

1. `SECRET_KEY`
2. `FIELD_ENCRYPTION_KEYS`, the key that encrypts National Insurance numbers, UTRs and codes
3. `EMAIL_WEBHOOK_SECRET`

**Keep a copy of `FIELD_ENCRYPTION_KEYS` outside the host as well**, for example in the practice's password manager. Without it, the encrypted values in a restored backup cannot be read. The go-live checklist asks for this.

---

## 3. Create the database and the bucket

1. **Database.** Create a PostgreSQL 16 database in a UK or EEA region. Turn on daily backups and point-in-time restore, keeping them at least 14 days. Copy its connection address. It looks like `postgres://user:password@host:5432/dbname`. If the host shows a separate "internal" address, use that one.
2. **Bucket.** Create a bucket in a UK or EEA region.
   - Block all public access.
   - Turn on versioning and default encryption.
   - Create an access key that can only read and write that bucket.
   - Copy the bucket name, the region, the access key and the secret key. Copy the endpoint address too if the provider is not AWS. For DigitalOcean Spaces in London it is `https://lon1.digitaloceanspaces.com`.

---

## 4. Create the app on the host

1. Point the host at this repository, or at an image you built and pushed. Tell it to use the `Dockerfile`.
2. Set up the three commands. Most hosts read them from the `Procfile` by themselves.

   | Process | Command |
   |---|---|
   | Release (runs once on each deploy, before the new version gets traffic) | `sh scripts/release.sh` |
   | `web` (the website, listens on `$PORT`) | `gunicorn config.wsgi:application -c gunicorn.conf.py` |
   | `worker` (background jobs; exactly **one** copy) | `python manage.py worker` |

3. Health check address: `/healthz/`. It answers `ok` when the database is reachable.
4. Request size: if the host's proxy lets you cap the request body, set it to 100 MB.
5. Logs: keep the host's log retention short (30 days or less). The host's own request log records full addresses, and some of those carry one-off link tokens.

---

## 5. Set the environment variables

Set these on **both** processes (web and worker), and on the release command if the host keeps them separate. The app refuses to start if a required one is missing, and the log says which.

### Required

| Variable | Example | What it is |
|---|---|---|
| `SECRET_KEY` | (from step 2) | Django's secret. 50 random characters |
| `DATABASE_URL` | `postgres://user:pass@host:5432/pm` | The database address |
| `FIELD_ENCRYPTION_KEYS` | (from step 2) | Keys for encrypted fields, newest first, separated by commas |
| `ALLOWED_HOSTS` | `pm.yourpractice.co.uk` | The site's domain |
| `CSRF_TRUSTED_ORIGINS` | `https://pm.yourpractice.co.uk` | The same, with `https://` |
| `SITE_URL` | `https://pm.yourpractice.co.uk` | Used in links in emails. Must start with `https://` |
| `DEFAULT_FROM_EMAIL` | `Your Practice <office@yourpractice.co.uk>` | The sending address |
| `EMAIL_PROVIDER` | `ses` | `ses`, `postmark` or `brevo` |
| `EMAIL_WEBHOOK_SECRET` | (from step 2) | `name:password` the provider uses for delivery reports |
| `STORAGE_BUCKET` | `yourpractice-pm-files` | The private bucket |
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | | The bucket's access key |

### For Amazon SES (`EMAIL_PROVIDER=ses`)

| Variable | Example |
|---|---|
| `EMAIL_ACCESS_KEY`, `EMAIL_SECRET_KEY` | An IAM user that may only `ses:SendRawEmail` |
| `EMAIL_REGION` | `eu-west-2` (the default) |
| `EMAIL_CONFIGURATION_SET` | `pm-events` (see step 8) |

For Postmark or Brevo, set `EMAIL_API_KEY` instead.

### Usually needed

| Variable | Example | What it is |
|---|---|---|
| `TRUSTED_PROXY_COUNT` | `1` | How many proxies the host puts in front of the app. Usually 1. Lockout and rate limits use this to find the visitor's real address |
| `TRUSTED_CLIENT_IP_HEADER` | `Fly-Client-IP` | Use this instead of the count if the host sets its own header with the visitor's address. Check the host's documentation |
| `STORAGE_ENDPOINT` | `https://lon1.digitaloceanspaces.com` | Only for non-AWS buckets |
| `STORAGE_REGION` | `eu-west-2` | The bucket's region |
| `COMPANIES_HOUSE_API_KEY` | | Companies House (step 10) |
| `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET` | | Xero (step 10) |

### Optional

| Variable | What it is |
|---|---|
| `APP_VERSION` | A name for this release, for example `2026.11.1`. It shows on Settings, System |
| `SENTRY_DSN` | Error reports to Sentry (EU region). Personal data is scrubbed before sending |
| `WEB_CONCURRENCY` | Web worker processes. Default 3 |
| `LOG_LEVEL` | Default `INFO` |
| `STORAGE_SSE` | `false` only if the bucket provider rejects the server-side encryption header and encrypts at rest by itself |

**Never set in production:** `DEBUG`, `MFA_TOTP_INSECURE_BYPASS_CODE` or `ALLOW_DEMO_DATA`. The app refuses to start if any of them is set.

---

## 6. First release and the first owner

1. Deploy. The release command runs `migrate`, `createcachetable` and Django's deployment checks. Then the web process starts.
2. Open `https://<host's temporary address>/healthz/`. It should say `ok`.
3. Use the host's "run a command" or "console" feature on the web process to create the first owner:

       python manage.py create_owner --email you@yourpractice.co.uk --name "Your Name"

   It asks for a password (at least 12 characters).
4. Sign in at `/login/`. You are sent to set up two-factor with an authenticator app. Save the recovery codes somewhere safe.
5. Open Settings, Practice details, and fill them in. Open Settings, Security and check the session times and retention years.

---

## 7. Point the domain at it

1. In the host's settings, add the custom domain, for example `pm.yourpractice.co.uk`.
2. The host shows a DNS record to add, usually a `CNAME`. Add it where the domain's DNS is managed.
3. Wait for the host to show the certificate as issued. Certificates renew by themselves.
4. Check from any computer with the app installed:

       python manage.py check_headers https://pm.yourpractice.co.uk

   It should finish with "All security headers are right".

---

## 8. Email: prove the domain and get delivery reports

This uses Amazon SES in London. Postmark and Brevo have the same three kinds of DNS record under their own names.

1. In the AWS console, switch to the **Europe (London) eu-west-2** region. Open SES, then Identities, then Create identity, then Domain. Enter `yourpractice.co.uk`.
2. SES shows **three DKIM `CNAME` records**. Add all three to the domain's DNS.
3. Under the identity, set a **custom MAIL FROM domain**, for example `mail.yourpractice.co.uk`. Add the `MX` record and the SPF `TXT` record that SES shows (`v=spf1 include:amazonses.com ~all`).
4. Add a **DMARC** record if the domain does not have one. Start in monitoring mode:

   | Type | Name | Value |
   |---|---|---|
   | `TXT` | `_dmarc.yourpractice.co.uk` | `v=DMARC1; p=none; rua=mailto:office@yourpractice.co.uk` |

   After a month of clean reports, change `p=none` to `p=quarantine`.
5. In SES, open Account dashboard and **request production access**. Until it is granted, SES sends only to verified addresses.
6. **Delivery reports:**
   1. Create an SNS topic `pm-email-events` in eu-west-2.
   2. Add an HTTPS subscription with this address, using the `EMAIL_WEBHOOK_SECRET` name and password:

          https://NAME:PASSWORD@pm.yourpractice.co.uk/email/events/

      The app confirms the subscription by itself.
   3. In SES, create a configuration set `pm-events` with an event destination of that SNS topic, for Delivery, Bounce, Complaint and Reject.
   4. Set `EMAIL_CONFIGURATION_SET=pm-events` and redeploy.
7. Send a test. Sign in, add a test client with yourself as its main contact, and use Send email to send a message to your own address. Approve it. It should arrive in the inbox, not in spam. A minute later the Queued page should show it as delivered. Delete the test client afterwards.

For Postmark or Brevo, the webhook address is the same `https://NAME:PASSWORD@…/email/events/`, entered in their webhook settings.

---

## 9. The worker

The worker runs every background job: the nightly Companies House and Xero syncs, deadline generation, reminders and the sending of approved emails. Run **exactly one** copy. Settings, System shows "Worker running" when it is alive.

---

## 10. Connect Companies House and Xero

- **Companies House:**
  1. Register at developer.company-information.service.gov.uk.
  2. Create a REST API key for the live service.
  3. Set `COMPANIES_HOUSE_API_KEY` and redeploy.
  4. Check it from the host's console:

         python manage.py ch_check <company number>

     Use the number of a company you know, such as the practice's own. It should print the company's filing dates.
- **Xero:** follow `docs/XERO_SETUP.md`. The redirect address is `https://pm.yourpractice.co.uk/integrations/xero/callback`.

---

## 11. Releasing an update

1. Run the checks locally: `make lint` and `make test`.
2. Merge to the branch the host deploys from, or build and push a new image. Set `APP_VERSION` to the new release name.
3. The host runs the release command (migrations) before the new version takes traffic. If it fails, the old version keeps running. Read the release log.
4. Open Settings, System. Check the version and that the worker is running.

**Rolling back:**

- **If the release added no migrations:** redeploy the previous image or commit from the host's "deploys" list.
- **If it did add migrations:** the old code may not work with the new database. Either fix forward with a new release (preferred), or restore the database to just before the release (`docs/RUNBOOK.md`, "Restoring from a backup") and then redeploy the old version. A restore loses anything entered since, so fix forward when you can.

## 12. What is left to do once a host is chosen

- Write the host's exact screens and names into steps 3 to 7 of this guide, and record the host in `docs/SUBPROCESSORS.md`.
- Build the image on the host and run the go-live checklist.
- Set the bucket's lifecycle rule to keep old versions of deleted files for 30 days.
