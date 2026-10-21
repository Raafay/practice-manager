"""Write `.env.beta` with fresh random keys, once: `make beta-init DOMAIN=app.example.co.uk`.

Refuses to overwrite an existing `.env.beta`: a new FIELD_ENCRYPTION_KEYS would make
the encrypted values already in the database unreadable. See docs/BETA.md.
"""

import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / ".env.beta"


def main() -> int:
    if len(sys.argv) != 2 or "." not in sys.argv[1] or "/" in sys.argv[1]:
        print("Usage: make beta-init DOMAIN=app.example.co.uk")
        return 2
    domain = sys.argv[1].strip().lower()
    if TARGET.exists():
        print(".env.beta already exists. Not changed: new keys would lock out the data.")
        return 1
    data_dir = Path.home() / "pm-beta"
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    (data_dir / "backups").mkdir(parents=True, exist_ok=True)
    field_key = Fernet.generate_key().decode()
    TARGET.write_text(
        "# Beta settings. Never commit this file. Keep a copy of FIELD_ENCRYPTION_KEYS\n"
        "# in the practice's password manager: without it the encrypted values in a\n"
        "# backup cannot be read. See docs/BETA.md.\n"
        "DATABASE_URL=postgres://pm:pm@localhost:5432/pm_beta\n"
        f"SECRET_KEY={secrets.token_urlsafe(50)}\n"
        f"FIELD_ENCRYPTION_KEYS={field_key}\n"
        f"ALLOWED_HOSTS={domain}\n"
        f"CSRF_TRUSTED_ORIGINS=https://{domain}\n"
        f"SITE_URL=https://{domain}\n"
        f"MEDIA_ROOT={data_dir / 'files'}\n"
        f"BACKUP_DIR={data_dir / 'backups'}\n"
        "COMPANIES_HOUSE_API_KEY=\n"
    )
    TARGET.chmod(0o600)
    print(f"Wrote .env.beta for https://{domain}. Uploaded files go in {data_dir / 'files'}.")
    print("Now copy FIELD_ENCRYPTION_KEYS from .env.beta into your password manager.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
