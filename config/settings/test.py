"""Test settings. PostgreSQL by default, fast hashing, in-memory email and cache."""

from cryptography.fernet import Fernet

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "django-insecure-test-only"
ALLOWED_HOSTS = ["testserver", "localhost"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# A fresh key for every test run. Nothing encrypted in tests outlives the run.
FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]

MEDIA_ROOT = BASE_DIR / "media_test"  # noqa: F405

ALLOW_DEMO_DATA = True

# A model with an encrypted field, for the field's own tests. No migrations: the
# test database creates its table directly.
INSTALLED_APPS = [*INSTALLED_APPS, "apps.core.tests.encrypted_app"]  # noqa: F405

# Tests never call Companies House or gov.uk: they use the saved samples.
COMPANIES_HOUSE_TRANSPORT = "fake"
COMPANIES_HOUSE_API_KEY = ""
XERO_TRANSPORT = "fake"
XERO_CLIENT_ID = "test-client-id"
XERO_CLIENT_SECRET = "test-client-secret"
BANK_HOLIDAYS_FROM_DATABASE = False
