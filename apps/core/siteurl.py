from django.conf import settings


def absolute(path: str) -> str:
    """A full address for a path on this site, for links in emails."""
    return f"{settings.SITE_URL}{path}"
