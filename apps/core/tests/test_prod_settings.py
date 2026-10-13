"""Load prod.py with a made-up environment and check spec 01 (security), section 11."""

import importlib
import sys

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

FAKE_ENV = {
    "SECRET_KEY": "a-long-random-production-secret-for-testing-only-0123456789",
    "DATABASE_URL": "postgres://user:pass@db.example.com:5432/pm",
    "FIELD_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
    "ALLOWED_HOSTS": "app.example.com",
}


def load_prod(monkeypatch, **overrides):
    for name in ("DEBUG", "MFA_TOTP_INSECURE_BYPASS_CODE", "AWS_STORAGE_BUCKET_NAME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**FAKE_ENV, **overrides}.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    saved = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name.startswith("config.settings.")
    }
    try:
        return importlib.import_module("config.settings.prod")
    finally:
        for name in [n for n in sys.modules if n.startswith("config.settings.")]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_production_settings_are_safe(monkeypatch):
    prod = load_prod(monkeypatch)
    assert prod.DEBUG is False
    assert FAKE_ENV["SECRET_KEY"] == prod.SECRET_KEY
    assert prod.DATABASES["default"]["HOST"] == "db.example.com"
    assert [FAKE_ENV["FIELD_ENCRYPTION_KEYS"]] == prod.FIELD_ENCRYPTION_KEYS
    assert prod.ALLOWED_HOSTS == ["app.example.com"]
    # HTTPS only, HSTS for a year, secure HttpOnly cookies, SameSite Lax
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_HSTS_SECONDS >= 31536000
    assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE
    assert prod.SESSION_COOKIE_HTTPONLY is True
    assert prod.SESSION_COOKIE_SAMESITE == "Lax" and prod.CSRF_COOKIE_SAMESITE == "Lax"
    # Headers
    assert prod.SECURE_REFERRER_POLICY == "same-origin"
    assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert prod.X_FRAME_OPTIONS == "DENY"
    csp = prod.CONTENT_SECURITY_POLICY
    assert "default-src 'self'" in csp
    assert (
        "script-src 'self'" in csp
        and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    )
    assert "img-src 'self' data: blob:" in csp
    assert "frame-ancestors 'none'" in csp
    # No development shortcuts, and the database cache
    assert not hasattr(prod, "MFA_TOTP_INSECURE_BYPASS_CODE")
    assert prod.ALLOW_DEMO_DATA is False
    assert prod.CACHES["default"]["BACKEND"].endswith("DatabaseCache")
    # Logs leave out request paths below error level
    assert prod.LOGGING["loggers"]["django.request"]["level"] == "ERROR"


@pytest.mark.parametrize(
    "missing", ["SECRET_KEY", "DATABASE_URL", "FIELD_ENCRYPTION_KEYS", "ALLOWED_HOSTS"]
)
def test_refuses_to_start_without_required_settings(monkeypatch, missing):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, **{missing: None})


def test_refuses_to_start_with_debug_on(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, DEBUG="true")


def test_refuses_to_start_with_the_two_factor_bypass(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, MFA_TOTP_INSECURE_BYPASS_CODE="000000")


def test_refuses_a_development_secret_key(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, SECRET_KEY="django-insecure-something")


def test_private_bucket_when_configured(monkeypatch):
    prod = load_prod(monkeypatch, AWS_STORAGE_BUCKET_NAME="pm-files")
    options = prod.STORAGES["default"]["OPTIONS"]
    assert options["default_acl"] == "private"
    assert options["querystring_auth"] is True
