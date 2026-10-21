"""Load beta.py with a made-up environment: safe like production, files on disk,
email to the terminal only, and refusing to start without what it needs."""

import importlib
import sys

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

FAKE_ENV = {
    "SECRET_KEY": "a-long-random-beta-secret-for-testing-only-0123456789abcdef",
    "DATABASE_URL": "postgres://pm:pm@localhost:5432/pm_beta",
    "FIELD_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
    "ALLOWED_HOSTS": "app.example.com",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
    "SITE_URL": "https://app.example.com",
    "MEDIA_ROOT": "/srv/pm-beta-test/files",
}
CLEARED = (
    "DEBUG",
    "MFA_TOTP_INSECURE_BYPASS_CODE",
    "ALLOW_DEMO_DATA",
    "EMAIL_BACKEND",
    "SMS_BACKEND",
    "TRUSTED_CLIENT_IP_HEADER",
)


def load_beta(monkeypatch, **overrides):
    for name in CLEARED:
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
        return importlib.import_module("config.settings.beta")
    finally:
        for name in [n for n in sys.modules if n.startswith("config.settings.")]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_beta_settings_are_safe(monkeypatch):
    beta = load_beta(monkeypatch)
    assert beta.DEBUG is False
    assert not hasattr(beta, "MFA_TOTP_INSECURE_BYPASS_CODE")
    assert beta.ALLOW_DEMO_DATA is False
    assert beta.ALLOWED_HOSTS == ["app.example.com"]
    assert beta.SITE_URL == "https://app.example.com"
    assert beta.SESSION_COOKIE_SECURE and beta.CSRF_COOKIE_SECURE
    assert beta.SECURE_HSTS_SECONDS >= 31536000
    assert beta.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert beta.TRUSTED_CLIENT_IP_HEADER == "CF-Connecting-IP"
    assert beta.CACHES["default"]["BACKEND"].endswith("DatabaseCache")
    # Files on the laptop's disk outside the code folder; nothing reaches a client
    assert str(beta.MEDIA_ROOT) == FAKE_ENV["MEDIA_ROOT"]
    assert beta.STORAGES["default"]["BACKEND"].endswith("FileSystemStorage")
    assert beta.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"
    assert beta.SMS_BACKEND == ""
    assert "frame-ancestors 'none'" in beta.CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("missing", list(FAKE_ENV))
def test_beta_refuses_to_start_without_required_settings(monkeypatch, missing):
    with pytest.raises(ImproperlyConfigured):
        load_beta(monkeypatch, **{missing: None})


@pytest.mark.parametrize(
    "unsafe",
    [
        {"DEBUG": "true"},
        {"MFA_TOTP_INSECURE_BYPASS_CODE": "000000"},
        {"SECRET_KEY": "django-insecure-something-long-enough-to-pass-the-length-check"},
        {"SECRET_KEY": "short"},
        {"ALLOW_DEMO_DATA": "true"},
        {"SITE_URL": "http://app.example.com"},
        {"EMAIL_BACKEND": "anymail.backends.amazon_ses.EmailBackend"},
        {"SMS_BACKEND": "apps.comms.sms.ConsoleSmsBackend"},
    ],
)
def test_beta_refuses_to_start_with_something_unsafe(monkeypatch, unsafe):
    with pytest.raises(ImproperlyConfigured):
        load_beta(monkeypatch, **unsafe)
