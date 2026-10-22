# Running the beta from one laptop

The beta runs on **one Mac** (the host) and is reached at **`https://app.fpas.co.uk`** through a free Cloudflare Tunnel. Only people whose email is on the Cloudflare Access list can even see the sign-in page. There is no server. The data stays on the host laptop.

What the beta mode (`config/settings/beta.py`) does:

- It is as strict as production. No error pages with details, no `000000` two-factor code, and no demo data.
- Uploaded files go in `~/pm-beta/files`, outside the code folder.
- **No email or text leaves the laptop.** Emails are printed in the terminal window that runs the app, so the client portal and reminders do not work in the beta, and nothing can reach a client by accident.
- The app listens on `127.0.0.1` only. Other devices on the office Wi-Fi cannot reach it. The only way in is through the tunnel.
- It uses its own database (`pm_beta`) and its own settings file (`.env.beta`). `make dev` and `make seed` keep using `pm_dev` and `.env`, so they never touch real data.

**Limits:** the site only works while the host laptop is on, awake and running `make beta`. Moving to another laptop or a server takes about an hour (see the last section).

---

## 1. Prepare the host Mac (once)

1. Turn on FileVault: System Settings → Privacy & Security → FileVault.
2. Stop it sleeping while plugged in: System Settings → Battery → Options → "Prevent automatic sleeping on power adapter when the display is off".
3. Turn on Time Machine with an external drive.
4. Check that the development setup works: `make setup`, then `make test` passes. On a Mac, PDFs need `brew install pango` first; the app finds Homebrew's libraries by itself. If `make test` fails with a missing `libhvf.dylib`, Homebrew's freetype was built for a newer macOS: `brew reinstall --build-from-source freetype` fixes it.

## 2. Create the beta database and settings (once)

    createdb -h localhost -U pm pm_beta
    make beta-init DOMAIN=app.fpas.co.uk

If `createdb` is refused, run `createdb pm_beta -O pm` as the Mac user that installed PostgreSQL.

`make beta-init` writes `.env.beta` with new random keys and creates `~/pm-beta/`. It refuses to run a second time, because new keys would make the data already stored unreadable.

**Straight away:** copy the `FIELD_ENCRYPTION_KEYS` line from `.env.beta` into the practice's password manager. Copy the whole file there too if the manager allows notes. Never paste it into a chat or commit it.

Optional: paste the Companies House key after `COMPANIES_HOUSE_API_KEY=` in `.env.beta`.

## 3. Cloudflare (the person who owns the Cloudflare account does this)

These steps assume `fpas.co.uk` is already on Cloudflare and its nameservers are switched. The existing website's records (`@`, `www`) and the email records (MX, TXT) must be **DNS only** (grey cloud), so the website and email behave exactly as before.

Cloudflare renames its menus now and then. Look for the nearest match.

1. **The access list first.** Zero Trust → Access → Applications → Add an application → Self-hosted.
   - Application domain: `app.fpas.co.uk`.
   - Policy: Action **Allow**, Include **Emails**, listing each beta user's email address.
   - Login method: **One-time PIN**.
2. **The tunnel.** Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared → name it `pm-beta`.
   - Choose macOS. Run the install command it shows on the host Mac (`brew install cloudflared`, then `sudo cloudflared service install <token>`). The tunnel then starts by itself whenever the Mac starts.
   - Public hostname: subdomain `app`, domain `fpas.co.uk`, service **HTTP**, URL `127.0.0.1:8000`.
3. **HTTPS only.** On the `fpas.co.uk` site: SSL/TLS → Edge Certificates → Always Use HTTPS: **On**.

## 4. Start the app

    make beta

Leave that terminal window open: it is the app. It runs migrations, builds the styles, checks the security settings, then starts the website and the background worker. Ctrl+C stops both. Run `make beta` again after a restart.

Open `https://app.fpas.co.uk`. Cloudflare asks for your email and sends a code, then the app's sign-in page appears.

## 5. Accounts

1. Create the owner (asks for a password; use a long one from the password manager):

       DJANGO_SETTINGS_MODULE=config.settings.beta uv run python manage.py create_owner --email <owner email> --name "<owner name>"

2. Sign in at `https://app.fpas.co.uk` and set up the authenticator app when asked.
3. Invite the others from Settings → Users. The invitation email is **printed in the `make beta` terminal** instead of being sent. Copy the link from there and send it to the person yourself. It works once and lasts 72 hours.
4. Add each person's email to the Cloudflare Access list (step 3.1) too, or they will not get past Cloudflare.

## 6. Backups (once, then nightly)

1. Run one now: `make beta-backup`. It writes a database copy and a files copy to `~/pm-beta/backups` and keeps the newest 30 of each. Time Machine copies that folder off the laptop.
2. Run it every night: `crontab -e` and add these two lines (adjust the folder if the code is elsewhere):

       PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
       30 21 * * * cd "$HOME/practice-manager" && /bin/sh scripts/beta_backup.sh >> "$HOME/pm-beta/backup.log" 2>&1

3. Test a restore once, into a scratch database, and check that the client count matches:

       createdb -h localhost -U pm pm_restore_test
       pg_restore --no-owner -d postgres://pm:pm@localhost:5432/pm_restore_test ~/pm-beta/backups/db_<newest>.dump
       psql postgres://pm:pm@localhost:5432/pm_restore_test -c "select count(*) from clients_client"
       dropdb -h localhost -U pm pm_restore_test

## Everyday

- **Updating the app:** stop it (Ctrl+C), `git pull`, then `make beta` again. Migrations run by themselves. Take a `make beta-backup` first.
- **Reminder schedules** stay off. The owner switches them on only after go-live with real email sending.
- **Never** run `make seed`, or any command with `DJANGO_SETTINGS_MODULE=config.settings.dev`, pointed at `pm_beta`. Never commit `.env.beta` (git ignores it).

## Moving to another laptop or a server

1. On the old laptop: stop the app, run `make beta-backup`, and copy the newest `db_*.dump`, `files_*.tar.gz` and `.env.beta` to the new machine (an encrypted USB stick or AirDrop, never email).
2. On the new machine: set up the code (`make setup`), `createdb pm_beta`, put `.env.beta` in the code folder (fix `MEDIA_ROOT` and `BACKUP_DIR` if the home folder differs), then:

       pg_restore --no-owner -d <DATABASE_URL from .env.beta> db_<stamp>.dump
       mkdir -p ~/pm-beta/files && tar -xzf files_<stamp>.tar.gz -C ~/pm-beta/files

3. Install the tunnel on the new machine with the same token from the Cloudflare tunnel page, then uninstall it on the old one (`sudo cloudflared service uninstall`). Run `make beta`. The address stays the same.

For a proper server, `docs/DEPLOY.md` takes over. The same database dump and files are loaded there.
