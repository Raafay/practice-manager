# When something goes wrong

Each section says what you will see, what to check, and what to do, in order. "The console" means the host's way to run a command on the live app (often called "Shell", "Console" or "Run command"). Run the commands there, from the app's folder.

Weekly habit, five minutes: open **Settings, System**. Check that the worker is running, that no job failed, and that no emails failed or bounced. Then read the Queued page.

---

## The site is down

**You see:** the site does not load, or shows the host's error page.

1. Open `https://<your domain>/healthz/`.
   - **It says `ok`:** the app and the database are up. The problem is the domain or the certificate. Check the domain's DNS records and the host's domain page.
   - **It says `database unavailable`:** the database is down or full. Check the database's page at the host: status, disk space, connection limit.
   - **Nothing loads:** the app is not running. Go on to step 2.
2. Open the host's dashboard. Is the web process running? Read its logs for the last error. Each line is JSON with `level` and `message`.
3. **Did a release just happen?** Roll back to the previous deploy (`docs/DEPLOY.md`, "Rolling back").
4. **Does the log say a setting is missing ("These must be set in the environment…")?** Set it and redeploy.
5. If it is still down after 30 minutes, check the host's status page. Tell staff to work from BrightManager (while it is still running) or on paper. Note the time. Nothing is lost: emails wait in the queue until the site is back.

## A job keeps failing

**You see:** a notification "A background job failed", or a red row on Settings, System.

1. Settings, System, then **All jobs and their run log**. Open the failed run and read its message.
2. Common causes:
   - "Companies House refused the API key": the key was revoked or mistyped. Make a new key and set `COMPANIES_HOUSE_API_KEY`.
   - Xero "needs attention": the connection was revoked or expired. Settings, Integrations, then Connect Xero again.
   - A network error: usually passes by itself. Wait for the next run.
3. Run it again by hand: press **Run now** on the jobs page, or in the console:

       python manage.py run_job <job name>

4. **"Worker not running":** the worker process has stopped. Restart it in the host's dashboard. Run **exactly one** copy.

## Emails are not arriving

1. **Queued page.** Is the message still "Needs approval"? Nothing goes without approval unless its template is set to send automatically.
2. Is **Pause all automatic sending** on? See Settings, System or the Queued page.
3. Is the message "Failed"? Read the error under it, fix the cause, then press Retry.
4. Is it "Bounced: check the address"? The client's address is wrong or their mailbox is full. Correct the contact's email and send again.
5. Sent and delivered, but the client cannot find it? Ask them to check spam. Then check the DNS records (`docs/DEPLOY.md` step 8). In SES, check the identity still shows "Verified" and DKIM "Successful".
6. With Amazon SES: is the account still out of the sandbox, and under its sending quota? See the SES Account dashboard. A complaint rate over 0.1% can pause the account.

## Someone is locked out, or lost their phone

- **Five wrong passwords:** the account is locked for 15 minutes from that address. Waiting is enough. To unlock now, in the console:

      python manage.py axes_reset_username their.email@yourpractice.co.uk

- **Forgotten password:** they open `https://<your domain>/password/reset/`, enter their work email and follow the emailed link.
- **Lost phone (staff):** they can sign in with one of their recovery codes. If they have none, the owner opens Settings, Users, the person, **Reset two-factor**. They set it up again at their next sign-in.
- **Lost phone (the owner, no recovery codes):** in the console:

      python manage.py reset_two_factor --email owner@yourpractice.co.uk

  This is recorded in the activity log.
- **A client cannot get into the portal:** codes last 10 minutes and allow 5 tries. Ask them to request a new code. Check their contact's email and that "Portal access" is ticked for that client.

## A staff member leaves

On their last day:

1. Settings, Users, the person, then **Deactivate**. Choose who takes over their clients and open tasks. They are signed out at their next click.
2. Remove them from any shared mailbox, and from Xero or Companies House if they had their own logins there.
3. If they knew the owner password or any key, change it. Rotate the keys if needed (below).
4. Every three months, review who has an account. Settings, Users shows the last sign-in.

## A suspected data breach

Examples: a laptop with the app open is stolen; an email went to the wrong client; someone saw data they should not have; a key or password leaked.

**Act at once. The clock starts when you become aware of it.**

1. **Contain it.**
   - Deactivate any account involved.
   - Turn on **Pause all automatic sending** if email is involved.
   - Rotate any secret that may have leaked (below).
   - Change the owner's password.
2. **Write it down.** Note what happened, when you found out, what data and whose, and how many people. Keep notes in the practice's breach log, outside this app. The activity log (Settings, Audit log) shows who viewed, revealed or downloaded what. Export the relevant part.
3. **Decide whether to report it.** A personal data breach that is likely to put people at risk **must be reported to the Information Commissioner's Office within 72 hours** of becoming aware of it. Use ico.org.uk ("Report a breach") or the ICO helpline, 0303 123 1113. If you are unsure, report anyway: you can add details later.
4. **Tell the people affected** without delay if the risk to them is high. Say what happened, what data was involved, what you are doing, and what they should do (for example, watch for phishing that uses their details).
5. If tax records were involved, think about telling HMRC, and the practice's professional body and insurer.
6. Afterwards, write down what will stop it happening again.

## Restoring from a backup

Restore into a **new, empty database** first. Never overwrite the live one until you have checked the copy.

**With the host's point-in-time restore (preferred):**

1. In the database's page at the host, choose **Restore** or **Fork**. Pick a time just before the problem. Create it as a new database.
2. Copy the new database's address.
3. Check it: start the app against it (`docs/BACKUPS.md`, "Restore test") and confirm that recent records are there.
4. To switch over: stop the web and worker processes (scale them to zero), set `DATABASE_URL` to the new address on web, worker and release, and redeploy. Keep the old database for 14 days before deleting it.

**From a dump file (any PostgreSQL host).** On a computer with Docker, with the two addresses in the environment:

    # Take a copy of the live database (read-only, safe to run any time)
    docker run --rm -v "$PWD":/backup postgres:16 \
      pg_dump --format=custom --no-owner --dbname "$LIVE_DATABASE_URL" --file /backup/pm-$(date +%Y%m%d).dump

    # Load it into a new, empty database
    docker run --rm -v "$PWD":/backup postgres:16 \
      pg_restore --no-owner --no-privileges --dbname "$NEW_DATABASE_URL" /backup/pm-20261014.dump

The encrypted values in a restored database need the same `FIELD_ENCRYPTION_KEYS`. That is why a copy of the keys is kept outside the host. Uploaded files live in the bucket, not the database. Versioning on the bucket keeps earlier copies of anything overwritten or deleted.

## Rotating the encryption keys and the secret key

**Encryption keys** (`FIELD_ENCRYPTION_KEYS`), for example after someone with access leaves:

1. Make a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Put it **in front** of the old one: `FIELD_ENCRYPTION_KEYS=NEWKEY,OLDKEY`. Redeploy.
3. In the console: `python manage.py rotate_encryption_keys`. It re-encrypts every value with the new key.
4. Remove the old key: `FIELD_ENCRYPTION_KEYS=NEWKEY`. Redeploy.
5. Store the new key outside the host too, and destroy the old copy **only after** the next backup restore test passes with the new key.

**Secret key** (`SECRET_KEY`):

1. Make a new one: `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
2. Set `SECRET_KEY` to the new value and `SECRET_KEY_FALLBACKS` to the old value. Redeploy.
3. Everyone is signed out. Codes and links already sent keep working during the fallback.
4. After a day, remove `SECRET_KEY_FALLBACKS` and redeploy.

**Other keys** (email, bucket, Companies House, Xero): make a new key at the provider, set it, redeploy, then delete the old key at the provider.

## Ongoing care

| How often | What |
|---|---|
| Weekly | Settings, System. Read the failed and bounced messages on the Queued page. |
| Monthly | Security updates: `uv lock --upgrade`, then `make test`, then `uv export --frozen --no-hashes --format requirements-txt > reqs.txt && uvx pip-audit -r reqs.txt --disable-pip --no-deps`, then release. Look at the retention report (Settings, Retention report). |
| Every three months | Restore test (`docs/BACKUPS.md`). Review who has an account. |
| Yearly | Renew the ICO registration. Check that `docs/SUBPROCESSORS.md` and the privacy notice still match. |
