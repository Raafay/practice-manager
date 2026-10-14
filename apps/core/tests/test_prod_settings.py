"""Load prod.py with a made-up environment and check spec 01 section 11 and spec 12
section 3: safe values, and refusing to start without what it needs."""

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
    "CSRF_TRUSTED_ORIGINS": "https://app.example.com",
    "SITE_URL": "https://app.example.com",
    "DEFAULT_FROM_EMAIL": "Example Practice <office@example.com>",
    "EMAIL_PROVIDER": "ses",
    "EMAIL_ACCESS_KEY": "made-up-access",
    "EMAIL_SECRET_KEY": "made-up-secret",
    "EMAIL_WEBHOOK_SECRET": "made-up-name:made-up-password-0123456789",
    "STORAGE_BUCKET": "pm-files",
    "STORAGE_ACCESS_KEY": "made-up-storage-access",
    "STORAGE_SECRET_KEY": "made-up-storage-secret",
}
CLEARED = (
    "DEBUG",
    "MFA_TOTP_INSECURE_BYPASS_CODE",
    "ALLOW_DEMO_DATA",
    "SENTRY_DSN",
    "EMAIL_API_KEY",
    "SMS_BACKEND",
    "STORAGE_ENDPOINT",
)


def load_prod(monkeypatch, **overrides):
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
    assert prod.SITE_URL == "https://app.example.com"
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
    script_src = csp.split("script-src")[1].split(";")[0]
    assert "'self'" in script_src and "unsafe" not in script_src
    assert "img-src 'self' data: blob:" in csp
    assert "frame-ancestors 'none'" in csp
    # No development shortcuts, the database cache, a real email provider
    assert not hasattr(prod, "MFA_TOTP_INSECURE_BYPASS_CODE")
    assert prod.ALLOW_DEMO_DATA is False
    assert prod.CACHES["default"]["BACKEND"].endswith("DatabaseCache")
    assert prod.EMAIL_BACKEND == "anymail.backends.amazon_ses.EmailBackend"
    assert prod.ANYMAIL["AMAZON_SES_CLIENT_PARAMS"]["region_name"] == "eu-west-2"
    assert prod.ANYMAIL["WEBHOOK_SECRET"] == FAKE_ENV["EMAIL_WEBHOOK_SECRET"]
    # Static files by whitenoise; logs as JSON lines with tokens taken out
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in prod.MIDDLEWARE
    assert prod.STORAGES["staticfiles"]["BACKEND"].startswith("whitenoise.")
    assert prod.LOGGING["handlers"]["console"]["formatter"] == "json"
    assert prod.LOGGING["handlers"]["console"]["filters"] == ["redact"]
    assert prod.LOGGING["loggers"]["django.request"]["level"] == "ERROR"


@pytest.mark.parametrize(
    "missing",
    [
        "SECRET_KEY",
        "DATABASE_URL",
        "FIELD_ENCRYPTION_KEYS",
        "ALLOWED_HOSTS",
        "CSRF_TRUSTED_ORIGINS",
        "SITE_URL",
        "DEFAULT_FROM_EMAIL",
        "EMAIL_PROVIDER",
        "EMAIL_WEBHOOK_SECRET",
        "EMAIL_ACCESS_KEY",
        "STORAGE_BUCKET",
        "STORAGE_ACCESS_KEY",
        "STORAGE_SECRET_KEY",
    ],
)
def test_refuses_to_start_without_required_settings(monkeypatch, missing):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, **{missing: None})


@pytest.mark.parametrize(
    "unsafe",
    [
        {"DEBUG": "true"},
        {"MFA_TOTP_INSECURE_BYPASS_CODE": "000000"},
        {"SECRET_KEY": "django-insecure-something-long-enough-to-pass-the-length-check"},
        {"SECRET_KEY": "short"},
        {"ALLOW_DEMO_DATA": "true"},
        {"SITE_URL": "http://app.example.com"},
        {"EMAIL_PROVIDER": "console"},
        {"EMAIL_PROVIDER": "locmem"},
        {"EMAIL_WEBHOOK_SECRET": "no-colon-here"},
        {"SMS_BACKEND": "apps.comms.sms.ConsoleSmsBackend"},
        {"EMAIL_PROVIDER": "postmark"},  # without EMAIL_API_KEY
    ],
)
def test_refuses_to_start_with_something_unsafe(monkeypatch, unsafe):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, **unsafe)


def test_other_email_providers(monkeypatch):
    prod = load_prod(monkeypatch, EMAIL_PROVIDER="postmark", EMAIL_API_KEY="made-up-token")
    assert prod.EMAIL_BACKEND == "anymail.backends.postmark.EmailBackend"
    assert prod.ANYMAIL["POSTMARK_SERVER_TOKEN"] == "made-up-token"


def test_private_bucket(monkeypatch):
    prod = load_prod(monkeypatch, STORAGE_ENDPOINT="https://s3.example.com")
    storage = prod.STORAGES["default"]
    assert storage["BACKEND"] == "storages.backends.s3.S3Storage"
    options = storage["OPTIONS"]
    assert options["bucket_name"] == "pm-files"
    assert options["endpoint_url"] == "https://s3.example.com"
    assert options["default_acl"] == "private"
    assert options["querystring_auth"] is True
    assert options["file_overwrite"] is False
    assert options["object_parameters"] == {"ServerSideEncryption": "AES256"}


def test_sentry_is_off_unless_asked_for(monkeypatch):
    prod = load_prod(monkeypatch)
    assert prod.SENTRY_DSN == ""


def test_error_reports_carry_no_personal_data():
    from apps.core.sentry import scrub_event

    event = {
        "request": {
            "method": "POST",
            "url": "https://app.example.com/sign/SECRET-TOKEN/",
            "data": {"typed_name": "Pat Sample"},
            "cookies": {"sessionid": "abc"},
            "headers": {"Cookie": "sessionid=abc"},
        },
        "user": {"email": "pat@example.com"},
        "breadcrumbs": {"values": [{"message": "pat@example.com signed in"}]},
        "exception": {
            "values": [
                {
                    "type": "IntegrityError",
                    "value": "Key (email)=(pat@example.com) already exists.",
                    "stacktrace": {"frames": [{"filename": "x.py", "vars": {"ni": "ZZ"}}]},
                }
            ]
        },
    }
    scrubbed = scrub_event(event)
    text = str(scrubbed)
    for secret in ("SECRET-TOKEN", "Pat Sample", "pat@example.com", "sessionid", "'ni'"):
        assert secret not in text
    assert scrubbed["exception"]["values"][0]["type"] == "IntegrityError"


def test_static_files_collect_with_the_build_settings(tmp_path, settings):
    """The image build runs collectstatic with whitenoise's manifest; a broken reference
    (a vendored file pointing at a missing source map) would stop the build."""
    from django.core.management import call_command

    settings.STATIC_ROOT = tmp_path / "static"
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    call_command("collectstatic", interactive=False, verbosity=0)
    assert (tmp_path / "static" / "staticfiles.json").exists()


def test_the_production_backends_can_be_loaded(monkeypatch):
    """A missing library (boto3 for the bucket and SES) would only show up in production."""
    from django.utils.module_loading import import_string

    prod = load_prod(monkeypatch)
    import_string(prod.STORAGES["default"]["BACKEND"])
    for backend in prod.EMAIL_PROVIDERS.values():
        import_string(backend)
