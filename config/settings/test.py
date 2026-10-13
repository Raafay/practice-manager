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
