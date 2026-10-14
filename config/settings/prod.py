"""Production settings. Every value comes from the environment.

The app refuses to start when something it needs is missing or when something
unsafe is set. The full list of variables, with what each is for, is in
docs/DEPLOY.md.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .env import env, env_bool, env_list

REQUIRED = (
    "SECRET_KEY",
    "DATABASE_URL",
    "FIELD_ENCRYPTION_KEYS",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "SITE_URL",
    "DEFAULT_FROM_EMAIL",
    "EMAIL_PROVIDER",
    "STORAGE_BUCKET",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
)
_missing = [name for name in REQUIRED if not env(name)]
if _missing:
    raise ImproperlyConfigured(
        "These must be set in the environment: " + ", ".join(_missing) + ". See docs/DEPLOY.md."
    )

if env_bool("DEBUG"):
    raise ImproperlyConfigured("DEBUG must be off in production.")
if env("MFA_TOTP_INSECURE_BYPASS_CODE") or globals().get("MFA_TOTP_INSECURE_BYPASS_CODE"):
    raise ImproperlyConfigured("MFA_TOTP_INSECURE_BYPASS_CODE must not be set in production.")
if env("SECRET_KEY").startswith("django-insecure") or len(env("SECRET_KEY")) < 40:
    raise ImproperlyConfigured("SECRET_KEY looks like a development key. Use 50 random characters.")
if env_bool("ALLOW_DEMO_DATA"):
    raise ImproperlyConfigured("ALLOW_DEMO_DATA must be off in production.")
if not env("SITE_URL").startswith("https://"):
    raise ImproperlyConfigured("SITE_URL must start with https://.")

DEBUG = False
SECRET_KEY = env("SECRET_KEY")
# While changing the secret key, put the old one here for a day so signed values made
# with it (password reset links, "trust this browser") keep working. See RUNBOOK.md.
SECRET_KEY_FALLBACKS = env_list("SECRET_KEY_FALLBACKS")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL").rstrip("/")
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS")
ALLOW_DEMO_DATA = False

# HTTPS only. The host's proxy ends TLS and sets X-Forwarded-Proto.
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]  # the host's own health check may use plain HTTP
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 365 * 24 * 60 * 60
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# HSTS preload is left off on purpose: joining the browsers' preload list is hard to
# undo, and the practice may still move the domain. The warning is silenced.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

# The database cache, so rate limits hold across processes. The release command
# runs `createcachetable`.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_table",
    }
}

# Uploaded files: a private bucket that speaks S3, in the UK or EEA, encrypted at
# rest. No public ACL; files are only ever streamed through permission-checked views.
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("STORAGE_BUCKET"),
            "endpoint_url": env("STORAGE_ENDPOINT") or None,
            "region_name": env("STORAGE_REGION", "eu-west-2"),
            "access_key": env("STORAGE_ACCESS_KEY"),
            "secret_key": env("STORAGE_SECRET_KEY"),
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": 60,
            "file_overwrite": False,
            "object_parameters": {"ServerSideEncryption": "AES256"}
            if env_bool("STORAGE_SSE", True)
            else {},
        },
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Email through django-anymail. EMAIL_PROVIDER picks the company (docs/DEPLOY.md).
EMAIL_PROVIDERS = {
    "ses": "anymail.backends.amazon_ses.EmailBackend",
    "postmark": "anymail.backends.postmark.EmailBackend",
    "brevo": "anymail.backends.brevo.EmailBackend",
}
EMAIL_PROVIDER = env("EMAIL_PROVIDER").lower()
if EMAIL_PROVIDER not in EMAIL_PROVIDERS:
    raise ImproperlyConfigured(
        f"EMAIL_PROVIDER must be one of {', '.join(EMAIL_PROVIDERS)}. "
        "The console and in-memory backends are for development and tests only."
    )
EMAIL_BACKEND = EMAIL_PROVIDERS[EMAIL_PROVIDER]
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
if not env("EMAIL_WEBHOOK_SECRET") or ":" not in env("EMAIL_WEBHOOK_SECRET"):
    raise ImproperlyConfigured(
        "EMAIL_WEBHOOK_SECRET must be set as name:password (random, at least 20 characters "
        "each). The provider sends delivery reports with it."
    )
ANYMAIL = {"WEBHOOK_SECRET": env("EMAIL_WEBHOOK_SECRET")}
if EMAIL_PROVIDER == "ses":
    for _name in ("EMAIL_ACCESS_KEY", "EMAIL_SECRET_KEY"):
        if not env(_name):
            raise ImproperlyConfigured(f"{_name} must be set for Amazon SES.")
    ANYMAIL["AMAZON_SES_CLIENT_PARAMS"] = {
        "region_name": env("EMAIL_REGION", "eu-west-2"),
        "aws_access_key_id": env("EMAIL_ACCESS_KEY"),
        "aws_secret_access_key": env("EMAIL_SECRET_KEY"),
    }
    if env("EMAIL_CONFIGURATION_SET"):
        ANYMAIL["AMAZON_SES_CONFIGURATION_SET_NAME"] = env("EMAIL_CONFIGURATION_SET")
else:
    if not env("EMAIL_API_KEY"):
        raise ImproperlyConfigured(f"EMAIL_API_KEY must be set for {EMAIL_PROVIDER}.")
    _key_setting = {"postmark": "POSTMARK_SERVER_TOKEN", "brevo": "BREVO_API_KEY"}
    ANYMAIL[_key_setting[EMAIL_PROVIDER]] = env("EMAIL_API_KEY")

# Text messages stay off unless a real provider is named (never the console one,
# which writes numbers and text to the log).
if "Console" in SMS_BACKEND:  # noqa: F405
    raise ImproperlyConfigured("SMS_BACKEND must not be the console backend in production.")

# Logs: one JSON object a line on standard output, tokens taken out (apps/core/logs.py).
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405

# Optional error reporting. Personal data is never sent: no request bodies, cookies,
# headers or user details, and addresses have their tokens taken out.
SENTRY_DSN = env("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk

    from apps.core.sentry import scrub_event

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=scrub_event,
        traces_sample_rate=0.0,
        environment=env("SENTRY_ENVIRONMENT", "production"),
        release=env("APP_VERSION") or None,
    )
