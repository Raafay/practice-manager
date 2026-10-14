"""Settings used only while the container image is built (CSS and collectstatic).

No secrets and no database are needed to build an image; the real settings
(prod.py) are read when the container starts.
"""

from .base import *  # noqa: F403

SECRET_KEY = "build-only-not-a-secret"  # noqa: S105 - never used to sign anything
DEBUG = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
