"""Settings shared by every environment. Values come from the environment."""

from datetime import timedelta
from pathlib import Path

import dj_database_url

from apps.core.flags import PracticeFlag

from .env import env, env_bool, env_list

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
# The address clients use, for links in emails. Set it in production (Stage 13).
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "apps.core.admin_config.ControlAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "axes",
    "django_htmx",
    "django_tailwind_cli",
    "apps.core",
    "apps.accounts",
    "apps.events",
    "apps.clients",
    "apps.jobs",
    "apps.companieshouse",
    "apps.services",
    "apps.tasks",
    "apps.comms",
    "apps.onboarding",
    "apps.aml",
    "apps.pipeline",
    "apps.portal",
    "apps.timekeeping",
    "apps.finance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
    "apps.events.middleware.RequestContextMiddleware",
    "apps.accounts.middleware.SessionLimitsMiddleware",
    "apps.accounts.middleware.RequireTwoFactorMiddleware",
    # Axes must come last so it can replace the response when an account is locked.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.layout",
            ],
            "builtins": ["apps.core.templatetags.ui"],
        },
    }
]

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgres://pm:pm@localhost:5432/pm_dev"),
        conn_max_age=60,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/"

# UK English, London time, dates as dd/mm/yyyy (formats live in config/formats).
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ["config.formats"]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Uploaded files are private. They have no public address and are served by
# views that check permission. MEDIA_URL is deliberately not routed.
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

TAILWIND_CLI_SRC_CSS = "assets/css/source.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Sessions. Idle and absolute limits are enforced by SessionLimitsMiddleware
# from the values on Practice settings. The cookie itself never outlives 12 hours.
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
PORTAL_SESSION_IDLE_MINUTES = 30
PORTAL_SESSION_MAX_HOURS = 8

# Security headers. The Content-Security-Policy is sent in every environment so
# that a page that breaks it is noticed in development, not in production.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# django-allauth: staff sign in with email, password and an authenticator app.
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"
ACCOUNT_FORMS = {"login": "apps.accounts.forms.StaffLoginForm"}
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_SESSION_REMEMBER = False
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"
ACCOUNT_REAUTHENTICATION_TIMEOUT = 300
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_LOGIN_BY_CODE_ENABLED = False
# Lockout per account is django-axes' job. allauth keeps a coarse limit per address.
ACCOUNT_RATE_LIMITS = {"login_failed": "30/m/ip"}

MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_TOTP_ISSUER = "Practice Manager"
MFA_RECOVERY_CODES_SHOW_ONCE = True
MFA_TRUST_ENABLED = PracticeFlag("mfa_trust_enabled", default=True)
MFA_TRUST_COOKIE_AGE = timedelta(days=30)

# django-axes: five wrong passwords lock that account from that address for 15 minutes.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_CALLABLE = "apps.accounts.lockout.get_username"
AXES_LOCKOUT_TEMPLATE = "account/lockout.html"
AXES_RESET_ON_SUCCESS = True
AXES_VERBOSE = False

FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS")

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Practice Manager <no-reply@example.com>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
# Text messages stay off until a provider class is named here (Stage 6, spec 07 section 7).
SMS_BACKEND = env("SMS_BACKEND", "")

INVITATION_VALID_HOURS = 72
ALLOW_DEMO_DATA = env_bool("ALLOW_DEMO_DATA", False)

# Companies House. The key is never shown, logged or put in a page.
COMPANIES_HOUSE_API_KEY = env("COMPANIES_HOUSE_API_KEY")
# "live" calls the real service. "fake" serves the saved samples (tests and CI).
COMPANIES_HOUSE_TRANSPORT = env("COMPANIES_HOUSE_TRANSPORT", "live")
# Read refreshed bank holidays from the database as well as the bundled list.
BANK_HOLIDAYS_FROM_DATABASE = True

# Logs carry no personal data. Request warnings include the path, which can
# hold a token, so django.request only logs errors.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "axes": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
