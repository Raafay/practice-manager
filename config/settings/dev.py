"""Development settings. Reads `.env` before anything else."""

import base64
import hashlib
from pathlib import Path

from .env import env, env_list, read_env_file

read_env_file(Path(__file__).resolve().parent.parent.parent / ".env")

from .base import *  # noqa: E402,F403

DEBUG = True
SECRET_KEY = env("SECRET_KEY", "django-insecure-development-only")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")

# Without a key in .env, derive a stable development key from the secret key.
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS") or [
    base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()
]

# Lets seeded users get past two-factor without a phone. Development only:
# prod.py refuses to start if this is set.
MFA_TOTP_INSECURE_BYPASS_CODE = env("MFA_TOTP_INSECURE_BYPASS_CODE", "000000")

ALLOW_DEMO_DATA = True
