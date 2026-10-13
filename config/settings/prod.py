"""Production settings. Refuses to start when something unsafe is set or missing."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .env import env, env_bool, env_list

for _name in ("SECRET_KEY", "DATABASE_URL", "FIELD_ENCRYPTION_KEYS", "ALLOWED_HOSTS"):
    if not env(_name):
        raise ImproperlyConfigured(f"{_name} must be set in the environment.")

if env_bool("DEBUG"):
    raise ImproperlyConfigured("DEBUG must be off in production.")
if env("MFA_TOTP_INSECURE_BYPASS_CODE") or globals().get("MFA_TOTP_INSECURE_BYPASS_CODE"):
    raise ImproperlyConfigured("MFA_TOTP_INSECURE_BYPASS_CODE must not be set in production.")
if env("SECRET_KEY").startswith("django-insecure"):
    raise ImproperlyConfigured("SECRET_KEY looks like a development key.")

DEBUG = False
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS")

# HTTPS only. The platform's proxy terminates TLS and sets X-Forwarded-Proto.
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 365 * 24 * 60 * 60
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

# The release command runs `createcachetable`.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_table",
    }
}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if env("AWS_STORAGE_BUCKET_NAME"):
    # A private bucket: no public ACL, short-lived signed links only, encrypted at rest.
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
            "region_name": env("AWS_S3_REGION_NAME", "eu-west-2"),
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": 60,
            "file_overwrite": False,
            "object_parameters": {"ServerSideEncryption": "AES256"},
        },
    }

EMAIL_BACKEND = env("EMAIL_BACKEND", "anymail.backends.amazon_ses.EmailBackend")
