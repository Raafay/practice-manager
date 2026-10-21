"""Beta settings: the live app run from one laptop, reached through a Cloudflare Tunnel.

Safe like prod.py (DEBUG off, no two-factor bypass, no demo data, secure cookies)
but with no bucket and no email provider: uploaded files stay on the laptop's
encrypted disk and email is only written to the terminal, so nothing reaches a
client. Values come from `.env.beta`, which is separate from the development
`.env` so `make dev` and `make seed` never touch the real data.
See docs/BETA.md.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .env import env, env_bool, env_list, read_env_file

read_env_file(Path(__file__).resolve().parent.parent.parent / ".env.beta")

from .base import *  # noqa: E402,F403

REQUIRED = (
    "SECRET_KEY",
    "DATABASE_URL",
    "FIELD_ENCRYPTION_KEYS",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "SITE_URL",
    "MEDIA_ROOT",
)
_missing = [name for name in REQUIRED if not env(name)]
if _missing:
    raise ImproperlyConfigured(
        "These must be set in .env.beta: " + ", ".join(_missing) + ". See docs/BETA.md."
    )

if env_bool("DEBUG"):
    raise ImproperlyConfigured("DEBUG must be off in the beta.")
if env("MFA_TOTP_INSECURE_BYPASS_CODE"):
    raise ImproperlyConfigured("MFA_TOTP_INSECURE_BYPASS_CODE must not be set in the beta.")
if env("SECRET_KEY").startswith("django-insecure") or len(env("SECRET_KEY")) < 40:
    raise ImproperlyConfigured("SECRET_KEY looks like a development key. Use 50 random characters.")
if env_bool("ALLOW_DEMO_DATA"):
    raise ImproperlyConfigured("ALLOW_DEMO_DATA must be off in the beta.")
if not env("SITE_URL").startswith("https://"):
    raise ImproperlyConfigured("SITE_URL must start with https://.")
if env("EMAIL_BACKEND") or env("SMS_BACKEND"):
    raise ImproperlyConfigured(
        "The beta sends no email or text messages. Remove EMAIL_BACKEND and SMS_BACKEND."
    )

DEBUG = False
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL").rstrip("/")
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS")
ALLOW_DEMO_DATA = False

# Cloudflare ends HTTPS and forwards to the app on 127.0.0.1 only (scripts/beta.sh),
# so nothing on the local network can reach it over plain HTTP. Cloudflare's
# "Always Use HTTPS" does the redirect, so the app does not.
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 365 * 24 * 60 * 60
SILENCED_SYSTEM_CHECKS = ["security.W008", "security.W021"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

# Cloudflare always overwrites this header with the visitor's real address.
TRUSTED_CLIENT_IP_HEADER = env("TRUSTED_CLIENT_IP_HEADER", "CF-Connecting-IP")
ALLAUTH_TRUSTED_CLIENT_IP_HEADER = TRUSTED_CLIENT_IP_HEADER

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_table",
    }
}

# Uploaded files on the laptop's encrypted disk, outside the code folder.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Email goes to the terminal only. Nothing reaches a client during the beta.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SMS_BACKEND = ""
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Practice Manager beta <no-reply@localhost>")
